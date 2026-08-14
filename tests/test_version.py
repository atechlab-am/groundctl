from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.models import VersionCheck
from app.version_check import VersionCheckError
from tests._rate_limit_helper import reset_login_rate_limit
from tests.conftest import auth_headers

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


def test_check_version_now_as_admin_updates_cache(client, admin_token):
    with patch("app.version_check.fetch_latest_release_version", return_value="99.0.0"):
        r = client.post("/version/check-now", headers=auth_headers(admin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["latest_version"] == "99.0.0"
    assert body["update_available"] is True
    assert body["last_checked_at"] is not None

    # Cached — a plain GET now reflects it without calling GitHub again.
    r2 = client.get("/version")
    assert r2.json()["latest_version"] == "99.0.0"


def test_check_version_now_as_operator_forbidden(client, operator_token):
    r = client.post("/version/check-now", headers=auth_headers(operator_token))
    assert r.status_code == 403, r.text


def test_check_version_now_as_viewer_forbidden(client, viewer_token):
    r = client.post("/version/check-now", headers=auth_headers(viewer_token))
    assert r.status_code == 403, r.text


def test_check_version_now_unauthenticated_forbidden(client):
    r = client.post("/version/check-now")
    assert r.status_code == 401, r.text


def test_check_version_now_preserves_latest_version_on_failure(client, admin_token, db_session):
    db_session.add(
        VersionCheck(
            id=_VERSION_CHECK_ID,
            latest_version="5.0.0",
            checked_at=datetime.now(timezone.utc),
            check_failed=False,
        )
    )
    db_session.commit()

    with patch(
        "app.version_check.fetch_latest_release_version",
        side_effect=VersionCheckError("could not reach GitHub releases API"),
    ):
        r = client.post("/version/check-now", headers=auth_headers(admin_token))
    assert r.status_code == 200, r.text
    # A failed refresh must not wipe out a previously known latest_version.
    assert r.json()["latest_version"] == "5.0.0"


def test_get_version_changelog_as_viewer(client, viewer_token):
    r = client.get("/version/changelog", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    assert "# Changelog" in r.json()["content"]


def test_get_version_changelog_unauthenticated_forbidden(client):
    r = client.get("/version/changelog")
    assert r.status_code == 401, r.text
