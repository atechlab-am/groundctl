from unittest.mock import patch

import pytest

from app.aptly_client import get_aptly_client
from app.archive_probe import ArchiveProbeError
from app.main import app
from tests._rate_limit_helper import reset_login_rate_limit
from tests.conftest import Role, TestClient, _token_for, auth_headers


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
    with patch("app.tasks.sync_repository_task.delay") as mock_delay:
        r = client.post("/repositories/sync-repo/sync", headers=auth_headers(operator_token))
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["job_type"] == "sync_repository"
        assert body["status"] == "pending"
        assert body["target_type"] == "repository"
        mock_delay.assert_called_once_with(str(body["id"]))


def test_sync_repository_as_viewer_forbidden(client, operator_token, viewer_token):
    client.post("/repositories", json=_repo_payload("sync-repo2"), headers=auth_headers(operator_token))
    with patch("app.tasks.sync_repository_task.delay") as mock_delay:
        r = client.post("/repositories/sync-repo2/sync", headers=auth_headers(viewer_token))
        assert r.status_code == 403, r.text
        mock_delay.assert_not_called()


def test_sync_repository_not_found(client, operator_token):
    with patch("app.tasks.sync_repository_task.delay") as mock_delay:
        r = client.post("/repositories/does-not-exist/sync", headers=auth_headers(operator_token))
        assert r.status_code == 404, r.text
        mock_delay.assert_not_called()


def test_sync_repository_invalid_name_rejected(client, operator_token):
    with patch("app.tasks.sync_repository_task.delay") as mock_delay:
        r = client.post("/repositories/../etc/sync", headers=auth_headers(operator_token))
        assert r.status_code in (404, 422), r.text
        mock_delay.assert_not_called()


def test_get_repository_as_viewer(client, operator_token, viewer_token):
    client.post("/repositories", json=_repo_payload("get-repo"), headers=auth_headers(operator_token))
    r = client.get("/repositories/get-repo", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "get-repo"
    assert body["archive_url"].rstrip("/") == "http://archive.ubuntu.com/ubuntu"


def test_get_repository_not_found(client, viewer_token):
    r = client.get("/repositories/does-not-exist", headers=auth_headers(viewer_token))
    assert r.status_code == 404, r.text


def test_repository_auto_sync_enabled_by_default(client, operator_token):
    r = client.post("/repositories", json=_repo_payload("auto-sync-default"), headers=auth_headers(operator_token))
    assert r.status_code == 201, r.text
    assert r.json()["auto_sync_enabled"] is True


def test_update_repository_auto_sync_as_operator(client, operator_token):
    client.post("/repositories", json=_repo_payload("auto-sync-repo"), headers=auth_headers(operator_token))
    r = client.patch(
        "/repositories/auto-sync-repo/auto-sync",
        json={"auto_sync_enabled": False},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["auto_sync_enabled"] is False

    r2 = client.get("/repositories/auto-sync-repo", headers=auth_headers(operator_token))
    assert r2.json()["auto_sync_enabled"] is False


def test_update_repository_auto_sync_as_viewer_forbidden(client, operator_token, viewer_token):
    client.post("/repositories", json=_repo_payload("auto-sync-repo2"), headers=auth_headers(operator_token))
    r = client.patch(
        "/repositories/auto-sync-repo2/auto-sync",
        json={"auto_sync_enabled": False},
        headers=auth_headers(viewer_token),
    )
    assert r.status_code == 403, r.text


def test_update_repository_auto_sync_not_found(client, operator_token):
    r = client.patch(
        "/repositories/does-not-exist/auto-sync",
        json={"auto_sync_enabled": False},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_scheduled_sync_all_repositories_skips_disabled(db_session, mock_aptly, operator_token, client):
    from app.tasks import scheduled_sync_all_repositories

    client.post("/repositories", json=_repo_payload("auto-sync-on"), headers=auth_headers(operator_token))
    client.post(
        "/repositories", json=_repo_payload("auto-sync-off", distribution="jammy"), headers=auth_headers(operator_token)
    )
    client.patch(
        "/repositories/auto-sync-off/auto-sync",
        json={"auto_sync_enabled": False},
        headers=auth_headers(operator_token),
    )

    with patch("app.tasks.get_aptly_client", return_value=mock_aptly):
        result = scheduled_sync_all_repositories()

    assert "auto-sync-off" not in result
    mock_aptly.sync_mirror.assert_any_call("auto-sync-on")
    assert "auto-sync-off" not in [c.args[0] for c in mock_aptly.sync_mirror.call_args_list]


def test_delete_repository_as_operator(client, operator_token):
    client.post("/repositories", json=_repo_payload("delete-repo"), headers=auth_headers(operator_token))
    with patch("app.tasks.delete_repository_task.delay") as mock_delay:
        r = client.delete("/repositories/delete-repo", headers=auth_headers(operator_token))
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["job_type"] == "delete_repository"
        assert body["status"] == "pending"
        assert body["target_type"] == "repository"
        mock_delay.assert_called_once_with(str(body["id"]))

    # Not actually deleted yet — deletion happens in the (mocked-away) task.
    r2 = client.get("/repositories/delete-repo", headers=auth_headers(operator_token))
    assert r2.status_code == 200, r2.text


def test_delete_repository_as_viewer_forbidden(client, operator_token, viewer_token):
    client.post("/repositories", json=_repo_payload("delete-repo2"), headers=auth_headers(operator_token))
    with patch("app.tasks.delete_repository_task.delay") as mock_delay:
        r = client.delete("/repositories/delete-repo2", headers=auth_headers(viewer_token))
        assert r.status_code == 403, r.text
        mock_delay.assert_not_called()


def test_delete_repository_not_found(client, operator_token):
    with patch("app.tasks.delete_repository_task.delay") as mock_delay:
        r = client.delete("/repositories/does-not-exist", headers=auth_headers(operator_token))
        assert r.status_code == 404, r.text
        mock_delay.assert_not_called()


def test_delete_repository_referenced_by_content_view_conflicts(client, operator_token):
    repo = client.post(
        "/repositories", json=_repo_payload("cv-repo"), headers=auth_headers(operator_token)
    ).json()
    cv = client.post(
        "/content-views",
        json={"name": "guards-delete-cv", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    )
    assert cv.status_code == 201, cv.text

    with patch("app.tasks.delete_repository_task.delay") as mock_delay:
        r = client.delete("/repositories/cv-repo", headers=auth_headers(operator_token))
        assert r.status_code == 409, r.text
        assert "guards-delete-cv" in r.json()["detail"]
        mock_delay.assert_not_called()


def test_delete_repository_task_deletes_mirror_and_row(client, operator_token, mock_aptly):
    from app.tasks import delete_repository_task

    client.post("/repositories", json=_repo_payload("task-delete-repo"), headers=auth_headers(operator_token))
    with patch("app.tasks.delete_repository_task.delay"):
        del_r = client.delete("/repositories/task-delete-repo", headers=auth_headers(operator_token))
        job_id = del_r.json()["id"]

    with patch("app.tasks.get_aptly_client", return_value=mock_aptly):
        delete_repository_task(job_id)

    mock_aptly.delete_mirror.assert_called_with("task-delete-repo")

    job_r = client.get(f"/jobs/{job_id}", headers=auth_headers(operator_token))
    assert job_r.json()["status"] == "success"

    repo_r = client.get("/repositories/task-delete-repo", headers=auth_headers(operator_token))
    assert repo_r.status_code == 404, repo_r.text


def test_update_repository_as_operator(client, operator_token):
    client.post("/repositories", json=_repo_payload("update-repo"), headers=auth_headers(operator_token))
    with patch("app.tasks.update_repository_task.delay") as mock_delay:
        r = client.put(
            "/repositories/update-repo",
            json={
                "archive_url": "http://archive.ubuntu.com/ubuntu",
                "distribution": "jammy-updates",
                "components": ["main", "universe"],
                "architectures": ["amd64", "arm64"],
            },
            headers=auth_headers(operator_token),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["job_type"] == "update_repository"
        assert body["status"] == "pending"
        assert body["target_type"] == "repository"
        mock_delay.assert_called_once_with(str(body["id"]))

    # Not actually changed yet — the swap happens in the (mocked-away) task.
    r2 = client.get("/repositories/update-repo", headers=auth_headers(operator_token))
    assert r2.json()["distribution"] == "jammy"


def test_update_repository_as_viewer_forbidden(client, operator_token, viewer_token):
    client.post("/repositories", json=_repo_payload("update-repo2"), headers=auth_headers(operator_token))
    with patch("app.tasks.update_repository_task.delay") as mock_delay:
        r = client.put(
            "/repositories/update-repo2",
            json={
                "archive_url": "http://archive.ubuntu.com/ubuntu",
                "distribution": "jammy",
                "components": ["main"],
                "architectures": ["amd64"],
            },
            headers=auth_headers(viewer_token),
        )
        assert r.status_code == 403, r.text
        mock_delay.assert_not_called()


def test_update_repository_not_found(client, operator_token):
    with patch("app.tasks.update_repository_task.delay") as mock_delay:
        r = client.put(
            "/repositories/does-not-exist",
            json={
                "archive_url": "http://archive.ubuntu.com/ubuntu",
                "distribution": "jammy",
                "components": ["main"],
                "architectures": ["amd64"],
            },
            headers=auth_headers(operator_token),
        )
        assert r.status_code == 404, r.text
        mock_delay.assert_not_called()


def test_update_repository_referenced_by_content_view_conflicts(client, operator_token):
    repo = client.post(
        "/repositories", json=_repo_payload("cv-repo2"), headers=auth_headers(operator_token)
    ).json()
    cv = client.post(
        "/content-views",
        json={"name": "guards-update-cv", "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    )
    assert cv.status_code == 201, cv.text

    with patch("app.tasks.update_repository_task.delay") as mock_delay:
        r = client.put(
            "/repositories/cv-repo2",
            json={
                "archive_url": "http://archive.ubuntu.com/ubuntu",
                "distribution": "jammy",
                "components": ["main"],
                "architectures": ["amd64"],
            },
            headers=auth_headers(operator_token),
        )
        assert r.status_code == 409, r.text
        mock_delay.assert_not_called()


def test_update_repository_task_swaps_mirror_settings(client, operator_token, mock_aptly):
    from app.tasks import update_repository_task

    client.post("/repositories", json=_repo_payload("task-update-repo"), headers=auth_headers(operator_token))
    with patch("app.tasks.update_repository_task.delay"):
        put_r = client.put(
            "/repositories/task-update-repo",
            json={
                "archive_url": "http://archive.ubuntu.com/ubuntu",
                "distribution": "jammy-updates",
                "components": ["main", "universe"],
                "architectures": ["amd64", "arm64"],
            },
            headers=auth_headers(operator_token),
        )
        job_id = put_r.json()["id"]

    with patch("app.tasks.get_aptly_client", return_value=mock_aptly):
        update_repository_task(job_id)

    mock_aptly.delete_mirror.assert_called_once_with("task-update-repo")
    mock_aptly.create_mirror.assert_called_with(
        name="task-update-repo",
        archive_url="http://archive.ubuntu.com/ubuntu",
        distribution="jammy-updates",
        components=["main", "universe"],
        architectures=["amd64", "arm64"],
    )

    job_r = client.get(f"/jobs/{job_id}", headers=auth_headers(operator_token))
    assert job_r.json()["status"] == "success"

    repo_r = client.get("/repositories/task-update-repo", headers=auth_headers(operator_token))
    body = repo_r.json()
    assert body["distribution"] == "jammy-updates"
    assert body["components"] == ["main", "universe"]
    assert body["architectures"] == ["amd64", "arm64"]
    assert body["last_synced_at"] is None
    assert body["size_bytes"] is None


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


def test_sync_repository_task_marks_job_failed_on_aptly_error(db_session, mock_aptly, mock_aptly_unreachable):
    """Sync now runs async (sync_repository_task, app/tasks.py) instead of
    inline, so an unreachable aptly no longer surfaces as a synchronous 502
    from the /sync endpoint (see test_sync_repository_as_operator) — it
    surfaces as the Job ending up JobStatus.failed. Exercises the task
    function directly, same layer other job tests stop short of (they only
    assert the trigger endpoint enqueues correctly, since the task itself
    talks to ansible/aptly) — worth it here because do_sync_repository's
    AptlyError handling is new in this task and not covered elsewhere.
    """
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
            repo_id = r.json()["id"]

            with patch("app.tasks.sync_repository_task.delay"):
                sync_r = c.post("/repositories/sync-unreachable/sync", headers=auth_headers(token))
                assert sync_r.status_code == 201, sync_r.text
                job_id = sync_r.json()["id"]
    finally:
        app.dependency_overrides.clear()

    from app.aptly_client import get_aptly_client as _get_aptly_client_dep
    from app.tasks import sync_repository_task

    app.dependency_overrides[_get_aptly_client_dep] = lambda: mock_aptly_unreachable
    try:
        with patch("app.tasks.get_aptly_client", return_value=mock_aptly_unreachable):
            sync_repository_task(job_id)
    finally:
        app.dependency_overrides.clear()

    with TestClient(app) as c:
        job_r = c.get(f"/jobs/{job_id}", headers=auth_headers(token))
        assert job_r.status_code == 200, job_r.text
        assert job_r.json()["status"] == "failed"

        repo_r = c.get("/repositories", params={"distribution": "jammy"}, headers=auth_headers(token))
        repo = next(r for r in repo_r.json() if r["id"] == repo_id)
        assert repo["last_synced_at"] is None
