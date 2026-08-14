import pytest

from tests._rate_limit_helper import reset_login_rate_limit
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    reset_login_rate_limit()
    yield


def test_get_instance_settings_defaults_when_unconfigured(client, admin_token):
    r = client.get("/instance-settings", headers=auth_headers(admin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated_at"] is None
    assert all(v is False for v in body["overridden"].values())
    assert body["has_webhook_secret"] is False
    assert body["webhook_url"] is None
    # These match config.py's defaults exactly.
    assert body["audit_log_retention_days"] == 365
    assert body["stale_checkin_hours"] == 24 * 7


def test_get_instance_settings_as_operator_forbidden(client, operator_token):
    r = client.get("/instance-settings", headers=auth_headers(operator_token))
    assert r.status_code == 403, r.text


def test_get_instance_settings_as_viewer_forbidden(client, viewer_token):
    r = client.get("/instance-settings", headers=auth_headers(viewer_token))
    assert r.status_code == 403, r.text


def test_update_instance_settings_as_admin(client, admin_token):
    r = client.put(
        "/instance-settings",
        json={"audit_log_retention_days": 90, "stale_checkin_hours": 48},
        headers=auth_headers(admin_token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["audit_log_retention_days"] == 90
    assert body["stale_checkin_hours"] == 48
    assert body["overridden"]["audit_log_retention_days"] is True
    assert body["overridden"]["stale_checkin_hours"] is True
    # Untouched fields stay at their default, unaffected by the partial update.
    assert body["overridden"]["disk_usage_warn_percent"] is False

    r2 = client.get("/instance-settings", headers=auth_headers(admin_token))
    assert r2.json()["audit_log_retention_days"] == 90


def test_update_instance_settings_as_operator_forbidden(client, operator_token):
    r = client.put(
        "/instance-settings",
        json={"audit_log_retention_days": 90},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 403, r.text


def test_update_instance_settings_reset_to_default(client, admin_token):
    client.put(
        "/instance-settings",
        json={"stale_checkin_hours": 12},
        headers=auth_headers(admin_token),
    )
    r = client.put(
        "/instance-settings",
        json={"stale_checkin_hours": None},
        headers=auth_headers(admin_token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["overridden"]["stale_checkin_hours"] is False
    assert body["stale_checkin_hours"] == 24 * 7


def test_update_instance_settings_rejects_non_positive(client, admin_token):
    r = client.put(
        "/instance-settings",
        json={"audit_log_retention_days": 0},
        headers=auth_headers(admin_token),
    )
    assert r.status_code == 422, r.text


def test_update_instance_settings_repository_stale_threshold_allows_zero(client, admin_token):
    # Unlike the other hour/day thresholds, 0 is legitimate here — "flag as
    # stale immediately once synced" (see _repository_health_status).
    r = client.put(
        "/instance-settings",
        json={"repository_stale_threshold_hours": 0},
        headers=auth_headers(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["repository_stale_threshold_hours"] == 0


def test_update_instance_settings_repository_stale_threshold_rejects_negative(client, admin_token):
    r = client.put(
        "/instance-settings",
        json={"repository_stale_threshold_hours": -1},
        headers=auth_headers(admin_token),
    )
    assert r.status_code == 422, r.text


def test_update_instance_settings_rejects_bad_percent(client, admin_token):
    r = client.put(
        "/instance-settings",
        json={"disk_usage_warn_percent": 150},
        headers=auth_headers(admin_token),
    )
    assert r.status_code == 422, r.text


def test_webhook_secret_never_returned(client, admin_token):
    r = client.put(
        "/instance-settings",
        json={"webhook_url": "https://example.com/hook", "webhook_secret": "supersecret"},
        headers=auth_headers(admin_token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "webhook_secret" not in body
    assert body["has_webhook_secret"] is True
    assert body["webhook_url"] == "https://example.com/hook"

    r2 = client.get("/instance-settings", headers=auth_headers(admin_token))
    assert "webhook_secret" not in r2.json()
    assert r2.json()["has_webhook_secret"] is True


def test_webhook_secret_clear(client, admin_token):
    client.put(
        "/instance-settings",
        json={"webhook_secret": "supersecret"},
        headers=auth_headers(admin_token),
    )
    r = client.put(
        "/instance-settings",
        json={"webhook_secret": None},
        headers=auth_headers(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["has_webhook_secret"] is False
