import pytest

from tests._rate_limit_helper import reset_login_rate_limit
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    reset_login_rate_limit()
    yield


def _create_repo(client, operator_token, name="al-repo"):
    r = client.post(
        "/repositories",
        json={
            "name": name,
            "archive_url": "http://archive.ubuntu.com/ubuntu",
            "distribution": "jammy",
            "components": ["main"],
            "architectures": ["amd64"],
        },
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_list_audit_logs_as_admin(client, admin_token, operator_token):
    # Trigger a mutation so there's data to list.
    _create_repo(client, operator_token, "audit-repo-1")

    r = client.get("/audit-logs", headers=auth_headers(admin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(row["action"] == "create_repository" for row in body)


def test_list_audit_logs_as_operator_forbidden(client, admin_token, operator_token):
    _create_repo(client, operator_token, "audit-repo-2")
    r = client.get("/audit-logs", headers=auth_headers(operator_token))
    assert r.status_code == 403, r.text


def test_list_audit_logs_as_viewer_forbidden(client, viewer_token, operator_token):
    _create_repo(client, operator_token, "audit-repo-3")
    r = client.get("/audit-logs", headers=auth_headers(viewer_token))
    assert r.status_code == 403, r.text


def test_list_audit_logs_filter_by_action(client, admin_token, operator_token):
    _create_repo(client, operator_token, "audit-repo-4")
    r = client.get("/audit-logs", params={"action": "create_repository"}, headers=auth_headers(admin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) > 0
    assert all(row["action"] == "create_repository" for row in body)


def test_list_audit_logs_pagination(client, admin_token, operator_token):
    for i in range(5):
        _create_repo(client, operator_token, f"audit-page-repo-{i}")

    r = client.get(
        "/audit-logs", params={"action": "create_repository", "limit": 2, "offset": 0}, headers=auth_headers(admin_token)
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) == 2


def test_export_audit_logs_as_admin_returns_csv(client, admin_token, operator_token):
    _create_repo(client, operator_token, "audit-repo-5")

    r = client.get("/audit-logs/export", headers=auth_headers(admin_token))
    assert r.status_code == 200, r.text
    assert "text/csv" in r.headers["content-type"]
    assert "id,user_id,action,resource_type,resource_id,detail,created_at" in r.text
    assert "create_repository" in r.text


def test_export_audit_logs_as_operator_forbidden(client, operator_token):
    r = client.get("/audit-logs/export", headers=auth_headers(operator_token))
    assert r.status_code == 403, r.text


def test_export_audit_logs_as_viewer_forbidden(client, viewer_token):
    r = client.get("/audit-logs/export", headers=auth_headers(viewer_token))
    assert r.status_code == 403, r.text
