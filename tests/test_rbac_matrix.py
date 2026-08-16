"""Automated RBAC sweep: a representative sample of endpoints spanning all
three role tiers (viewer-gated GETs, operator-gated mutations, and the two
admin-only exceptions — POST /jobs/run-command and POST /auth/register),
asserting viewer/operator/admin each get the expected status code. This is
the automated equivalent of the manual RBAC verification done in an earlier
session, made permanent per ROADMAP Phase 7.
"""

import pytest

from tests._rate_limit_helper import reset_login_rate_limit
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    reset_login_rate_limit()
    yield


@pytest.fixture
def seeded_chain(client, operator_token, db_session):
    """A full repo -> content-view -> lifecycle-environment -> server chain,
    plus a host group and an activation key, so the RBAC sweep has real
    resource ids to hit without every test needing its own setup.
    """
    repo = client.post(
        "/repositories",
        json={
            "name": "rbac-repo",
            "archive_url": "http://archive.ubuntu.com/ubuntu",
            "distribution": "jammy",
            "components": ["main"],
            "architectures": ["amd64"],
        },
        headers=auth_headers(operator_token),
    ).json()
    cv = client.post(
        "/content-views", json={"name": "rbac-cv", "repository_ids": [repo["id"]]}, headers=auth_headers(operator_token)
    ).json()
    env = client.post(
        "/lifecycle-environments", json={"name": "rbac-env"}, headers=auth_headers(operator_token)
    ).json()
    server = client.post(
        "/servers",
        json={
            "hostname": "rbac-server.example.com",
            "ip_address": "10.9.9.9",
            "ssh_user": "ubuntu",
            "environment_id": env["id"],
        },
        headers=auth_headers(operator_token),
    ).json()
    host_group = client.post(
        "/host-groups", json={"name": "rbac-hg"}, headers=auth_headers(operator_token)
    ).json()
    return {"repo": repo, "cv": cv, "env": env, "server": server, "host_group": host_group}


# --- viewer-gated GET endpoints: all three tiers should get 200 ---


def test_list_repositories_all_tiers_200(client, viewer_token, operator_token, admin_token, seeded_chain):
    for token in (viewer_token, operator_token, admin_token):
        r = client.get("/repositories", headers=auth_headers(token))
        assert r.status_code == 200, r.text


def test_list_servers_all_tiers_200(client, viewer_token, operator_token, admin_token, seeded_chain):
    for token in (viewer_token, operator_token, admin_token):
        r = client.get("/servers", headers=auth_headers(token))
        assert r.status_code == 200, r.text


def test_list_jobs_all_tiers_200(client, viewer_token, operator_token, admin_token, seeded_chain):
    for token in (viewer_token, operator_token, admin_token):
        r = client.get("/jobs", headers=auth_headers(token))
        assert r.status_code == 200, r.text


# --- operator-gated mutations: viewer 403, operator/admin succeed ---


def test_create_repository_operator_tiers(client, viewer_token, operator_token, admin_token):
    payload_base = {
        "archive_url": "http://archive.ubuntu.com/ubuntu",
        "distribution": "jammy",
        "components": ["main"],
        "architectures": ["amd64"],
    }
    r_viewer = client.post(
        "/repositories", json={**payload_base, "name": "rbac-op-viewer"}, headers=auth_headers(viewer_token)
    )
    assert r_viewer.status_code == 403, r_viewer.text

    r_operator = client.post(
        "/repositories", json={**payload_base, "name": "rbac-op-operator"}, headers=auth_headers(operator_token)
    )
    assert r_operator.status_code == 201, r_operator.text

    r_admin = client.post(
        "/repositories", json={**payload_base, "name": "rbac-op-admin"}, headers=auth_headers(admin_token)
    )
    assert r_admin.status_code == 201, r_admin.text


def test_decommission_server_operator_tiers(client, viewer_token, operator_token, admin_token, seeded_chain):
    server_id = seeded_chain["server"]["id"]

    r_viewer = client.post(f"/servers/{server_id}/decommission", headers=auth_headers(viewer_token))
    assert r_viewer.status_code == 403, r_viewer.text

    r_operator = client.post(f"/servers/{server_id}/decommission", headers=auth_headers(operator_token))
    assert r_operator.status_code == 200, r_operator.text


def test_create_host_group_operator_tiers(client, viewer_token, operator_token, admin_token):
    r_viewer = client.post("/host-groups", json={"name": "rbac-hg-viewer"}, headers=auth_headers(viewer_token))
    assert r_viewer.status_code == 403, r_viewer.text

    r_operator = client.post("/host-groups", json={"name": "rbac-hg-operator"}, headers=auth_headers(operator_token))
    assert r_operator.status_code == 201, r_operator.text

    r_admin = client.post("/host-groups", json={"name": "rbac-hg-admin"}, headers=auth_headers(admin_token))
    assert r_admin.status_code == 201, r_admin.text


def test_trigger_gather_facts_operator_tiers(client, viewer_token, operator_token, seeded_chain):
    environment_id = seeded_chain["env"]["id"]

    r_viewer = client.post(
        "/jobs/gather-facts", params={"environment_id": environment_id}, headers=auth_headers(viewer_token)
    )
    assert r_viewer.status_code == 403, r_viewer.text

    r_operator = client.post(
        "/jobs/gather-facts", params={"environment_id": environment_id}, headers=auth_headers(operator_token)
    )
    assert r_operator.status_code == 201, r_operator.text


# --- the two admin-only exceptions ---


def test_run_command_admin_only(client, viewer_token, operator_token, admin_token, seeded_chain):
    payload = {"server_ids": [seeded_chain["server"]["id"]], "command": "uptime"}

    r_viewer = client.post("/jobs/run-command", json=payload, headers=auth_headers(viewer_token))
    assert r_viewer.status_code == 403, r_viewer.text

    r_operator = client.post("/jobs/run-command", json=payload, headers=auth_headers(operator_token))
    assert r_operator.status_code == 403, r_operator.text

    r_admin = client.post("/jobs/run-command", json=payload, headers=auth_headers(admin_token))
    assert r_admin.status_code == 201, r_admin.text


def test_register_user_admin_only(client, viewer_token, operator_token, admin_token):
    def payload(username):
        return {"username": username, "email": f"{username}@example.com", "password": "Passw0rd!", "role": "viewer"}

    r_viewer = client.post("/auth/register", json=payload("rbac-reg-viewer"), headers=auth_headers(viewer_token))
    assert r_viewer.status_code == 403, r_viewer.text

    r_operator = client.post("/auth/register", json=payload("rbac-reg-operator"), headers=auth_headers(operator_token))
    assert r_operator.status_code == 403, r_operator.text

    r_admin = client.post("/auth/register", json=payload("rbac-reg-admin"), headers=auth_headers(admin_token))
    assert r_admin.status_code == 201, r_admin.text


# --- admin-only read endpoint (audit logs) — operator also denied, unlike most GETs ---


def test_audit_logs_admin_only(client, viewer_token, operator_token, admin_token, seeded_chain):
    r_viewer = client.get("/audit-logs", headers=auth_headers(viewer_token))
    assert r_viewer.status_code == 403, r_viewer.text

    r_operator = client.get("/audit-logs", headers=auth_headers(operator_token))
    assert r_operator.status_code == 403, r_operator.text

    r_admin = client.get("/audit-logs", headers=auth_headers(admin_token))
    assert r_admin.status_code == 200, r_admin.text
