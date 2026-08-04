from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.aptly_client import get_aptly_client
from app.archive_probe import ArchiveProbeError
from app.main import app
from tests._rate_limit_helper import reset_login_rate_limit
from tests.conftest import Role, _token_for, auth_headers


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    reset_login_rate_limit()
    yield


def _repo_payload(name="jammy-main", distribution="jammy"):
    return {
        "name": name,
        "archive_url": "http://archive.ubuntu.com/ubuntu",
        "distribution": distribution,
        "components": ["main"],
        "architectures": ["amd64"],
    }


def test_create_repository_as_operator(client, operator_token):
    r = client.post("/repositories", json=_repo_payload(), headers=auth_headers(operator_token))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "jammy-main"
    assert body["distribution"] == "jammy"
    assert body["components"] == ["main"]
    assert body["architectures"] == ["amd64"]
    assert body["last_synced_at"] is None


def test_create_repository_as_admin(client, admin_token):
    r = client.post("/repositories", json=_repo_payload("jammy-admin"), headers=auth_headers(admin_token))
    assert r.status_code == 201, r.text


def test_create_repository_as_viewer_forbidden(client, viewer_token):
    r = client.post("/repositories", json=_repo_payload(), headers=auth_headers(viewer_token))
    assert r.status_code == 403, r.text


def test_create_repository_duplicate_name_conflicts(client, operator_token):
    r1 = client.post("/repositories", json=_repo_payload("dup-repo"), headers=auth_headers(operator_token))
    assert r1.status_code == 201, r1.text
    r2 = client.post("/repositories", json=_repo_payload("dup-repo"), headers=auth_headers(operator_token))
    assert r2.status_code == 409, r2.text


def test_create_repository_aptly_unreachable_returns_502(db_session, mock_aptly_unreachable):
    app.dependency_overrides[get_aptly_client] = lambda: mock_aptly_unreachable
    try:
        with TestClient(app) as c:
            token = _token_for(c, db_session, Role.operator)
            r = c.post(
                "/repositories",
                json=_repo_payload("unreachable-repo"),
                headers=auth_headers(token),
            )
            assert r.status_code == 502, r.text
    finally:
        app.dependency_overrides.clear()


def test_list_repositories(client, operator_token, viewer_token):
    client.post("/repositories", json=_repo_payload("focal-main", "focal"), headers=auth_headers(operator_token))
    client.post("/repositories", json=_repo_payload("jammy-main", "jammy"), headers=auth_headers(operator_token))

    r = client.get("/repositories", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    names = {repo["name"] for repo in r.json()}
    assert {"focal-main", "jammy-main"} <= names


def test_list_repositories_filter_by_distribution(client, operator_token, viewer_token):
    client.post("/repositories", json=_repo_payload("focal-main", "focal"), headers=auth_headers(operator_token))
    client.post("/repositories", json=_repo_payload("jammy-main", "jammy"), headers=auth_headers(operator_token))

    r = client.get("/repositories", params={"distribution": "focal"}, headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert all(repo["distribution"] == "focal" for repo in body)
    assert any(repo["name"] == "focal-main" for repo in body)


def test_list_repositories_limit_offset(client, operator_token, viewer_token):
    for i in range(5):
        client.post(
            "/repositories", json=_repo_payload(f"repo-{i}", "jammy"), headers=auth_headers(operator_token)
        )

    r = client.get("/repositories", params={"limit": 2, "offset": 0}, headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    assert len(r.json()) == 2


def test_sync_repository_as_operator(client, operator_token):
    client.post("/repositories", json=_repo_payload("sync-repo"), headers=auth_headers(operator_token))
    r = client.post("/repositories/sync-repo/sync", headers=auth_headers(operator_token))
    assert r.status_code == 200, r.text
    assert r.json()["last_synced_at"] is not None


def test_sync_repository_as_viewer_forbidden(client, operator_token, viewer_token):
    client.post("/repositories", json=_repo_payload("sync-repo2"), headers=auth_headers(operator_token))
    r = client.post("/repositories/sync-repo2/sync", headers=auth_headers(viewer_token))
    assert r.status_code == 403, r.text


def test_sync_repository_not_found(client, operator_token):
    r = client.post("/repositories/does-not-exist/sync", headers=auth_headers(operator_token))
    assert r.status_code == 404, r.text


def test_sync_repository_invalid_name_rejected(client, operator_token):
    r = client.post("/repositories/../etc/sync", headers=auth_headers(operator_token))
    assert r.status_code in (404, 422), r.text


def test_probe_repository_archive_as_operator(client, operator_token):
    with patch("app.routers.repositories.probe_distributions", return_value=["jammy", "jammy-updates"]) as m:
        r = client.post(
            "/repositories/probe",
            json={"archive_url": "http://archive.ubuntu.com/ubuntu"},
            headers=auth_headers(operator_token),
        )
    assert r.status_code == 200, r.text
    assert r.json()["distributions"] == ["jammy", "jammy-updates"]
    m.assert_called_once_with("http://archive.ubuntu.com/ubuntu")


def test_probe_repository_archive_as_viewer_forbidden(client, viewer_token):
    r = client.post(
        "/repositories/probe",
        json={"archive_url": "http://archive.ubuntu.com/ubuntu"},
        headers=auth_headers(viewer_token),
    )
    assert r.status_code == 403, r.text


def test_probe_repository_archive_unreachable_returns_502(client, operator_token):
    with patch(
        "app.routers.repositories.probe_distributions",
        side_effect=ArchiveProbeError("could not reach http://bad.example/dists/: connection refused"),
    ):
        r = client.post(
            "/repositories/probe",
            json={"archive_url": "http://bad.example"},
            headers=auth_headers(operator_token),
        )
    assert r.status_code == 502, r.text


def test_create_repositories_batch_as_operator(client, operator_token):
    r = client.post(
        "/repositories/batch",
        json={
            "archive_url": "http://archive.ubuntu.com/ubuntu",
            "distributions": ["jammy", "jammy-updates"],
            "components": ["main", "universe"],
            "architectures": ["amd64"],
        },
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert {repo["name"] for repo in body["created"]} == {"jammy", "jammy-updates"}
    assert body["errors"] == []
    for repo in body["created"]:
        assert repo["components"] == ["main", "universe"]
        assert repo["architectures"] == ["amd64"]


def test_create_repositories_batch_as_viewer_forbidden(client, viewer_token):
    r = client.post(
        "/repositories/batch",
        json={
            "archive_url": "http://archive.ubuntu.com/ubuntu",
            "distributions": ["jammy"],
            "components": ["main"],
            "architectures": ["amd64"],
        },
        headers=auth_headers(viewer_token),
    )
    assert r.status_code == 403, r.text


def test_create_repositories_batch_partial_conflict_reported_per_item(client, operator_token):
    client.post("/repositories", json=_repo_payload("jammy", "jammy"), headers=auth_headers(operator_token))

    r = client.post(
        "/repositories/batch",
        json={
            "archive_url": "http://archive.ubuntu.com/ubuntu",
            "distributions": ["jammy", "jammy-updates"],
            "components": ["main"],
            "architectures": ["amd64"],
        },
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert [repo["name"] for repo in body["created"]] == ["jammy-updates"]
    assert len(body["errors"]) == 1
    assert body["errors"][0]["distribution"] == "jammy"
    assert "already exists" in body["errors"][0]["detail"]


def test_create_repositories_batch_aptly_error_reported_per_item(db_session, mock_aptly):
    from app.aptly_client import AptlyError

    mock_aptly.create_mirror.side_effect = [{}, AptlyError("aptly rejected mirror")]
    app.dependency_overrides[get_aptly_client] = lambda: mock_aptly
    try:
        with TestClient(app) as c:
            token = _token_for(c, db_session, Role.operator)
            r = c.post(
                "/repositories/batch",
                json={
                    "archive_url": "http://archive.ubuntu.com/ubuntu",
                    "distributions": ["jammy", "jammy-updates"],
                    "components": ["main"],
                    "architectures": ["amd64"],
                },
                headers=auth_headers(token),
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 201, r.text
    body = r.json()
    assert [repo["name"] for repo in body["created"]] == ["jammy"]
    assert len(body["errors"]) == 1
    assert body["errors"][0]["distribution"] == "jammy-updates"
    assert "aptly rejected mirror" in body["errors"][0]["detail"]


def test_sync_repository_aptly_unreachable_returns_502(db_session, mock_aptly, mock_aptly_unreachable):
    # First create the repo with a reachable aptly mock, then switch to
    # unreachable for the sync call itself.
    app.dependency_overrides[get_aptly_client] = lambda: mock_aptly
    try:
        with TestClient(app) as c:
            token = _token_for(c, db_session, Role.operator)
            r = c.post(
                "/repositories",
                json=_repo_payload("sync-unreachable"),
                headers=auth_headers(token),
            )
            assert r.status_code == 201, r.text
    finally:
        app.dependency_overrides.clear()

    app.dependency_overrides[get_aptly_client] = lambda: mock_aptly_unreachable
    try:
        with TestClient(app) as c:
            r = c.post(
                "/repositories/sync-unreachable/sync",
                headers=auth_headers(token),
            )
            assert r.status_code == 502, r.text
    finally:
        app.dependency_overrides.clear()
