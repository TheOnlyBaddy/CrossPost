"""Everything that is written down: users, sessions, connected accounts, posts.

MongoDB, one collection per thing. The shapes the rest of the app sees are
unchanged from the SQLite version that came before — same method signatures,
same dicts out — so routers, publishers and the scheduler did not have to
learn anything about the move.

Timestamps are stored as the canonical UTC ISO strings produced by
`to_utc_iso`, because fixed-width ISO sorts lexicographically in the same
order it sorts chronologically, and the scheduler compares them directly.
"""

import json
import re
import secrets
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from cryptography.fernet import Fernet, InvalidToken
from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from .models import Platform, PublishResult, TargetState


def to_utc_iso(moment: datetime) -> str:
    """One canonical timestamp format.

    Fixed-width UTC ISO, so lexicographic string comparison in a query is also
    chronological comparison.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _now() -> str:
    return to_utc_iso(datetime.now(timezone.utc))


def _hide_password(url: str) -> str:
    """Connection strings carry credentials, and this one ends up in logs."""
    return re.sub(r"://[^@/]+@", "://***@", url)


class Store:
    def __init__(
        self,
        mongo_url: str,
        db_name: str,
        encryption_key: str,
        client: MongoClient | None = None,
    ) -> None:
        # `client` is for tests, which pass a mongomock client rather than
        # standing up a real server.
        self._client = client or MongoClient(
            mongo_url,
            tz_aware=False,
            # Default is 30s. A wrong or unreachable MONGO_URL should say so
            # quickly rather than hanging the startup.
            serverSelectionTimeoutMS=5000,
        )
        self._db = self._client[db_name]
        self._encryption_key = encryption_key
        try:
            self._ensure_indexes()
        except PyMongoError as exc:
            raise RuntimeError(
                f"Cannot reach MongoDB at {_hide_password(mongo_url)} - {exc.__class__.__name__}. "
                "Check MONGO_URL in backend/.env, and that your IP is allowed "
                "in the Atlas cluster's Network Access list."
            ) from exc

    @property
    def users(self):
        return self._db.users

    @property
    def sessions(self):
        return self._db.sessions

    @property
    def accounts(self):
        return self._db.accounts

    @property
    def posts(self):
        return self._db.posts

    @property
    def targets(self):
        return self._db.post_targets

    def _ensure_indexes(self) -> None:
        # Unique on the lowercased email, which is how SQLite's COLLATE NOCASE
        # behaved: one account per address, whatever its capitalisation.
        self.users.create_index("email_key", unique=True)
        self.accounts.create_index([("user_id", ASCENDING), ("platform", ASCENDING)])
        self.posts.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
        self.posts.create_index("scheduled_at")
        self.targets.create_index([("post_id", ASCENDING), ("platform", ASCENDING)])
        self.targets.create_index("state")

    # --- token encryption ------------------------------------------------

    @property
    def fernet(self) -> Fernet:
        if not self._encryption_key:
            raise RuntimeError(
                "TOKEN_ENCRYPTION_KEY is not set, so tokens cannot be stored. "
                "Generate one with: "
                'py -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"'
            )
        return Fernet(self._encryption_key.encode())

    def _encrypt(self, value: str | None) -> bytes | None:
        return self.fernet.encrypt(value.encode()) if value is not None else None

    def _decrypt(self, value: bytes | None) -> str | None:
        if value is None:
            return None
        try:
            return self.fernet.decrypt(bytes(value)).decode()
        except InvalidToken:
            # The key changed. Treat it as disconnected rather than crashing:
            # reconnecting the account is the only real fix anyway.
            return None

    @contextmanager
    def connect(self) -> Iterator["Store"]:
        """Kept so callers written against the old API still read naturally."""
        yield self

    @staticmethod
    def _account_key(platform: "Platform | str") -> str:
        """The `accounts` key. Usually a Platform, but the interim Meta user
        token is parked under a plain string key."""
        return platform.value if isinstance(platform, Platform) else platform

    # --- users and sessions ----------------------------------------------

    def create_user(self, email: str, password_hash: str) -> str | None:
        """Returns the new user id, or None if the email is already taken."""
        user_id = uuid.uuid4().hex
        try:
            self.users.insert_one(
                {
                    "_id": user_id,
                    "email": email.strip(),
                    "email_key": email.strip().lower(),
                    "password_hash": password_hash,
                    "created_at": _now(),
                }
            )
        except DuplicateKeyError:
            return None
        return user_id

    def get_user_by_email(self, email: str) -> dict | None:
        doc = self.users.find_one({"email_key": email.strip().lower()})
        return self._user_dict(doc, with_hash=True) if doc else None

    def get_user(self, user_id: str) -> dict | None:
        doc = self.users.find_one({"_id": user_id})
        return self._user_dict(doc) if doc else None

    @staticmethod
    def _user_dict(doc: dict, with_hash: bool = False) -> dict:
        out = {
            "id": doc["_id"],
            "email": doc["email"],
            "created_at": doc["created_at"],
        }
        if with_hash:
            out["password_hash"] = doc["password_hash"]
        return out

    def count_users(self) -> int:
        return self.users.count_documents({})

    def adopt_unowned_accounts(self, user_id: str) -> int:
        """Hand connections made before sign-up existed to their first owner.

        The account key is "<user_id>:<platform>" and Mongo cannot update an
        _id, so each one is re-inserted under its new key rather than edited
        in place.
        """
        adopted = 0
        for doc in list(self.accounts.find({"user_id": ""})):
            old_id = doc["_id"]
            doc["_id"] = f"{user_id}:{doc['platform']}"
            doc["user_id"] = user_id
            self.accounts.delete_one({"_id": old_id})
            self.accounts.insert_one(doc)
            adopted += 1

        self.posts.update_many({"user_id": ""}, {"$set": {"user_id": user_id}})
        return adopted

    def create_session(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        self.sessions.insert_one(
            {"_id": token, "user_id": user_id, "created_at": _now()}
        )
        return token

    def user_for_session(self, token: str) -> dict | None:
        if not token:
            return None
        session = self.sessions.find_one({"_id": token})
        if session is None:
            return None
        user = self.users.find_one({"_id": session["user_id"]})
        return {"id": user["_id"], "email": user["email"]} if user else None

    def delete_session(self, token: str) -> None:
        self.sessions.delete_one({"_id": token})

    # --- accounts ---------------------------------------------------------

    def save_account(
        self,
        user_id: str,
        platform: "Platform | str",
        *,
        external_id: str | None,
        display_name: str | None,
        access_token: str | None,
        refresh_token: str | None = None,
        expires_at: str | None = None,
        extra: dict | None = None,
    ) -> None:
        key = self._account_key(platform)
        update = {
            "user_id": user_id,
            "platform": key,
            "external_id": external_id,
            "display_name": display_name,
            "access_token": self._encrypt(access_token),
            "expires_at": expires_at,
            "extra": json.dumps(extra or {}),
            "updated_at": _now(),
        }
        # A reconnect that returns no refresh token must not wipe the one we
        # already hold — Google only issues it on the first consent.
        encrypted_refresh = self._encrypt(refresh_token)
        if encrypted_refresh is not None:
            update["refresh_token"] = encrypted_refresh

        if encrypted_refresh is not None:
            # Writing it in $set and $setOnInsert at once is a conflicting path
            # error, so only one of the two ever mentions refresh_token.
            change = {"$set": {**update, "refresh_token": encrypted_refresh}}
        else:
            change = {"$set": update, "$setOnInsert": {"refresh_token": None}}

        self.accounts.update_one({"_id": f"{user_id}:{key}"}, change, upsert=True)

    def get_account(self, user_id: str, platform: "Platform | str") -> dict | None:
        doc = self.accounts.find_one(
            {"_id": f"{user_id}:{self._account_key(platform)}"}
        )
        if doc is None:
            return None
        return {
            "platform": doc["platform"],
            "external_id": doc.get("external_id"),
            "display_name": doc.get("display_name"),
            "access_token": self._decrypt(doc.get("access_token")),
            "refresh_token": self._decrypt(doc.get("refresh_token")),
            "expires_at": doc.get("expires_at"),
            "extra": json.loads(doc.get("extra") or "{}"),
        }

    def list_connections(self, user_id: str) -> list[dict]:
        """Connection status for the UI. Never returns token material."""
        rows = {
            doc["platform"]: doc for doc in self.accounts.find({"user_id": user_id})
        }
        return [
            {
                "platform": platform.value,
                "connected": platform.value in rows,
                "displayName": rows.get(platform.value, {}).get("display_name"),
                "externalId": rows.get(platform.value, {}).get("external_id"),
            }
            for platform in Platform
        ]

    def delete_account(self, user_id: str, platform: "Platform | str") -> None:
        self.accounts.delete_one({"_id": f"{user_id}:{self._account_key(platform)}"})

    # --- posts ------------------------------------------------------------

    def create_post(
        self,
        *,
        user_id: str,
        title: str,
        caption: str,
        filename: str,
        media_path: Path,
        targets: list[Platform],
        scheduled_at: str,
    ) -> str:
        """Create a post due at `scheduled_at` (canonical UTC ISO).

        Targets start SCHEDULED even when the time is now — "post now" and
        "post later" are the same code path, so there is only one way a post
        can reach a platform.
        """
        post_id = uuid.uuid4().hex
        now = _now()
        self.posts.insert_one(
            {
                "_id": post_id,
                "user_id": user_id,
                "created_at": now,
                "scheduled_at": scheduled_at,
                "canceled_at": None,
                "title": title,
                "caption": caption,
                "filename": filename,
                "media_path": str(media_path),
            }
        )
        if targets:
            self.targets.insert_many(
                [
                    {
                        "_id": f"{post_id}:{p.value}",
                        "post_id": post_id,
                        "platform": p.value,
                        "state": TargetState.SCHEDULED.value,
                        "url": None,
                        "external_id": None,
                        "error": None,
                        "raw": None,
                        "updated_at": now,
                    }
                    for p in targets
                ]
            )
        return post_id

    # --- scheduling -------------------------------------------------------

    def claim_due_targets(self, now_iso: str) -> list[tuple[str, Platform, str]]:
        """Move every due SCHEDULED target to PENDING and return it.

        Each flip is a single `find_one_and_update`, which MongoDB applies
        atomically to one document. That is what stops a slow publish from
        being picked up twice by the next scheduler tick: the second claim
        matches nothing, because the state is no longer SCHEDULED.
        """
        claimed: list[tuple[str, Platform, str]] = []
        due_posts = self.posts.find(
            {"canceled_at": None, "scheduled_at": {"$lte": now_iso}}
        ).sort("scheduled_at", ASCENDING)

        for post in due_posts:
            targets = self.targets.find(
                {"post_id": post["_id"], "state": TargetState.SCHEDULED.value}
            ).sort("platform", ASCENDING)
            for target in list(targets):
                won = self.targets.find_one_and_update(
                    {"_id": target["_id"], "state": TargetState.SCHEDULED.value},
                    {
                        "$set": {
                            "state": TargetState.PENDING.value,
                            "updated_at": _now(),
                        }
                    },
                    return_document=ReturnDocument.AFTER,
                )
                if won is not None:
                    claimed.append(
                        (post["_id"], Platform(target["platform"]), post["user_id"])
                    )
        return claimed

    def cancel_post(self, post_id: str, user_id: str) -> int:
        """Cancel the legs that have not gone out yet.

        Anything already published, failed or in flight is left alone — you
        cannot unsend a video.
        """
        if self.posts.find_one({"_id": post_id, "user_id": user_id}) is None:
            return 0

        canceled = self.targets.update_many(
            {"post_id": post_id, "state": TargetState.SCHEDULED.value},
            {"$set": {"state": TargetState.CANCELED.value, "updated_at": _now()}},
        ).modified_count
        self.posts.update_one(
            {"_id": post_id, "user_id": user_id}, {"$set": {"canceled_at": _now()}}
        )
        return canceled

    def reschedule_post(self, post_id: str, scheduled_at: str, user_id: str) -> None:
        self.posts.update_one(
            {"_id": post_id, "user_id": user_id},
            {"$set": {"scheduled_at": scheduled_at, "canceled_at": None}},
        )

    def recover_interrupted(self) -> dict[str, int]:
        """Clean up after a process that died mid-publish.

        PENDING means claimed but not started, so it is safe to put back in the
        queue. UPLOADING is ambiguous — bytes may already have reached the
        platform — so it is failed with an explanation rather than retried
        automatically, because a silent duplicate upload is worse than a
        message asking you to check.
        """
        requeued = self.targets.update_many(
            {"state": TargetState.PENDING.value},
            {"$set": {"state": TargetState.SCHEDULED.value, "updated_at": _now()}},
        ).modified_count
        interrupted = self.targets.update_many(
            {"state": TargetState.UPLOADING.value},
            {
                "$set": {
                    "state": TargetState.FAILED.value,
                    "error": "Interrupted by a restart while uploading. Check the "
                    "platform before retrying — the upload may have completed.",
                    "updated_at": _now(),
                }
            },
        ).modified_count
        return {"requeued": requeued, "interrupted": interrupted}

    def set_target_state(
        self, post_id: str, platform: Platform, state: TargetState
    ) -> None:
        self.targets.update_one(
            {"_id": f"{post_id}:{platform.value}"},
            {"$set": {"state": state.value, "updated_at": _now()}},
        )

    def set_target_result(
        self, post_id: str, platform: Platform, result: PublishResult
    ) -> None:
        self.targets.update_one(
            {"_id": f"{post_id}:{platform.value}"},
            {
                "$set": {
                    "state": result.state.value,
                    "url": result.url,
                    "external_id": result.external_id,
                    "error": result.error,
                    "raw": result.raw,
                    "updated_at": _now(),
                }
            },
        )

    def get_post(self, post_id: str, user_id: str | None = None) -> dict | None:
        """user_id=None skips the ownership check, for the publish worker,
        which has already resolved the owner from the claimed target."""
        query = {"_id": post_id}
        if user_id is not None:
            query["user_id"] = user_id
        post = self.posts.find_one(query)
        if post is None:
            return None
        return _post_to_dict(post, self._targets_for(post_id))

    def list_posts(self, user_id: str, limit: int = 25) -> list[dict]:
        posts = (
            self.posts.find({"user_id": user_id})
            .sort("created_at", DESCENDING)
            .limit(limit)
        )
        return [_post_to_dict(p, self._targets_for(p["_id"])) for p in posts]

    def _targets_for(self, post_id: str) -> list[dict]:
        return list(
            self.targets.find({"post_id": post_id}).sort("platform", ASCENDING)
        )


def _post_to_dict(post: dict, targets: list[dict]) -> dict:
    return {
        "id": post["_id"],
        "userId": post["user_id"],
        "createdAt": post["created_at"],
        "scheduledAt": post["scheduled_at"],
        "canceledAt": post.get("canceled_at"),
        "title": post["title"],
        "caption": post["caption"],
        "filename": post["filename"],
        "mediaPath": post["media_path"],
        "targets": [
            {
                "platform": t["platform"],
                "state": t["state"],
                "url": t.get("url"),
                "externalId": t.get("external_id"),
                "error": t.get("error"),
                "updatedAt": t["updated_at"],
            }
            for t in targets
        ],
    }
