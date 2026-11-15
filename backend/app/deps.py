from functools import lru_cache

from fastapi import Cookie, HTTPException

from .config import Settings, get_settings
from .scheduler import Scheduler
from .store import Store


@lru_cache
def get_store() -> Store:
    settings = get_settings()
    settings.ensure_dirs()
    return Store(
        settings.mongo_url, settings.mongo_db, settings.token_encryption_key
    )


@lru_cache
def get_scheduler() -> Scheduler:
    """The single publish worker. Started and stopped by the app lifespan."""
    return Scheduler(get_store(), get_settings())


def get_settings_dep() -> Settings:
    return get_settings()


SESSION_COOKIE = "crosspost_session"


def current_user(
    crosspost_session: str | None = Cookie(default=None),
) -> dict:
    """Every route that touches a user's posts or connections depends on this.

    401 rather than 403: the frontend treats it as "show the login page".
    """
    user = get_store().user_for_session(crosspost_session or "")
    if user is None:
        raise HTTPException(401, "Sign in to continue")
    return user
