import logging
from contextlib import asynccontextmanager

from fastapi import Cookie, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .deps import get_scheduler, get_store
from .routers import auth, posts, session
from .validation import (
    MAX_CAPTION_CHARS,
    MAX_DURATION_S,
    MAX_TITLE_CHARS,
    MIN_DURATION_S,
    ffprobe_available,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s"
)

settings = get_settings()
settings.ensure_dirs()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    scheduler = get_scheduler()
    await scheduler.start()
    try:
        yield
    finally:
        await scheduler.stop()


app = FastAPI(title="Cross Post", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Instagram fetches the video from a URL rather than accepting bytes, so the
# uploaded file has to be served publicly. In production put this behind a CDN
# or object storage instead of serving it from the app process.
app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")

app.include_router(auth.router)
app.include_router(posts.router)
app.include_router(session.router)


@app.get("/api/health")
def health(crosspost_session: str | None = Cookie(default=None)) -> dict:
    """Setup state, so the UI can tell you what is not wired up yet.

    Public, because the login page needs it. Connections are per user, so they
    are only filled in once there is a session.
    """
    store = get_store()
    user = store.user_for_session(crosspost_session or "")
    public_is_https = settings.public_base_url.startswith("https://")
    return {
        "ok": True,
        "setup": {
            "youtubeCredentials": settings.youtube_configured,
            "metaCredentials": settings.meta_configured,
            "tokenEncryptionKey": bool(settings.token_encryption_key),
            "ffprobe": ffprobe_available(),
            "publicBaseUrl": settings.public_base_url,
            "publicBaseUrlIsHttps": public_is_https,
            "instagramCanFetchMedia": public_is_https,
            "youtubePrivacyStatus": settings.youtube_privacy_status,
            "schedulerPollSeconds": settings.scheduler_poll_seconds,
            "schedulerMaxCatchupMinutes": settings.scheduler_max_catchup_minutes,
        },
        "user": {"id": user["id"], "email": user["email"]} if user else None,
        "connections": store.list_connections(user["id"]) if user else [],
        "limits": {
            "maxDurationSeconds": MAX_DURATION_S,
            "minDurationSeconds": MIN_DURATION_S,
            "maxTitleChars": MAX_TITLE_CHARS,
            "maxCaptionChars": MAX_CAPTION_CHARS,
        },
    }
