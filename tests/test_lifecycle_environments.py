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


def _version_id(client, operator_token, cv):
    versions_r = client.get(f"/content-views/{cv['id']}/versions", headers=auth_headers(operator_token))
    return versions_r.json()[0]["id"]


def _create_env(client, operator_token, name="dev", description=None, prior_environment_id=None):
    # An environment is now pure path structure: name/description/
    # prior_environment_id only (LifecycleEnvironmentCreate) — NO content
    # view association at creation time.
    payload = {"name": name, "description": description}
    if prior_environment_id is not None:
        payload["prior_environment_id"] = prior_environment_id
    r = client.post("/lifecycle-environments", json=payload, headers=auth_headers(operator_token))
    assert r.status_code == 201, r.text
    return r.json()


def _library(client, operator_token):
    # Position 0 is always Library and never path-order-gated — tests
    # that just need ONE directly-assignable environment (no chaining)
    # use this instead of a freshly _create_env'd one, since any new
    # environment created with no prior now lands at position 1+ and
    # would need its OWN predecessor promoted first (see
    # test_path_order_enforced_for_first_promote_at_position_1 for that
    # scenario deliberately exercised). Creates a throwaway environment
    # first if Library doesn't exist yet in this test's fresh DB, purely
    # to trigger auto-seeding (see create_lifecycle_environment,
    # lifecycle_environments.py) — the throwaway itself is discarded.
    listed = client.get("/lifecycle-environments", headers=auth_headers(operator_token)).json()
    library = next((e for e in listed if e["name"] == "Library"), None)
    if library is not None:
        return library
    client.post("/lifecycle-environments", json={"name": "_seed"}, headers=auth_headers(operator_token))
    listed = client.get("/lifecycle-environments", headers=auth_headers(operator_token)).json()
    return next(e for e in listed if e["name"] == "Library")


def _assign_cv(client, operator_token, env, cv, version_id=None, gpg_key_id=None, allow_unsigned=True):
    # POST /{environment_id}/content-views assigns a content view to an
    # environment AND performs its first promote in one call.
    if version_id is None:
        version_id = _version_id(client, operator_token, cv)
    payload = {"content_view_id": cv["id"], "content_view_version_id": version_id}
    if gpg_key_id is not None:
        payload["gpg_key_id"] = gpg_key_id
    else:
        payload["allow_unsigned"] = allow_unsigned
    r = client.post(
        f"/lifecycle-environments/{env['id']}/content-views", json=payload, headers=auth_headers(operator_token)
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# POST /lifecycle-environments — single path, always rooted at auto-Library
# ---------------------------------------------------------------------------


def test_create_lifecycle_environment_minimal(client, operator_token):
    # First-ever environment on a fresh DB: omitting prior auto-seeds
    # Library (position 0) and appends this one right after it.
    env = _create_env(client, operator_token, "dev1")
    assert env["name"] == "dev1"
    assert env["description"] is None
    assert env["path_name"] == "Library"
    assert env["position"] == 1
    assert env["content_view_count"] == 0
    assert env["host_count"] == 0


def test_create_lifecycle_environment_auto_seeds_library(client, operator_token):
    env = _create_env(client, operator_token, "dev1b")
    assert env["path_name"] == "Library"
    assert env["position"] == 1

    listed = client.get("/lifecycle-environments", headers=auth_headers(operator_token)).json()
    names_positions = {(e["name"], e["position"]) for e in listed}
    assert ("Library", 0) in names_positions
    assert ("dev1b", 1) in names_positions


def test_create_lifecycle_environment_second_create_appends_at_true_end(client, operator_token):
    # "No prior" always means "append at the end of the whole path", not
    # "chain right after Library specifically" — the second environment
    # lands after the first, not back at position 1.
    first = _create_env(client, operator_token, "dev1c")
    second = _create_env(client, operator_token, "dev1d")
    assert first["position"] == 1
    assert second["position"] == 2


def test_create_lifecycle_environment_with_description(client, operator_token):
    env = _create_env(client, operator_token, "dev2", description="dev tier")
    assert env["description"] == "dev tier"


def test_create_lifecycle_environment_with_prior_chains_path(client, operator_token):
    dev = _create_env(client, operator_token, "dev3")
    staging = _create_env(client, operator_token, "staging3", prior_environment_id=dev["id"])
    assert staging["path_name"] == dev["path_name"]
    assert staging["position"] == dev["position"] + 1


def test_create_lifecycle_environment_prior_inserts_and_shifts_successors(client, operator_token):
    """Real insert-in-place: explicit prior_environment_id inserts right
    after that environment, shifting every environment currently past
    that point back by one position.
    """
    a = _create_env(client, operator_token, "path-a")
    b = _create_env(client, operator_token, "path-b", prior_environment_id=a["id"])
    c = _create_env(client, operator_token, "path-c", prior_environment_id=b["id"])
    assert [e["position"] for e in (a, b, c)] == [a["position"], a["position"] + 1, a["position"] + 2]

    d = _create_env(client, operator_token, "path-d", prior_environment_id=a["id"])
    assert d["position"] == a["position"] + 1

    listed = client.get("/lifecycle-environments", headers=auth_headers(operator_token)).json()
    by_name = {e["name"]: e["position"] for e in listed}
    assert by_name["path-a"] == a["position"]
    assert by_name["path-d"] == a["position"] + 1
    assert by_name["path-b"] == a["position"] + 2  # shifted back by one
    assert by_name["path-c"] == a["position"] + 3  # shifted back by one


def test_create_lifecycle_environment_prior_not_found(client, operator_token):
    r = client.post(
        "/lifecycle-environments",
        json={"name": "orphan4", "prior_environment_id": "00000000-0000-0000-0000-000000000000"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_create_lifecycle_environment_duplicate_name_conflicts(client, operator_token):
    _create_env(client, operator_token, "dev5")
    r = client.post("/lifecycle-environments", json={"name": "dev5"}, headers=auth_headers(operator_token))
    assert r.status_code == 409, r.text


def test_create_lifecycle_environment_name_unique_globally(client, operator_token):
    # name uniqueness is global — an environment doesn't belong to a
    # content view (models.py's LifecycleEnvironment docstring). Same
    # name is rejected even for two otherwise-unrelated environments.
    _create_env(client, operator_token, "dev5b")
    r = client.post("/lifecycle-environments", json={"name": "dev5b"}, headers=auth_headers(operator_token))
    assert r.status_code == 409, r.text


def test_create_lifecycle_environment_as_viewer_forbidden(client, viewer_token):
    r = client.post("/lifecycle-environments", json={"name": "dev7"}, headers=auth_headers(viewer_token))
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# DELETE /lifecycle-environments/{id}
# ---------------------------------------------------------------------------


def test_delete_lifecycle_environment_unassigned_succeeds(client, operator_token):
    env = _create_env(client, operator_token, "del-env1")
    r = client.delete(f"/lifecycle-environments/{env['id']}", headers=auth_headers(operator_token))
    assert r.status_code == 204, r.text

    listed = client.get("/lifecycle-environments", headers=auth_headers(operator_token)).json()
    assert env["id"] not in {e["id"] for e in listed}


def test_delete_lifecycle_environment_not_found(client, operator_token):
    r = client.delete(
        "/lifecycle-environments/00000000-0000-0000-0000-000000000000", headers=auth_headers(operator_token)
    )
    assert r.status_code == 404, r.text


def test_delete_lifecycle_environment_as_viewer_forbidden(client, operator_token, viewer_token):
    env = _create_env(client, operator_token, "del-env2")
    r = client.delete(f"/lifecycle-environments/{env['id']}", headers=auth_headers(viewer_token))
    assert r.status_code == 403, r.text


def test_delete_lifecycle_environment_blocked_while_content_view_assigned(client, operator_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "del-repo1")
    cv = _create_cv(client, operator_token, repo, "del-cv1")
    library = _library(client, operator_token)
    _assign_cv(client, operator_token, library, cv)

    r = client.delete(f"/lifecycle-environments/{library['id']}", headers=auth_headers(operator_token))
    assert r.status_code == 409, r.text
    assert "1 content view" in r.text

    r = client.delete(
        f"/lifecycle-environments/{library['id']}/content-views/{cv['id']}", headers=auth_headers(operator_token)
    )
    assert r.status_code == 204, r.text

    r = client.delete(f"/lifecycle-environments/{library['id']}", headers=auth_headers(operator_token))
    assert r.status_code == 204, r.text


def test_delete_lifecycle_environment_blocked_while_server_assigned(client, operator_token):
    env = _create_env(client, operator_token, "del-env3")
    r = client.post(
        "/servers",
        json={"hostname": "del-host1.example.com", "ip_address": "10.0.0.1", "ssh_user": "ubuntu", "environment_id": env["id"]},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 201, r.text

    r = client.delete(f"/lifecycle-environments/{env['id']}", headers=auth_headers(operator_token))
    assert r.status_code == 409, r.text
    assert "1 server" in r.text


def test_list_lifecycle_environments_includes_counts(client, operator_token):
    env = _create_env(client, operator_token, "count-env1")
    listed = client.get("/lifecycle-environments", headers=auth_headers(operator_token)).json()
    row = next(e for e in listed if e["id"] == env["id"])
    assert row["content_view_count"] == 0
    assert row["host_count"] == 0


# ---------------------------------------------------------------------------
# PATCH /lifecycle-environments/{id}
# ---------------------------------------------------------------------------


def test_update_lifecycle_environment_sets_description(client, operator_token):
    env = _create_env(client, operator_token, "dev8")
    r = client.patch(
        f"/lifecycle-environments/{env['id']}",
        json={"description": "now described"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["description"] == "now described"


def test_update_lifecycle_environment_not_found(client, operator_token):
    r = client.patch(
        "/lifecycle-environments/00000000-0000-0000-0000-000000000000",
        json={"description": "x"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_update_lifecycle_environment_as_viewer_forbidden(client, operator_token, viewer_token):
    env = _create_env(client, operator_token, "dev10")
    r = client.patch(
        f"/lifecycle-environments/{env['id']}",
        json={"description": "x"},
        headers=auth_headers(viewer_token),
    )
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# GET /lifecycle-environments (list + path_name filter)
# ---------------------------------------------------------------------------


def test_list_lifecycle_environments_paginated_and_filtered(client, operator_token, viewer_token):
    dev = _create_env(client, operator_token, "dev11")
    _create_env(client, operator_token, "staging11", prior_environment_id=dev["id"])

    r = client.get(
        "/lifecycle-environments", params={"path_name": dev["path_name"]}, headers=auth_headers(viewer_token)
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) == 2


def test_list_lifecycle_environments_as_viewer(client, operator_token, viewer_token):
    _create_env(client, operator_token, "dev11b")
    r = client.get("/lifecycle-environments", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    assert any(e["name"] == "dev11b" for e in r.json())


# ---------------------------------------------------------------------------
# POST /{environment_id}/content-views (assign + first promote)
# ---------------------------------------------------------------------------


def test_assign_content_view_requires_signing_choice(client, operator_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    repo = _create_repo(client, operator_token, "le-repo16")
    cv = _create_cv(client, operator_token, repo, "le-cv16")
    version_id = _version_id(client, operator_token, cv)
    env = _create_env(client, operator_token, "dev16")

    r = client.post(
        f"/lifecycle-environments/{env['id']}/content-views",
        json={"content_view_id": cv["id"], "content_view_version_id": version_id},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 422, r.text


def test_assign_content_view_derives_release_and_publish_prefix(client, operator_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "le-repo17")
    cv = _create_cv(client, operator_token, repo, "le-cv17")
    version_id = _version_id(client, operator_token, cv)
    env = _library(client, operator_token)

    ecv = _assign_cv(client, operator_token, env, cv, version_id=version_id)
    assert ecv["current_version_id"] == version_id
    assert ecv["environment_id"] == env["id"]
    assert ecv["content_view_id"] == cv["id"]
    # publish_prefix is "<environment-name>/<content-view-name>" — derived,
    # never operator-set (EnvironmentContentView docstring, models.py).
    assert ecv["publish_prefix"] == f"{env['name']}/{cv['name']}"
    assert ecv["release"] == "jammy"  # from repo's distribution
    assert mock_aptly.publish_snapshot.call_count == 1
    call = mock_aptly.publish_snapshot.call_args_list[-1]
    assert call.args[0] == f"{env['name']}/{cv['name']}"
    assert call.args[1] == "jammy"


def test_assign_content_view_gpg_key_set_skips_allow_unsigned(client, operator_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "le-repo18")
    cv = _create_cv(client, operator_token, repo, "le-cv18")
    version_id = _version_id(client, operator_token, cv)
    env = _library(client, operator_token)

    ecv = _assign_cv(client, operator_token, env, cv, version_id=version_id, gpg_key_id="D" * 40)
    assert ecv["gpg_key_id"] == "D" * 40


def test_assign_content_view_environment_not_found(client, operator_token, mock_aptly):
    repo = _create_repo(client, operator_token, "le-repo-notfound")
    cv = _create_cv(client, operator_token, repo, "le-cv-notfound")
    version_id = _version_id(client, operator_token, cv)
    r = client.post(
        "/lifecycle-environments/00000000-0000-0000-0000-000000000000/content-views",
        json={"content_view_id": cv["id"], "content_view_version_id": version_id, "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_assign_content_view_not_found(client, operator_token):
    env = _create_env(client, operator_token, "dev-cv-notfound")
    r = client.post(
        f"/lifecycle-environments/{env['id']}/content-views",
        json={
            "content_view_id": "00000000-0000-0000-0000-000000000000",
            "content_view_version_id": "00000000-0000-0000-0000-000000000000",
            "allow_unsigned": True,
        },
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_assign_content_view_already_assigned_conflicts(client, operator_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "le-repo-dup")
    cv = _create_cv(client, operator_token, repo, "le-cv-dup")
    version_id = _version_id(client, operator_token, cv)
    env = _library(client, operator_token)
    _assign_cv(client, operator_token, env, cv, version_id=version_id)

    r = client.post(
        f"/lifecycle-environments/{env['id']}/content-views",
        json={"content_view_id": cv["id"], "content_view_version_id": version_id, "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 409, r.text


def test_assign_content_view_as_viewer_forbidden(client, operator_token, viewer_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = []
    repo = _create_repo(client, operator_token, "le-repo20")
    cv = _create_cv(client, operator_token, repo, "le-cv20")
    version_id = _version_id(client, operator_token, cv)
    env = _create_env(client, operator_token, "dev20")

    r = client.post(
        f"/lifecycle-environments/{env['id']}/content-views",
        json={"content_view_id": cv["id"], "content_view_version_id": version_id, "allow_unsigned": True},
        headers=auth_headers(viewer_token),
    )
    assert r.status_code == 403, r.text


def test_assign_content_view_aptly_unreachable_returns_502(db_session, mock_aptly, mock_aptly_unreachable):
    from app.aptly_client import get_aptly_client
    from app.main import app
    from tests.conftest import Role, TestClient, _token_for

    app.dependency_overrides[get_aptly_client] = lambda: mock_aptly
    try:
        with TestClient(app) as c:
            token = _token_for(c, db_session, Role.operator)
            repo = _create_repo(c, token, "le-repo22")
            cv = _create_cv(c, token, repo, "le-cv22")
            version_id = _version_id(c, token, cv)
            env = _library(c, token)
    finally:
        app.dependency_overrides.clear()

    app.dependency_overrides[get_aptly_client] = lambda: mock_aptly_unreachable
    try:
        with TestClient(app) as c:
            r = c.post(
                f"/lifecycle-environments/{env['id']}/content-views",
                json={"content_view_id": cv["id"], "content_view_version_id": version_id, "allow_unsigned": True},
                headers=auth_headers(token),
            )
            assert r.status_code == 502, r.text
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /{environment_id}/content-views, GET .../gpg-key
# ---------------------------------------------------------------------------


def test_list_environment_content_views_empty(client, operator_token):
    env = _create_env(client, operator_token, "dev-empty-ecvs")
    r = client.get(f"/lifecycle-environments/{env['id']}/content-views", headers=auth_headers(operator_token))
    assert r.status_code == 200, r.text
    assert r.json() == []


def test_list_environment_content_views_not_found(client, operator_token):
    r = client.get(
        "/lifecycle-environments/00000000-0000-0000-0000-000000000000/content-views",
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_get_gpg_key_404_when_not_configured(client, operator_token, viewer_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "le-repo14")
    cv = _create_cv(client, operator_token, repo, "le-cv14")
    env = _library(client, operator_token)
    _assign_cv(client, operator_token, env, cv)

    r = client.get(
        f"/lifecycle-environments/{env['id']}/content-views/{cv['id']}/gpg-key", headers=auth_headers(viewer_token)
    )
    assert r.status_code == 404, r.text


def test_get_gpg_key_not_assigned_404s(client, operator_token, viewer_token):
    env = _create_env(client, operator_token, "dev14b")
    r = client.get(
        f"/lifecycle-environments/{env['id']}/content-views/00000000-0000-0000-0000-000000000000/gpg-key",
        headers=auth_headers(viewer_token),
    )
    assert r.status_code == 404, r.text


# ---------------------------------------------------------------------------
# POST /{environment_id}/content-views/{content_view_id}/promote — later promotes
# ---------------------------------------------------------------------------


def test_second_promote_omits_version_and_publishes_latest(client, operator_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "le-repo19")
    cv = _create_cv(client, operator_token, repo, "le-cv19")
    version_id = _version_id(client, operator_token, cv)
    env = _library(client, operator_token)
    _assign_cv(client, operator_token, env, cv, version_id=version_id)

    mock_aptly.publish_exists.return_value = True
    r = client.post(
        f"/lifecycle-environments/{env['id']}/content-views/{cv['id']}/promote",
        json={},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 200, r.text
    # Still the same version (do_publish is a no-op — nothing changed).
    assert r.json()["current_version_id"] == version_id


def test_promote_environment_content_view_as_viewer_forbidden(client, operator_token, viewer_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = True
    repo = _create_repo(client, operator_token, "le-repo20b")
    cv = _create_cv(client, operator_token, repo, "le-cv20b")
    env = _library(client, operator_token)
    _assign_cv(client, operator_token, env, cv)

    r = client.post(
        f"/lifecycle-environments/{env['id']}/content-views/{cv['id']}/promote",
        json={},
        headers=auth_headers(viewer_token),
    )
    assert r.status_code == 403, r.text


def test_promote_environment_content_view_not_assigned_404s(client, operator_token):
    env = _create_env(client, operator_token, "dev-promote-notassigned")
    r = client.post(
        f"/lifecycle-environments/{env['id']}/content-views/00000000-0000-0000-0000-000000000000/promote",
        json={},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_promote_environment_content_view_environment_not_found(client, operator_token):
    r = client.post(
        "/lifecycle-environments/00000000-0000-0000-0000-000000000000/content-views/"
        "00000000-0000-0000-0000-000000000000/promote",
        json={},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_promote_environment_content_view_aptly_unreachable_returns_502(
    db_session, mock_aptly, mock_aptly_unreachable
):
    from app.aptly_client import get_aptly_client
    from app.main import app
    from tests.conftest import Role, TestClient, _token_for

    app.dependency_overrides[get_aptly_client] = lambda: mock_aptly
    try:
        with TestClient(app) as c:
            token = _token_for(c, db_session, Role.operator)
            mock_aptly.get_mirror_packages.return_value = [
                {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
            ]
            mock_aptly.publish_exists.return_value = False
            repo = _create_repo(c, token, "le-repo-unreachable")
            cv = _create_cv(c, token, repo, "le-cv-unreachable")
            env = _library(c, token)
            _assign_cv(c, token, env, cv)
    finally:
        app.dependency_overrides.clear()

    app.dependency_overrides[get_aptly_client] = lambda: mock_aptly_unreachable
    try:
        with TestClient(app) as c:
            r = c.post(
                f"/lifecycle-environments/{env['id']}/content-views/{cv['id']}/promote",
                json={},
                headers=auth_headers(token),
            )
            assert r.status_code == 502, r.text
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Path-order enforcement — PER CONTENT VIEW
# ---------------------------------------------------------------------------


def test_path_order_enforced_for_first_promote_at_position_1(client, operator_token, mock_aptly):
    """A content view's very first assign+promote at position 1 is itself
    path-order-gated: position 1 requires THIS content view to already be
    current at position 0. dev (position 0) has never had this content
    view assigned at all when staging tries — rejected.
    """
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "le-repo21")
    cv = _create_cv(client, operator_token, repo, "le-cv21")
    version_id = _version_id(client, operator_token, cv)
    dev = _library(client, operator_token)
    staging = _create_env(client, operator_token, "staging21", prior_environment_id=dev["id"])

    r = client.post(
        f"/lifecycle-environments/{staging['id']}/content-views",
        json={"content_view_id": cv["id"], "content_view_version_id": version_id, "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 409, r.text

    # dev promotes first, then staging succeeds with the same version.
    _assign_cv(client, operator_token, dev, cv, version_id=version_id)

    r2 = client.post(
        f"/lifecycle-environments/{staging['id']}/content-views",
        json={"content_view_id": cv["id"], "content_view_version_id": version_id, "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )
    assert r2.status_code == 201, r2.text


def test_path_order_enforced_for_later_promote(client, operator_token, mock_aptly):
    """Once both dev and staging have this content view assigned at v1,
    staging must not be able to jump straight to v2 while dev is still on
    v1 — the SAME check applies to later promotes via the nested route,
    not just the first.
    """
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "le-repo21b")
    cv = _create_cv(client, operator_token, repo, "le-cv21b")
    v1 = _version_id(client, operator_token, cv)
    dev = _library(client, operator_token)
    staging = _create_env(client, operator_token, "staging21b", prior_environment_id=dev["id"])
    _assign_cv(client, operator_token, dev, cv, version_id=v1)
    _assign_cv(client, operator_token, staging, cv, version_id=v1)

    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.19.0-1", "Architecture": "amd64"}
    ]
    publish_r = client.post(f"/content-views/{cv['id']}/publish", headers=auth_headers(operator_token))
    assert publish_r.status_code == 201, publish_r.text
    v2 = publish_r.json()["content_view_version"]["id"]

    r = client.post(
        f"/lifecycle-environments/{staging['id']}/content-views/{cv['id']}/promote",
        json={"content_view_version_id": v2},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 409, r.text

    # dev promotes to v2 first, then staging succeeds.
    dev_promote = client.post(
        f"/lifecycle-environments/{dev['id']}/content-views/{cv['id']}/promote",
        json={"content_view_version_id": v2},
        headers=auth_headers(operator_token),
    )
    assert dev_promote.status_code == 200, dev_promote.text

    r2 = client.post(
        f"/lifecycle-environments/{staging['id']}/content-views/{cv['id']}/promote",
        json={"content_view_version_id": v2},
        headers=auth_headers(operator_token),
    )
    assert r2.status_code == 200, r2.text


def test_path_order_independent_per_content_view(client, operator_token, mock_aptly):
    """The core new capability: two DIFFERENT content views assigned to
    the SAME environment path are promoted completely independently.
    Content view A can be live at staging (position 1) while content view
    B has never even been assigned there — A's promotion history imposes
    no constraint on B, and vice versa.
    """
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo_a = _create_repo(client, operator_token, "le-repo-indep-a")
    repo_b = _create_repo(client, operator_token, "le-repo-indep-b")
    cv_a = _create_cv(client, operator_token, repo_a, "le-cv-indep-a")
    cv_b = _create_cv(client, operator_token, repo_b, "le-cv-indep-b")
    v_a = _version_id(client, operator_token, cv_a)

    dev = _library(client, operator_token)
    staging = _create_env(client, operator_token, "staging-indep", prior_environment_id=dev["id"])

    # cv_a travels the full path: dev then staging.
    _assign_cv(client, operator_token, dev, cv_a, version_id=v_a)
    r = client.post(
        f"/lifecycle-environments/{staging['id']}/content-views",
        json={"content_view_id": cv_a["id"], "content_view_version_id": v_a, "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 201, r.text

    # cv_b assigned DIRECTLY to staging (position 1) despite never having
    # been assigned to dev at all — allowed, because path-order only gates
    # a content view against ITS OWN predecessor state, and dev simply has
    # no EnvironmentContentView row for cv_b (predecessor_ecv is None,
    # which _check_path_order treats the same as "predecessor never had
    # this content view live" — i.e. still gated)...
    v_b = _version_id(client, operator_token, cv_b)
    r2 = client.post(
        f"/lifecycle-environments/{staging['id']}/content-views",
        json={"content_view_id": cv_b["id"], "content_view_version_id": v_b, "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )
    # ...so this specific attempt (cv_b straight to position 1) is
    # correctly rejected — proving path-order is real per content view,
    # not just decorative.
    assert r2.status_code == 409, r2.text

    # But assigning cv_b to dev (position 0, no predecessor gate) succeeds
    # independently of cv_a's own state at dev.
    r3 = client.post(
        f"/lifecycle-environments/{dev['id']}/content-views",
        json={"content_view_id": cv_b["id"], "content_view_version_id": v_b, "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )
    assert r3.status_code == 201, r3.text

    # Both content views are now independently assigned to dev, each with
    # its own current_version_id.
    dev_ecvs = client.get(
        f"/lifecycle-environments/{dev['id']}/content-views", headers=auth_headers(operator_token)
    ).json()
    ecvs_by_cv = {e["content_view_id"]: e for e in dev_ecvs}
    assert ecvs_by_cv[cv_a["id"]]["current_version_id"] == v_a
    assert ecvs_by_cv[cv_b["id"]]["current_version_id"] == v_b
    assert len(dev_ecvs) == 2


def test_multiple_content_views_assigned_to_same_environment(client, operator_token, mock_aptly):
    """Any number of content views can be assigned to one environment now
    — two independent content views, both assigned+promoted to the SAME
    environment, each keeping its own current_version_id and
    publish_prefix.
    """
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo_a = _create_repo(client, operator_token, "le-repo-multi-a")
    repo_b = _create_repo(client, operator_token, "le-repo-multi-b")
    cv_a = _create_cv(client, operator_token, repo_a, "le-cv-multi-a")
    cv_b = _create_cv(client, operator_token, repo_b, "le-cv-multi-b")
    env = _library(client, operator_token)

    ecv_a = _assign_cv(client, operator_token, env, cv_a)
    ecv_b = _assign_cv(client, operator_token, env, cv_b)

    assert ecv_a["environment_id"] == env["id"]
    assert ecv_b["environment_id"] == env["id"]
    assert ecv_a["content_view_id"] != ecv_b["content_view_id"]
    assert ecv_a["publish_prefix"] != ecv_b["publish_prefix"]
    assert ecv_a["publish_prefix"] == f"{env['name']}/{cv_a['name']}"
    assert ecv_b["publish_prefix"] == f"{env['name']}/{cv_b['name']}"

    listed = client.get(
        f"/lifecycle-environments/{env['id']}/content-views", headers=auth_headers(operator_token)
    ).json()
    assert {e["content_view_id"] for e in listed} == {cv_a["id"], cv_b["id"]}


# ---------------------------------------------------------------------------
# DELETE /{environment_id}/content-views/{content_view_id} (unassign)
# ---------------------------------------------------------------------------


def test_unassign_content_view_removes_assignment(client, operator_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "le-repo-unassign")
    cv = _create_cv(client, operator_token, repo, "le-cv-unassign")
    env = _library(client, operator_token)
    _assign_cv(client, operator_token, env, cv)

    r = client.delete(
        f"/lifecycle-environments/{env['id']}/content-views/{cv['id']}", headers=auth_headers(operator_token)
    )
    assert r.status_code == 204, r.text

    listed = client.get(
        f"/lifecycle-environments/{env['id']}/content-views", headers=auth_headers(operator_token)
    ).json()
    assert listed == []


def test_unassign_content_view_not_assigned_404s(client, operator_token):
    env = _create_env(client, operator_token, "env-unassign-404")
    r = client.delete(
        f"/lifecycle-environments/{env['id']}/content-views/00000000-0000-0000-0000-000000000000",
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_unassign_content_view_as_viewer_forbidden(client, operator_token, viewer_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "le-repo-unassign-viewer")
    cv = _create_cv(client, operator_token, repo, "le-cv-unassign-viewer")
    env = _library(client, operator_token)
    _assign_cv(client, operator_token, env, cv)

    r = client.delete(
        f"/lifecycle-environments/{env['id']}/content-views/{cv['id']}", headers=auth_headers(viewer_token)
    )
    assert r.status_code == 403, r.text


def test_unassign_then_reassign_content_view_allowed(client, operator_token, mock_aptly):
    """Unassigning frees up the (environment, content_view) pair for a
    fresh assign+first-promote — the 409 "already assigned" guard is
    scoped to an ACTIVE assignment, not a permanent lock.
    """
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "le-repo-reassign")
    cv = _create_cv(client, operator_token, repo, "le-cv-reassign")
    env = _library(client, operator_token)
    _assign_cv(client, operator_token, env, cv)

    unassign_r = client.delete(
        f"/lifecycle-environments/{env['id']}/content-views/{cv['id']}", headers=auth_headers(operator_token)
    )
    assert unassign_r.status_code == 204, unassign_r.text

    reassigned = _assign_cv(client, operator_token, env, cv)
    assert reassigned["environment_id"] == env["id"]
    assert reassigned["content_view_id"] == cv["id"]


# ---------------------------------------------------------------------------
# Content view deletion guard interacts with assignment (see also
# test_content_views.py's own delete-guard test, which covers the same
# invariant from the content-view side).
# ---------------------------------------------------------------------------


def test_content_view_delete_blocked_while_assigned_then_succeeds_after_unassign(client, operator_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "le-repo-delguard")
    cv = _create_cv(client, operator_token, repo, "le-cv-delguard")
    env = _library(client, operator_token)
    _assign_cv(client, operator_token, env, cv)

    blocked = client.delete(f"/content-views/{cv['id']}", headers=auth_headers(operator_token))
    assert blocked.status_code == 409, blocked.text
    assert env["name"] in blocked.json()["detail"]

    unassign_r = client.delete(
        f"/lifecycle-environments/{env['id']}/content-views/{cv['id']}", headers=auth_headers(operator_token)
    )
    assert unassign_r.status_code == 204, unassign_r.text

    allowed = client.delete(f"/content-views/{cv['id']}", headers=auth_headers(operator_token))
    assert allowed.status_code == 204, allowed.text


# ---------------------------------------------------------------------------
# POST /{environment_id}/content-views/{content_view_id}/rollback
# ---------------------------------------------------------------------------


def test_rollback_environment_content_view_requires_previously_live_version(client, operator_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "le-repo23")
    cv = _create_cv(client, operator_token, repo, "le-cv23")
    v1 = _version_id(client, operator_token, cv)
    env = _library(client, operator_token)
    _assign_cv(client, operator_token, env, cv, version_id=v1)

    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.19.0-1", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = True
    v2 = client.post(
        f"/lifecycle-environments/{env['id']}/content-views/{cv['id']}/promote",
        json={},
        headers=auth_headers(operator_token),
    ).json()["current_version_id"]
    assert v2 != v1

    r = client.post(
        f"/lifecycle-environments/{env['id']}/content-views/{cv['id']}/rollback",
        json={"content_view_version_id": v1},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["current_version_id"] == v1


def test_rollback_environment_content_view_rejects_never_live_version(
    client, operator_token, db_session, mock_aptly
):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "le-repo24")
    cv = _create_cv(client, operator_token, repo, "le-cv24")
    version_id = _version_id(client, operator_token, cv)
    env = _library(client, operator_token)
    _assign_cv(client, operator_token, env, cv, version_id=version_id)

    # Manufacture a version this environment's content view has, but which
    # was never promoted here (simulating a version cut elsewhere).
    from app.models import ContentViewVersion

    phantom = ContentViewVersion(
        content_view_id=cv["id"],
        version=99,
        snapshots=[],
        content_hash="phantom-hash",
    )
    db_session.add(phantom)
    db_session.commit()
    db_session.refresh(phantom)

    r = client.post(
        f"/lifecycle-environments/{env['id']}/content-views/{cv['id']}/rollback",
        json={"content_view_version_id": str(phantom.id)},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 409, r.text


def test_rollback_environment_content_view_as_viewer_forbidden(client, operator_token, viewer_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "le-repo25")
    cv = _create_cv(client, operator_token, repo, "le-cv25")
    version_id = _version_id(client, operator_token, cv)
    env = _library(client, operator_token)
    ecv = _assign_cv(client, operator_token, env, cv, version_id=version_id)

    r = client.post(
        f"/lifecycle-environments/{env['id']}/content-views/{cv['id']}/rollback",
        json={"content_view_version_id": ecv["current_version_id"]},
        headers=auth_headers(viewer_token),
    )
    assert r.status_code == 403, r.text


def test_rollback_environment_content_view_not_assigned_404s(client, operator_token):
    env = _create_env(client, operator_token, "dev-rollback-notassigned")
    r = client.post(
        f"/lifecycle-environments/{env['id']}/content-views/00000000-0000-0000-0000-000000000000/rollback",
        json={"content_view_version_id": "00000000-0000-0000-0000-000000000000"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_rollback_environment_content_view_environment_not_found(client, operator_token):
    r = client.post(
        "/lifecycle-environments/00000000-0000-0000-0000-000000000000/content-views/"
        "00000000-0000-0000-0000-000000000000/rollback",
        json={"content_view_version_id": "00000000-0000-0000-0000-000000000000"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text
