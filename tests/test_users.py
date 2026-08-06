import pytest

from tests._rate_limit_helper import reset_login_rate_limit
from tests.conftest import Role, _make_user, auth_headers


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    reset_login_rate_limit()
    yield


def _user_id_for_token(client, token: str) -> str:
    r = client.get("/auth/me", headers=auth_headers(token))
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_list_users_as_admin(client, admin_token):
    r = client.get("/users", headers=auth_headers(admin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) >= 1
    assert all("hashed_password" not in u for u in body)
    assert all("active" in u for u in body)


def test_list_users_as_operator_forbidden(client, operator_token):
    r = client.get("/users", headers=auth_headers(operator_token))
    assert r.status_code == 403, r.text


def test_update_user_email_as_admin(client, admin_token, db_session):
    target = _make_user(db_session, Role.viewer)

    r = client.patch(f"/users/{target.id}", json={"email": "new-email@example.com"}, headers=auth_headers(admin_token))
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "new-email@example.com"


def test_update_user_role_as_admin(client, admin_token, db_session):
    target = _make_user(db_session, Role.viewer)

    r = client.patch(f"/users/{target.id}", json={"role": "operator"}, headers=auth_headers(admin_token))
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "operator"


def test_update_user_duplicate_email_conflicts(client, admin_token, db_session):
    existing = _make_user(db_session, Role.viewer)
    target = _make_user(db_session, Role.viewer)

    r = client.patch(f"/users/{target.id}", json={"email": existing.email}, headers=auth_headers(admin_token))
    assert r.status_code == 409, r.text


def test_update_user_as_operator_forbidden(client, operator_token, db_session):
    target = _make_user(db_session, Role.viewer)

    r = client.patch(f"/users/{target.id}", json={"email": "x@example.com"}, headers=auth_headers(operator_token))
    assert r.status_code == 403, r.text


def test_update_user_not_found(client, admin_token):
    r = client.patch(
        "/users/00000000-0000-0000-0000-000000000099", json={"email": "x@example.com"}, headers=auth_headers(admin_token)
    )
    assert r.status_code == 404, r.text


def test_deactivate_and_reactivate_user(client, admin_token, db_session):
    target = _make_user(db_session, Role.viewer)

    r = client.post(f"/users/{target.id}/deactivate", headers=auth_headers(admin_token))
    assert r.status_code == 200, r.text
    assert r.json()["active"] is False

    # Deactivated user can no longer log in.
    login = client.post("/auth/login", data={"username": target.username, "password": "Passw0rd!"})
    assert login.status_code == 401, login.text

    r2 = client.post(f"/users/{target.id}/reactivate", headers=auth_headers(admin_token))
    assert r2.status_code == 200, r2.text
    assert r2.json()["active"] is True

    login2 = client.post("/auth/login", data={"username": target.username, "password": "Passw0rd!"})
    assert login2.status_code == 200, login2.text


def test_deactivate_self_forbidden(client, db_session):
    admin = _make_user(db_session, Role.admin)
    login = client.post("/auth/login", data={"username": admin.username, "password": "Passw0rd!"})
    token = login.json()["access_token"]

    r = client.post(f"/users/{admin.id}/deactivate", headers=auth_headers(token))
    assert r.status_code == 409, r.text


def test_deactivate_last_admin_forbidden(client, admin_token, db_session):
    # admin_token's own underlying admin is deliberately left alone as the
    # caller for the boundary check below — it must stay untouched (not
    # deactivated, not demoted) so the count of "other active admins" at
    # the moment of that check is unambiguous and doesn't depend on
    # ordering games with the two admins this test itself is exercising.
    other_admin = _make_user(db_session, Role.admin)

    login = client.post("/auth/login", data={"username": other_admin.username, "password": "Passw0rd!"})
    other_token = login.json()["access_token"]

    # other_admin deactivates admin_token's admin — fine, other_admin
    # itself remains active, so this doesn't hit the guard.
    r1 = client.post(f"/users/{_user_id_for_token(client, admin_token)}/deactivate", headers=auth_headers(other_token))
    assert r1.status_code == 200, r1.text

    # Now other_admin is the only active admin left. Deactivating it (as
    # itself, or via any caller) must be refused.
    r2 = client.post(f"/users/{other_admin.id}/deactivate", headers=auth_headers(other_token))
    assert r2.status_code == 409, r2.text


def test_demote_last_admin_forbidden(client, admin_token, db_session):
    other_admin = _make_user(db_session, Role.admin)

    login = client.post("/auth/login", data={"username": other_admin.username, "password": "Passw0rd!"})
    other_token = login.json()["access_token"]

    # other_admin demotes admin_token's admin to operator — fine,
    # other_admin itself remains admin.
    r1 = client.patch(
        f"/users/{_user_id_for_token(client, admin_token)}",
        json={"role": "operator"},
        headers=auth_headers(other_token),
    )
    assert r1.status_code == 200, r1.text

    # Now other_admin is the only active admin left. Demoting it must be
    # refused, even though the caller (other_admin itself) still has a
    # currently-valid admin session at the moment of the request.
    r2 = client.patch(f"/users/{other_admin.id}", json={"role": "viewer"}, headers=auth_headers(other_token))
    assert r2.status_code == 409, r2.text
