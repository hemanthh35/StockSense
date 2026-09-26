"""Test setup. Runs against its own database (stocksense_test) so real data is never touched."""
import os
import uuid

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
os.environ["RATE_LIMIT_ENABLED"] = "false"  # dedicated tests switch it on when they need it
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
        # the first person to sign up owns the system (administrator), so create the test admin before anything else
        r = c.post("/api/auth/signup", json={
            "login_id": "pytest_admin", "email": "pytest_admin@example.com", "password": PASSWORD, "confirm_password": PASSWORD,
        })
        assert r.status_code == 201, r.text
        assert r.json()["user"]["role"] == "admin"
        c.admin_token = r.json()["token"]
        yield c


@pytest.fixture(scope="session")
def anon(client):
    return Api(client)


@pytest.fixture(scope="session")
def api(client):
    return Api(client, client.admin_token)


@pytest.fixture(scope="session")
def make_user(client, api):
    """Factory: make_user("manager") -> an Api signed in as a new user with that role."""
    counter = {"n": 0}

    def make(role: str = "staff") -> Api:
        counter["n"] += 1
        login = f"{role[:3]}{counter['n']:03d}{uuid.uuid4().hex[:4]}"
        r = client.post("/api/auth/signup", json={"login_id": login, "email": f"{login}@example.com", "password": PASSWORD, "confirm_password": PASSWORD})
        assert r.status_code == 201, r.text
        uid = r.json()["user"]["id"]
        if role != "staff":
            up = api.put(f"/users/{uid}", json={"role": role, "active": True})
            assert up.status_code == 200, up.text
        return Api(client, r.json()["token"])

    return make


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
