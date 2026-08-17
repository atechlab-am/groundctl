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


def _make_env(client, operator_token, suffix):
    repo = _create_repo(client, operator_token, f"ak-repo-{suffix}")
    cv = _create_cv(client, operator_token, repo, f"ak-cv-{suffix}")
    return _create_env(client, operator_token, cv, f"ak-env-{suffix}", f"ak-path-{suffix}", 0, f"ak-prefix-{suffix}")


def _ak_payload(env, name="key1", **overrides):
    payload = {"name": name, "environment_id": env["id"]}
    payload.update(overrides)
    return payload


def test_create_activation_key_as_operator(client, operator_token):
    env = _make_env(client, operator_token, "1")
    r = client.post("/activation-keys", json=_ak_payload(env, "key1"), headers=auth_headers(operator_token))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "key1"
    assert body["environment_id"] == env["id"]
    assert "token" in body
    assert isinstance(body["token"], str) and len(body["token"]) > 0
    assert body["host_group_id"] is None
    assert body["tags"] == []
    assert body["max_uses"] is None


def test_create_activation_key_as_admin(client, admin_token, operator_token):
    env = _make_env(client, operator_token, "admin1")
    r = client.post("/activation-keys", json=_ak_payload(env, "key-admin"), headers=auth_headers(admin_token))
    assert r.status_code == 201, r.text


def test_create_activation_key_as_viewer_forbidden(client, operator_token, viewer_token):
    env = _make_env(client, operator_token, "2")
    r = client.post("/activation-keys", json=_ak_payload(env, "key2"), headers=auth_headers(viewer_token))
    assert r.status_code == 403, r.text


def test_create_activation_key_environment_not_found(client, operator_token):
    payload = {"name": "orphan-key", "environment_id": "00000000-0000-0000-0000-000000000000"}
    r = client.post("/activation-keys", json=payload, headers=auth_headers(operator_token))
    assert r.status_code == 404, r.text


def test_create_activation_key_with_max_uses_and_tags(client, operator_token):
    env = _make_env(client, operator_token, "3")
    r = client.post(
        "/activation-keys",
        json=_ak_payload(env, "key3", max_uses=5, tags=["prod", "web"]),
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["max_uses"] == 5
    assert body["tags"] == ["prod", "web"]


def test_get_activation_key_omits_token(client, operator_token):
    env = _make_env(client, operator_token, "4")
    created = client.post(
        "/activation-keys", json=_ak_payload(env, "key4"), headers=auth_headers(operator_token)
    ).json()
    assert "token" in created

    r = client.get(f"/activation-keys/{created['id']}", headers=auth_headers(operator_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "token" not in body
    assert body["id"] == created["id"]
    assert body["name"] == "key4"
    assert body["use_count"] == 0
    assert body["revoked"] is False


def test_get_activation_key_not_found(client, operator_token):
    r = client.get(
        "/activation-keys/00000000-0000-0000-0000-000000000000", headers=auth_headers(operator_token)
    )
    assert r.status_code == 404, r.text


def test_list_activation_keys_paginated(client, operator_token):
    env = _make_env(client, operator_token, "5")
    for i in range(3):
        client.post(
            "/activation-keys", json=_ak_payload(env, f"key5-{i}"), headers=auth_headers(operator_token)
        )

    r = client.get("/activation-keys", headers=auth_headers(operator_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) >= 3
    assert all("token" not in item for item in body)

    r2 = client.get("/activation-keys", params={"limit": 1, "offset": 0}, headers=auth_headers(operator_token))
    assert r2.status_code == 200, r2.text
    assert len(r2.json()) == 1


def test_list_activation_keys_as_viewer(client, operator_token, viewer_token):
    env = _make_env(client, operator_token, "5v")
    client.post("/activation-keys", json=_ak_payload(env, "key5v"), headers=auth_headers(operator_token))

    r = client.get("/activation-keys", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text


def test_revoke_activation_key_as_operator(client, operator_token):
    env = _make_env(client, operator_token, "6")
    created = client.post(
        "/activation-keys", json=_ak_payload(env, "key6"), headers=auth_headers(operator_token)
    ).json()

    r = client.post(f"/activation-keys/{created['id']}/revoke", headers=auth_headers(operator_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["revoked"] is True
    assert "token" not in body


def test_revoke_activation_key_as_viewer_forbidden(client, operator_token, viewer_token):
    env = _make_env(client, operator_token, "7")
    created = client.post(
        "/activation-keys", json=_ak_payload(env, "key7"), headers=auth_headers(operator_token)
    ).json()

    r = client.post(f"/activation-keys/{created['id']}/revoke", headers=auth_headers(viewer_token))
    assert r.status_code == 403, r.text


def test_revoke_activation_key_not_found(client, operator_token):
    r = client.post(
        "/activation-keys/00000000-0000-0000-0000-000000000000/revoke",
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text
