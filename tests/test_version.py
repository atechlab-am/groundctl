from datetime import datetime, timezone

import pytest

from app.models import VersionCheck
from tests._rate_limit_helper import reset_login_rate_limit

_VERSION_CHECK_ID = "00000000-0000-0000-0000-000000000003"


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    reset_login_rate_limit()
    yield


def test_get_version_unauthenticated_ok(client):
    r = client.get("/version")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["current_version"]
    assert body["latest_version"] is None
    assert body["update_available"] is False
    assert body["last_checked_at"] is None


def test_get_version_reports_update_available(client, db_session):
    db_session.add(
        VersionCheck(
            id=_VERSION_CHECK_ID,
            latest_version="99.0.0",
            checked_at=datetime.now(timezone.utc),
            check_failed=False,
        )
    )
    db_session.commit()

    r = client.get("/version")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["latest_version"] == "99.0.0"
    assert body["update_available"] is True


def test_get_version_not_newer_when_latest_is_older_or_equal(client, db_session):
    from app.version_check import get_current_version

    db_session.add(
        VersionCheck(
            id=_VERSION_CHECK_ID,
            latest_version=get_current_version(),
            checked_at=datetime.now(timezone.utc),
            check_failed=False,
        )
    )
    db_session.commit()

    r = client.get("/version")
    assert r.status_code == 200, r.text
    assert r.json()["update_available"] is False


def test_get_version_malformed_latest_never_reports_available(client, db_session):
    db_session.add(
        VersionCheck(
            id=_VERSION_CHECK_ID,
            latest_version="not-a-version",
            checked_at=datetime.now(timezone.utc),
            check_failed=False,
        )
    )
    db_session.commit()

    r = client.get("/version")
    assert r.status_code == 200, r.text
    assert r.json()["update_available"] is False
