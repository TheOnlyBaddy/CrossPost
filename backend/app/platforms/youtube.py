"""YouTube upload via the Data API v3.

Quota, confirmed against the official quota calculator on 2026-11-14
(https://developers.google.com/youtube/data/determine_quota_cost, page last
updated 2026-11-12):

    videos.insert has its OWN quota bucket: 100 calls per day, 1 unit each.
    search.list likewise. All other endpoints share 10,000 units/day.

So the ceiling is ~100 uploads/day *per Google Cloud project* — not the ~6/day
that the widely-copied "10,000 units / 1,600 per upload" arithmetic gives. That
1,600-unit figure is stale; don't design around it.

TODO verify before going live:
  - The unaudited-project restriction: projects that have not passed the
    YouTube API Services compliance audit reportedly have uploads locked to
    private visibility. That is why YOUTUBE_PRIVACY_STATUS defaults to
    "private" here — find out where you stand before flipping it to public.
  - Required `status` fields, and whether selfDeclaredMadeForKids is still
    mandatory.
"""

import json
import logging

from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from ..config import Settings
from ..models import Platform, PublishResult, TargetState
from ..store import Store
from .base import PublishRequest

log = logging.getLogger(__name__)

TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CHUNK_SIZE = 8 * 1024 * 1024  # 8 MiB resumable chunks

# "22" is People & Blogs — a safe default. TODO make this selectable.
DEFAULT_CATEGORY_ID = "22"


class YouTubePublisher:
    platform = Platform.YOUTUBE

    def __init__(self, settings: Settings, store: Store) -> None:
        self.settings = settings
        self.store = store

    def _credentials(self) -> Credentials | None:
        account = self.store.get_account(req.user_id, Platform.YOUTUBE)
        if not account or not account.get("refresh_token"):
            return None
        return Credentials(
            token=account.get("access_token"),
            refresh_token=account["refresh_token"],
            token_uri=TOKEN_URI,
            client_id=self.settings.google_client_id,
            client_secret=self.settings.google_client_secret,
            scopes=SCOPES,
        )

    def publish(self, req: PublishRequest) -> PublishResult:
        if not self.settings.youtube_configured:
            return PublishResult.not_configured(
                "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set in .env"
            )

        creds = self._credentials()
        if creds is None:
            return PublishResult.not_configured("YouTube account is not connected")

        try:
            if creds.expired or not creds.token:
                creds.refresh(GoogleRequest())

            youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

            body = {
                "snippet": {
                    "title": req.title[:100],
                    "description": req.caption[:5000],
                    "categoryId": DEFAULT_CATEGORY_ID,
                },
                "status": {
                    "privacyStatus": self.settings.youtube_privacy_status,
                    "selfDeclaredMadeForKids": False,
                },
            }

            media = MediaFileUpload(
                str(req.video_path),
                mimetype="video/mp4",
                chunksize=CHUNK_SIZE,
                resumable=True,
            )
            insert = youtube.videos().insert(
                part="snippet,status", body=body, media_body=media
            )

            response = None
            while response is None:
                _status, response = insert.next_chunk()

            video_id = response.get("id")
            if not video_id:
                return PublishResult.failed(
                    "Upload returned no video id", raw=json.dumps(response)
                )

            # The API returns as soon as the bytes are in. YouTube is still
            # transcoding, so the video is not live yet.
            return PublishResult(
                state=TargetState.PROCESSING,
                external_id=video_id,
                url=f"https://www.youtube.com/watch?v={video_id}",
                raw=json.dumps(response),
            )

        except HttpError as exc:
            detail = exc.content.decode(errors="replace") if exc.content else str(exc)
            log.warning("YouTube upload failed: %s", detail)
            return PublishResult.failed(
                f"YouTube API error {exc.resp.status}", raw=detail
            )
        except Exception as exc:  # noqa: BLE001 - surface anything, never crash the job
            log.exception("YouTube upload failed")
            return PublishResult.failed(str(exc))
