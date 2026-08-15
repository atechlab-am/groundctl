import pytest

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


def _create_env(client, operator_token, cv, name="beacon-env", path_name="beacon-path", position=0, publish_prefix="beacon-prefix"):
    r = client.post(
        "/lifecycle-environments",
        json={
            "name": name,
            "path_name": path_name,
            "position": position,
            "content_view_id": cv["id"],
            "distro": "ubuntu",
            "release": "jammy",
            "publish_prefix": publish_prefix,
            "allow_unsigned": True,
        },
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 201, r.text
    return r.json()


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
    assert body["environment"]["id"] == env["id"]
    assert body["apt_source"]["filename"] == f"groundctl-{env['name']}.list"
    assert "deb [trusted=yes]" in body["apt_source"]["contents"]
    assert body["checkin_interval_seconds"] == 300
    assert body["actions"] == []
    assert body["config_serial"] == 1

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
    assert r2.json()["environment"]["id"] == env_b["id"]


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
