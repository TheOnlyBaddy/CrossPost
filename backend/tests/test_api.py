"""API-level checks: the routes exist, and the v1 gate rejects before anything
reaches a platform.

Nothing here talks to YouTube or Meta. With no credentials configured, every
platform leg should resolve to 'not_configured' rather than erroring — which
is the same code path as a real partial failure.
"""


class TestHealth:
    def test_health_reports_setup_state(self, client):
        body = client.get("/api/health").json()
        assert body["ok"] is True

        setup = body["setup"]
        assert setup["youtubeCredentials"] is False
        assert setup["metaCredentials"] is False
        assert setup["tokenEncryptionKey"] is True
        # localhost is not reachable by Meta, so Instagram cannot work yet.
        assert setup["instagramCanFetchMedia"] is False
        assert setup["youtubePrivacyStatus"] == "private"

    def test_health_lists_all_three_platforms_disconnected(self, client):
        connections = client.get("/api/health").json()["connections"]
        assert {c["platform"] for c in connections} == {
            "youtube",
            "instagram",
            "facebook",
        }
        assert all(c["connected"] is False for c in connections)


class TestConnections:
    def test_connections_endpoint(self, client):
        body = client.get("/api/auth/connections").json()
        assert body["metaUserConnected"] is False
        assert len(body["connections"]) == 3

    def test_oauth_start_refuses_without_credentials(self, client):
        for path in ("/api/auth/youtube/start", "/api/auth/meta/start"):
            resp = client.get(path, follow_redirects=False)
            assert resp.status_code == 400
            assert "not set in .env" in resp.json()["detail"]

    def test_meta_pages_refuses_before_connecting(self, client):
        resp = client.get("/api/auth/meta/pages")
        assert resp.status_code == 400


class TestPostValidation:
    def test_posts_list_starts_empty(self, client):
        assert client.get("/api/posts").json()["posts"] == []

    def test_rejects_missing_title(self, client):
        resp = client.post(
            "/api/posts",
            data={"title": "   ", "caption": "hi"},
            files={"file": ("clip.mp4", b"\x00" * 16, "video/mp4")},
        )
        assert resp.status_code == 422
        assert "YouTube requires a title" in resp.json()["detail"]["problems"][0]

    def test_rejects_overlong_title(self, client):
        resp = client.post(
            "/api/posts",
            data={"title": "x" * 101, "caption": ""},
            files={"file": ("clip.mp4", b"\x00" * 16, "video/mp4")},
        )
        assert resp.status_code == 422

    def test_rejects_wrong_file_type(self, client):
        resp = client.post(
            "/api/posts",
            data={"title": "A title", "caption": ""},
            files={"file": ("clip.avi", b"\x00" * 16, "video/x-msvideo")},
        )
        assert resp.status_code == 422
        assert ".mp4" in resp.json()["detail"]["problems"][0]

    def test_rejects_unknown_platform(self, client):
        resp = client.post(
            "/api/posts",
            data={"title": "A title", "caption": "", "targets": "tiktok"},
            files={"file": ("clip.mp4", b"\x00" * 16, "video/mp4")},
        )
        assert resp.status_code == 422

    def test_rejects_empty_target_list(self, client):
        resp = client.post(
            "/api/posts",
            data={"title": "A title", "caption": "", "targets": " "},
            files={"file": ("clip.mp4", b"\x00" * 16, "video/mp4")},
        )
        assert resp.status_code == 422


class TestRetry:
    def test_retry_unknown_post_is_404(self, client):
        assert client.post("/api/posts/nope/retry/youtube").status_code == 404

    def test_retry_unknown_platform_is_422(self, client):
        assert client.post("/api/posts/nope/retry/tiktok").status_code == 422


class TestMetaStart:
    """The login dialog carries either a scope list or a Configuration ID,
    never both — Meta's manual-flow guide says not to send scope with one."""

    @staticmethod
    def _dialog_query(client, monkeypatch, config_id: str) -> dict:
        from urllib.parse import parse_qs, urlparse

        from app.config import get_settings

        monkeypatch.setenv("META_APP_ID", "123")
        monkeypatch.setenv("META_APP_SECRET", "shh")
        monkeypatch.setenv("META_CONFIG_ID", config_id)
        get_settings.cache_clear()
        try:
            response = client.get("/api/auth/meta/start", follow_redirects=False)
            assert response.status_code == 307
            return parse_qs(urlparse(response.headers["location"]).query)
        finally:
            get_settings.cache_clear()

    def test_scope_flow_when_no_config_id(self, client, monkeypatch):
        query = self._dialog_query(client, monkeypatch, config_id="")
        assert "config_id" not in query
        assert "instagram_content_publish" in query["scope"][0]

    def test_config_id_replaces_scope(self, client, monkeypatch):
        query = self._dialog_query(client, monkeypatch, config_id="98765")
        assert query["config_id"] == ["98765"]
        assert "scope" not in query

    def test_start_is_refused_without_credentials(self, client):
        assert client.get("/api/auth/meta/start").status_code == 400


class TestPendingMetaConnection:
    """A Meta login stops at the Page picker. Health has to say so, or the
    half-finished state disappears on the next reload."""

    def test_health_reports_no_pending_meta_by_default(self, client):
        assert client.get("/api/health").json()["metaUserConnected"] is False

    def test_health_reports_a_meta_login_awaiting_its_page(self, client):
        from app.deps import get_store

        user_id = client.get("/api/session").json()["id"]
        store = get_store()
        store.save_account(
            user_id,
            "meta_user",
            external_id=None,
            display_name=None,
            access_token="interim-user-token",
        )
        try:
            body = client.get("/api/health").json()
            assert body["metaUserConnected"] is True
            # Still not publishable: no Page has been chosen.
            assert all(not c["connected"] for c in body["connections"])
        finally:
            store.delete_account(user_id, "meta_user")

    def test_anonymous_health_never_reports_a_pending_meta_login(self, anon_client):
        assert anon_client.get("/api/health").json()["metaUserConnected"] is False
