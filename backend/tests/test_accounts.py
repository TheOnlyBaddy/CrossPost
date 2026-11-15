"""Sign-up, sign-in, and the thing that actually matters once there is more
than one account: that one user cannot see or touch another user's work."""

from app.passwords import hash_password, verify_password
from app.store import Store


class TestPasswords:
    def test_round_trips(self):
        stored = hash_password("correct horse battery")
        assert verify_password("correct horse battery", stored)

    def test_rejects_the_wrong_password(self):
        assert not verify_password("nope", hash_password("correct horse battery"))

    def test_hash_is_not_the_password(self):
        stored = hash_password("correct horse battery")
        assert "correct horse battery" not in stored
        assert stored.startswith("scrypt$")

    def test_same_password_hashes_differently(self):
        """Per-password salt, so a stolen table cannot be attacked in bulk."""
        assert hash_password("same") != hash_password("same")

    def test_garbage_in_the_column_is_not_a_match(self):
        assert not verify_password("anything", "")
        assert not verify_password("anything", "bcrypt$whatever")


class TestSignUp:
    def test_creates_a_session(self, anon_client):
        client = anon_client.__class__(anon_client.app)
        response = client.post(
            "/api/users", json={"email": "first@example.com", "password": "a" * 12}
        )
        assert response.status_code == 201
        assert client.cookies.get("crosspost_session")
        assert client.get("/api/session").json()["email"] == "first@example.com"

    def test_rejects_a_duplicate_email(self, client, anon_client):
        response = anon_client.post(
            "/api/users",
            json={"email": "tester@example.com", "password": "a" * 12},
        )
        assert response.status_code == 409

    def test_rejects_a_short_password(self, anon_client):
        response = anon_client.post(
            "/api/users", json={"email": "short@example.com", "password": "abc"}
        )
        assert response.status_code == 422

    def test_rejects_a_non_email(self, anon_client):
        response = anon_client.post(
            "/api/users", json={"email": "not-an-email", "password": "a" * 12}
        )
        assert response.status_code == 422


class TestSignIn:
    def test_wrong_password_is_refused(self, client, anon_client):
        response = anon_client.post(
            "/api/session",
            json={"email": "tester@example.com", "password": "wrong"},
        )
        assert response.status_code == 401

    def test_unknown_email_gives_the_same_answer(self, anon_client):
        """Same status and message, so this cannot be used to discover which
        emails have accounts."""
        response = anon_client.post(
            "/api/session",
            json={"email": "nobody@example.com", "password": "whatever"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Wrong email or password"


class TestRoutesRequireASession:
    def test_posts_are_refused(self, anon_client):
        assert anon_client.get("/api/posts").status_code == 401

    def test_connections_are_refused(self, anon_client):
        assert anon_client.get("/api/auth/connections").status_code == 401

    def test_oauth_start_is_refused(self, anon_client):
        assert anon_client.get("/api/auth/youtube/start").status_code == 401

    def test_health_stays_public(self, anon_client):
        """The login page reads it, so it cannot require a session."""
        body = anon_client.get("/api/health").json()
        assert body["ok"] is True
        assert body["user"] is None
        assert body["connections"] == []


class TestIsolation:
    """Two users in one database. Neither should be able to reach the other."""

    def _two_users(self, tmp_path) -> tuple[Store, str, str]:
        from cryptography.fernet import Fernet

        store = Store(tmp_path / "iso.sqlite3", Fernet.generate_key().decode())
        alice = store.create_user("alice@example.com", "x")
        bob = store.create_user("bob@example.com", "x")
        return store, alice, bob

    def _post(self, store, tmp_path, user_id, title):
        from app.models import Platform

        return store.create_post(
            user_id=user_id,
            title=title,
            caption="",
            filename="v.mp4",
            media_path=tmp_path / "v.mp4",
            targets=[Platform.YOUTUBE],
            scheduled_at="2026-01-01T00:00:00.000000+00:00",
        )

    def test_posts_are_not_shared(self, tmp_path):
        store, alice, bob = self._two_users(tmp_path)
        self._post(store, tmp_path, alice, "alice only")

        assert [p["title"] for p in store.list_posts(alice)] == ["alice only"]
        assert store.list_posts(bob) == []

    def test_a_post_cannot_be_read_by_id_across_users(self, tmp_path):
        store, alice, bob = self._two_users(tmp_path)
        post_id = self._post(store, tmp_path, alice, "alice only")

        assert store.get_post(post_id, alice) is not None
        assert store.get_post(post_id, bob) is None

    def test_a_post_cannot_be_cancelled_across_users(self, tmp_path):
        store, alice, bob = self._two_users(tmp_path)
        post_id = self._post(store, tmp_path, alice, "alice only")

        assert store.cancel_post(post_id, bob) == 0
        assert store.get_post(post_id, alice)["canceledAt"] is None
        assert store.cancel_post(post_id, alice) == 1

    def test_connections_are_not_shared(self, tmp_path):
        from app.models import Platform

        store, alice, bob = self._two_users(tmp_path)
        store.save_account(
            alice,
            Platform.YOUTUBE,
            external_id="UC1",
            display_name="Alice's channel",
            access_token="secret",
        )

        assert store.get_account(bob, Platform.YOUTUBE) is None
        assert all(not c["connected"] for c in store.list_connections(bob))
        assert store.get_account(alice, Platform.YOUTUBE)["access_token"] == "secret"

    def test_both_users_can_connect_the_same_platform(self, tmp_path):
        """The primary key is (user_id, platform), so two people each having a
        YouTube account is normal rather than a conflict."""
        from app.models import Platform

        store, alice, bob = self._two_users(tmp_path)
        for user, channel in ((alice, "UC-alice"), (bob, "UC-bob")):
            store.save_account(
                user,
                Platform.YOUTUBE,
                external_id=channel,
                display_name=channel,
                access_token=f"token-{channel}",
            )

        assert store.get_account(alice, Platform.YOUTUBE)["external_id"] == "UC-alice"
        assert store.get_account(bob, Platform.YOUTUBE)["external_id"] == "UC-bob"


class TestAdoption:
    def test_first_user_inherits_connections_made_before_sign_up(self, tmp_path):
        """Upgrading an existing install must not drop a working OAuth token."""
        from cryptography.fernet import Fernet

        from app.models import Platform

        store = Store(tmp_path / "adopt.sqlite3", Fernet.generate_key().decode())
        store.save_account(
            "",
            Platform.YOUTUBE,
            external_id="UC1",
            display_name="Legacy channel",
            access_token="legacy",
        )

        user_id = store.create_user("owner@example.com", "x")
        assert store.adopt_unowned_accounts(user_id) == 1
        assert store.get_account(user_id, Platform.YOUTUBE)["display_name"] == (
            "Legacy channel"
        )

    def test_a_second_user_inherits_nothing(self, tmp_path):
        from cryptography.fernet import Fernet

        from app.models import Platform

        store = Store(tmp_path / "adopt2.sqlite3", Fernet.generate_key().decode())
        store.save_account(
            "", Platform.YOUTUBE, external_id="UC1", display_name="L", access_token="t"
        )
        first = store.create_user("first@example.com", "x")
        store.adopt_unowned_accounts(first)

        second = store.create_user("second@example.com", "x")
        assert store.adopt_unowned_accounts(second) == 0
        assert store.get_account(second, Platform.YOUTUBE) is None


class TestSocialLogin:
    """The redirect the provider gets, and the account the callback lands in.

    The round trip itself needs Google or Meta, so what is checked here is
    everything on this side of it.
    """

    def test_google_start_asks_for_identity_not_upload_rights(
        self, anon_client, monkeypatch
    ):
        from urllib.parse import parse_qs, urlparse

        from app.config import get_settings

        monkeypatch.setenv("GOOGLE_CLIENT_ID", "gid")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "gsecret")
        get_settings.cache_clear()
        try:
            response = anon_client.get("/api/login/google", follow_redirects=False)
            query = parse_qs(urlparse(response.headers["location"]).query)
        finally:
            get_settings.cache_clear()

        assert query["scope"][0] == "openid email profile"
        assert "youtube" not in query["scope"][0]
        assert query["redirect_uri"][0].endswith("/api/login/google/callback")

    def test_sign_in_is_offered_without_a_session(self, anon_client):
        """It is the login page: requiring a session would be circular."""
        response = anon_client.get("/api/login/google", follow_redirects=False)
        assert response.status_code in (307, 302)

    def test_unconfigured_provider_explains_itself(self, anon_client):
        """With no credentials it bounces back to the UI with a message rather
        than sending the user to a broken consent screen."""
        response = anon_client.get("/api/login/meta", follow_redirects=False)
        assert "META_APP_ID" in response.headers["location"]

    def test_a_social_account_has_no_usable_password(self, tmp_path):
        from cryptography.fernet import Fernet

        from app.passwords import UNUSABLE_PASSWORD, verify_password
        from app.store import Store

        store = Store(tmp_path / "social.sqlite3", Fernet.generate_key().decode())
        store.create_user("viagoogle@example.com", UNUSABLE_PASSWORD)

        user = store.get_user_by_email("viagoogle@example.com")
        assert not verify_password("", user["password_hash"])
        assert not verify_password(UNUSABLE_PASSWORD, user["password_hash"])
        assert not verify_password("password", user["password_hash"])

    def test_signing_in_twice_reuses_the_same_account(self, tmp_path):
        """Matching on the verified email is what makes Google and Facebook
        land in one account rather than two."""
        from cryptography.fernet import Fernet

        from app.passwords import UNUSABLE_PASSWORD
        from app.store import Store

        store = Store(tmp_path / "same.sqlite3", Fernet.generate_key().decode())
        first = store.create_user("both@example.com", UNUSABLE_PASSWORD)

        assert store.create_user("both@example.com", UNUSABLE_PASSWORD) is None
        assert store.get_user_by_email("both@example.com")["id"] == first

    def test_email_match_ignores_case(self, tmp_path):
        from cryptography.fernet import Fernet

        from app.passwords import UNUSABLE_PASSWORD
        from app.store import Store

        store = Store(tmp_path / "case.sqlite3", Fernet.generate_key().decode())
        user_id = store.create_user("Mixed@Example.com", UNUSABLE_PASSWORD)
        assert store.get_user_by_email("mixed@example.com")["id"] == user_id
