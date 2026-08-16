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
    r = client.post("/lifecycle-environments", json={"name": name}, headers=auth_headers(operator_token))
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


def _make_env(client, operator_token, suffix):
    repo = _create_repo(client, operator_token, f"st-repo-{suffix}")
    cv = _create_cv(client, operator_token, repo, f"st-cv-{suffix}")
    return _create_env(client, operator_token, cv, f"st-env-{suffix}", f"st-path-{suffix}", 0, f"st-prefix-{suffix}")


def _site_payload(name="site1", description="a site"):
    return {"name": name, "description": description}


def test_create_site_as_operator(client, operator_token):
    r = client.post("/sites", json=_site_payload("site-op"), headers=auth_headers(operator_token))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "site-op"
    assert body["description"] == "a site"


def test_create_site_as_admin(client, admin_token):
    r = client.post("/sites", json=_site_payload("site-admin"), headers=auth_headers(admin_token))
    assert r.status_code == 201, r.text


def test_create_site_as_viewer_forbidden(client, viewer_token):
    r = client.post("/sites", json=_site_payload("site-viewer"), headers=auth_headers(viewer_token))
    assert r.status_code == 403, r.text


def test_create_site_duplicate_name_conflicts(client, operator_token):
    r1 = client.post("/sites", json=_site_payload("dup-site"), headers=auth_headers(operator_token))
    assert r1.status_code == 201, r1.text
    r2 = client.post("/sites", json=_site_payload("dup-site"), headers=auth_headers(operator_token))
    assert r2.status_code == 409, r2.text


def test_list_sites(client, operator_token, viewer_token):
    client.post("/sites", json=_site_payload("list-site-a"), headers=auth_headers(operator_token))
    client.post("/sites", json=_site_payload("list-site-b"), headers=auth_headers(operator_token))

    r = client.get("/sites", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    names = {s["name"] for s in r.json()}
    assert {"list-site-a", "list-site-b"} <= names


def test_list_sites_limit_offset(client, operator_token, viewer_token):
    for i in range(4):
        client.post("/sites", json=_site_payload(f"page-site-{i}"), headers=auth_headers(operator_token))

    r = client.get("/sites", params={"limit": 2, "offset": 0}, headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    assert len(r.json()) == 2


def test_get_site_as_viewer(client, operator_token, viewer_token):
    created = client.post("/sites", json=_site_payload("get-site"), headers=auth_headers(operator_token)).json()

    r = client.get(f"/sites/{created['id']}", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    assert r.json()["id"] == created["id"]


def test_get_site_not_found(client, viewer_token):
    r = client.get("/sites/00000000-0000-0000-0000-000000000000", headers=auth_headers(viewer_token))
    assert r.status_code == 404, r.text


def test_update_site_as_operator(client, operator_token):
    created = client.post(
        "/sites", json=_site_payload("update-site"), headers=auth_headers(operator_token)
    ).json()

    r = client.put(
        f"/sites/{created['id']}",
        json={"name": "update-site", "description": "added later"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["description"] == "added later"

    r2 = client.get(f"/sites/{created['id']}", headers=auth_headers(operator_token))
    assert r2.json()["description"] == "added later"


def test_update_site_rename(client, operator_token):
    created = client.post(
        "/sites", json=_site_payload("rename-site"), headers=auth_headers(operator_token)
    ).json()

    r = client.put(
        f"/sites/{created['id']}",
        json={"name": "renamed-site", "description": None},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "renamed-site"
    assert r.json()["description"] is None


def test_update_site_as_viewer_forbidden(client, operator_token, viewer_token):
    created = client.post(
        "/sites", json=_site_payload("update-site-viewer"), headers=auth_headers(operator_token)
    ).json()

    r = client.put(
        f"/sites/{created['id']}",
        json={"name": "update-site-viewer", "description": "nope"},
        headers=auth_headers(viewer_token),
    )
    assert r.status_code == 403, r.text


def test_update_site_not_found(client, operator_token):
    r = client.put(
        "/sites/00000000-0000-0000-0000-000000000000",
        json={"name": "does-not-exist", "description": None},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_update_site_rename_conflicts_with_existing_name(client, operator_token):
    client.post("/sites", json=_site_payload("taken-name"), headers=auth_headers(operator_token))
    created = client.post(
        "/sites", json=_site_payload("to-be-renamed"), headers=auth_headers(operator_token)
    ).json()

    r = client.put(
        f"/sites/{created['id']}",
        json={"name": "taken-name", "description": None},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 409, r.text


def test_create_relay_as_operator(client, operator_token):
    site = client.post("/sites", json=_site_payload("relay-site1"), headers=auth_headers(operator_token)).json()

    r = client.post(
        f"/sites/{site['id']}/relay",
        json={"hostname": "relay1.example.com", "ssh_user": "ubuntu"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["site_id"] == site["id"]
    assert body["hostname"] == "relay1.example.com"
    assert body["sync_status"] == "never_synced"


def test_create_relay_as_viewer_forbidden(client, operator_token, viewer_token):
    site = client.post("/sites", json=_site_payload("relay-site2"), headers=auth_headers(operator_token)).json()

    r = client.post(
        f"/sites/{site['id']}/relay",
        json={"hostname": "relay2.example.com", "ssh_user": "ubuntu"},
        headers=auth_headers(viewer_token),
    )
    assert r.status_code == 403, r.text


def test_create_relay_site_not_found(client, operator_token):
    r = client.post(
        "/sites/00000000-0000-0000-0000-000000000000/relay",
        json={"hostname": "relay3.example.com", "ssh_user": "ubuntu"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_create_relay_duplicate_for_site_conflicts(client, operator_token):
    site = client.post("/sites", json=_site_payload("relay-site3"), headers=auth_headers(operator_token)).json()
    r1 = client.post(
        f"/sites/{site['id']}/relay",
        json={"hostname": "relay4.example.com", "ssh_user": "ubuntu"},
        headers=auth_headers(operator_token),
    )
    assert r1.status_code == 201, r1.text

    r2 = client.post(
        f"/sites/{site['id']}/relay",
        json={"hostname": "relay5.example.com", "ssh_user": "ubuntu"},
        headers=auth_headers(operator_token),
    )
    assert r2.status_code == 409, r2.text


def test_get_relay_as_viewer(client, operator_token, viewer_token):
    site = client.post("/sites", json=_site_payload("relay-site4"), headers=auth_headers(operator_token)).json()
    client.post(
        f"/sites/{site['id']}/relay",
        json={"hostname": "relay6.example.com", "ssh_user": "ubuntu"},
        headers=auth_headers(operator_token),
    )

    r = client.get(f"/sites/{site['id']}/relay", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    assert r.json()["hostname"] == "relay6.example.com"


def test_get_relay_404_when_none(client, operator_token, viewer_token):
    site = client.post("/sites", json=_site_payload("relay-site5"), headers=auth_headers(operator_token)).json()

    r = client.get(f"/sites/{site['id']}/relay", headers=auth_headers(viewer_token))
    assert r.status_code == 404, r.text


def test_get_relay_site_not_found(client, viewer_token):
    r = client.get(
        "/sites/00000000-0000-0000-0000-000000000000/relay", headers=auth_headers(viewer_token)
    )
    assert r.status_code == 404, r.text


def test_list_site_environments_empty_and_site_not_found(client, operator_token, viewer_token):
    site = client.post("/sites", json=_site_payload("env-site1"), headers=auth_headers(operator_token)).json()

    r = client.get(f"/sites/{site['id']}/environments", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    assert r.json() == []

    r2 = client.get(
        "/sites/00000000-0000-0000-0000-000000000000/environments", headers=auth_headers(viewer_token)
    )
    assert r2.status_code == 404, r2.text


def test_replace_site_environments_as_operator(client, operator_token, viewer_token):
    site = client.post("/sites", json=_site_payload("env-site2"), headers=auth_headers(operator_token)).json()
    env1 = _make_env(client, operator_token, "s1")
    env2 = _make_env(client, operator_token, "s2")

    r = client.put(
        f"/sites/{site['id']}/environments",
        json={"environment_ids": [env1["id"], env2["id"]]},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {e["id"] for e in body}
    assert ids == {env1["id"], env2["id"]}

    listed = client.get(f"/sites/{site['id']}/environments", headers=auth_headers(viewer_token))
    assert listed.status_code == 200, listed.text
    assert {e["id"] for e in listed.json()} == {env1["id"], env2["id"]}

    # Replace again with just env1 — env2 should be dropped.
    r2 = client.put(
        f"/sites/{site['id']}/environments",
        json={"environment_ids": [env1["id"]]},
        headers=auth_headers(operator_token),
    )
    assert r2.status_code == 200, r2.text
    assert {e["id"] for e in r2.json()} == {env1["id"]}


def test_replace_site_environments_as_viewer_forbidden(client, operator_token, viewer_token):
    site = client.post("/sites", json=_site_payload("env-site3"), headers=auth_headers(operator_token)).json()
    env1 = _make_env(client, operator_token, "s3")

    r = client.put(
        f"/sites/{site['id']}/environments",
        json={"environment_ids": [env1["id"]]},
        headers=auth_headers(viewer_token),
    )
    assert r.status_code == 403, r.text


def test_replace_site_environments_site_not_found(client, operator_token):
    env1 = _make_env(client, operator_token, "s4")

    r = client.put(
        "/sites/00000000-0000-0000-0000-000000000000/environments",
        json={"environment_ids": [env1["id"]]},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_replace_site_environments_missing_environment_404(client, operator_token):
    site = client.post("/sites", json=_site_payload("env-site4"), headers=auth_headers(operator_token)).json()

    r = client.put(
        f"/sites/{site['id']}/environments",
        json={"environment_ids": ["00000000-0000-0000-0000-000000000000"]},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text
