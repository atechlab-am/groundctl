import os
import uuid
from unittest.mock import MagicMock

import pytest

# DATABASE_URL must be set before any app.* import — app/database.py binds
# its engine at module import time. Real Postgres, not SQLite: the schema
# uses postgresql.UUID/ARRAY column types SQLite cannot render at all
# (confirmed by direct testing during Phase 7 planning — see
# docs/testing.md, which supersedes the old SQLite guidance in CLAUDE.md).
os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://groundctl_test:testpass@127.0.0.1:5432/groundctl_test"),
)
os.environ.setdefault("JWT_SECRET", "test_jwt_secret")
os.environ.setdefault("ANSIBLE_PRIVATE_KEY_PATH", "/tmp/gc7-test-ansible-keys/id_ed25519")
os.environ.setdefault("ANSIBLE_HOST_KEYS_DIR", "/tmp/gc7-test-ansible-keys/hosts")
os.environ.setdefault("TLS_CERT_PATH", "/tmp/gc7-test-tls/cert.pem")
os.environ.setdefault("TLS_KEY_PATH", "/tmp/gc7-test-tls/key.pem")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/0")
os.environ.setdefault("PUBLISHED_REPO_BASE_URL", "https://groundctl-test.local:8080")
os.environ.setdefault("GROUNDCTL_API_BASE_URL", "https://groundctl-test.local:8000")

from alembic import command  # noqa: E402
from alembic.config import Config as AlembicConfig  # noqa: E402
from fastapi.testclient import TestClient as _FastAPITestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.aptly_client import AptlyError, get_aptly_client  # noqa: E402
from app.auth import hash_password  # noqa: E402
from app.models import Role, User  # noqa: E402

_engine = create_engine(os.environ["DATABASE_URL"])
_SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

# Every resource router is mounted under /api server-side (see
# app/main.py — kept API paths from colliding with the web UI's own
# client-side page routes, e.g. /servers is both a page and a resource
# name). The test suite predates that prefix and every one of its ~400
# client.get/post/put/delete("/...") calls uses the bare resource path —
# rewriting all of them isn't worth the churn/risk when the join point
# already exists: TestClient (built on httpx's Client) resolves every
# request through _merge_url. Overriding it here to prepend /api (unless
# the path already targets /api, or one of the few genuinely unprefixed
# routes: /health, /metrics, /docs, /openapi.json) makes every existing
# bare-path test call resolve correctly with zero per-call-site changes,
# while still allowing a test to explicitly target /api/... or /health
# itself without double-prefixing.
_UNPREFIXED_PATHS = ("/health", "/metrics", "/docs", "/openapi.json", "/redoc")


class TestClient(_FastAPITestClient):
    def _merge_url(self, url):
        # Matches whatever httpx-compatible URL type _FastAPITestClient's
        # own base class (httpx.Client, or an environment-local fork of it)
        # actually uses internally — imported dynamically here rather than
        # hardcoding `import httpx` so this stays correct regardless of
        # which concrete package is installed.
        URL = type(self.base_url)

        merged = URL(url)
        if merged.is_relative_url:
            path = merged.raw_path.decode() if isinstance(merged.raw_path, bytes) else str(merged.raw_path)
            if not path.startswith("/api/") and not path.startswith(_UNPREFIXED_PATHS):
                merged = URL("/api" + path)
        return super()._merge_url(merged)


@pytest.fixture(scope="session", autouse=True)
def _migrated_schema():
    """Applies the real Alembic migration chain once per test session —
    exercising the actual migration path is the point (ROADMAP Phase 7),
    not create_all(). Tables are truncated (not dropped) between tests by
    the db_session fixture below.
    """
    alembic_cfg = AlembicConfig(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    command.upgrade(alembic_cfg, "head")
    yield


@pytest.fixture
def db_session(_migrated_schema):
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        # Truncate everything except alembic's own bookkeeping table —
        # matches this project's own live-verification TRUNCATE ... CASCADE
        # pattern from every prior phase, now automated per-test.
        with _engine.begin() as conn:
            tables = conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                    "AND tablename != 'alembic_version'"
                )
            ).scalars().all()
            if tables:
                conn.execute(text(f"TRUNCATE TABLE {', '.join(tables)} CASCADE"))


def _mock_aptly() -> MagicMock:
    from app.aptly_client import AptlyClient

    mock = MagicMock(spec=AptlyClient)
    mock.create_mirror.return_value = {}
    mock.delete_mirror.return_value = None
    mock.sync_mirror.return_value = {}
    mock.get_mirror_packages.return_value = []
    mock.get_mirror_size_bytes.return_value = 0
    mock.get_mirror_size_and_count.return_value = (0, 0)
    mock.create_snapshot_from_mirror.return_value = {}
    mock.get_snapshot_packages.return_value = []
    mock.publish_exists.return_value = False
    mock.publish_snapshot.return_value = {}
    mock.switch_publish.return_value = {}
    mock.create_filtered_snapshot.return_value = {}
    mock.cleanup_db.return_value = {}
    mock.ping.return_value = None
    return mock


@pytest.fixture
def mock_aptly():
    return _mock_aptly()


@pytest.fixture
def mock_aptly_unreachable():
    mock = _mock_aptly()
    for method_name in (
        "create_mirror",
        "delete_mirror",
        "sync_mirror",
        "get_mirror_packages",
        "get_mirror_size_bytes",
        "get_mirror_size_and_count",
        "create_snapshot_from_mirror",
        "get_snapshot_packages",
        "publish_exists",
        "publish_snapshot",
        "switch_publish",
        "create_filtered_snapshot",
        "cleanup_db",
        "ping",
    ):
        getattr(mock, method_name).side_effect = AptlyError("aptly unreachable: connection refused")
    return mock


@pytest.fixture
def client(db_session, mock_aptly):
    from app.main import app

    app.dependency_overrides[get_aptly_client] = lambda: mock_aptly
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_user(db_session, role: Role) -> User:
    username = f"{role.value}-{uuid.uuid4().hex[:8]}"
    user = User(
        username=username,
        email=f"{username}@example.com",
        hashed_password=hash_password("Passw0rd!"),
        role=role,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _token_for(client, db_session, role: Role) -> str:
    user = _make_user(db_session, role)
    r = client.post("/auth/login", data={"username": user.username, "password": "Passw0rd!"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture
def admin_token(client, db_session):
    return _token_for(client, db_session, Role.admin)


@pytest.fixture
def operator_token(client, db_session):
    return _token_for(client, db_session, Role.operator)


@pytest.fixture
def viewer_token(client, db_session):
    return _token_for(client, db_session, Role.viewer)


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
