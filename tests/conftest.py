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
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.aptly_client import AptlyError, get_aptly_client  # noqa: E402
from app.auth import hash_password  # noqa: E402
from app.models import Role, User  # noqa: E402

_engine = create_engine(os.environ["DATABASE_URL"])
_SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


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
    mock.sync_mirror.return_value = {}
    mock.get_mirror_packages.return_value = []
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
        "sync_mirror",
        "get_mirror_packages",
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
