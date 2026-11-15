"""Instagram Reels publishing via the Content Publishing API.

This is a three-step container flow, not a file upload:

    1. POST /{ig-user-id}/media  (media_type=REELS, video_url, caption)
    2. poll GET /{container-id}?fields=status_code  until FINISHED
    3. POST /{ig-user-id}/media_publish  (creation_id)

The architectural consequence, and it drives the whole storage design:
Instagram FETCHES the video from `video_url`. It does not accept bytes in this
flow. So the file must sit at a publicly reachable HTTPS URL for long enough
that Meta can pull it — localhost will not do.

Rate limit: 100 API-published posts per rolling 24h per account, per Meta's
Content Publishing doc (seen 2026-11-14). The "25 posts" figure repeated on
many vendor help pages appears to be stale.

TODO verify before going live:
  - Whether the resumable `rupload.facebook.com` path can take raw bytes for
    Reels. If it can, the public-URL requirement above disappears and this
    whole class gets simpler.
  - The current permission names (instagram_content_publish vs the newer
    instagram_business_content_publish).
  - The current Graph API version (GRAPH_API_VERSION in .env).
"""

import json
import logging
import time

import httpx

from ..config import Settings
from ..models import Platform, PublishResult, TargetState
from ..store import Store
from .base import PublishRequest

log = logging.getLogger(__name__)

POLL_INTERVAL_S = 5
POLL_TIMEOUT_S = 300


class InstagramPublisher:
    platform = Platform.INSTAGRAM

    def __init__(self, settings: Settings, store: Store) -> None:
        self.settings = settings
        self.store = store

    @property
    def _base(self) -> str:
        return f"https://graph.facebook.com/{self.settings.graph_api_version}"

    def publish(self, req: PublishRequest) -> PublishResult:
        if not self.settings.meta_configured:
            return PublishResult.not_configured(
                "META_APP_ID / META_APP_SECRET are not set in .env"
            )

        account = self.store.get_account(req.user_id, Platform.INSTAGRAM)
        if not account or not account.get("access_token"):
            return PublishResult.not_configured("Instagram account is not connected")

        ig_user_id = account.get("extra", {}).get("ig_user_id") or account.get(
            "external_id"
        )
        if not ig_user_id:
            return PublishResult.not_configured(
                "No Instagram user id stored — reconnect the account"
            )

        # Fail fast with a useful message rather than letting Meta return an
        # opaque fetch error.
        if not req.public_url.startswith("https://"):
            return PublishResult.failed(
                "Instagram fetches the video from PUBLIC_BASE_URL, so it must be a "
                f"public HTTPS URL. It is currently '{req.public_url}'. Use a "
                "Cloudflare Tunnel or ngrok in development."
            )

        token = account["access_token"]

        try:
            with httpx.Client(timeout=60) as client:
                container_id = self._create_container(client, ig_user_id, token, req)
                if isinstance(container_id, PublishResult):
                    return container_id

                ready = self._await_container(client, container_id, token)
                if isinstance(ready, PublishResult):
                    return ready

                return self._publish_container(client, ig_user_id, token, container_id)

        except httpx.HTTPError as exc:
            log.exception("Instagram publish failed")
            return PublishResult.failed(f"Network error talking to Meta: {exc}")

    def _create_container(
        self, client: httpx.Client, ig_user_id: str, token: str, req: PublishRequest
    ) -> str | PublishResult:
        resp = client.post(
            f"{self._base}/{ig_user_id}/media",
            data={
                "media_type": "REELS",
                "video_url": req.public_url,
                "caption": req.caption[:2200],
                "access_token": token,
            },
        )
        body = resp.text
        if resp.status_code >= 400:
            return PublishResult.failed(
                f"Could not create Instagram container (HTTP {resp.status_code})",
                raw=body,
            )
        container_id = resp.json().get("id")
        if not container_id:
            return PublishResult.failed("Meta returned no container id", raw=body)
        return container_id

    def _await_container(
        self, client: httpx.Client, container_id: str, token: str
    ) -> None | PublishResult:
        deadline = time.monotonic() + POLL_TIMEOUT_S
        while time.monotonic() < deadline:
            resp = client.get(
                f"{self._base}/{container_id}",
                params={"fields": "status_code,status", "access_token": token},
            )
            if resp.status_code >= 400:
                return PublishResult.failed(
                    f"Could not read container status (HTTP {resp.status_code})",
                    raw=resp.text,
                )

            payload = resp.json()
            status = payload.get("status_code")

            if status == "FINISHED":
                return None
            if status in ("ERROR", "EXPIRED"):
                return PublishResult.failed(
                    f"Instagram rejected the video ({status})", raw=resp.text
                )

            time.sleep(POLL_INTERVAL_S)

        return PublishResult.failed(
            f"Instagram was still processing after {POLL_TIMEOUT_S}s"
        )

    def _publish_container(
        self, client: httpx.Client, ig_user_id: str, token: str, container_id: str
    ) -> PublishResult:
        resp = client.post(
            f"{self._base}/{ig_user_id}/media_publish",
            data={"creation_id": container_id, "access_token": token},
        )
        body = resp.text
        if resp.status_code >= 400:
            return PublishResult.failed(
                f"Instagram publish failed (HTTP {resp.status_code})", raw=body
            )

        media_id = resp.json().get("id")
        return PublishResult(
            state=TargetState.DONE,
            external_id=media_id,
            url=f"https://www.instagram.com/reel/{media_id}/" if media_id else None,
            raw=body,
        )

    def remaining_quota(self, user_id: str) -> dict | None:
        """GET /{ig-user-id}/content_publishing_limit — how much of the rolling
        24h window is left. Useful for the UI; not required to publish."""
        account = self.store.get_account(user_id, Platform.INSTAGRAM)
        if not account or not account.get("access_token"):
            return None
        ig_user_id = account.get("extra", {}).get("ig_user_id") or account.get(
            "external_id"
        )
        with httpx.Client(timeout=30) as client:
            resp = client.get(
                f"{self._base}/{ig_user_id}/content_publishing_limit",
                params={
                    "fields": "quota_usage,config",
                    "access_token": account["access_token"],
                },
            )
        if resp.status_code >= 400:
            log.warning("content_publishing_limit failed: %s", resp.text)
            return None
        return json.loads(resp.text)
