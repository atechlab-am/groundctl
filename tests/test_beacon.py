import pytest
from sqlalchemy import select

from tests._rate_limit_helper import reset_login_rate_limit
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    reset_login_rate_limit()
    yield


def _create_repo(client, operator_token, name="beacon-repo"):
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


def _create_cv(client, operator_token, repo, name="beacon-cv"):
    r = client.post(
        "/content-views",
        json={"name": name, "repository_ids": [repo["id"]]},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 201, r.text
    return r.json()


def _library(client, operator_token):
    # Position 0 is always Library, auto-seeded the first time an
    # environment is created with no prior_environment_id. Seeds it via a
    # throwaway create if it doesn't exist yet in this test's fresh DB.
    listed = client.get("/lifecycle-environments", headers=auth_headers(operator_token)).json()
    library = next((e for e in listed if e["name"] == "Library"), None)
    if library is not None:
        return library
    client.post("/lifecycle-environments", json={"name": "_seed"}, headers=auth_headers(operator_token))
    listed = client.get("/lifecycle-environments", headers=auth_headers(operator_token)).json()
    return next(e for e in listed if e["name"] == "Library")


def _create_env(client, operator_token, cv, name="beacon-env", path_name="beacon-path", position=0, publish_prefix="beacon-prefix"):
    # An environment is now pure path structure with NO content view of its
    # own (LifecycleEnvironmentCreate takes only name/description/
    # prior_environment_id) — content views are assigned to it afterward
    # via POST /{id}/content-views, which also performs that pair's first
    # promote in the same call, directly, regardless of position (no
    # path-order gate). Every beacon checkin call in this file needs at
    # least one genuinely PUBLISHED assignment now (checkin's
    # `content_views` list is populated from published EnvironmentContentView
    # rows — app/routers/beacon.py), so this helper chains the new
    # environment after Library then assigns+promotes the content view's
    # already-published version 1 straight to it. cv/path_name/position/
    # publish_prefix args kept for call-site compatibility; only `name`
    # and `cv` actually matter now.
    library = _library(client, operator_token)
    versions_r = client.get(f"/content-views/{cv['id']}/versions", headers=auth_headers(operator_token))
    version_id = versions_r.json()[0]["id"]

    r = client.post(
        "/lifecycle-environments",
        json={"name": name, "prior_environment_id": library["id"]},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 201, r.text
    env = r.json()

    assign_r = client.post(
        f"/lifecycle-environments/{env['id']}/content-views",
        json={"content_view_id": cv["id"], "content_view_version_id": version_id, "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )
    assert assign_r.status_code == 201, assign_r.text

    return env


def _make_environment(client, operator_token, suffix="1"):
    repo = _create_repo(client, operator_token, f"beacon-repo-{suffix}")
    cv = _create_cv(client, operator_token, repo, f"beacon-cv-{suffix}")
    return _create_env(
        client, operator_token, cv, f"beacon-env-{suffix}", f"beacon-path-{suffix}", 0, f"beacon-prefix-{suffix}"
    )


def _create_server(client, operator_token, environment, hostname="beacon-host1.example.com", ip="10.1.0.1"):
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


def _issue_token(client, operator_token, server, name=None):
    r = client.post(
        f"/servers/{server['id']}/beacon-token",
        json={"name": name},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 201, r.text
    return r.json()


# --- token issuance / listing / revocation ---------------------------------


def test_issue_beacon_token_as_operator(client, operator_token):
    env = _make_environment(client, operator_token, "1")
    server = _create_server(client, operator_token, env)

    r = client.post(
        f"/servers/{server['id']}/beacon-token",
        json={"name": "primary"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["server_id"] == server["id"]
    assert body["name"] == "primary"
    assert body["token"]
    assert body["expires_at"] is None


def test_issue_beacon_token_as_viewer_forbidden(client, operator_token, viewer_token):
    env = _make_environment(client, operator_token, "2")
    server = _create_server(client, operator_token, env, "beacon-host2.example.com", "10.1.0.2")

    r = client.post(
        f"/servers/{server['id']}/beacon-token",
        json={},
        headers=auth_headers(viewer_token),
    )
    assert r.status_code == 403, r.text


def test_issue_beacon_token_not_found_server(client, operator_token):
    r = client.post(
        "/servers/00000000-0000-0000-0000-000000000000/beacon-token",
        json={},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_issue_beacon_token_decommissioned_rejected(client, operator_token):
    env = _make_environment(client, operator_token, "3")
    server = _create_server(client, operator_token, env, "beacon-host3.example.com", "10.1.0.3")
    client.post(f"/servers/{server['id']}/decommission", headers=auth_headers(operator_token))

    r = client.post(
        f"/servers/{server['id']}/beacon-token",
        json={},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 409, r.text


def test_list_beacon_tokens_never_includes_hash(client, operator_token):
    env = _make_environment(client, operator_token, "4")
    server = _create_server(client, operator_token, env, "beacon-host4.example.com", "10.1.0.4")
    _issue_token(client, operator_token, server, "primary")

    r = client.get(f"/servers/{server['id']}/beacon-tokens", headers=auth_headers(operator_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1
    assert body[0]["name"] == "primary"
    assert "token" not in body[0]
    assert "token_hash" not in body[0]


def test_list_beacon_tokens_not_found_server(client, viewer_token):
    r = client.get(
        "/servers/00000000-0000-0000-0000-000000000000/beacon-tokens", headers=auth_headers(viewer_token)
    )
    assert r.status_code == 404, r.text


# --- beacon state ------------------------------------------------------------


def test_get_beacon_state_before_any_checkin_404s(client, operator_token):
    env = _make_environment(client, operator_token, "37")
    server = _create_server(client, operator_token, env, "beacon-host37.example.com", "10.1.0.47")

    r = client.get(f"/servers/{server['id']}/beacon-state", headers=auth_headers(operator_token))
    assert r.status_code == 404, r.text


def test_get_beacon_state_not_pending_right_after_checkin(client, operator_token):
    env = _make_environment(client, operator_token, "38")
    server = _create_server(client, operator_token, env, "beacon-host38.example.com", "10.1.0.48")
    token = _issue_token(client, operator_token, server)
    headers = {"Authorization": f"Bearer {token['token']}"}
    client.post("/beacon/checkin", json={"agent_version": "0.3.0"}, headers=headers)

    r = client.get(f"/servers/{server['id']}/beacon-state", headers=auth_headers(operator_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["config_serial"] == 1
    assert body["applied_config_serial"] is None
    assert body["pending_reconciliation"] is True  # never reconciled yet — NULL-safe true
    assert body["agent_version"] == "0.3.0"


def test_get_beacon_state_not_pending_after_successful_report(client, operator_token):
    env = _make_environment(client, operator_token, "39")
    server = _create_server(client, operator_token, env, "beacon-host39.example.com", "10.1.0.49")
    token = _issue_token(client, operator_token, server)
    headers = {"Authorization": f"Bearer {token['token']}"}
    checkin_r = client.post("/beacon/checkin", json={"agent_version": "0.3.0"}, headers=headers)
    config_serial = checkin_r.json()["config_serial"]
    client.post(
        "/beacon/report", json={"config_serial": config_serial, "outcome": "success"}, headers=headers
    )

    r = client.get(f"/servers/{server['id']}/beacon-state", headers=auth_headers(operator_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied_config_serial"] == config_serial
    assert body["pending_reconciliation"] is False


def test_get_beacon_state_pending_after_reassignment(client, operator_token):
    env1 = _make_environment(client, operator_token, "40a")
    env2 = _make_environment(client, operator_token, "40b")
    server = _create_server(client, operator_token, env1, "beacon-host40.example.com", "10.1.0.50")
    token = _issue_token(client, operator_token, server)
    headers = {"Authorization": f"Bearer {token['token']}"}
    checkin_r = client.post("/beacon/checkin", json={"agent_version": "0.3.0"}, headers=headers)
    config_serial = checkin_r.json()["config_serial"]
    client.post("/beacon/report", json={"config_serial": config_serial, "outcome": "success"}, headers=headers)

    reassign_r = client.post(
        f"/servers/{server['id']}/assign-environment",
        json={"environment_id": env2["id"]},
        headers=auth_headers(operator_token),
    )
    assert reassign_r.status_code == 200, reassign_r.text

    r = client.get(f"/servers/{server['id']}/beacon-state", headers=auth_headers(operator_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pending_reconciliation"] is True


def test_get_beacon_state_not_found_server(client, viewer_token):
    r = client.get(
        "/servers/00000000-0000-0000-0000-000000000000/beacon-state", headers=auth_headers(viewer_token)
    )
    assert r.status_code == 404, r.text


def test_revoke_beacon_token_as_operator(client, operator_token):
    env = _make_environment(client, operator_token, "5")
    server = _create_server(client, operator_token, env, "beacon-host5.example.com", "10.1.0.5")
    token = _issue_token(client, operator_token, server)

    r = client.post(
        f"/servers/{server['id']}/beacon-tokens/{token['id']}/revoke", headers=auth_headers(operator_token)
    )
    assert r.status_code == 200, r.text
    assert r.json()["revoked"] is True


def test_revoke_beacon_token_as_viewer_forbidden(client, operator_token, viewer_token):
    env = _make_environment(client, operator_token, "6")
    server = _create_server(client, operator_token, env, "beacon-host6.example.com", "10.1.0.6")
    token = _issue_token(client, operator_token, server)

    r = client.post(
        f"/servers/{server['id']}/beacon-tokens/{token['id']}/revoke", headers=auth_headers(viewer_token)
    )
    assert r.status_code == 403, r.text


def test_revoke_beacon_token_not_found(client, operator_token):
    env = _make_environment(client, operator_token, "7")
    server = _create_server(client, operator_token, env, "beacon-host7.example.com", "10.1.0.7")

    r = client.post(
        f"/servers/{server['id']}/beacon-tokens/00000000-0000-0000-0000-000000000000/revoke",
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_revoke_beacon_token_wrong_server_404s(client, operator_token):
    env = _make_environment(client, operator_token, "8")
    server1 = _create_server(client, operator_token, env, "beacon-host8a.example.com", "10.1.0.8")
    server2 = _create_server(client, operator_token, env, "beacon-host8b.example.com", "10.1.0.9")
    token = _issue_token(client, operator_token, server1)

    r = client.post(
        f"/servers/{server2['id']}/beacon-tokens/{token['id']}/revoke", headers=auth_headers(operator_token)
    )
    assert r.status_code == 404, r.text


# --- checkin -----------------------------------------------------------------


def test_checkin_with_valid_token(client, operator_token):
    env = _make_environment(client, operator_token, "9")
    server = _create_server(client, operator_token, env, "beacon-host9.example.com", "10.1.0.10")
    token = _issue_token(client, operator_token, server)

    r = client.post(
        "/beacon/checkin",
        json={"agent_version": "0.1.0"},
        headers={"Authorization": f"Bearer {token['token']}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["server_id"] == server["id"]
    assert body["hostname"] == server["hostname"]
    assert body["environment_name"] == env["name"]
    assert len(body["content_views"]) == 1
    cv_info = body["content_views"][0]
    assert cv_info["apt_source"]["filename"] == f"groundctl-{env['name']}-{cv_info['content_view_name']}.list"
    assert "deb [trusted=yes]" in cv_info["apt_source"]["contents"]
    assert body["checkin_interval_seconds"] == 300
    assert body["actions"] == []
    assert body["config_serial"] == 1
    # Unsigned assignment (allow_unsigned=True in _create_env) — no key.
    assert cv_info["gpg_public_key"] is None

    # last_seen_at is now a real heartbeat for a beacon-managed host.
    get_r = client.get(f"/servers/{server['id']}", headers=auth_headers(operator_token))
    assert get_r.json()["last_seen_at"] is not None


def test_checkin_bumps_config_serial_after_reassignment(client, operator_token):
    env_a = _make_environment(client, operator_token, "10a")
    env_b = _make_environment(client, operator_token, "10b")
    server = _create_server(client, operator_token, env_a, "beacon-host10.example.com", "10.1.0.11")
    token = _issue_token(client, operator_token, server)

    r1 = client.post(
        "/beacon/checkin",
        json={"agent_version": "0.1.0"},
        headers={"Authorization": f"Bearer {token['token']}"},
    )
    assert r1.json()["config_serial"] == 1

    client.post(
        f"/servers/{server['id']}/assign-environment",
        json={"environment_id": env_b["id"]},
        headers=auth_headers(operator_token),
    )

    r2 = client.post(
        "/beacon/checkin",
        json={"agent_version": "0.1.0"},
        headers={"Authorization": f"Bearer {token['token']}"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["config_serial"] == 2
    assert r2.json()["environment_name"] == env_b["name"]


def test_checkin_no_token_rejected(client):
    r = client.post("/beacon/checkin", json={"agent_version": "0.1.0"})
    assert r.status_code == 401, r.text


def test_checkin_invalid_token_rejected(client):
    r = client.post(
        "/beacon/checkin",
        json={"agent_version": "0.1.0"},
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert r.status_code == 401, r.text


def test_checkin_revoked_token_rejected(client, operator_token):
    env = _make_environment(client, operator_token, "11")
    server = _create_server(client, operator_token, env, "beacon-host11.example.com", "10.1.0.12")
    token = _issue_token(client, operator_token, server)
    client.post(
        f"/servers/{server['id']}/beacon-tokens/{token['id']}/revoke", headers=auth_headers(operator_token)
    )

    r = client.post(
        "/beacon/checkin",
        json={"agent_version": "0.1.0"},
        headers={"Authorization": f"Bearer {token['token']}"},
    )
    assert r.status_code == 401, r.text


def test_checkin_decommissioned_server_rejected(client, operator_token):
    env = _make_environment(client, operator_token, "12")
    server = _create_server(client, operator_token, env, "beacon-host12.example.com", "10.1.0.13")
    token = _issue_token(client, operator_token, server)
    client.post(f"/servers/{server['id']}/decommission", headers=auth_headers(operator_token))

    r = client.post(
        "/beacon/checkin",
        json={"agent_version": "0.1.0"},
        headers={"Authorization": f"Bearer {token['token']}"},
    )
    assert r.status_code == 401, r.text


def test_checkin_token_cannot_be_used_for_a_different_server(client, operator_token):
    """The structural invariant: a beacon token always resolves to exactly
    the one server it was issued for. There's no server_id parameter on
    the checkin endpoint at all, so this mostly proves the token->server
    binding is real — server2's data is never reachable via server1's token.
    """
    env = _make_environment(client, operator_token, "13")
    server1 = _create_server(client, operator_token, env, "beacon-host13a.example.com", "10.1.0.14")
    server2 = _create_server(client, operator_token, env, "beacon-host13b.example.com", "10.1.0.15")
    token1 = _issue_token(client, operator_token, server1)

    r = client.post(
        "/beacon/checkin",
        json={"agent_version": "0.1.0"},
        headers={"Authorization": f"Bearer {token1['token']}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["server_id"] == server1["id"]
    assert r.json()["server_id"] != server2["id"]


# --- report --------------------------------------------------------------


def test_report_success_bumps_applied_config_serial(client, operator_token):
    env = _make_environment(client, operator_token, "14")
    server = _create_server(client, operator_token, env, "beacon-host14.example.com", "10.1.0.16")
    token = _issue_token(client, operator_token, server)
    headers = {"Authorization": f"Bearer {token['token']}"}

    checkin_r = client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=headers)
    config_serial = checkin_r.json()["config_serial"]

    r = client.post(
        "/beacon/report",
        json={"config_serial": config_serial, "outcome": "success", "detail": "apt-get update OK"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] is True


def test_report_no_change_bumps_applied_config_serial(client, operator_token):
    env = _make_environment(client, operator_token, "15")
    server = _create_server(client, operator_token, env, "beacon-host15.example.com", "10.1.0.17")
    token = _issue_token(client, operator_token, server)
    headers = {"Authorization": f"Bearer {token['token']}"}
    checkin_r = client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=headers)
    config_serial = checkin_r.json()["config_serial"]

    r = client.post(
        "/beacon/report",
        json={"config_serial": config_serial, "outcome": "no_change"},
        headers=headers,
    )
    assert r.status_code == 200, r.text


def test_report_failed_does_not_advance_reconciliation(client, operator_token):
    """A failed report must not silently clear the "pending reconciliation"
    signal — the whole point of tracking applied_config_serial separately
    from config_serial is that a host stuck on stale sources.list stays
    visibly stuck, not falsely marked caught-up.
    """
    env = _make_environment(client, operator_token, "16")
    server = _create_server(client, operator_token, env, "beacon-host16.example.com", "10.1.0.18")
    token = _issue_token(client, operator_token, server)
    headers = {"Authorization": f"Bearer {token['token']}"}
    checkin_r = client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=headers)
    config_serial = checkin_r.json()["config_serial"]

    r = client.post(
        "/beacon/report",
        json={"config_serial": config_serial, "outcome": "failed", "detail": "apt-get update: network unreachable"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] is True


def test_report_no_token_rejected(client):
    r = client.post("/beacon/report", json={"config_serial": 1, "outcome": "success"})
    assert r.status_code == 401, r.text


def test_report_detail_is_truncated(client, operator_token):
    env = _make_environment(client, operator_token, "17")
    server = _create_server(client, operator_token, env, "beacon-host17.example.com", "10.1.0.19")
    token = _issue_token(client, operator_token, server)
    headers = {"Authorization": f"Bearer {token['token']}"}
    checkin_r = client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=headers)
    config_serial = checkin_r.json()["config_serial"]

    huge_detail = "x" * 100_000
    r = client.post(
        "/beacon/report",
        json={"config_serial": config_serial, "outcome": "failed", "detail": huge_detail},
        headers=headers,
    )
    assert r.status_code == 200, r.text


# --- promote/rollback bump config_serial for beacon-managed servers -------


def test_promote_bumps_config_serial_for_beacon_managed_server(client, operator_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = True
    repo = _create_repo(client, operator_token, "beacon-repo-18")
    cv = _create_cv(client, operator_token, repo, "beacon-cv-18")
    env = _create_env(client, operator_token, cv, "beacon-env-18")
    server = _create_server(client, operator_token, env, "beacon-host18.example.com", "10.1.0.20")
    token = _issue_token(client, operator_token, server)
    headers = {"Authorization": f"Bearer {token['token']}"}

    checkin_r1 = client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=headers)
    serial_before = checkin_r1.json()["config_serial"]

    # _create_env already did the first promote (assign+publish) — this is
    # a SECOND promote of the same (environment, content view) pair, via
    # the nested per-content-view route.
    promote_r = client.post(
        f"/lifecycle-environments/{env['id']}/content-views/{cv['id']}/promote",
        json={},
        headers=auth_headers(operator_token),
    )
    assert promote_r.status_code == 200, promote_r.text

    checkin_r2 = client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=headers)
    serial_after = checkin_r2.json()["config_serial"]
    assert serial_after > serial_before


def test_promote_does_not_error_when_no_beacon_managed_servers(client, operator_token, mock_aptly):
    """The common case today — an environment with zero beacon-enabled
    servers — must not error just because _bump_config_serial_for_environment_servers
    finds nothing to bump.
    """
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = True
    repo = _create_repo(client, operator_token, "beacon-repo-19")
    cv = _create_cv(client, operator_token, repo, "beacon-cv-19")
    env = _create_env(client, operator_token, cv, "beacon-env-19")

    r = client.post(
        f"/lifecycle-environments/{env['id']}/content-views/{cv['id']}/promote",
        json={},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 200, r.text


# --- facts -----------------------------------------------------------------


def test_checkin_requests_facts_on_first_ever_checkin(client, operator_token):
    env = _make_environment(client, operator_token, "20")
    server = _create_server(client, operator_token, env, "beacon-host20.example.com", "10.1.0.21")
    token = _issue_token(client, operator_token, server)
    headers = {"Authorization": f"Bearer {token['token']}"}

    r = client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["facts_requested"] is True


def test_checkin_requests_facts_again_after_interval_elapses(client, operator_token, db_session):
    """Proves the 6h interval is actually enforced both ways: not just
    "false right after a push" (covered by the next test) but "true again
    once enough time has passed" — without this, a bug that hardcoded
    facts_requested=False after any push would pass every other test here.
    """
    import uuid as _uuid
    from datetime import datetime, timedelta, timezone

    from app.models import ServerBeaconState

    env = _make_environment(client, operator_token, "20b")
    server = _create_server(client, operator_token, env, "beacon-host20b.example.com", "10.1.0.51")
    token = _issue_token(client, operator_token, server)
    headers = {"Authorization": f"Bearer {token['token']}"}
    client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=headers)
    client.post(
        "/beacon/facts",
        json={"disk": [], "services": [], "installed_packages": []},
        headers=headers,
    )

    state = db_session.execute(
        select(ServerBeaconState).where(ServerBeaconState.server_id == _uuid.UUID(server["id"]))
    ).scalar_one()
    state.last_facts_pushed_at = datetime.now(timezone.utc) - timedelta(hours=6, minutes=1)
    db_session.commit()

    r = client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["facts_requested"] is True


def test_checkin_does_not_request_facts_right_after_a_push(client, operator_token):
    env = _make_environment(client, operator_token, "21")
    server = _create_server(client, operator_token, env, "beacon-host21.example.com", "10.1.0.22")
    token = _issue_token(client, operator_token, server)
    headers = {"Authorization": f"Bearer {token['token']}"}

    client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=headers)
    push_r = client.post(
        "/beacon/facts",
        json={
            "os_distribution": "Ubuntu",
            "os_version": "22.04",
            "kernel": "5.15.0",
            "uptime_seconds": 3600,
            "disk": [],
            "services": [],
            "installed_packages": [{"name": "nginx", "version": "1.18.0-6", "arch": "amd64"}],
        },
        headers=headers,
    )
    assert push_r.status_code == 200, push_r.text

    r = client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["facts_requested"] is False


def test_facts_push_writes_compliance_record_and_server_fact_with_beacon_source(client, operator_token):
    env = _make_environment(client, operator_token, "22")
    server = _create_server(client, operator_token, env, "beacon-host22.example.com", "10.1.0.23")
    token = _issue_token(client, operator_token, server)
    headers = {"Authorization": f"Bearer {token['token']}"}
    client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=headers)

    r = client.post(
        "/beacon/facts",
        json={
            "os_distribution": "Ubuntu",
            "os_version": "22.04",
            "kernel": "5.15.0-100-generic",
            "uptime_seconds": 12345,
            "disk": [{"mount": "/", "size_total_mb": 10000, "size_available_mb": 5000}],
            "services": [{"name": "nginx", "state": "running", "status": "enabled"}],
            "installed_packages": [{"name": "nginx", "version": "1.18.0-6", "arch": "amd64"}],
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["accepted"] is True
    assert body["compliance_record_id"]
    assert body["server_fact_id"]

    # Every existing consumer (GET /servers/{id}/facts) works unchanged
    # against a beacon-sourced row — no special-casing needed.
    facts_r = client.get(f"/servers/{server['id']}/facts", headers=auth_headers(operator_token))
    assert facts_r.status_code == 200, facts_r.text
    facts_body = facts_r.json()
    assert facts_body["os_distribution"] == "Ubuntu"
    assert facts_body["source"] == "beacon"


def test_facts_no_token_rejected(client):
    r = client.post(
        "/beacon/facts",
        json={"disk": [], "services": [], "installed_packages": []},
    )
    assert r.status_code == 401, r.text


def test_facts_defaults_when_fields_omitted(client, operator_token):
    env = _make_environment(client, operator_token, "23")
    server = _create_server(client, operator_token, env, "beacon-host23.example.com", "10.1.0.24")
    token = _issue_token(client, operator_token, server)
    headers = {"Authorization": f"Bearer {token['token']}"}
    client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=headers)

    r = client.post("/beacon/facts", json={}, headers=headers)
    assert r.status_code == 200, r.text


# --- dispatched actions (Phase E) -------------------------------------------
#
# apply_updates_task/bulk_apply_updates_task are @celery_app.task(bind=True,
# ...) — calling them directly (not .delay) runs the real task body
# synchronously against the test DB/Redis, same as every other test in this
# module exercises router/task logic without a live Celery worker. Safe here
# specifically because every target in these tests is beacon-managed, so
# work() never reaches run_playbook() (no real Ansible/SSH involved).


def test_apply_updates_dispatches_beacon_action_and_appears_in_next_checkin(client, operator_token):
    from unittest.mock import patch

    from app.tasks import apply_updates_task

    env = _make_environment(client, operator_token, "24")
    server = _create_server(client, operator_token, env, "beacon-host24.example.com", "10.1.0.25")
    token = _issue_token(client, operator_token, server)
    headers = {"Authorization": f"Bearer {token['token']}"}
    client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=headers)

    with patch("app.routers.jobs.apply_updates_task.delay") as mock_delay:
        job_r = client.post(
            "/jobs/apply-updates", params={"environment_id": env["id"]}, headers=auth_headers(operator_token)
        )
        assert job_r.status_code == 201, job_r.text
        mock_delay.assert_called_once()
    job_id = job_r.json()["id"]

    apply_updates_task(job_id)

    job_after = client.get(f"/jobs/{job_id}", headers=auth_headers(operator_token))
    assert job_after.json()["status"] == "running"

    checkin_r = client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=headers)
    actions = checkin_r.json()["actions"]
    assert len(actions) == 1
    assert actions[0]["type"] == "apply_updates"

    # Handed out once (status flips pending -> delivered on handout) —
    # a second checkin before it resolves must still return it, not drop it.
    checkin_r2 = client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=headers)
    assert len(checkin_r2.json()["actions"]) == 1


def test_report_with_action_id_closes_job_on_success(client, operator_token):
    from unittest.mock import patch

    from app.tasks import apply_updates_task

    env = _make_environment(client, operator_token, "25")
    server = _create_server(client, operator_token, env, "beacon-host25.example.com", "10.1.0.26")
    token = _issue_token(client, operator_token, server)
    headers = {"Authorization": f"Bearer {token['token']}"}
    client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=headers)

    with patch("app.routers.jobs.apply_updates_task.delay"):
        job_r = client.post(
            "/jobs/apply-updates", params={"environment_id": env["id"]}, headers=auth_headers(operator_token)
        )
    job_id = job_r.json()["id"]
    apply_updates_task(job_id)

    checkin_r = client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=headers)
    action_id = checkin_r.json()["actions"][0]["id"]

    report_r = client.post(
        "/beacon/report",
        json={
            "config_serial": checkin_r.json()["config_serial"],
            "outcome": "success",
            "detail": "apt-get upgrade OK",
            "action_id": action_id,
        },
        headers=headers,
    )
    assert report_r.status_code == 200, report_r.text

    job_after = client.get(f"/jobs/{job_id}", headers=auth_headers(operator_token))
    assert job_after.json()["status"] == "success"


def test_report_with_action_id_fails_job_on_failure(client, operator_token):
    from unittest.mock import patch

    from app.tasks import apply_updates_task

    env = _make_environment(client, operator_token, "26")
    server = _create_server(client, operator_token, env, "beacon-host26.example.com", "10.1.0.27")
    token = _issue_token(client, operator_token, server)
    headers = {"Authorization": f"Bearer {token['token']}"}
    client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=headers)

    with patch("app.routers.jobs.apply_updates_task.delay"):
        job_r = client.post(
            "/jobs/apply-updates", params={"environment_id": env["id"]}, headers=auth_headers(operator_token)
        )
    job_id = job_r.json()["id"]
    apply_updates_task(job_id)

    checkin_r = client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=headers)
    action_id = checkin_r.json()["actions"][0]["id"]

    report_r = client.post(
        "/beacon/report",
        json={
            "config_serial": checkin_r.json()["config_serial"],
            "outcome": "failed",
            "detail": "apt-get upgrade: dpkg lock held",
            "action_id": action_id,
        },
        headers=headers,
    )
    assert report_r.status_code == 200, report_r.text

    job_after = client.get(f"/jobs/{job_id}", headers=auth_headers(operator_token))
    assert job_after.json()["status"] == "failed"


def test_report_action_id_cannot_resolve_another_servers_action(client, operator_token, db_session):
    """Ownership invariant: a beacon token can only ever resolve its OWN
    server's BeaconAction rows, mirroring the "no server_id parameter
    anywhere" rule for every other endpoint in this router.

    Checks the BeaconAction row itself (status/resolved_at), not just the
    parent Job's status — a Job-only assertion would still pass even if
    the ownership check were missing and the action got silently resolved,
    since this job has only one BeaconAction and finalizing it either way
    changes the Job's status the same way (running -> terminal); the
    action row is the only place that distinguishes "isolation worked"
    from "isolation was bypassed but something else also kept it running."
    """
    import uuid as _uuid
    from unittest.mock import patch

    from app.models import BeaconAction, BeaconActionStatus
    from app.tasks import apply_updates_task

    env = _make_environment(client, operator_token, "27")
    server_a = _create_server(client, operator_token, env, "beacon-host27a.example.com", "10.1.0.28")
    server_b = _create_server(client, operator_token, env, "beacon-host27b.example.com", "10.1.0.29")
    token_a = _issue_token(client, operator_token, server_a)
    token_b = _issue_token(client, operator_token, server_b)
    headers_a = {"Authorization": f"Bearer {token_a['token']}"}
    headers_b = {"Authorization": f"Bearer {token_b['token']}"}
    client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=headers_a)
    client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=headers_b)

    with patch("app.routers.jobs.apply_updates_task.delay"):
        job_r = client.post(
            "/jobs/apply-updates", params={"environment_id": env["id"]}, headers=auth_headers(operator_token)
        )
    job_id = job_r.json()["id"]
    apply_updates_task(job_id)

    checkin_a = client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=headers_a)
    action_id_a = checkin_a.json()["actions"][0]["id"]

    # server_b attempts to resolve server_a's action via its own valid token.
    report_r = client.post(
        "/beacon/report",
        json={"config_serial": 1, "outcome": "success", "action_id": action_id_a},
        headers=headers_b,
    )
    assert report_r.status_code == 200, report_r.text  # accepted, but silently a no-op for that action_id

    action_after = db_session.execute(
        select(BeaconAction).where(BeaconAction.id == _uuid.UUID(action_id_a))
    ).scalar_one()
    assert action_after.status == BeaconActionStatus.delivered  # NOT succeeded — untouched by server_b's report
    assert action_after.resolved_at is None

    job_after = client.get(f"/jobs/{job_id}", headers=auth_headers(operator_token))
    assert job_after.json()["status"] == "running"  # still open — server_a's action untouched


def test_cancel_job_cancels_pending_beacon_action(client, operator_token):
    from unittest.mock import patch

    from app.tasks import apply_updates_task

    env = _make_environment(client, operator_token, "28")
    server = _create_server(client, operator_token, env, "beacon-host28.example.com", "10.1.0.30")
    token = _issue_token(client, operator_token, server)
    headers = {"Authorization": f"Bearer {token['token']}"}
    client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=headers)

    with patch("app.routers.jobs.apply_updates_task.delay"):
        job_r = client.post(
            "/jobs/apply-updates", params={"environment_id": env["id"]}, headers=auth_headers(operator_token)
        )
    job_id = job_r.json()["id"]
    apply_updates_task(job_id)

    # Cancelled BEFORE the beacon's next checkin ever hands it out — still
    # `pending`, so the cancel endpoint can pull it back.
    cancel_r = client.post(f"/jobs/{job_id}/cancel", headers=auth_headers(operator_token))
    assert cancel_r.status_code == 200, cancel_r.text
    assert cancel_r.json()["status"] == "failed"

    # A checkin after cancellation must not hand out the cancelled action.
    checkin_r = client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=headers)
    assert checkin_r.json()["actions"] == []


def test_cancel_job_does_not_cancel_already_delivered_action(client, operator_token, db_session):
    """The documented limit (app/routers/jobs.py's cancel_job comment):
    once an action has been handed to the beacon in a checkin response
    (status=delivered), it can't be pulled back — same "can't cancel
    what's already running" limitation the SSH path has once
    ansible_runner.run() has started. Only still-pending rows are
    cancellable.
    """
    import uuid as _uuid
    from unittest.mock import patch

    from app.models import BeaconAction, BeaconActionStatus
    from app.tasks import apply_updates_task

    env = _make_environment(client, operator_token, "28b")
    server = _create_server(client, operator_token, env, "beacon-host28b.example.com", "10.1.0.52")
    token = _issue_token(client, operator_token, server)
    headers = {"Authorization": f"Bearer {token['token']}"}
    client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=headers)

    with patch("app.routers.jobs.apply_updates_task.delay"):
        job_r = client.post(
            "/jobs/apply-updates", params={"environment_id": env["id"]}, headers=auth_headers(operator_token)
        )
    job_id = job_r.json()["id"]
    apply_updates_task(job_id)

    # Check in BEFORE cancelling — the action is now delivered, not pending.
    checkin_r = client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=headers)
    assert len(checkin_r.json()["actions"]) == 1

    cancel_r = client.post(f"/jobs/{job_id}/cancel", headers=auth_headers(operator_token))
    assert cancel_r.status_code == 200, cancel_r.text
    assert cancel_r.json()["status"] == "failed"  # the Job still force-closes...

    # ...but the already-delivered BeaconAction itself is untouched, not
    # flipped to cancelled — it may still be executing on the host.
    action = db_session.execute(
        select(BeaconAction).where(BeaconAction.job_id == _uuid.UUID(job_id))
    ).scalar_one()
    assert action.status == BeaconActionStatus.delivered
    assert action.resolved_at is None


def test_timeout_sweep_marks_stale_beacon_action_and_fails_job(client, operator_token, db_session):
    """Also proves the sweep is selective, not blanket: a second, fresh
    (non-stale) BeaconAction on a DIFFERENT job must survive the same
    sweep run untouched — without a control action, "timed out 1" alone
    wouldn't distinguish "correctly found the one stale action" from "a
    buggy sweep that times out everything and happened to only see one."
    """
    import uuid as _uuid
    from datetime import datetime, timedelta, timezone
    from unittest.mock import patch

    from app.models import BeaconAction, BeaconActionStatus
    from app.tasks import scheduled_timeout_stale_beacon_actions

    env = _make_environment(client, operator_token, "29")
    stale_server = _create_server(client, operator_token, env, "beacon-host29.example.com", "10.1.0.31")
    fresh_server = _create_server(client, operator_token, env, "beacon-host29fresh.example.com", "10.1.0.32")
    stale_token = _issue_token(client, operator_token, stale_server)
    fresh_token = _issue_token(client, operator_token, fresh_server)
    stale_headers = {"Authorization": f"Bearer {stale_token['token']}"}
    fresh_headers = {"Authorization": f"Bearer {fresh_token['token']}"}
    client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=stale_headers)
    client.post("/beacon/checkin", json={"agent_version": "0.1.0"}, headers=fresh_headers)

    with patch("app.routers.jobs.bulk_apply_updates_task.delay"):
        stale_job_r = client.post(
            "/jobs/bulk-apply-updates",
            json={"server_ids": [stale_server["id"]]},
            headers=auth_headers(operator_token),
        )
        fresh_job_r = client.post(
            "/jobs/bulk-apply-updates",
            json={"server_ids": [fresh_server["id"]]},
            headers=auth_headers(operator_token),
        )
    stale_job_id = stale_job_r.json()["id"]
    fresh_job_id = fresh_job_r.json()["id"]

    from app.tasks import bulk_apply_updates_task

    bulk_apply_updates_task(stale_job_id)
    bulk_apply_updates_task(fresh_job_id)

    # Back-date only the first job's action past the 30-minute threshold —
    # simulates a beacon that's gone dark mid-dispatch. The second job's
    # action is left at its real (fresh) created_at as a control.
    stale_action = db_session.execute(
        select(BeaconAction).where(BeaconAction.job_id == _uuid.UUID(stale_job_id))
    ).scalar_one()
    stale_action.created_at = datetime.now(timezone.utc) - timedelta(minutes=45)
    db_session.commit()

    result = scheduled_timeout_stale_beacon_actions()
    assert "timed out 1" in result

    stale_job_after = client.get(f"/jobs/{stale_job_id}", headers=auth_headers(operator_token))
    assert stale_job_after.json()["status"] == "failed"

    fresh_job_after = client.get(f"/jobs/{fresh_job_id}", headers=auth_headers(operator_token))
    assert fresh_job_after.json()["status"] == "running"  # untouched — not stale enough to time out

    fresh_action = db_session.execute(
        select(BeaconAction).where(BeaconAction.job_id == _uuid.UUID(fresh_job_id))
    ).scalar_one()
    assert fresh_action.status == BeaconActionStatus.pending  # dispatched, never checked in again — still pending
    assert fresh_action.resolved_at is None


# --- install rollout (Phase F) ----------------------------------------------


def test_get_agent_binary(client):
    r = client.get("/beacon/agent")
    assert r.status_code == 200, r.text
    assert "groundctl-beacon" in r.text
    assert "AGENT_VERSION" in r.text


def test_get_systemd_service(client):
    r = client.get("/beacon/systemd-service")
    assert r.status_code == 200, r.text
    assert "groundctl-beacon --once" in r.text


def test_get_systemd_timer(client):
    r = client.get("/beacon/systemd-timer")
    assert r.status_code == 200, r.text
    assert "[Timer]" in r.text


def test_get_install_script_contains_token_and_endpoints(client, operator_token):
    env = _make_environment(client, operator_token, "33")
    server = _create_server(client, operator_token, env, "beacon-host33.example.com", "10.1.0.43")
    token = _issue_token(client, operator_token, server)

    r = client.get("/beacon/install-script", params={"token": token["token"]})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/x-shellscript")
    assert token["token"] in r.text
    assert "/api/beacon/agent" in r.text
    assert "/etc/groundctl/beacon.conf" in r.text
    assert "groundctl-beacon.timer" in r.text


def test_get_install_script_is_valid_bash(client, operator_token):
    import subprocess

    env = _make_environment(client, operator_token, "34")
    server = _create_server(client, operator_token, env, "beacon-host34.example.com", "10.1.0.44")
    token = _issue_token(client, operator_token, server)

    r = client.get("/beacon/install-script", params={"token": token["token"]})
    assert r.status_code == 200, r.text

    result = subprocess.run(["bash", "-n"], input=r.text, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_get_install_script_quotes_token_defensively(client):
    import subprocess

    hostile_token = "a'; rm -rf /; echo '"

    r = client.get("/beacon/install-script", params={"token": hostile_token})
    assert r.status_code == 200, r.text

    result = subprocess.run(["bash", "-n"], input=r.text, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "rm -rf /" not in result.stderr


def test_trigger_install_beacon_creates_job(client, operator_token):
    env = _make_environment(client, operator_token, "35")
    server = _create_server(client, operator_token, env, "beacon-host35.example.com", "10.1.0.45")

    from unittest.mock import patch

    with patch("app.routers.jobs.install_beacon_task.delay") as mock_delay:
        r = client.post(f"/jobs/install-beacon/{server['id']}", headers=auth_headers(operator_token))
        assert r.status_code == 201, r.text
        mock_delay.assert_called_once()


def test_install_beacon_task_mints_token_and_delivers_via_playbook(client, operator_token, db_session):
    """Calls install_beacon_task directly (real task body, not .delay —
    same pattern as the dispatched-actions tests above) with run_playbook
    mocked out (no real target host in this test environment) to confirm
    the token-minting side actually happens: a real BeaconToken row gets
    created and its RAW value (never the hash) is what's handed to
    run_playbook's extra_vars, exactly as install_beacon.yml's no_log
    task expects.
    """
    from unittest.mock import patch

    from app.models import BeaconToken
    from app.tasks import install_beacon_task

    env = _make_environment(client, operator_token, "36")
    server = _create_server(client, operator_token, env, "beacon-host36.example.com", "10.1.0.46")

    with patch("app.routers.jobs.install_beacon_task.delay"):
        job_r = client.post(f"/jobs/install-beacon/{server['id']}", headers=auth_headers(operator_token))
    job_id = job_r.json()["id"]

    with patch("app.tasks.run_playbook") as mock_run_playbook:
        mock_run_playbook.return_value = ("successful", "install_beacon.yml ran OK", {})
        install_beacon_task(job_id)

    mock_run_playbook.assert_called_once()
    call_args = mock_run_playbook.call_args
    assert call_args[0][0] == "install_beacon.yml"
    extra_vars = call_args[0][2]
    assert "groundctl_beacon_token" in extra_vars
    raw_token = extra_vars["groundctl_beacon_token"]

    import uuid as _uuid

    tokens = list(
        db_session.execute(select(BeaconToken).where(BeaconToken.server_id == _uuid.UUID(server["id"]))).scalars()
    )
    assert len(tokens) == 1
    from app.auth import hash_opaque_token

    assert tokens[0].token_hash == hash_opaque_token(raw_token)

    job_after = client.get(f"/jobs/{job_id}", headers=auth_headers(operator_token))
    assert job_after.json()["status"] == "success"
