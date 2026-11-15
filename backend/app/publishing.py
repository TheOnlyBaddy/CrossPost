"""Fan-out: take one post and push it to each selected platform.

Two rules this module exists to enforce:

  1. Platforms are independent. One failing never stops or rolls back another.
     Partial success is the normal case.
  2. Retrying one platform must not re-publish to the others. Each leg owns its
     own state, so a retry only touches the leg you name.

Runs on FastAPI BackgroundTasks for now, which is enough for a single-user
app. TODO: move to a real queue (arq / Celery / RQ) once this needs to survive
a restart mid-publish, or once more than one post can be in flight.
"""

import logging
from pathlib import Path
from urllib.parse import quote

from .config import Settings
from .models import Platform, TargetState
from .platforms import PublishRequest, get_publisher
from .store import Store

log = logging.getLogger(__name__)


def public_media_url(settings: Settings, filename: str) -> str:
    return f"{settings.public_base_url.rstrip('/')}/media/{quote(filename)}"


def publish_one(
    store: Store, settings: Settings, post_id: str, platform: Platform
) -> None:
    post = store.get_post(post_id)
    if post is None:
        log.warning("publish_one: post %s is gone", post_id)
        return

    req = PublishRequest(
        post_id=post_id,
        user_id=post["userId"],
        title=post["title"],
        caption=post["caption"],
        video_path=Path(post["mediaPath"]),
        public_url=public_media_url(settings, post["filename"]),
    )

    store.set_target_state(post_id, platform, TargetState.UPLOADING)

    publisher = get_publisher(platform, settings, store)
    try:
        result = publisher.publish(req)
    except Exception as exc:  # noqa: BLE001 - one platform must never take down the rest
        log.exception("Unhandled error publishing %s to %s", post_id, platform.value)
        store.set_target_state(post_id, platform, TargetState.FAILED)
        from .models import PublishResult

        store.set_target_result(post_id, platform, PublishResult.failed(str(exc)))
        return

    store.set_target_result(post_id, platform, result)
    log.info(
        "post=%s platform=%s state=%s error=%s",
        post_id,
        platform.value,
        result.state.value,
        result.error,
    )


def publish_all(
    store: Store, settings: Settings, post_id: str, platforms: list[Platform]
) -> None:
    for platform in platforms:
        publish_one(store, settings, post_id, platform)
