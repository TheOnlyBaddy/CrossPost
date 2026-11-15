"""Sign up, log in, log out.

The session token is a random value looked up in the database, not a signed
blob, so logging out actually ends the session rather than waiting for an
expiry to pass.
"""

import re

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel

from ..deps import current_user, get_store
from ..passwords import hash_password, verify_password

router = APIRouter(prefix="/api", tags=["session"])

SESSION_COOKIE = "crosspost_session"
SESSION_MAX_AGE_S = 60 * 60 * 24 * 30

MIN_PASSWORD_CHARS = 8
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Credentials(BaseModel):
    email: str
    password: str


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE_S,
        httponly=True,
        samesite="lax",
        # The tunnel is https and localhost is not, so this cannot be hardcoded
        # to secure=True without breaking local development.
        secure=False,
        path="/",
    )


@router.post("/users", status_code=201)
def sign_up(body: Credentials, response: Response) -> dict:
    email = body.email.strip()
    if not _EMAIL.match(email):
        raise HTTPException(422, "That does not look like an email address")
    if len(body.password) < MIN_PASSWORD_CHARS:
        raise HTTPException(
            422, f"Use at least {MIN_PASSWORD_CHARS} characters for the password"
        )

    store = get_store()
    user_id = store.create_user(email, hash_password(body.password))
    if user_id is None:
        raise HTTPException(409, "That email is already registered")

    # Connections made before sign-up existed belong to whoever arrives first.
    store.adopt_unowned_accounts(user_id)

    set_session_cookie(response, store.create_session(user_id))
    return {"id": user_id, "email": email}


@router.post("/session")
def log_in(body: Credentials, response: Response) -> dict:
    store = get_store()
    user = store.get_user_by_email(body.email)
    if user is None or not verify_password(body.password, user["password_hash"]):
        # One message for both cases, so this cannot be used to find out which
        # emails have accounts.
        raise HTTPException(401, "Wrong email or password")

    set_session_cookie(response, store.create_session(user["id"]))
    return {"id": user["id"], "email": user["email"]}


@router.get("/session")
def who_am_i(user: dict = Depends(current_user)) -> dict:
    return {"id": user["id"], "email": user["email"]}


@router.delete("/session", status_code=204)
def log_out(
    response: Response,
    token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> None:
    if token:
        get_store().delete_session(token)
    response.delete_cookie(SESSION_COOKIE, path="/")
