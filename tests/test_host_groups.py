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
    # path_name/position/publish_prefix are no longer creation-time fields
    # (see LifecycleEnvironmentCreate) — publish_prefix is derived from
    # `name` at first promote instead. This helper immediately promotes
    # the content view's already-published version 1 so callers keep
    # getting back a fully linked, published environment exactly like
    # before. No caller in this file uses position>0, so prior-chaining
    # isn't needed here.
    r = client.post(
        "/lifecycle-environments", json={"name": name, "content_view_id": cv["id"]}, headers=auth_headers(operator_token)
    )
    assert r.status_code == 201, r.text
    env = r.json()

    versions_r = client.get(f"/content-views/{cv['id']}/versions", headers=auth_headers(operator_token))
    version_id = versions_r.json()[0]["id"]
    promote_r = client.post(
        f"/lifecycle-environments/{env['id']}/promote",
        json={"content_view_version_id": version_id, "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )
    assert promote_r.status_code == 200, promote_r.text

    get_r = client.get(
        "/lifecycle-environments", params={"content_view_id": cv["id"]}, headers=auth_headers(operator_token)
    )
    return next(e for e in get_r.json() if e["id"] == env["id"])


def _create_server(client, operator_token, env, hostname="host1.example.com"):
    r = client.post(
        "/servers",
        json={
            "hostname": hostname,
            "ip_address": "10.0.0.5",
            "ssh_user": "ubuntu",
            "environment_id": env["id"],
        },
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 201, r.text
    return r.json()


def _seed_env_and_servers(client, operator_token, suffix, count=1):
    repo = _create_repo(client, operator_token, f"hg-repo-{suffix}")
    cv = _create_cv(client, operator_token, repo, f"hg-cv-{suffix}")
    env = _create_env(client, operator_token, cv, f"hg-env-{suffix}", f"hg-path-{suffix}", 0, f"hg-prefix-{suffix}")
    servers = [
        _create_server(client, operator_token, env, f"hg-host-{suffix}-{i}.example.com") for i in range(count)
    ]
    return env, servers


# ---------------------------------------------------------------------------
# POST /host-groups
# ---------------------------------------------------------------------------


def test_create_host_group_as_operator(client, operator_token):
    r = client.post(
        "/host-groups",
        json={"name": "webservers"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "webservers"
    assert body["description"] is None
    assert body["default_environment_id"] is None


def test_create_host_group_with_default_environment(client, operator_token):
    env, _ = _seed_env_and_servers(client, operator_token, "default-env")
    r = client.post(
        "/host-groups",
        json={"name": "with-default-env", "description": "desc", "default_environment_id": env["id"]},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["default_environment_id"] == env["id"]
    assert body["description"] == "desc"


def test_create_host_group_duplicate_name_conflicts(client, operator_token):
    r1 = client.post("/host-groups", json={"name": "dup-group"}, headers=auth_headers(operator_token))
    assert r1.status_code == 201, r1.text
    r2 = client.post("/host-groups", json={"name": "dup-group"}, headers=auth_headers(operator_token))
    assert r2.status_code == 409, r2.text


def test_create_host_group_as_viewer_forbidden(client, viewer_token):
    r = client.post("/host-groups", json={"name": "viewer-group"}, headers=auth_headers(viewer_token))
    assert r.status_code == 403, r.text


def test_create_host_group_as_admin(client, admin_token):
    r = client.post("/host-groups", json={"name": "admin-group"}, headers=auth_headers(admin_token))
    assert r.status_code == 201, r.text


# ---------------------------------------------------------------------------
# GET /host-groups
# ---------------------------------------------------------------------------


def test_list_host_groups_paginated(client, operator_token, viewer_token):
    for i in range(5):
        client.post("/host-groups", json={"name": f"list-group-{i}"}, headers=auth_headers(operator_token))

    r = client.get("/host-groups", params={"limit": 2, "offset": 0}, headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    assert len(r.json()) == 2


def test_list_host_groups_as_viewer_allowed(client, operator_token, viewer_token):
    client.post("/host-groups", json={"name": "viewer-list-group"}, headers=auth_headers(operator_token))
    r = client.get("/host-groups", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    names = {g["name"] for g in r.json()}
    assert "viewer-list-group" in names


# ---------------------------------------------------------------------------
# GET /host-groups/{id}
# ---------------------------------------------------------------------------


def test_get_host_group_found(client, operator_token, viewer_token):
    created = client.post(
        "/host-groups", json={"name": "get-group"}, headers=auth_headers(operator_token)
    ).json()

    r = client.get(f"/host-groups/{created['id']}", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    assert r.json()["id"] == created["id"]


def test_get_host_group_not_found(client, viewer_token):
    r = client.get(
        "/host-groups/00000000-0000-0000-0000-000000000000", headers=auth_headers(viewer_token)
    )
    assert r.status_code == 404, r.text


# ---------------------------------------------------------------------------
# GET /host-groups/{id}/members
# ---------------------------------------------------------------------------


def test_list_host_group_members_empty(client, operator_token, viewer_token):
    group = client.post(
        "/host-groups", json={"name": "empty-members-group"}, headers=auth_headers(operator_token)
    ).json()

    r = client.get(f"/host-groups/{group['id']}/members", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    assert r.json() == []


def test_list_host_group_members_not_found(client, viewer_token):
    r = client.get(
        "/host-groups/00000000-0000-0000-0000-000000000000/members", headers=auth_headers(viewer_token)
    )
    assert r.status_code == 404, r.text


def test_list_host_group_members_after_add_paginated(client, operator_token, viewer_token):
    env, servers = _seed_env_and_servers(client, operator_token, "members-page", count=5)
    group = client.post(
        "/host-groups", json={"name": "members-page-group"}, headers=auth_headers(operator_token)
    ).json()

    server_ids = [s["id"] for s in servers]
    put_r = client.put(
        f"/host-groups/{group['id']}/members",
        json={"server_ids": server_ids},
        headers=auth_headers(operator_token),
    )
    assert put_r.status_code == 200, put_r.text

    r = client.get(
        f"/host-groups/{group['id']}/members", params={"limit": 2, "offset": 0}, headers=auth_headers(viewer_token)
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) == 2

    r_all = client.get(f"/host-groups/{group['id']}/members", headers=auth_headers(viewer_token))
    assert r_all.status_code == 200, r_all.text
    assert {s["id"] for s in r_all.json()} == set(server_ids)


# ---------------------------------------------------------------------------
# PUT /host-groups/{id}/members
# ---------------------------------------------------------------------------


def test_replace_host_group_members_as_operator(client, operator_token):
    env, servers = _seed_env_and_servers(client, operator_token, "replace-op", count=2)
    group = client.post(
        "/host-groups", json={"name": "replace-op-group"}, headers=auth_headers(operator_token)
    ).json()

    server_ids = [s["id"] for s in servers]
    r = client.put(
        f"/host-groups/{group['id']}/members",
        json={"server_ids": server_ids},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 200, r.text
    assert {s["id"] for s in r.json()} == set(server_ids)


def test_replace_host_group_members_overwrites_existing(client, operator_token):
    env, servers = _seed_env_and_servers(client, operator_token, "replace-overwrite", count=3)
    group = client.post(
        "/host-groups", json={"name": "replace-overwrite-group"}, headers=auth_headers(operator_token)
    ).json()

    first_ids = [servers[0]["id"], servers[1]["id"]]
    r1 = client.put(
        f"/host-groups/{group['id']}/members",
        json={"server_ids": first_ids},
        headers=auth_headers(operator_token),
    )
    assert r1.status_code == 200, r1.text
    assert {s["id"] for s in r1.json()} == set(first_ids)

    second_ids = [servers[2]["id"]]
    r2 = client.put(
        f"/host-groups/{group['id']}/members",
        json={"server_ids": second_ids},
        headers=auth_headers(operator_token),
    )
    assert r2.status_code == 200, r2.text
    assert {s["id"] for s in r2.json()} == set(second_ids)


def test_replace_host_group_members_missing_server_404s(client, operator_token):
    group = client.post(
        "/host-groups", json={"name": "missing-server-group"}, headers=auth_headers(operator_token)
    ).json()

    r = client.put(
        f"/host-groups/{group['id']}/members",
        json={"server_ids": ["00000000-0000-0000-0000-000000000000"]},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_replace_host_group_members_group_not_found(client, operator_token):
    env, servers = _seed_env_and_servers(client, operator_token, "no-group", count=1)
    r = client.put(
        "/host-groups/00000000-0000-0000-0000-000000000000/members",
        json={"server_ids": [servers[0]["id"]]},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_replace_host_group_members_empty_list_rejected(client, operator_token):
    group = client.post(
        "/host-groups", json={"name": "empty-list-group"}, headers=auth_headers(operator_token)
    ).json()

    r = client.put(
        f"/host-groups/{group['id']}/members",
        json={"server_ids": []},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 422, r.text


def test_replace_host_group_members_as_viewer_forbidden(client, operator_token, viewer_token):
    env, servers = _seed_env_and_servers(client, operator_token, "replace-viewer", count=1)
    group = client.post(
        "/host-groups", json={"name": "replace-viewer-group"}, headers=auth_headers(operator_token)
    ).json()

    r = client.put(
        f"/host-groups/{group['id']}/members",
        json={"server_ids": [servers[0]["id"]]},
        headers=auth_headers(viewer_token),
    )
    assert r.status_code == 403, r.text
