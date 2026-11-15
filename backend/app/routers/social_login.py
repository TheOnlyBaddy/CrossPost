"""Sign in with Google.

Separate from the OAuth in auth.py, which is about *publishing*: this flow
asks only for an identity and never stores a token. The account is matched on
the verified email Google returns.

There is deliberately no "sign in with Facebook". The Meta app carries the two
publishing use cases (Pages and Instagram) and not the authentication one, so
Meta rejects `email` as an invalid scope. Facebook sign-in would only duplicate
two sign-in methods that already work; Meta publishing is unaffected and lives
in auth.py.
"""

import logging
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from ..config import get_settings
from ..deps import get_store
from ..passwords import UNUSABLE_PASSWORD
from .session import set_session_cookie

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/login", tags=["social login"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

# Identity only. No youtube.upload here: connecting a channel is a separate,
# later decision, and asking for upload rights just to log in is rude.
GOOGLE_LOGIN_SCOPES = ["openid", "email", "profile"]

_PENDING: dict[str, float] = {}
_STATE_TTL_S = 600


def _issue_state() -> str:
    state = secrets.token_urlsafe(24)
    now = time.monotonic()
    for old, created in list(_PENDING.items()):
        if now - created > _STATE_TTL_S:
            _PENDING.pop(old, None)
    _PENDING[state] = now
    return state


def _consume_state(state: str) -> bool:
    created = _PENDING.pop(state, None)
    return created is not None and (time.monotonic() - created) <= _STATE_TTL_S


def _redirect_uri(path: str) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}{path}"


def _back_to_frontend(**params: str) -> RedirectResponse:
    origin = get_settings().frontend_origin.rstrip("/")
    return RedirectResponse(f"{origin}/?{urlencode(params)}")


def _sign_in(email: str, provider: str) -> RedirectResponse:
    """Find the account for this verified email, or make one, then start a
    session. Accounts created this way have no usable password until the owner
    sets one, so the provider stays the only way in."""
    store = get_store()
    user = store.get_user_by_email(email)
    if user is None:
        user_id = store.create_user(email, UNUSABLE_PASSWORD)
        if user_id is None:  # lost a race with another sign-up
            user = store.get_user_by_email(email)
            if user is None:
                return _back_to_frontend(error=f"{provider}: could not create account")
            user_id = user["id"]
        # First account on a fresh install inherits connections made before
        # sign-up existed, same as the password flow.
        store.adopt_unowned_accounts(user_id)
    else:
        user_id = user["id"]

    response = _back_to_frontend(signedIn=provider)
    set_session_cookie(response, store.create_session(user_id))
    return response


# --- Google ------------------------------------------------------------


@router.get("/google")
def google_start() -> RedirectResponse:
    settings = get_settings()
    if not settings.youtube_configured:
        return _back_to_frontend(
            error="Google sign-in is unavailable: GOOGLE_CLIENT_ID / "
            "GOOGLE_CLIENT_SECRET are not set"
        )
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": _redirect_uri("/api/login/google/callback"),
        "response_type": "code",
        "scope": " ".join(GOOGLE_LOGIN_SCOPES),
        "state": _issue_state(),
    }
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


@router.get("/google/callback")
def google_callback(
    code: str | None = None, state: str = "", error: str | None = None
) -> RedirectResponse:
    if error:
        return _back_to_frontend(error=f"Google sign-in: {error}")
    if not code or not _consume_state(state):
        return _back_to_frontend(error="Google sign-in: invalid or expired state")

    settings = get_settings()
    with httpx.Client(timeout=30) as client:
        token_resp = client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": _redirect_uri("/api/login/google/callback"),
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code >= 400:
            log.warning("Google login token exchange failed: %s", token_resp.text)
            return _back_to_frontend(error="Google sign-in: token exchange failed")

        info = client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {token_resp.json()['access_token']}"},
        )
        if info.status_code >= 400:
            return _back_to_frontend(error="Google sign-in: could not read profile")

    profile = info.json()
    # Google says whether it checked the address. An unverified one would let
    # someone claim an account they do not own.
    if not profile.get("email") or not profile.get("email_verified"):
        return _back_to_frontend(
            error="Google sign-in: that account has no verified email"
        )
    return _sign_in(profile["email"], "google")
