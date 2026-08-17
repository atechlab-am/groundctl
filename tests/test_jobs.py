from unittest.mock import patch

import pytest

from tests._rate_limit_helper import reset_login_rate_limit
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    reset_login_rate_limit()
    yield


def _create_repo(client, operator_token, name="jammy-main"):
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


def _create_cv(client, operator_token, repo, name="cv"):
    r = client.post(
        "/content-views",
        json={"name": name, "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 201, r.text
    return r.json()


def _create_env(client, operator_token, cv, name="dev", path_name="main", position=0, publish_prefix="dev"):
    # An environment is now pure path structure with NO content view of its
    # own (LifecycleEnvironmentCreate takes only name/description/
    # prior_environment_id) — `cv` is accepted for call-site compatibility
    # but intentionally left UNASSIGNED here. Every job task in this file
    # is only exercised via mocked .delay (never a real task-body call), so
    # having no EnvironmentContentView assignment at all is harmless —
    # nothing reads it. cv/path_name/position/publish_prefix args kept for
    # call-site compatibility only.
    r = client.post(
        "/lifecycle-environments", json={"name": name}, headers=auth_headers(operator_token)
    )
    assert r.status_code == 201, r.text
    return r.json()


def _make_environment(client, operator_token, suffix="1"):
    repo = _create_repo(client, operator_token, f"job-repo-{suffix}")
    cv = _create_cv(client, operator_token, repo, f"job-cv-{suffix}")
    return _create_env(client, operator_token, cv, f"job-env-{suffix}", f"job-path-{suffix}", 0, f"job-prefix-{suffix}")


def _create_server(client, operator_token, environment, hostname="host1.example.com", ip="10.1.0.1"):
    r = client.post(
        "/servers",
        json={
            "hostname": hostname,
            "ip_address": ip,
            "ssh_user": "deploy",
            "environment_id": environment["id"],
        },
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# GET /jobs
# ---------------------------------------------------------------------------


def test_list_jobs_empty(client, viewer_token):
    r = client.get("/jobs", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    assert r.json() == []


def test_list_jobs_filter_by_job_type_status_environment_server(client, operator_token):
    env = _make_environment(client, operator_token, "1")
    server = _create_server(client, operator_token, env, "jobhost1.example.com", "10.1.0.10")

    with patch("app.routers.jobs.bootstrap_task.delay") as mock_delay:
        r = client.post(f"/jobs/bootstrap/{server['id']}", headers=auth_headers(operator_token))
        assert r.status_code == 201, r.text
        job = r.json()
        mock_delay.assert_called_once_with(str(job["id"]))

    # job_type filter
    r = client.get("/jobs", params={"job_type": "bootstrap"}, headers=auth_headers(operator_token))
    assert r.status_code == 200, r.text
    assert any(j["id"] == job["id"] for j in r.json())

    r = client.get("/jobs", params={"job_type": "apply_updates"}, headers=auth_headers(operator_token))
    assert r.status_code == 200, r.text
    assert all(j["id"] != job["id"] for j in r.json())

    # status filter (external query param name is "status", python param is status_)
    r = client.get("/jobs", params={"status": "pending"}, headers=auth_headers(operator_token))
    assert r.status_code == 200, r.text
    assert any(j["id"] == job["id"] for j in r.json())

    r = client.get("/jobs", params={"status": "success"}, headers=auth_headers(operator_token))
    assert r.status_code == 200, r.text
    assert all(j["id"] != job["id"] for j in r.json())

    # server_id filter
    r = client.get("/jobs", params={"server_id": server["id"]}, headers=auth_headers(operator_token))
    assert r.status_code == 200, r.text
    assert any(j["id"] == job["id"] for j in r.json())

    # environment_id filter — bootstrap job targets a server, not an
    # environment, so it should NOT show up when filtering by environment_id.
    r = client.get("/jobs", params={"environment_id": env["id"]}, headers=auth_headers(operator_token))
    assert r.status_code == 200, r.text
    assert all(j["id"] != job["id"] for j in r.json())


def test_list_jobs_paginated(client, operator_token):
    env = _make_environment(client, operator_token, "2")
    server = _create_server(client, operator_token, env, "jobhost2.example.com", "10.1.0.11")

    with patch("app.routers.jobs.bootstrap_task.delay"):
        for _ in range(3):
            r = client.post(f"/jobs/bootstrap/{server['id']}", headers=auth_headers(operator_token))
            assert r.status_code == 201, r.text

    r = client.get("/jobs", params={"limit": 2, "offset": 0}, headers=auth_headers(operator_token))
    assert r.status_code == 200, r.text
    assert len(r.json()) == 2


# ---------------------------------------------------------------------------
# POST /jobs/bootstrap/{server_id}
# ---------------------------------------------------------------------------


def test_trigger_bootstrap_as_operator(client, operator_token):
    env = _make_environment(client, operator_token, "3")
    server = _create_server(client, operator_token, env, "jobhost3.example.com", "10.1.0.12")

    with patch("app.routers.jobs.bootstrap_task.delay") as mock_delay:
        r = client.post(f"/jobs/bootstrap/{server['id']}", headers=auth_headers(operator_token))
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["job_type"] == "bootstrap"
        assert body["status"] == "pending"
        assert body["target_type"] == "server"
        assert body["server_id"] == server["id"]
        assert body["server_ids"] == [server["id"]]
        mock_delay.assert_called_once_with(str(body["id"]))


def test_trigger_bootstrap_as_viewer_forbidden(client, operator_token, viewer_token):
    env = _make_environment(client, operator_token, "4")
    server = _create_server(client, operator_token, env, "jobhost4.example.com", "10.1.0.13")

    with patch("app.routers.jobs.bootstrap_task.delay") as mock_delay:
        r = client.post(f"/jobs/bootstrap/{server['id']}", headers=auth_headers(viewer_token))
        assert r.status_code == 403, r.text
        mock_delay.assert_not_called()


def test_trigger_bootstrap_server_not_found(client, operator_token):
    with patch("app.routers.jobs.bootstrap_task.delay") as mock_delay:
        r = client.post(
            "/jobs/bootstrap/00000000-0000-0000-0000-000000000000", headers=auth_headers(operator_token)
        )
        assert r.status_code == 404, r.text
        mock_delay.assert_not_called()


# ---------------------------------------------------------------------------
# POST /jobs/install-beacon/{server_id}
# ---------------------------------------------------------------------------


def test_trigger_install_beacon_as_operator(client, operator_token):
    env = _make_environment(client, operator_token, "30")
    server = _create_server(client, operator_token, env, "jobhost30.example.com", "10.1.0.40")

    with patch("app.routers.jobs.install_beacon_task.delay") as mock_delay:
        r = client.post(f"/jobs/install-beacon/{server['id']}", headers=auth_headers(operator_token))
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["job_type"] == "install_beacon"
        assert body["status"] == "pending"
        assert body["target_type"] == "server"
        assert body["server_id"] == server["id"]
        assert body["server_ids"] == [server["id"]]
        mock_delay.assert_called_once_with(str(body["id"]))


def test_trigger_install_beacon_as_viewer_forbidden(client, operator_token, viewer_token):
    env = _make_environment(client, operator_token, "31")
    server = _create_server(client, operator_token, env, "jobhost31.example.com", "10.1.0.41")

    with patch("app.routers.jobs.install_beacon_task.delay") as mock_delay:
        r = client.post(f"/jobs/install-beacon/{server['id']}", headers=auth_headers(viewer_token))
        assert r.status_code == 403, r.text
        mock_delay.assert_not_called()


def test_trigger_install_beacon_server_not_found(client, operator_token):
    with patch("app.routers.jobs.install_beacon_task.delay") as mock_delay:
        r = client.post(
            "/jobs/install-beacon/00000000-0000-0000-0000-000000000000", headers=auth_headers(operator_token)
        )
        assert r.status_code == 404, r.text
        mock_delay.assert_not_called()


def test_trigger_install_beacon_decommissioned_rejected(client, operator_token):
    env = _make_environment(client, operator_token, "32")
    server = _create_server(client, operator_token, env, "jobhost32.example.com", "10.1.0.42")
    decommission_r = client.post(
        f"/servers/{server['id']}/decommission", headers=auth_headers(operator_token)
    )
    assert decommission_r.status_code == 200, decommission_r.text

    with patch("app.routers.jobs.install_beacon_task.delay") as mock_delay:
        r = client.post(f"/jobs/install-beacon/{server['id']}", headers=auth_headers(operator_token))
        assert r.status_code == 409, r.text
        mock_delay.assert_not_called()


# ---------------------------------------------------------------------------
# POST /jobs/apply-updates
# ---------------------------------------------------------------------------


def test_trigger_apply_updates_as_operator(client, operator_token):
    env = _make_environment(client, operator_token, "5")
    server = _create_server(client, operator_token, env, "jobhost5.example.com", "10.1.0.14")

    with patch("app.routers.jobs.apply_updates_task.delay") as mock_delay:
        r = client.post(
            "/jobs/apply-updates", params={"environment_id": env["id"]}, headers=auth_headers(operator_token)
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["job_type"] == "apply_updates"
        assert body["target_type"] == "environment"
        assert body["environment_id"] == env["id"]
        assert body["server_ids"] == [server["id"]]
        mock_delay.assert_called_once_with(str(body["id"]))


def test_trigger_apply_updates_as_viewer_forbidden(client, operator_token, viewer_token):
    env = _make_environment(client, operator_token, "6")
    with patch("app.routers.jobs.apply_updates_task.delay") as mock_delay:
        r = client.post(
            "/jobs/apply-updates", params={"environment_id": env["id"]}, headers=auth_headers(viewer_token)
        )
        assert r.status_code == 403, r.text
        mock_delay.assert_not_called()


def test_trigger_apply_updates_environment_not_found(client, operator_token):
    with patch("app.routers.jobs.apply_updates_task.delay") as mock_delay:
        r = client.post(
            "/jobs/apply-updates",
            params={"environment_id": "00000000-0000-0000-0000-000000000000"},
            headers=auth_headers(operator_token),
        )
        assert r.status_code == 404, r.text
        mock_delay.assert_not_called()


# ---------------------------------------------------------------------------
# POST /jobs/gather-facts
# ---------------------------------------------------------------------------


def test_trigger_gather_facts_as_operator(client, operator_token):
    env = _make_environment(client, operator_token, "7")
    server = _create_server(client, operator_token, env, "jobhost7.example.com", "10.1.0.15")

    with patch("app.routers.jobs.gather_facts_task.delay") as mock_delay:
        r = client.post(
            "/jobs/gather-facts", params={"environment_id": env["id"]}, headers=auth_headers(operator_token)
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["job_type"] == "gather_facts"
        assert body["target_type"] == "environment"
        assert body["server_ids"] == [server["id"]]
        mock_delay.assert_called_once_with(str(body["id"]))


def test_trigger_gather_facts_as_viewer_forbidden(client, operator_token, viewer_token):
    env = _make_environment(client, operator_token, "8")
    with patch("app.routers.jobs.gather_facts_task.delay") as mock_delay:
        r = client.post(
            "/jobs/gather-facts", params={"environment_id": env["id"]}, headers=auth_headers(viewer_token)
        )
        assert r.status_code == 403, r.text
        mock_delay.assert_not_called()


def test_trigger_gather_facts_environment_not_found(client, operator_token):
    with patch("app.routers.jobs.gather_facts_task.delay") as mock_delay:
        r = client.post(
            "/jobs/gather-facts",
            params={"environment_id": "00000000-0000-0000-0000-000000000000"},
            headers=auth_headers(operator_token),
        )
        assert r.status_code == 404, r.text
        mock_delay.assert_not_called()


# ---------------------------------------------------------------------------
# POST /jobs/bulk-apply-updates
# ---------------------------------------------------------------------------


def test_trigger_bulk_apply_updates_by_server_ids(client, operator_token):
    env = _make_environment(client, operator_token, "9")
    server1 = _create_server(client, operator_token, env, "jobhost9a.example.com", "10.1.0.16")
    server2 = _create_server(client, operator_token, env, "jobhost9b.example.com", "10.1.0.17")

    with patch("app.routers.jobs.bulk_apply_updates_task.delay") as mock_delay:
        r = client.post(
            "/jobs/bulk-apply-updates",
            json={"server_ids": [server1["id"], server2["id"]]},
            headers=auth_headers(operator_token),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["job_type"] == "bulk_apply_updates"
        assert body["target_type"] == "adhoc"
        assert set(body["server_ids"]) == {server1["id"], server2["id"]}
        mock_delay.assert_called_once_with(str(body["id"]))


def test_trigger_bulk_apply_updates_missing_server_id_404s(client, operator_token):
    with patch("app.routers.jobs.bulk_apply_updates_task.delay") as mock_delay:
        r = client.post(
            "/jobs/bulk-apply-updates",
            json={"server_ids": ["00000000-0000-0000-0000-000000000000"]},
            headers=auth_headers(operator_token),
        )
        assert r.status_code == 404, r.text
        mock_delay.assert_not_called()


def test_trigger_bulk_apply_updates_both_selectors_set_422(client, operator_token, db_session):
    from app.models import HostGroup

    hg = HostGroup(name="hg-bulk-both")
    db_session.add(hg)
    db_session.commit()
    db_session.refresh(hg)

    with patch("app.routers.jobs.bulk_apply_updates_task.delay") as mock_delay:
        r = client.post(
            "/jobs/bulk-apply-updates",
            json={"host_group_id": str(hg.id), "server_ids": ["00000000-0000-0000-0000-000000000000"]},
            headers=auth_headers(operator_token),
        )
        assert r.status_code == 422, r.text
        mock_delay.assert_not_called()


def test_trigger_bulk_apply_updates_neither_selector_set_422(client, operator_token):
    with patch("app.routers.jobs.bulk_apply_updates_task.delay") as mock_delay:
        r = client.post("/jobs/bulk-apply-updates", json={}, headers=auth_headers(operator_token))
        assert r.status_code == 422, r.text
        mock_delay.assert_not_called()


def test_trigger_bulk_apply_updates_as_viewer_forbidden(client, operator_token, viewer_token):
    env = _make_environment(client, operator_token, "10")
    server = _create_server(client, operator_token, env, "jobhost10.example.com", "10.1.0.18")

    with patch("app.routers.jobs.bulk_apply_updates_task.delay") as mock_delay:
        r = client.post(
            "/jobs/bulk-apply-updates",
            json={"server_ids": [server["id"]]},
            headers=auth_headers(viewer_token),
        )
        assert r.status_code == 403, r.text
        mock_delay.assert_not_called()


# ---------------------------------------------------------------------------
# POST /jobs/run-command — admin only (RBAC exception)
# ---------------------------------------------------------------------------


def test_trigger_run_command_as_operator_forbidden(client, operator_token):
    env = _make_environment(client, operator_token, "11")
    server = _create_server(client, operator_token, env, "jobhost11.example.com", "10.1.0.19")

    with patch("app.routers.jobs.run_command_task.delay") as mock_delay:
        r = client.post(
            "/jobs/run-command",
            json={"server_ids": [server["id"]], "command": "uptime"},
            headers=auth_headers(operator_token),
        )
        assert r.status_code == 403, r.text
        mock_delay.assert_not_called()


def test_trigger_run_command_as_admin_succeeds(client, admin_token, operator_token):
    env = _make_environment(client, operator_token, "12")
    server = _create_server(client, operator_token, env, "jobhost12.example.com", "10.1.0.20")

    with patch("app.routers.jobs.run_command_task.delay") as mock_delay:
        r = client.post(
            "/jobs/run-command",
            json={"server_ids": [server["id"]], "command": "uptime"},
            headers=auth_headers(admin_token),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["job_type"] == "run_command"
        assert body["server_ids"] == [server["id"]]
        mock_delay.assert_called_once_with(str(body["id"]))


def test_trigger_run_command_rejects_shell_metacharacters(client, admin_token, operator_token):
    env = _make_environment(client, operator_token, "13")
    server = _create_server(client, operator_token, env, "jobhost13.example.com", "10.1.0.21")

    with patch("app.routers.jobs.run_command_task.delay") as mock_delay:
        r = client.post(
            "/jobs/run-command",
            json={"server_ids": [server["id"]], "command": "uptime; rm -rf /"},
            headers=auth_headers(admin_token),
        )
        assert r.status_code == 422, r.text
        mock_delay.assert_not_called()


# ---------------------------------------------------------------------------
# POST /jobs/manage-package
# ---------------------------------------------------------------------------


def test_trigger_manage_package_as_operator(client, operator_token):
    env = _make_environment(client, operator_token, "14")
    server = _create_server(client, operator_token, env, "jobhost14.example.com", "10.1.0.22")

    with patch("app.routers.jobs.manage_package_task.delay") as mock_delay:
        r = client.post(
            "/jobs/manage-package",
            json={"server_id": server["id"], "package_name": "nginx", "action": "install"},
            headers=auth_headers(operator_token),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["job_type"] == "manage_package"
        assert body["target_type"] == "server"
        assert body["server_id"] == server["id"]
        mock_delay.assert_called_once_with(str(body["id"]))


def test_trigger_manage_package_as_viewer_forbidden(client, operator_token, viewer_token):
    env = _make_environment(client, operator_token, "15")
    server = _create_server(client, operator_token, env, "jobhost15.example.com", "10.1.0.23")

    with patch("app.routers.jobs.manage_package_task.delay") as mock_delay:
        r = client.post(
            "/jobs/manage-package",
            json={"server_id": server["id"], "package_name": "nginx", "action": "install"},
            headers=auth_headers(viewer_token),
        )
        assert r.status_code == 403, r.text
        mock_delay.assert_not_called()


def test_trigger_manage_package_server_not_found(client, operator_token):
    with patch("app.routers.jobs.manage_package_task.delay") as mock_delay:
        r = client.post(
            "/jobs/manage-package",
            json={
                "server_id": "00000000-0000-0000-0000-000000000000",
                "package_name": "nginx",
                "action": "install",
            },
            headers=auth_headers(operator_token),
        )
        assert r.status_code == 404, r.text
        mock_delay.assert_not_called()


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}, POST /jobs/{job_id}/cancel
# ---------------------------------------------------------------------------


def test_get_job_by_id(client, operator_token):
    env = _make_environment(client, operator_token, "16")
    server = _create_server(client, operator_token, env, "jobhost16.example.com", "10.1.0.24")

    with patch("app.routers.jobs.bootstrap_task.delay"):
        job = client.post(f"/jobs/bootstrap/{server['id']}", headers=auth_headers(operator_token)).json()

    r = client.get(f"/jobs/{job['id']}", headers=auth_headers(operator_token))
    assert r.status_code == 200, r.text
    assert r.json()["id"] == job["id"]


def test_get_job_not_found(client, viewer_token):
    r = client.get("/jobs/00000000-0000-0000-0000-000000000000", headers=auth_headers(viewer_token))
    assert r.status_code == 404, r.text


def test_cancel_pending_job(client, operator_token):
    env = _make_environment(client, operator_token, "17")
    server = _create_server(client, operator_token, env, "jobhost17.example.com", "10.1.0.25")

    with patch("app.routers.jobs.bootstrap_task.delay"):
        job = client.post(f"/jobs/bootstrap/{server['id']}", headers=auth_headers(operator_token)).json()

    r = client.post(f"/jobs/{job['id']}/cancel", headers=auth_headers(operator_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "failed"
    assert body["log_output"] == "cancelled before execution"


def test_cancel_job_as_viewer_forbidden(client, operator_token, viewer_token):
    env = _make_environment(client, operator_token, "18")
    server = _create_server(client, operator_token, env, "jobhost18.example.com", "10.1.0.26")

    with patch("app.routers.jobs.bootstrap_task.delay"):
        job = client.post(f"/jobs/bootstrap/{server['id']}", headers=auth_headers(operator_token)).json()

    r = client.post(f"/jobs/{job['id']}/cancel", headers=auth_headers(viewer_token))
    assert r.status_code == 403, r.text


def test_cancel_job_not_found(client, operator_token):
    r = client.post(
        "/jobs/00000000-0000-0000-0000-000000000000/cancel", headers=auth_headers(operator_token)
    )
    assert r.status_code == 404, r.text


def test_cancel_already_finished_job_conflicts(client, operator_token, db_session):
    from datetime import datetime, timezone

    from app.models import Job, JobStatus, JobTargetType, JobType

    job = Job(
        job_type=JobType.bootstrap,
        target_type=JobTargetType.server,
        status=JobStatus.success,
        finished_at=datetime.now(timezone.utc),
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    r = client.post(f"/jobs/{job.id}/cancel", headers=auth_headers(operator_token))
    assert r.status_code == 409, r.text
