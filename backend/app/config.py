from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ — the directory holding .env and var/. Anchored to this file rather
# than to the process cwd, so the app behaves the same however it is launched.
BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    public_base_url: str = "http://localhost:8000"
    frontend_origin: str = "http://localhost:5173"

    data_dir: Path = BACKEND_DIR / "var"

    token_encryption_key: str = ""

    # MongoDB. The default is a local server; in production this is an Atlas
    # connection string.
    mongo_url: str = "mongodb://localhost:27017"
    mongo_db: str = "crosspost"

    google_client_id: str = ""
    google_client_secret: str = ""
    meta_app_id: str = ""
    meta_app_secret: str = ""

    # Facebook Login for Business hands out a Configuration ID that carries the
    # permission set, and Meta asks you to send that instead of `scope`. Empty
    # means the classic scope flow.
    meta_config_id: str = ""

    # Defaults to "private" on purpose: unaudited YouTube API projects
    # reportedly have uploads locked to private anyway, and a surprise public
    # upload is worse than a surprise private one. Flip to "public" once you
    # know where you stand on the compliance audit.
    youtube_privacy_status: str = "private"

    # Current as of the Graph API docs read on 2026-11-15, where every example
    # is v27.0.
    graph_api_version: str = "v27.0"

    # How often the publish worker looks for due posts. Creating a due post
    # nudges it immediately, so this is really the recovery interval.
    scheduler_poll_seconds: int = 5

    # If a scheduled time is missed by more than this (machine asleep, server
    # down), fail the post instead of publishing it late without warning.
    # Set to 0 to always publish late.
    scheduler_max_catchup_minutes: int = 60

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"


    @property
    def youtube_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def meta_configured(self) -> bool:
        return bool(self.meta_app_id and self.meta_app_secret)

    def ensure_dirs(self) -> None:
        self.media_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
