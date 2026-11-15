"""OAuth connect flows.

Both platforms want the same shape: redirect the browser to a consent screen,
get a code back on a redirect URI, exchange it server-side for tokens the
client never sees. This is exactly why the app is a web app — see the
web-vs-Android reasoning. An Android client would still need all of this.

Meta's flow has an extra step that YouTube's does not: one Meta login gives us
a *user* token, which we then trade for a list of Pages the user administers.
The user picks a Page; that Page's token is what publishes, and the Instagram
professional account hangs off the same Page. So /meta/callback does not
finish the connection — it parks the user token and hands the frontend a list
of Pages to choose from.

TODO before this is multi-user: `_PENDING_STATES` is a process-local dict, so
CSRF state does not survive a restart and does not work across replicas. Move
it to the database or a signed cookie.
"""

import logging
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from ..config import get_settings
from ..deps import current_user, get_store
from ..models import Platform

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

# youtube.upload is what we actually need. youtube.readonly is only so the UI
# can show which channel you connected; drop it if you would rather request
# less. Both are sensitive scopes and both feed into OAuth verification.
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

# Verified against Meta's Permissions Reference on 2026-11-15.
#
# instagram_basic / instagram_content_publish are the Facebook Login pair, which
# is the flow here (user token -> /me/accounts -> Page token -> IG user id). The
# instagram_business_* pair belongs to Instagram Login, a different flow, so the
# names are NOT interchangeable.
#
# pages_read_user_content is listed as a dependency of instagram_basic in the
# reference, but Meta's login dialog rejects it outright ("Invalid Scopes"), so
# it is not requestable here — the dependency is satisfied some other way.
#
# publish_video is deliberately absent: the reference defines it as publishing
# LIVE video, and the Video API publishing guide asks only for
# pages_manage_posts for POST /{page-id}/videos.
META_SCOPES = [
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
    "instagram_basic",
    "instagram_content_publish",
]

META_USER_KEY = "meta_user"  # pseudo-account holding the interim user token

_PENDING_STATES: dict[str, float] = {}
_STATE_TTL_S = 600


def _issue_state() -> str:
    state = secrets.token_urlsafe(24)
    now = time.monotonic()
    for old, created in list(_PENDING_STATES.items()):
        if now - created > _STATE_TTL_S:
            _PENDING_STATES.pop(old, None)
    _PENDING_STATES[state] = now
    return state


def _consume_state(state: str) -> bool:
    created = _PENDING_STATES.pop(state, None)
    return created is not None and (time.monotonic() - created) <= _STATE_TTL_S


def _redirect_uri(path: str) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}{path}"


def _back_to_frontend(**params: str) -> RedirectResponse:
    origin = get_settings().frontend_origin.rstrip("/")
    return RedirectResponse(f"{origin}/?{urlencode(params)}")


# --- status ------------------------------------------------------------


@router.get("/connections")
def connections(user: dict = Depends(current_user)) -> dict:
    store = get_store()
    pending = store.get_account(user["id"], META_USER_KEY)
    return {
        "connections": store.list_connections(user["id"]),
        "metaUserConnected": pending is not None,
    }


@router.delete("/{platform}")
def disconnect(platform: Platform, user: dict = Depends(current_user)) -> dict:
    get_store().delete_account(user["id"], platform)
    return {"ok": True, "platform": platform.value}


# --- YouTube -----------------------------------------------------------


@router.get("/youtube/start")
def youtube_start(user: dict = Depends(current_user)) -> RedirectResponse:
    settings = get_settings()
    if not settings.youtube_configured:
        raise HTTPException(
            status_code=400,
            detail="GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set in .env",
        )

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": _redirect_uri("/api/auth/youtube/callback"),
        "response_type": "code",
        "scope": " ".join(GOOGLE_SCOPES),
        # Both are required to get a refresh token back reliably.
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": _issue_state(),
    }
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


@router.get("/youtube/callback")
def youtube_callback(
    code: str | None = None,
    state: str = "",
    error: str | None = None,
    user: dict = Depends(current_user),
) -> RedirectResponse:
    if error:
        return _back_to_frontend(error=f"YouTube: {error}")
    if not code or not _consume_state(state):
        return _back_to_frontend(error="YouTube: invalid or expired OAuth state")

    settings = get_settings()
    with httpx.Client(timeout=30) as client:
        token_resp = client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": _redirect_uri("/api/auth/youtube/callback"),
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code >= 400:
            log.warning("Google token exchange failed: %s", token_resp.text)
            return _back_to_frontend(error="YouTube: token exchange failed")

        tokens = token_resp.json()
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            # Happens when the account was already authorised and Google
            # declines to re-issue one. Revoke access and retry.
            return _back_to_frontend(
                error="YouTube: no refresh token returned. Remove the app at "
                "myaccount.google.com/permissions and connect again."
            )

        channel_title, channel_id = _fetch_channel(client, tokens["access_token"])

    get_store().save_account(
        user["id"],
        Platform.YOUTUBE,
        external_id=channel_id,
        display_name=channel_title,
        access_token=tokens.get("access_token"),
        refresh_token=refresh_token,
        expires_at=None,
    )
    return _back_to_frontend(connected="youtube")


def _fetch_channel(client: httpx.Client, access_token: str) -> tuple[str | None, str | None]:
    resp = client.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={"part": "snippet", "mine": "true"},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if resp.status_code >= 400:
        log.warning("channels.list failed: %s", resp.text)
        return None, None
    items = resp.json().get("items") or []
    if not items:
        return None, None
    return items[0]["snippet"]["title"], items[0]["id"]


# --- Meta (Facebook Page + Instagram) ----------------------------------


@router.get("/meta/start")
def meta_start(user: dict = Depends(current_user)) -> RedirectResponse:
    settings = get_settings()
    if not settings.meta_configured:
        raise HTTPException(
            status_code=400,
            detail="META_APP_ID / META_APP_SECRET are not set in .env",
        )

    params = {
        "client_id": settings.meta_app_id,
        "redirect_uri": _redirect_uri("/api/auth/meta/callback"),
        "response_type": "code",
        "state": _issue_state(),
    }
    # Facebook Login for Business carries its permissions in the configuration,
    # and Meta's manual-flow guide says to send config_id instead of scope.
    if settings.meta_config_id:
        params["config_id"] = settings.meta_config_id
    else:
        params["scope"] = ",".join(META_SCOPES)
    return RedirectResponse(
        f"https://www.facebook.com/{settings.graph_api_version}/dialog/oauth"
        f"?{urlencode(params)}"
    )


@router.get("/meta/callback")
def meta_callback(
    code: str | None = None,
    state: str = "",
    error: str | None = None,
    error_description: str | None = None,
    user: dict = Depends(current_user),
) -> RedirectResponse:
    if error:
        return _back_to_frontend(error=f"Meta: {error_description or error}")
    if not code or not _consume_state(state):
        return _back_to_frontend(error="Meta: invalid or expired OAuth state")

    settings = get_settings()
    base = f"https://graph.facebook.com/{settings.graph_api_version}"

    with httpx.Client(timeout=30) as client:
        token_resp = client.get(
            f"{base}/oauth/access_token",
            params={
                "client_id": settings.meta_app_id,
                "client_secret": settings.meta_app_secret,
                "redirect_uri": _redirect_uri("/api/auth/meta/callback"),
                "code": code,
            },
        )
        if token_resp.status_code >= 400:
            log.warning("Meta token exchange failed: %s", token_resp.text)
            return _back_to_frontend(error="Meta: token exchange failed")

        short_lived = token_resp.json().get("access_token")

        # Trade the short-lived user token for a long-lived one.
        # TODO verify the current lifetime; short-lived tokens last ~1 hour.
        long_resp = client.get(
            f"{base}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": settings.meta_app_id,
                "client_secret": settings.meta_app_secret,
                "fb_exchange_token": short_lived,
            },
        )
        user_token = (
            long_resp.json().get("access_token")
            if long_resp.status_code < 400
            else short_lived
        )

    get_store().save_account(
        user["id"],
        META_USER_KEY,
        external_id=None,
        display_name=None,
        access_token=user_token,
    )
    # The connection is not finished: the user still has to pick a Page.
    return _back_to_frontend(connected="meta", next="choose-page")


@router.get("/meta/pages")
def meta_pages(user: dict = Depends(current_user)) -> dict:
    """Pages this user administers, each with the Instagram professional
    account linked to it (if any). This is the answer to 'which Page and which
    Instagram account do I post from'."""
    settings = get_settings()
    account = get_store().get_account(user["id"], META_USER_KEY)
    if not account or not account.get("access_token"):
        raise HTTPException(status_code=400, detail="Connect with Meta first")

    base = f"https://graph.facebook.com/{settings.graph_api_version}"
    with httpx.Client(timeout=30) as client:
        resp = client.get(
            f"{base}/me/accounts",
            params={
                "fields": "id,name,access_token,"
                "instagram_business_account{id,username}",
                "access_token": account["access_token"],
            },
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=resp.text)

    pages = []
    for page in resp.json().get("data", []):
        ig = page.get("instagram_business_account") or {}
        pages.append(
            {
                "id": page["id"],
                "name": page.get("name"),
                "instagramId": ig.get("id"),
                "instagramUsername": ig.get("username"),
            }
        )
    return {"pages": pages}


@router.post("/meta/select-page")
def meta_select_page(
    page_id: str = Query(..., alias="pageId"),
    user: dict = Depends(current_user),
) -> dict:
    """Finish the Meta connection for the chosen Page.

    Stores two accounts: the Facebook Page (with its Page token) and the
    Instagram professional account linked to it. If no Instagram account is
    linked, Facebook still connects and Instagram stays disconnected — which
    is the correct partial outcome, not an error.
    """
    settings = get_settings()
    store = get_store()
    account = store.get_account(user["id"], META_USER_KEY)
    if not account or not account.get("access_token"):
        raise HTTPException(status_code=400, detail="Connect with Meta first")

    base = f"https://graph.facebook.com/{settings.graph_api_version}"
    with httpx.Client(timeout=30) as client:
        resp = client.get(
            f"{base}/{page_id}",
            params={
                "fields": "id,name,access_token,"
                "instagram_business_account{id,username}",
                "access_token": account["access_token"],
            },
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=resp.text)

    page = resp.json()
    page_token = page.get("access_token")
    if not page_token:
        raise HTTPException(
            status_code=502,
            detail="No Page access token returned — check that you are an admin "
            "of this Page and that pages_show_list was granted.",
        )

    store.save_account(
        user["id"],
        Platform.FACEBOOK,
        external_id=page["id"],
        display_name=page.get("name"),
        access_token=page_token,
        extra={"page_id": page["id"]},
    )

    ig = page.get("instagram_business_account") or {}
    if ig.get("id"):
        store.save_account(
            user["id"],
            Platform.INSTAGRAM,
            external_id=ig["id"],
            display_name=ig.get("username"),
            access_token=page_token,  # IG publishing uses the Page token
            extra={"ig_user_id": ig["id"], "page_id": page["id"]},
        )

    return {
        "ok": True,
        "facebook": {"pageId": page["id"], "name": page.get("name")},
        "instagram": (
            {"igUserId": ig.get("id"), "username": ig.get("username")}
            if ig.get("id")
            else None
        ),
        "warning": (
            None
            if ig.get("id")
            else "No Instagram professional account is linked to this Page. "
            "Link one in Meta Business Suite, then reconnect."
        ),
    }
