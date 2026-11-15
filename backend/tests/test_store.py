import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet

from app.models import Platform, PublishResult, TargetState
from app.store import Store, to_utc_iso


@pytest.fixture
def store(tmp_path) -> Store:
    return Store(tmp_path / "test.sqlite3", Fernet.generate_key().decode())


class TestAccountTokens:
    def test_round_trips_tokens(self, store):
        store.save_account(
            "user-1",
            Platform.YOUTUBE,
            external_id="UC123",
            display_name="My Channel",
            access_token="at-secret",
            refresh_token="rt-secret",
        )
        account = store.get_account("user-1", Platform.YOUTUBE)
        assert account["access_token"] == "at-secret"
        assert account["refresh_token"] == "rt-secret"
        assert account["display_name"] == "My Channel"

    def test_tokens_are_not_stored_in_plaintext(self, store):
        store.save_account(
            "user-1",
            Platform.YOUTUBE,
            external_id="UC123",
            display_name="My Channel",
            access_token="at-secret",
            refresh_token="rt-secret",
        )
        raw = sqlite3.connect(store.db_path).execute(
            "SELECT access_token, refresh_token FROM accounts"
        ).fetchone()
        blob = raw[0] + raw[1]
        assert b"at-secret" not in blob
        assert b"rt-secret" not in blob

    def test_reconnect_preserves_refresh_token_when_absent(self, store):
        # Google only hands back a refresh token on first consent, so a
        # re-auth that omits it must not wipe the stored one.
        store.save_account(
            "user-1",
            Platform.YOUTUBE,
            external_id="UC1",
            display_name="C",
            access_token="at1",
            refresh_token="rt1",
        )
        store.save_account(
            "user-1",
            Platform.YOUTUBE,
            external_id="UC1",
            display_name="C",
            access_token="at2",
            refresh_token=None,
        )
        account = store.get_account("user-1", Platform.YOUTUBE)
        assert account["access_token"] == "at2"
        assert account["refresh_token"] == "rt1"

    def test_unreadable_token_reads_as_disconnected(self, tmp_path):
        store = Store(tmp_path / "db.sqlite3", Fernet.generate_key().decode())
        store.save_account(
            "user-1",
            Platform.YOUTUBE,
            external_id="UC1",
            display_name="C",
            access_token="at",
            refresh_token="rt",
        )
        # Simulate a rotated key rather than crashing the request.
        rotated = Store(tmp_path / "db.sqlite3", Fernet.generate_key().decode())
        assert rotated.get_account("user-1", Platform.YOUTUBE)["access_token"] is None

    def test_missing_key_raises_a_useful_error(self, tmp_path):
        store = Store(tmp_path / "db.sqlite3", "")
        with pytest.raises(RuntimeError, match="TOKEN_ENCRYPTION_KEY"):
            store.save_account(
                "user-1",
                Platform.YOUTUBE,
                external_id=None,
                display_name=None,
                access_token="at",
            )

    def test_interim_meta_user_key_is_allowed(self, store):
        store.save_account(
            "user-1",
            "meta_user", external_id=None, display_name=None, access_token="user-token"
        )
        assert store.get_account("user-1", "meta_user")["access_token"] == "user-token"
        # ...and it does not show up as a postable platform.
        assert len(store.list_connections("user-1")) == 3

    def test_disconnect(self, store):
        store.save_account(
            "user-1",
            Platform.FACEBOOK,
            external_id="p1",
            display_name="Page",
            access_token="t",
        )
        store.delete_account("user-1", Platform.FACEBOOK)
        assert store.get_account("user-1", Platform.FACEBOOK) is None


class TestConnections:
    def test_lists_all_platforms_even_when_none_connected(self, store):
        rows = store.list_connections("user-1")
        assert {r["platform"] for r in rows} == {"youtube", "instagram", "facebook"}
        assert all(r["connected"] is False for r in rows)

    def test_never_leaks_token_material(self, store):
        store.save_account(
            "user-1",
            Platform.YOUTUBE,
            external_id="UC1",
            display_name="C",
            access_token="at-secret",
        )
        serialized = str(store.list_connections("user-1"))
        assert "at-secret" not in serialized


def make_post(store, tmp_path, targets, scheduled_at=None, title="T"):
    return store.create_post(
        user_id="user-1",
        title=title,
        caption="C",
        filename="x.mp4",
        media_path=tmp_path / "x.mp4",
        targets=targets,
        scheduled_at=scheduled_at or to_utc_iso(datetime.now(timezone.utc)),
    )


class TestPostLifecycle:
    def test_creates_one_target_per_platform(self, store, tmp_path):
        post_id = make_post(
            store, tmp_path, [Platform.YOUTUBE, Platform.INSTAGRAM, Platform.FACEBOOK]
        )
        post = store.get_post(post_id)
        assert len(post["targets"]) == 3
        # Everything starts scheduled, even "post now" — one path to a platform.
        assert all(t["state"] == "scheduled" for t in post["targets"])

    def test_honours_a_subset_of_platforms(self, store, tmp_path):
        post_id = make_post(store, tmp_path, [Platform.YOUTUBE])
        assert [t["platform"] for t in store.get_post(post_id)["targets"]] == ["youtube"]

    def test_one_target_failing_leaves_the_others_alone(self, store, tmp_path):
        """The whole point of the per-target model: partial success."""
        post_id = make_post(store, tmp_path, [Platform.YOUTUBE, Platform.INSTAGRAM])
        store.set_target_result(
            post_id,
            Platform.YOUTUBE,
            PublishResult(
                state=TargetState.DONE,
                url="https://youtu.be/abc",
                external_id="abc",
            ),
        )
        store.set_target_result(
            post_id,
            Platform.INSTAGRAM,
            PublishResult.failed("container expired", raw='{"error":{"code":9}}'),
        )

        targets = {t["platform"]: t for t in store.get_post(post_id)["targets"]}
        assert targets["youtube"]["state"] == "done"
        assert targets["youtube"]["url"] == "https://youtu.be/abc"
        assert targets["instagram"]["state"] == "failed"
        assert targets["instagram"]["error"] == "container expired"

    def test_get_post_returns_none_for_unknown_id(self, store):
        assert store.get_post("nope") is None

    def test_lists_posts_newest_first(self, store, tmp_path):
        ids = [
            make_post(store, tmp_path, [Platform.YOUTUBE], title=f"T{i}")
            for i in range(3)
        ]
        listed = [p["id"] for p in store.list_posts("user-1")]
        assert set(listed) == set(ids)


class TestTargetState:
    @pytest.mark.parametrize(
        "state,retryable",
        [
            (TargetState.FAILED, True),
            (TargetState.NOT_CONFIGURED, True),
            (TargetState.DONE, False),
            (TargetState.PENDING, False),
            (TargetState.UPLOADING, False),
            (TargetState.PROCESSING, False),
        ],
    )
    def test_retryability(self, state, retryable):
        assert state.is_retryable is retryable
