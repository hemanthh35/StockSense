"""Test setup. Runs against its own database (stocksense_test) so real data is never touched."""
import os

import psycopg
import pytest

TEST_DB = "stocksense_test"


def _prepare_database() -> None:
    url = os.environ.get("DATABASE_URL", "postgresql+psycopg://stocksense:stocksense@localhost:5432/stocksense")
    base = url.rsplit("/", 1)[0]
    admin = base.replace("postgresql+psycopg", "postgresql") + "/postgres"
    with psycopg.connect(admin, autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,)).fetchone():
            conn.execute(f"CREATE DATABASE {TEST_DB}")
    os.environ["DATABASE_URL"] = f"{base}/{TEST_DB}"  # must be set before the app is imported


os.environ["DIGEST_ENABLED"] = "false"  # no background e-mail loop while testing
os.environ["BREVO_API_KEY"] = ""  # the developer's real key must never be used by tests
os.environ["BREVO_SENDER_EMAIL"] = ""
_prepare_database()

from fastapi.testclient import TestClient  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402

PASSWORD = "Str0ng!Passw"


class Api:
    """TestClient wrapper that adds the /api prefix and the bearer token."""

    def __init__(self, client: TestClient, token: str | None = None):
        self.client = client
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}

    def _call(self, method, path, **kw):
        return getattr(self.client, method)("/api" + path, headers=self.headers, **kw)

    def get(self, path, **kw):
        return self._call("get", path, **kw)

    def post(self, path, json=None, **kw):
        return self._call("post", path, json=json, **kw)

    def put(self, path, json=None, **kw):
        return self._call("put", path, json=json, **kw)

    def delete(self, path, **kw):
        return self._call("delete", path, **kw)


@pytest.fixture(scope="session")
def client():
    Base.metadata.drop_all(engine)  # start every run from a clean slate
    with TestClient(app) as c:  # startup: create tables, migrations, seed
        yield c


@pytest.fixture(scope="session")
def anon(client):
    return Api(client)


@pytest.fixture(scope="session")
def api(client):
    r = client.post("/api/auth/signup", json={
        "login_id": "pytest_admin", "email": "pytest_admin@example.com", "password": PASSWORD, "confirm_password": PASSWORD,
    })
    assert r.status_code == 201, r.text
    return Api(client, r.json()["token"])


@pytest.fixture(autouse=True)
def sent_otps(monkeypatch):
    """Capture OTP emails instead of calling Brevo."""
    sent = []
    monkeypatch.setattr("app.routers.auth.send_otp", lambda email, code: sent.append((email, code)) or True)
    return sent


@pytest.fixture(autouse=True)
def no_real_email(monkeypatch):
    """Belt and braces: if anything tries to reach Brevo during a test, fail loudly."""
    def boom(*a, **k):
        raise RuntimeError("a test tried to send a real email")
    monkeypatch.setattr("app.mail.httpx.post", boom)
