from datetime import datetime, timedelta, timezone

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


def _make_env(client, operator_token, suffix):
    repo = _create_repo(client, operator_token, f"en-repo-{suffix}")
    cv = _create_cv(client, operator_token, repo, f"en-cv-{suffix}")
    return _create_env(client, operator_token, cv, f"en-env-{suffix}", f"en-path-{suffix}", 0, f"en-prefix-{suffix}")


def _create_activation_key(client, operator_token, env, name="ek", **overrides):
    payload = {"name": name, "environment_id": env["id"]}
    payload.update(overrides)
    r = client.post("/activation-keys", json=payload, headers=auth_headers(operator_token))
    assert r.status_code == 201, r.text
    return r.json()


def _register_payload(token, hostname="host1.example.com", ip="10.0.0.1", ssh_user="ubuntu"):
    return {"token": token, "hostname": hostname, "ip_address": ip, "ssh_user": ssh_user}


def test_register_with_valid_token_creates_server(client, operator_token):
    env = _make_env(client, operator_token, "1")
    key = _create_activation_key(client, operator_token, env, "reg-key1")

    r = client.post("/enrollment/register", json=_register_payload(key["token"], "host-a.example.com"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["hostname"] == "host-a.example.com"
    assert body["environment_id"] == env["id"]
    assert "server_id" in body

    # Verify the server row was actually created and use_count incremented.
    get_key = client.get(f"/activation-keys/{key['id']}", headers=auth_headers(operator_token))
    assert get_key.json()["use_count"] == 1


def test_register_no_auth_header_required(client, operator_token):
    env = _make_env(client, operator_token, "noauth")
    key = _create_activation_key(client, operator_token, env, "reg-key-noauth")

    # Deliberately no Authorization header — this is the point of the endpoint.
    r = client.post(
        "/enrollment/register",
        json=_register_payload(key["token"], "host-noauth.example.com"),
    )
    assert r.status_code == 201, r.text


def test_register_with_invalid_token_401(client):
    r = client.post("/enrollment/register", json=_register_payload("not-a-real-token", "host-bad.example.com"))
    assert r.status_code == 401, r.text


def test_register_with_revoked_token_401(client, operator_token):
    env = _make_env(client, operator_token, "2")
    key = _create_activation_key(client, operator_token, env, "reg-key2")
    revoke = client.post(f"/activation-keys/{key['id']}/revoke", headers=auth_headers(operator_token))
    assert revoke.status_code == 200, revoke.text

    r = client.post("/enrollment/register", json=_register_payload(key["token"], "host-revoked.example.com"))
    assert r.status_code == 401, r.text


def test_register_with_expired_token_401(client, operator_token, db_session):
    from app.models import ActivationKey

    env = _make_env(client, operator_token, "3")
    key = _create_activation_key(client, operator_token, env, "reg-key3")

    # API doesn't allow creating with a past expires_at directly via schema
    # validation concerns, so seed it via the DB directly per task instructions.
    db_key = db_session.get(ActivationKey, key["id"])
    db_key.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.commit()

    r = client.post("/enrollment/register", json=_register_payload(key["token"], "host-expired.example.com"))
    assert r.status_code == 401, r.text


def test_register_with_exhausted_max_uses_401(client, operator_token):
    env = _make_env(client, operator_token, "4")
    key = _create_activation_key(client, operator_token, env, "reg-key4", max_uses=1)

    r1 = client.post("/enrollment/register", json=_register_payload(key["token"], "host-first.example.com"))
    assert r1.status_code == 201, r1.text

    r2 = client.post("/enrollment/register", json=_register_payload(key["token"], "host-second.example.com"))
    assert r2.status_code == 401, r2.text


def test_register_idempotent_same_hostname_updates_existing_server(client, operator_token):
    env = _make_env(client, operator_token, "5")
    key = _create_activation_key(client, operator_token, env, "reg-key5")

    r1 = client.post(
        "/enrollment/register",
        json=_register_payload(key["token"], "host-idempotent.example.com", ip="10.0.0.5"),
    )
    assert r1.status_code == 201, r1.text
    server_id_1 = r1.json()["server_id"]

    # Router logic (enrollment.py): looks up Server by hostname; if found,
    # updates ip_address/ssh_user/last_seen_at on the SAME row rather than
    # creating a new one or erroring. environment_id is left untouched.
    r2 = client.post(
        "/enrollment/register",
        json=_register_payload(key["token"], "host-idempotent.example.com", ip="10.0.0.6"),
    )
    assert r2.status_code == 201, r2.text
    assert r2.json()["server_id"] == server_id_1
    assert r2.json()["environment_id"] == env["id"]
