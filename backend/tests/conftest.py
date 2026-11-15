"""Point the app at a throwaway data dir before it is imported.

app.main reads settings at import time (it has to, to mount the media
directory), so these have to be set here rather than in a fixture.
"""

import os
import tempfile

from cryptography.fernet import Fernet

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="crosspost-test-")
os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["PUBLIC_BASE_URL"] = "http://localhost:8000"
os.environ["FRONTEND_ORIGIN"] = "http://localhost:5173"
os.environ["GOOGLE_CLIENT_ID"] = ""
os.environ["GOOGLE_CLIENT_SECRET"] = ""
os.environ["META_APP_ID"] = ""
os.environ["META_APP_SECRET"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


TEST_EMAIL = "tester@example.com"
TEST_PASSWORD = "correct horse battery"


@pytest.fixture(scope="session")
def anon_client() -> TestClient:
    """No session cookie: for checking that routes actually refuse."""
    from app.main import app

    return TestClient(app)


@pytest.fixture(scope="session")
def client(anon_client) -> TestClient:
    """Signed in. TestClient keeps the cookie the sign-up hands back."""
    from app.main import app

    signed_in = TestClient(app)
    response = signed_in.post(
        "/api/users", json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    assert response.status_code == 201, response.text
    return signed_in
