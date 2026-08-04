import pytest

from tests._rate_limit_helper import reset_login_rate_limit
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    reset_login_rate_limit()
    yield


def _register_payload(username="newuser", email=None, role="viewer"):
    return {
        "username": username,
        "email": email or f"{username}@example.com",
        "password": "Passw0rd!",
        "role": role,
    }


def test_register_as_admin_succeeds(client, admin_token):
    r = client.post("/auth/register", json=_register_payload("admin-created-user"), headers=auth_headers(admin_token))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["username"] == "admin-created-user"
    assert body["role"] == "viewer"
    assert "password" not in body
    assert "hashed_password" not in body


def test_register_as_operator_forbidden(client, operator_token):
    r = client.post("/auth/register", json=_register_payload("op-created-user"), headers=auth_headers(operator_token))
    assert r.status_code == 403, r.text


def test_register_as_viewer_forbidden(client, viewer_token):
    r = client.post("/auth/register", json=_register_payload("viewer-created-user"), headers=auth_headers(viewer_token))
    assert r.status_code == 403, r.text


def test_register_duplicate_username_conflicts(client, admin_token):
    r1 = client.post("/auth/register", json=_register_payload("dup-user"), headers=auth_headers(admin_token))
    assert r1.status_code == 201, r1.text
    r2 = client.post(
        "/auth/register", json=_register_payload("dup-user", email="different@example.com"), headers=auth_headers(admin_token)
    )
    assert r2.status_code == 409, r2.text


def test_login_valid_credentials(client, db_session):
    from app.auth import hash_password
    from app.models import Role, User

    user = User(
        username="login-user",
        email="login-user@example.com",
        hashed_password=hash_password("Passw0rd!"),
        role=Role.viewer,
    )
    db_session.add(user)
    db_session.commit()

    r = client.post("/auth/login", data={"username": "login-user", "password": "Passw0rd!"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]


def test_login_invalid_password_401(client, db_session):
    from app.auth import hash_password
    from app.models import Role, User

    user = User(
        username="login-user2",
        email="login-user2@example.com",
        hashed_password=hash_password("Passw0rd!"),
        role=Role.viewer,
    )
    db_session.add(user)
    db_session.commit()

    r = client.post("/auth/login", data={"username": "login-user2", "password": "wrong-password"})
    assert r.status_code == 401, r.text


def test_login_unknown_username_401(client):
    r = client.post("/auth/login", data={"username": "does-not-exist", "password": "whatever"})
    assert r.status_code == 401, r.text


# NOTE on rate limiting: POST /auth/login is decorated with @limiter.limit("5/minute")
# (app/routers/auth.py:58, backed by real Redis via app/limiter.py). This IS
# real enforcement and is worth knowing about, but we deliberately do NOT
# write a test that hammers the endpoint 6+ times expecting a 429 here: the
# limiter key is Redis-backed and NOT scoped per-test (confirmed while
# writing these tests — it persists across the whole session/window, keyed
# by remote address). A test asserting 429 after N attempts would consume
# from the same shared budget every other test file's admin_token/
# operator_token/viewer_token fixtures draw from, causing flaky spurious
# 429s elsewhere in the suite. The _reset_login_rate_limit autouse fixture
# above (tests/_rate_limit_helper.py) exists specifically to undo that
# damage between tests; deliberately hammering past the limit here would
# fight against every other file's use of that same fixture in a shared
# pytest run. Rate limiting on /auth/login is confirmed present by reading
# the code, not exercised end-to-end by this suite.


def test_refresh_issues_new_pair_and_revokes_old(client, db_session):
    from app.auth import hash_password
    from app.models import Role, User

    user = User(
        username="refresh-user",
        email="refresh-user@example.com",
        hashed_password=hash_password("Passw0rd!"),
        role=Role.viewer,
    )
    db_session.add(user)
    db_session.commit()

    login = client.post("/auth/login", data={"username": "refresh-user", "password": "Passw0rd!"})
    assert login.status_code == 200, login.text
    old_refresh = login.json()["refresh_token"]

    r = client.post("/auth/refresh", json={"refresh_token": old_refresh})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"]
    new_refresh = body["refresh_token"]
    assert new_refresh != old_refresh

    # Old refresh token is now revoked — a second use must fail.
    r2 = client.post("/auth/refresh", json={"refresh_token": old_refresh})
    assert r2.status_code == 401, r2.text

    # The new one should still work.
    r3 = client.post("/auth/refresh", json={"refresh_token": new_refresh})
    assert r3.status_code == 200, r3.text


def test_refresh_invalid_token_401(client):
    r = client.post("/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert r.status_code == 401, r.text


def test_logout_revokes_refresh_token(client, db_session):
    from app.auth import hash_password
    from app.models import Role, User

    user = User(
        username="logout-user",
        email="logout-user@example.com",
        hashed_password=hash_password("Passw0rd!"),
        role=Role.viewer,
    )
    db_session.add(user)
    db_session.commit()

    login = client.post("/auth/login", data={"username": "logout-user", "password": "Passw0rd!"})
    assert login.status_code == 200, login.text
    refresh_token = login.json()["refresh_token"]

    r = client.post("/auth/logout", json={"refresh_token": refresh_token})
    assert r.status_code == 204, r.text

    # Subsequent refresh with the now-revoked token must fail.
    r2 = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert r2.status_code == 401, r2.text


def test_logout_unknown_token_is_a_noop(client):
    r = client.post("/auth/logout", json={"refresh_token": "never-issued-token"})
    assert r.status_code == 204, r.text
