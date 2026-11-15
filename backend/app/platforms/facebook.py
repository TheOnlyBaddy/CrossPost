"""Facebook Page video publishing.

Posts to POST /{page-id}/videos using a PAGE access token (not the user
token — they are different things; the Page token comes from GET /me/accounts).

v1 uses a single multipart upload, which is fine for the sub-60-second clips
v1 accepts. TODO: switch to the resumable upload protocol
(upload_phase=start/transfer/finish) before allowing larger files.

TODO verify before going live:
  - The current endpoint, and whether Page Reels use a separate one.
  - Whether `publish_video` is still a distinct permission from
    `pages_manage_posts`.
  - Long-lived Page token exchange and its actual lifetime. Short-lived tokens
    expire in roughly an hour.
"""

import logging

import httpx

from ..config import Settings
from ..models import Platform, PublishResult, TargetState
from ..store import Store
from .base import PublishRequest

log = logging.getLogger(__name__)


class FacebookPublisher:
    platform = Platform.FACEBOOK

    def __init__(self, settings: Settings, store: Store) -> None:
        self.settings = settings
        self.store = store

    def publish(self, req: PublishRequest) -> PublishResult:
        if not self.settings.meta_configured:
            return PublishResult.not_configured(
                "META_APP_ID / META_APP_SECRET are not set in .env"
            )

        account = self.store.get_account(req.user_id, Platform.FACEBOOK)
        if not account or not account.get("access_token"):
            return PublishResult.not_configured("Facebook Page is not connected")

        page_id = account.get("extra", {}).get("page_id") or account.get("external_id")
        if not page_id:
            return PublishResult.not_configured(
                "No Page id stored — reconnect the account"
            )

        url = (
            f"https://graph-video.facebook.com/"
            f"{self.settings.graph_api_version}/{page_id}/videos"
        )

        try:
            with open(req.video_path, "rb") as handle:
                with httpx.Client(timeout=600) as client:
                    resp = client.post(
                        url,
                        data={
                            "title": req.title[:255],
                            "description": req.caption,
                            "access_token": account["access_token"],
                        },
                        files={"source": (req.video_path.name, handle, "video/mp4")},
                    )

            body = resp.text
            if resp.status_code >= 400:
                return PublishResult.failed(
                    f"Facebook upload failed (HTTP {resp.status_code})", raw=body
                )

            video_id = resp.json().get("id")
            return PublishResult(
                state=TargetState.PROCESSING,
                external_id=video_id,
                url=f"https://www.facebook.com/{video_id}" if video_id else None,
                raw=body,
            )

        except httpx.HTTPError as exc:
            log.exception("Facebook publish failed")
            return PublishResult.failed(f"Network error talking to Meta: {exc}")
        except OSError as exc:
            return PublishResult.failed(f"Could not read the video file: {exc}")
