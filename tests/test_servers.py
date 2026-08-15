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
    repo = _create_repo(client, operator_token, f"srv-repo-{suffix}")
    cv = _create_cv(client, operator_token, repo, f"srv-cv-{suffix}")
    return _create_env(client, operator_token, cv, f"srv-env-{suffix}", f"srv-path-{suffix}", 0, f"srv-prefix-{suffix}")


def _server_payload(environment, hostname="host1.example.com", ip="10.0.0.1", site_id=None):
    payload = {
        "hostname": hostname,
        "ip_address": ip,
        "ssh_user": "deploy",
        "environment_id": environment["id"],
    }
    if site_id is not None:
        payload["site_id"] = site_id
    return payload


def test_create_server_as_operator(client, operator_token):
    env = _make_environment(client, operator_token, "1")
    r = client.post("/servers", json=_server_payload(env), headers=auth_headers(operator_token))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["hostname"] == "host1.example.com"
    assert body["ip_address"] == "10.0.0.1"
    assert body["ssh_user"] == "deploy"
    assert body["environment_id"] == env["id"]
    assert body["site_id"] is None
    assert body["status"] == "registered"
    assert body["lifecycle_state"] == "active"


def test_create_server_as_viewer_forbidden(client, operator_token, viewer_token):
    env = _make_environment(client, operator_token, "2")
    r = client.post("/servers", json=_server_payload(env, "host2.example.com"), headers=auth_headers(viewer_token))
    assert r.status_code == 403, r.text


def test_create_server_environment_not_found(client, operator_token):
    payload = _server_payload({"id": "00000000-0000-0000-0000-000000000000"}, "host3.example.com")
    r = client.post("/servers", json=payload, headers=auth_headers(operator_token))
    assert r.status_code == 404, r.text


def test_create_server_site_not_found(client, operator_token):
    env = _make_environment(client, operator_token, "4")
    payload = _server_payload(env, "host4.example.com", site_id="00000000-0000-0000-0000-000000000000")
    r = client.post("/servers", json=payload, headers=auth_headers(operator_token))
    assert r.status_code == 404, r.text


def test_list_servers(client, operator_token, viewer_token):
    env = _make_environment(client, operator_token, "5")
    client.post("/servers", json=_server_payload(env, "host5a.example.com", "10.0.0.5"), headers=auth_headers(operator_token))
    client.post("/servers", json=_server_payload(env, "host5b.example.com", "10.0.0.6"), headers=auth_headers(operator_token))

    r = client.get("/servers", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    hostnames = {s["hostname"] for s in r.json()}
    assert {"host5a.example.com", "host5b.example.com"} <= hostnames


def test_list_servers_filter_by_environment_id(client, operator_token, viewer_token):
    env1 = _make_environment(client, operator_token, "6a")
    env2 = _make_environment(client, operator_token, "6b")
    client.post("/servers", json=_server_payload(env1, "host6a.example.com", "10.0.0.7"), headers=auth_headers(operator_token))
    client.post("/servers", json=_server_payload(env2, "host6b.example.com", "10.0.0.8"), headers=auth_headers(operator_token))

    r = client.get("/servers", params={"environment_id": env1["id"]}, headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert all(s["environment_id"] == env1["id"] for s in body)
    assert any(s["hostname"] == "host6a.example.com" for s in body)


def test_list_servers_filter_by_lifecycle_state(client, operator_token, viewer_token):
    env = _make_environment(client, operator_token, "7")
    active_server = client.post(
        "/servers", json=_server_payload(env, "host7a.example.com", "10.0.0.9"), headers=auth_headers(operator_token)
    ).json()
    decommissioned_server = client.post(
        "/servers", json=_server_payload(env, "host7b.example.com", "10.0.0.10"), headers=auth_headers(operator_token)
    ).json()
    client.post(
        f"/servers/{decommissioned_server['id']}/decommission", headers=auth_headers(operator_token)
    )

    r = client.get("/servers", params={"lifecycle_state": "decommissioned"}, headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {s["id"] for s in body}
    assert decommissioned_server["id"] in ids
    assert active_server["id"] not in ids


def test_list_servers_limit_offset(client, operator_token, viewer_token):
    env = _make_environment(client, operator_token, "8")
    for i in range(5):
        client.post(
            "/servers",
            json=_server_payload(env, f"host8-{i}.example.com", f"10.0.1.{i}"),
            headers=auth_headers(operator_token),
        )

    r = client.get("/servers", params={"limit": 2, "offset": 0}, headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    assert len(r.json()) == 2


def test_get_server_by_id(client, operator_token, viewer_token):
    env = _make_environment(client, operator_token, "9")
    server = client.post(
        "/servers", json=_server_payload(env, "host9.example.com", "10.0.0.20"), headers=auth_headers(operator_token)
    ).json()

    r = client.get(f"/servers/{server['id']}", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    assert r.json()["hostname"] == "host9.example.com"


def test_get_server_not_found(client, viewer_token):
    r = client.get("/servers/00000000-0000-0000-0000-000000000000", headers=auth_headers(viewer_token))
    assert r.status_code == 404, r.text


def test_get_server_facts_404_when_none_gathered(client, operator_token, viewer_token):
    env = _make_environment(client, operator_token, "10")
    server = client.post(
        "/servers", json=_server_payload(env, "host10.example.com", "10.0.0.21"), headers=auth_headers(operator_token)
    ).json()

    r = client.get(f"/servers/{server['id']}/facts", headers=auth_headers(viewer_token))
    assert r.status_code == 404, r.text


def test_get_server_facts_not_found_server(client, viewer_token):
    r = client.get(
        "/servers/00000000-0000-0000-0000-000000000000/facts", headers=auth_headers(viewer_token)
    )
    assert r.status_code == 404, r.text


def test_get_server_facts_happy_path(client, operator_token, viewer_token, db_session):
    from app.models import ServerFact

    env = _make_environment(client, operator_token, "11")
    server = client.post(
        "/servers", json=_server_payload(env, "host11.example.com", "10.0.0.22"), headers=auth_headers(operator_token)
    ).json()

    fact = ServerFact(
        server_id=server["id"],
        os_distribution="ubuntu",
        os_version="22.04",
        kernel="5.15.0-generic",
        uptime_seconds=3600,
        disk=[{"mount": "/", "size_total_mb": 1000, "size_available_mb": 500}],
        services=[{"name": "nginx", "state": "running", "status": "enabled"}],
    )
    db_session.add(fact)
    db_session.commit()

    r = client.get(f"/servers/{server['id']}/facts", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["server_id"] == server["id"]
    assert body["os_distribution"] == "ubuntu"
    assert body["os_version"] == "22.04"
    assert body["kernel"] == "5.15.0-generic"
    assert body["uptime_seconds"] == 3600
    assert body["disk"] == [{"mount": "/", "size_total_mb": 1000, "size_available_mb": 500}]
    assert body["services"] == [{"name": "nginx", "state": "running", "status": "enabled"}]


def test_get_server_facts_history_paginated(client, operator_token, viewer_token, db_session):
    from app.models import ServerFact

    env = _make_environment(client, operator_token, "12")
    server = client.post(
        "/servers", json=_server_payload(env, "host12.example.com", "10.0.0.23"), headers=auth_headers(operator_token)
    ).json()

    for _ in range(3):
        db_session.add(
            ServerFact(
                server_id=server["id"],
                os_distribution="ubuntu",
                os_version="22.04",
                kernel="5.15.0-generic",
                uptime_seconds=100,
                disk=[],
                services=[],
            )
        )
    db_session.commit()

    r = client.get(f"/servers/{server['id']}/facts/history", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    assert len(r.json()) == 3

    r2 = client.get(
        f"/servers/{server['id']}/facts/history", params={"limit": 1, "offset": 0}, headers=auth_headers(viewer_token)
    )
    assert r2.status_code == 200, r2.text
    assert len(r2.json()) == 1


def test_get_server_facts_history_not_found_server(client, viewer_token):
    r = client.get(
        "/servers/00000000-0000-0000-0000-000000000000/facts/history", headers=auth_headers(viewer_token)
    )
    assert r.status_code == 404, r.text


def test_decommission_server_as_operator(client, operator_token):
    env = _make_environment(client, operator_token, "13")
    server = client.post(
        "/servers", json=_server_payload(env, "host13.example.com", "10.0.0.24"), headers=auth_headers(operator_token)
    ).json()

    r = client.post(f"/servers/{server['id']}/decommission", headers=auth_headers(operator_token))
    assert r.status_code == 200, r.text
    assert r.json()["lifecycle_state"] == "decommissioned"


def test_decommission_server_as_viewer_forbidden(client, operator_token, viewer_token):
    env = _make_environment(client, operator_token, "14")
    server = client.post(
        "/servers", json=_server_payload(env, "host14.example.com", "10.0.0.25"), headers=auth_headers(operator_token)
    ).json()

    r = client.post(f"/servers/{server['id']}/decommission", headers=auth_headers(viewer_token))
    assert r.status_code == 403, r.text


def test_decommission_server_not_found(client, operator_token):
    r = client.post(
        "/servers/00000000-0000-0000-0000-000000000000/decommission", headers=auth_headers(operator_token)
    )
    assert r.status_code == 404, r.text


def test_assign_server_site_as_operator(client, operator_token, db_session):
    from app.models import Site

    env = _make_environment(client, operator_token, "15")
    server = client.post(
        "/servers", json=_server_payload(env, "host15.example.com", "10.0.0.26"), headers=auth_headers(operator_token)
    ).json()

    site = Site(name="site15")
    db_session.add(site)
    db_session.commit()
    db_session.refresh(site)

    r = client.post(
        f"/servers/{server['id']}/assign-site",
        params={"site_id": str(site.id)},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["site_id"] == str(site.id)


def test_assign_server_site_clears_when_none(client, operator_token, db_session):
    from app.models import Site

    env = _make_environment(client, operator_token, "16")
    server = client.post(
        "/servers", json=_server_payload(env, "host16.example.com", "10.0.0.27"), headers=auth_headers(operator_token)
    ).json()

    site = Site(name="site16")
    db_session.add(site)
    db_session.commit()
    db_session.refresh(site)

    client.post(
        f"/servers/{server['id']}/assign-site",
        params={"site_id": str(site.id)},
        headers=auth_headers(operator_token),
    )

    r = client.post(f"/servers/{server['id']}/assign-site", headers=auth_headers(operator_token))
    assert r.status_code == 200, r.text
    assert r.json()["site_id"] is None


def test_assign_server_site_as_viewer_forbidden(client, operator_token, viewer_token):
    env = _make_environment(client, operator_token, "17")
    server = client.post(
        "/servers", json=_server_payload(env, "host17.example.com", "10.0.0.28"), headers=auth_headers(operator_token)
    ).json()

    r = client.post(f"/servers/{server['id']}/assign-site", headers=auth_headers(viewer_token))
    assert r.status_code == 403, r.text


def test_assign_server_site_not_found_server(client, operator_token):
    r = client.post(
        "/servers/00000000-0000-0000-0000-000000000000/assign-site", headers=auth_headers(operator_token)
    )
    assert r.status_code == 404, r.text


def test_assign_server_site_not_found_site(client, operator_token):
    env = _make_environment(client, operator_token, "18")
    server = client.post(
        "/servers", json=_server_payload(env, "host18.example.com", "10.0.0.29"), headers=auth_headers(operator_token)
    ).json()

    r = client.post(
        f"/servers/{server['id']}/assign-site",
        params={"site_id": "00000000-0000-0000-0000-000000000000"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_assign_server_environment_as_operator(client, operator_token):
    env_a = _make_environment(client, operator_token, "19a")
    env_b = _make_environment(client, operator_token, "19b")
    server = client.post(
        "/servers", json=_server_payload(env_a, "host19.example.com", "10.0.0.30"), headers=auth_headers(operator_token)
    ).json()

    r = client.post(
        f"/servers/{server['id']}/assign-environment",
        json={"environment_id": env_b["id"], "reason": "moving to staging"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["environment_id"] == env_b["id"]

    get_r = client.get(f"/servers/{server['id']}", headers=auth_headers(operator_token))
    assert get_r.json()["environment_id"] == env_b["id"]


def test_assign_server_environment_idempotent_same_environment(client, operator_token):
    env = _make_environment(client, operator_token, "20")
    server = client.post(
        "/servers", json=_server_payload(env, "host20.example.com", "10.0.0.31"), headers=auth_headers(operator_token)
    ).json()

    r = client.post(
        f"/servers/{server['id']}/assign-environment",
        json={"environment_id": env["id"]},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["environment_id"] == env["id"]


def test_assign_server_environment_as_viewer_forbidden(client, operator_token, viewer_token):
    env_a = _make_environment(client, operator_token, "21a")
    env_b = _make_environment(client, operator_token, "21b")
    server = client.post(
        "/servers", json=_server_payload(env_a, "host21.example.com", "10.0.0.32"), headers=auth_headers(operator_token)
    ).json()

    r = client.post(
        f"/servers/{server['id']}/assign-environment",
        json={"environment_id": env_b["id"]},
        headers=auth_headers(viewer_token),
    )
    assert r.status_code == 403, r.text


def test_assign_server_environment_not_found_server(client, operator_token):
    env = _make_environment(client, operator_token, "22")
    r = client.post(
        "/servers/00000000-0000-0000-0000-000000000000/assign-environment",
        json={"environment_id": env["id"]},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_assign_server_environment_not_found_environment(client, operator_token):
    env = _make_environment(client, operator_token, "23")
    server = client.post(
        "/servers", json=_server_payload(env, "host23.example.com", "10.0.0.33"), headers=auth_headers(operator_token)
    ).json()

    r = client.post(
        f"/servers/{server['id']}/assign-environment",
        json={"environment_id": "00000000-0000-0000-0000-000000000000"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_assign_server_environment_decommissioned_rejected(client, operator_token):
    env_a = _make_environment(client, operator_token, "24a")
    env_b = _make_environment(client, operator_token, "24b")
    server = client.post(
        "/servers", json=_server_payload(env_a, "host24.example.com", "10.0.0.34"), headers=auth_headers(operator_token)
    ).json()

    client.post(f"/servers/{server['id']}/decommission", headers=auth_headers(operator_token))

    r = client.post(
        f"/servers/{server['id']}/assign-environment",
        json={"environment_id": env_b["id"]},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 409, r.text
