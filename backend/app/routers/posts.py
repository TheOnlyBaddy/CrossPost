"""Upload a video once, fan it out to the selected platforms — now or later."""

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ..config import get_settings
from ..deps import current_user, get_scheduler, get_store
from ..models import Platform, TargetState
from ..schedule_input import is_due, parse_schedule
from ..store import to_utc_iso
from ..validation import (
    check_text,
    check_v1_constraints,
    ffprobe_available,
    probe_with_ffprobe,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/posts", tags=["posts"])

ALLOWED_SUFFIXES = {".mp4", ".mov"}
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
CHUNK = 1024 * 1024


@router.get("")
def list_posts(limit: int = 25, user: dict = Depends(current_user)) -> dict:
    return {"posts": get_store().list_posts(user["id"], limit=limit)}


@router.get("/{post_id}")
def get_post(post_id: str, user: dict = Depends(current_user)) -> dict:
    post = get_store().get_post(post_id, user["id"])
    if post is None:
        raise HTTPException(status_code=404, detail="No such post")
    return post


@router.post("", status_code=201)
async def create_post(
    file: UploadFile = File(...),
    title: str = Form(...),
    caption: str = Form(""),
    targets: str = Form("youtube,instagram,facebook"),
    scheduled_at: str = Form("", alias="scheduledAt"),
    user: dict = Depends(current_user),
) -> dict:
    """Create a post. An empty `scheduledAt` means publish now.

    Either way the post is handed to the scheduler rather than published
    inline, so there is exactly one path to a platform.
    """
    settings = get_settings()
    store = get_store()
    settings.ensure_dirs()

    selected = _parse_targets(targets)

    schedule = parse_schedule(scheduled_at)
    if not schedule.ok:
        raise HTTPException(status_code=422, detail={"problems": [schedule.problem]})

    text_report = check_text(title, caption)
    if not text_report.ok:
        raise HTTPException(status_code=422, detail={"problems": text_report.problems})

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=422,
            detail={
                "problems": [
                    f"v1 takes {' or '.join(sorted(ALLOWED_SUFFIXES))} files. "
                    f"Got '{suffix or 'no extension'}'."
                ]
            },
        )

    stored_name = f"{uuid.uuid4().hex}{suffix}"
    media_path = settings.media_dir / stored_name
    written = await _save_upload(file, media_path)
    if written is None:
        media_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=413,
            detail={
                "problems": [
                    f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
                ]
            },
        )

    warnings = list(text_report.warnings)

    probe = probe_with_ffprobe(media_path)
    if probe is None:
        if not ffprobe_available():
            warnings.append(
                "ffprobe is not installed, so the video format was not verified "
                "server-side. Install ffmpeg to enable this check."
            )
        else:
            media_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=422,
                detail={"problems": ["Could not read that file as a video."]},
            )
    else:
        report = check_v1_constraints(probe)
        warnings.extend(report.warnings)
        if not report.ok:
            media_path.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail={"problems": report.problems})

    post_id = store.create_post(
        user_id=user["id"],
        title=title,
        caption=caption,
        filename=stored_name,
        media_path=media_path,
        targets=selected,
        scheduled_at=to_utc_iso(schedule.moment),
    )

    # Due right now? Don't make the user wait for the next poll.
    if is_due(schedule.moment):
        get_scheduler().nudge()

    created = store.get_post(post_id, user["id"])
    assert created is not None
    return {**created, "warnings": warnings}


@router.post("/{post_id}/cancel")
def cancel_post(post_id: str, user: dict = Depends(current_user)) -> dict:
    """Cancel the legs that have not gone out yet.

    Anything already published, in flight or failed is untouched — a video
    that has reached a platform cannot be unsent from here.
    """
    store = get_store()
    post = store.get_post(post_id, user["id"])
    if post is None:
        raise HTTPException(status_code=404, detail="No such post")

    cancelable = [
        t for t in post["targets"] if TargetState(t["state"]).is_cancelable
    ]
    if not cancelable:
        raise HTTPException(
            status_code=409,
            detail="Nothing left to cancel — every platform has already been "
            "attempted.",
        )

    canceled = store.cancel_post(post_id, user["id"])
    return {"ok": True, "postId": post_id, "canceled": canceled}


@router.post("/{post_id}/retry/{platform}")
def retry_target(
    post_id: str, platform: Platform, user: dict = Depends(current_user)
) -> dict:
    """Retry exactly one platform, immediately.

    This never touches the other legs — retrying Instagram must not re-upload
    to YouTube.
    """
    store = get_store()
    post = store.get_post(post_id, user["id"])
    if post is None:
        raise HTTPException(status_code=404, detail="No such post")

    target = next((t for t in post["targets"] if t["platform"] == platform.value), None)
    if target is None:
        raise HTTPException(
            status_code=404, detail=f"This post has no {platform.value} target"
        )

    state = TargetState(target["state"])
    if not state.is_retryable:
        raise HTTPException(
            status_code=409,
            detail=f"{platform.value} is '{state.value}' — only failed or "
            "not-configured targets can be retried",
        )

    if not Path(post["mediaPath"]).exists():
        raise HTTPException(
            status_code=410, detail="The video file for this post is gone"
        )

    # A retry means "go now", so pull the whole post's schedule to now and put
    # this one leg back in the queue. Other legs are already terminal, so they
    # are unaffected.
    store.reschedule_post(
        post_id, to_utc_iso(datetime.now(timezone.utc)), user["id"]
    )
    store.set_target_state(post_id, platform, TargetState.SCHEDULED)
    get_scheduler().nudge()

    return {"ok": True, "postId": post_id, "platform": platform.value}


@router.post("/{post_id}/reschedule")
def reschedule(
    post_id: str,
    scheduled_at: str = Form(..., alias="scheduledAt"),
    user: dict = Depends(current_user),
) -> dict:
    store = get_store()
    post = store.get_post(post_id, user["id"])
    if post is None:
        raise HTTPException(status_code=404, detail="No such post")

    schedule = parse_schedule(scheduled_at)
    if not schedule.ok:
        raise HTTPException(status_code=422, detail={"problems": [schedule.problem]})

    movable = [t for t in post["targets"] if TargetState(t["state"]).is_cancelable]
    if not movable:
        raise HTTPException(
            status_code=409,
            detail="Every platform has already been attempted, so there is "
            "nothing left to move.",
        )

    store.reschedule_post(post_id, to_utc_iso(schedule.moment), user["id"])
    if is_due(schedule.moment):
        get_scheduler().nudge()
    return {"ok": True, "postId": post_id, "scheduledAt": to_utc_iso(schedule.moment)}


def _parse_targets(raw: str) -> list[Platform]:
    names = [n.strip().lower() for n in raw.split(",") if n.strip()]
    if not names:
        raise HTTPException(status_code=422, detail="Pick at least one platform")

    out: list[Platform] = []
    for name in names:
        try:
            platform = Platform(name)
        except ValueError:
            raise HTTPException(
                status_code=422, detail=f"Unknown platform '{name}'"
            ) from None
        if platform not in out:
            out.append(platform)
    return out


async def _save_upload(file: UploadFile, dest: Path) -> int | None:
    """Stream to disk. Returns bytes written, or None if over the size cap."""
    written = 0
    with dest.open("wb") as handle:
        while chunk := await file.read(CHUNK):
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                return None
            handle.write(chunk)
    return written
