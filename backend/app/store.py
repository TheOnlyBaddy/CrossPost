"""SQLite persistence. Tokens are encrypted at rest with Fernet.

v1 holds at most one connected account per platform, which is why `accounts`
is keyed on platform alone. Multiple accounts per platform is a v2 feature.
"""

import json
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from cryptography.fernet import Fernet, InvalidToken

from .models import Platform, PublishResult, TargetState

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS accounts (
    user_id       TEXT NOT NULL,
    platform      TEXT NOT NULL,
    external_id   TEXT,
    display_name  TEXT,
    access_token  BLOB,
    refresh_token BLOB,
    expires_at    TEXT,
    extra         TEXT NOT NULL DEFAULT '{}',
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (user_id, platform)
);

CREATE TABLE IF NOT EXISTS posts (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    scheduled_at TEXT NOT NULL,
    canceled_at  TEXT,
    title        TEXT NOT NULL,
    caption      TEXT NOT NULL,
    filename     TEXT NOT NULL,
    media_path   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_posts_scheduled_at ON posts(scheduled_at);

CREATE TABLE IF NOT EXISTS post_targets (
    post_id     TEXT NOT NULL,
    platform    TEXT NOT NULL,
    state       TEXT NOT NULL,
    url         TEXT,
    external_id TEXT,
    error       TEXT,
    raw         TEXT,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (post_id, platform),
    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
);
"""


def to_utc_iso(moment: datetime) -> str:
    """One canonical timestamp format.

    Fixed-width UTC ISO, so lexicographic string comparison in SQL is also
    chronological comparison. Everything written to the database goes through
    here; naive datetimes are assumed to be UTC.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _now() -> str:
    return to_utc_iso(datetime.now(timezone.utc))


class Store:
    def __init__(self, db_path: Path, encryption_key: str) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._encryption_key = encryption_key
        self._fernet: Fernet | None = None
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Additive migrations for databases created before a column existed.

        SQLite has no ADD COLUMN IF NOT EXISTS, so check first.
        """
        account_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(accounts)")
        }
        if account_columns and "user_id" not in account_columns:
            # The primary key changes from (platform) to (user_id, platform),
            # which SQLite cannot ALTER, so the table is rebuilt. Existing rows
            # are kept with an empty owner and handed to the first account that
            # signs up — losing a working OAuth token is worse than the extra
            # few lines here.
            conn.execute("ALTER TABLE accounts RENAME TO accounts_pre_users")
            conn.executescript(SCHEMA)
            conn.execute(
                """
                INSERT INTO accounts (user_id, platform, external_id, display_name,
                                      access_token, refresh_token, expires_at,
                                      extra, updated_at)
                SELECT '', platform, external_id, display_name, access_token,
                       refresh_token, expires_at, extra, updated_at
                  FROM accounts_pre_users
                """
            )
            conn.execute("DROP TABLE accounts_pre_users")

        columns = {row["name"] for row in conn.execute("PRAGMA table_info(posts)")}
        if "user_id" not in columns:
            conn.execute(
                "ALTER TABLE posts ADD COLUMN user_id TEXT NOT NULL DEFAULT ''"
            )
        if "scheduled_at" not in columns:
            # Existing rows were published immediately, so their schedule time
            # is their creation time.
            conn.execute("ALTER TABLE posts ADD COLUMN scheduled_at TEXT NOT NULL DEFAULT ''")
            conn.execute("UPDATE posts SET scheduled_at = created_at WHERE scheduled_at = ''")
        if "canceled_at" not in columns:
            conn.execute("ALTER TABLE posts ADD COLUMN canceled_at TEXT")

    # --- encryption -----------------------------------------------------

    @property
    def fernet(self) -> Fernet:
        if self._fernet is None:
            if not self._encryption_key:
                raise RuntimeError(
                    "TOKEN_ENCRYPTION_KEY is not set, so OAuth tokens cannot be "
                    "stored. Generate one with: py -c \"from cryptography.fernet "
                    "import Fernet; print(Fernet.generate_key().decode())\""
                )
            self._fernet = Fernet(self._encryption_key.encode())
        return self._fernet

    def _encrypt(self, value: str | None) -> bytes | None:
        return self.fernet.encrypt(value.encode()) if value else None

    def _decrypt(self, value: bytes | None) -> str | None:
        if not value:
            return None
        try:
            return self.fernet.decrypt(value).decode()
        except InvalidToken:
            # Key rotated or corrupted — treat as "not connected" rather than
            # crashing the request.
            return None

    # --- plumbing -------------------------------------------------------

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- accounts -------------------------------------------------------

    @staticmethod
    def _account_key(platform: "Platform | str") -> str:
        """The `accounts` table key. Usually a Platform, but the interim Meta
        user token is parked under a plain string key."""
        return platform.value if isinstance(platform, Platform) else platform

    # --- users and sessions ---------------------------------------------

    def create_user(self, email: str, password_hash: str) -> str | None:
        """Returns the new user id, or None if the email is already taken."""
        user_id = uuid.uuid4().hex
        try:
            with self.connect() as conn:
                conn.execute(
                    "INSERT INTO users (id, email, password_hash, created_at)"
                    " VALUES (?, ?, ?, ?)",
                    (user_id, email.strip(), password_hash, _now()),
                )
        except sqlite3.IntegrityError:
            return None
        return user_id

    def get_user_by_email(self, email: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ?", (email.strip(),)
            ).fetchone()
        return dict(row) if row else None

    def get_user(self, user_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id, email, created_at FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return dict(row) if row else None

    def count_users(self) -> int:
        with self.connect() as conn:
            return conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]

    def adopt_unowned_accounts(self, user_id: str) -> int:
        """Hand connections made before sign-up existed to their first owner."""
        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE accounts SET user_id = ? WHERE user_id = ''", (user_id,)
            )
            conn.execute(
                "UPDATE posts SET user_id = ? WHERE user_id = ''", (user_id,)
            )
            return cursor.rowcount

    def create_session(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
                (token, user_id, _now()),
            )
        return token

    def user_for_session(self, token: str) -> dict | None:
        if not token:
            return None
        with self.connect() as conn:
            row = conn.execute(
                "SELECT u.id, u.email FROM sessions s JOIN users u ON u.id = s.user_id"
                " WHERE s.token = ?",
                (token,),
            ).fetchone()
        return dict(row) if row else None

    def delete_session(self, token: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))

    # --- accounts --------------------------------------------------------

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
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO accounts (user_id, platform, external_id, display_name,
                                      access_token, refresh_token, expires_at,
                                      extra, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, platform) DO UPDATE SET
                    external_id = excluded.external_id,
                    display_name = excluded.display_name,
                    access_token = excluded.access_token,
                    refresh_token = COALESCE(excluded.refresh_token, accounts.refresh_token),
                    expires_at = excluded.expires_at,
                    extra = excluded.extra,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    self._account_key(platform),
                    external_id,
                    display_name,
                    self._encrypt(access_token),
                    self._encrypt(refresh_token),
                    expires_at,
                    json.dumps(extra or {}),
                    _now(),
                ),
            )

    def get_account(self, user_id: str, platform: "Platform | str") -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM accounts WHERE user_id = ? AND platform = ?",
                (user_id, self._account_key(platform)),
            ).fetchone()
        if row is None:
            return None
        return {
            "platform": row["platform"],
            "external_id": row["external_id"],
            "display_name": row["display_name"],
            "access_token": self._decrypt(row["access_token"]),
            "refresh_token": self._decrypt(row["refresh_token"]),
            "expires_at": row["expires_at"],
            "extra": json.loads(row["extra"] or "{}"),
        }

    def list_connections(self, user_id: str) -> list[dict]:
        """Connection status for the UI. Never returns token material."""
        out = []
        with self.connect() as conn:
            rows = {
                r["platform"]: r
                for r in conn.execute(
                    "SELECT * FROM accounts WHERE user_id = ?", (user_id,)
                )
            }
        for platform in Platform:
            row = rows.get(platform.value)
            out.append(
                {
                    "platform": platform.value,
                    "connected": row is not None,
                    "displayName": row["display_name"] if row else None,
                    "externalId": row["external_id"] if row else None,
                }
            )
        return out

    def delete_account(self, user_id: str, platform: "Platform | str") -> None:
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM accounts WHERE user_id = ? AND platform = ?",
                (user_id, self._account_key(platform)),
            )

    # --- posts ----------------------------------------------------------

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
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO posts (id, user_id, created_at, scheduled_at, title,"
                " caption, filename, media_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    post_id,
                    user_id,
                    now,
                    scheduled_at,
                    title,
                    caption,
                    filename,
                    str(media_path),
                ),
            )
            conn.executemany(
                "INSERT INTO post_targets (post_id, platform, state, updated_at)"
                " VALUES (?, ?, ?, ?)",
                [(post_id, p.value, TargetState.SCHEDULED.value, now) for p in targets],
            )
        return post_id

    # --- scheduling -----------------------------------------------------

    def claim_due_targets(self, now_iso: str) -> list[tuple[str, Platform, str]]:
        """Atomically move every due SCHEDULED target to PENDING and return it.

        Claiming inside the transaction is what stops a slow publish from
        being picked up twice by the next scheduler tick.
        """
        claimed: list[tuple[str, Platform, str]] = []
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT t.post_id, t.platform, p.user_id
                  FROM post_targets t
                  JOIN posts p ON p.id = t.post_id
                 WHERE t.state = ?
                   AND p.canceled_at IS NULL
                   AND p.scheduled_at <= ?
                 ORDER BY p.scheduled_at, t.platform
                """,
                (TargetState.SCHEDULED.value, now_iso),
            ).fetchall()

            for row in rows:
                conn.execute(
                    "UPDATE post_targets SET state = ?, updated_at = ?"
                    " WHERE post_id = ? AND platform = ?",
                    (TargetState.PENDING.value, _now(), row["post_id"], row["platform"]),
                )
                claimed.append(
                    (row["post_id"], Platform(row["platform"]), row["user_id"])
                )
        return claimed

    def cancel_post(self, post_id: str, user_id: str) -> int:
        """Cancel the legs that have not gone out yet.

        Anything already published, failed or in flight is left alone — you
        cannot unsend a video.
        """
        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE post_targets SET state = ?, updated_at = ?"
                " WHERE post_id = ? AND state = ?"
                " AND post_id IN (SELECT id FROM posts WHERE user_id = ?)",
                (
                    TargetState.CANCELED.value,
                    _now(),
                    post_id,
                    TargetState.SCHEDULED.value,
                    user_id,
                ),
            )
            canceled = cursor.rowcount
            conn.execute(
                "UPDATE posts SET canceled_at = ? WHERE id = ? AND user_id = ?",
                (_now(), post_id, user_id),
            )
        return canceled

    def reschedule_post(self, post_id: str, scheduled_at: str, user_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE posts SET scheduled_at = ?, canceled_at = NULL"
                " WHERE id = ? AND user_id = ?",
                (scheduled_at, post_id, user_id),
            )

    def recover_interrupted(self) -> dict[str, int]:
        """Clean up after a process that died mid-publish.

        PENDING means claimed but not started, so it is safe to put back in the
        queue. UPLOADING is ambiguous — bytes may already have reached the
        platform — so it is failed with an explanation rather than retried
        automatically, because a silent duplicate upload is worse than a
        message asking you to check.
        """
        with self.connect() as conn:
            requeued = conn.execute(
                "UPDATE post_targets SET state = ?, updated_at = ? WHERE state = ?",
                (TargetState.SCHEDULED.value, _now(), TargetState.PENDING.value),
            ).rowcount
            interrupted = conn.execute(
                """
                UPDATE post_targets
                   SET state = ?, error = ?, updated_at = ?
                 WHERE state = ?
                """,
                (
                    TargetState.FAILED.value,
                    "Interrupted by a restart while uploading. Check the platform "
                    "before retrying — the upload may have completed.",
                    _now(),
                    TargetState.UPLOADING.value,
                ),
            ).rowcount
        return {"requeued": requeued, "interrupted": interrupted}

    def set_target_state(
        self, post_id: str, platform: Platform, state: TargetState
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE post_targets SET state = ?, updated_at = ?"
                " WHERE post_id = ? AND platform = ?",
                (state.value, _now(), post_id, platform.value),
            )

    def set_target_result(
        self, post_id: str, platform: Platform, result: PublishResult
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE post_targets
                   SET state = ?, url = ?, external_id = ?, error = ?, raw = ?,
                       updated_at = ?
                 WHERE post_id = ? AND platform = ?
                """,
                (
                    result.state.value,
                    result.url,
                    result.external_id,
                    result.error,
                    result.raw,
                    _now(),
                    post_id,
                    platform.value,
                ),
            )

    def get_post(self, post_id: str, user_id: str | None = None) -> dict | None:
        """user_id=None skips the ownership check, for the publish worker,
        which has already resolved the owner from the claimed target."""
        with self.connect() as conn:
            if user_id is None:
                post = conn.execute(
                    "SELECT * FROM posts WHERE id = ?", (post_id,)
                ).fetchone()
            else:
                post = conn.execute(
                    "SELECT * FROM posts WHERE id = ? AND user_id = ?",
                    (post_id, user_id),
                ).fetchone()
            if post is None:
                return None
            targets = conn.execute(
                "SELECT * FROM post_targets WHERE post_id = ? ORDER BY platform",
                (post_id,),
            ).fetchall()
        return _post_to_dict(post, targets)

    def list_posts(self, user_id: str, limit: int = 25) -> list[dict]:
        with self.connect() as conn:
            posts = conn.execute(
                "SELECT * FROM posts WHERE user_id = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
            out = []
            for post in posts:
                targets = conn.execute(
                    "SELECT * FROM post_targets WHERE post_id = ? ORDER BY platform",
                    (post["id"],),
                ).fetchall()
                out.append(_post_to_dict(post, targets))
        return out


def _post_to_dict(post: sqlite3.Row, targets: list[sqlite3.Row]) -> dict:
    return {
        "id": post["id"],
        "userId": post["user_id"],
        "createdAt": post["created_at"],
        "scheduledAt": post["scheduled_at"],
        "canceledAt": post["canceled_at"],
        "title": post["title"],
        "caption": post["caption"],
        "filename": post["filename"],
        "mediaPath": post["media_path"],
        "targets": [
            {
                "platform": t["platform"],
                "state": t["state"],
                "url": t["url"],
                "externalId": t["external_id"],
                "error": t["error"],
                "updatedAt": t["updated_at"],
            }
            for t in targets
        ],
    }
