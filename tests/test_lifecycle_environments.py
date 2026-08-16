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


def _create_env(client, operator_token, name="dev", description=None, prior_environment_id=None, gpg_key_id=None):
    payload = {
        "name": name,
        "description": description,
        "prior_environment_id": prior_environment_id,
        "gpg_key_id": gpg_key_id,
    }
    r = client.post("/lifecycle-environments", json=payload, headers=auth_headers(operator_token))
    assert r.status_code == 201, r.text
    return r.json()


def _version_id(client, operator_token, cv):
    versions_r = client.get(f"/content-views/{cv['id']}/versions", headers=auth_headers(operator_token))
    return versions_r.json()[0]["id"]


# ---------------------------------------------------------------------------
# POST /lifecycle-environments (simplified creation)
# ---------------------------------------------------------------------------


def test_create_lifecycle_environment_minimal(client, operator_token):
    env = _create_env(client, operator_token, "dev1")
    assert env["name"] == "dev1"
    assert env["description"] is None
    assert env["path_name"] == "dev1"  # no prior -> path_name defaults to own name
    assert env["position"] == 0
    assert env["content_view_id"] is None
    assert env["release"] is None
    assert env["publish_prefix"] is None
    assert env["gpg_key_id"] is None


def test_create_lifecycle_environment_with_description_and_gpg_key(client, operator_token):
    env = _create_env(client, operator_token, "dev2", description="dev tier", gpg_key_id="A" * 40)
    assert env["description"] == "dev tier"
    assert env["gpg_key_id"] == "A" * 40


def test_create_lifecycle_environment_with_prior_chains_path(client, operator_token):
    dev = _create_env(client, operator_token, "dev3")
    staging = _create_env(client, operator_token, "staging3", prior_environment_id=dev["id"])
    assert staging["path_name"] == dev["path_name"]
    assert staging["position"] == dev["position"] + 1


def test_create_lifecycle_environment_prior_not_found(client, operator_token):
    r = client.post(
        "/lifecycle-environments",
        json={"name": "orphan4", "prior_environment_id": "00000000-0000-0000-0000-000000000000"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_create_lifecycle_environment_duplicate_name_conflicts(client, operator_token):
    _create_env(client, operator_token, "dev5")
    r = client.post(
        "/lifecycle-environments", json={"name": "dev5"}, headers=auth_headers(operator_token)
    )
    assert r.status_code == 409, r.text


def test_create_lifecycle_environment_prior_already_has_successor_conflicts(client, operator_token):
    dev = _create_env(client, operator_token, "dev6")
    _create_env(client, operator_token, "staging6a", prior_environment_id=dev["id"])
    r = client.post(
        "/lifecycle-environments",
        json={"name": "staging6b", "prior_environment_id": dev["id"]},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 409, r.text


def test_create_lifecycle_environment_as_viewer_forbidden(client, operator_token, viewer_token):
    r = client.post(
        "/lifecycle-environments", json={"name": "dev7"}, headers=auth_headers(viewer_token)
    )
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# PATCH /lifecycle-environments/{id}
# ---------------------------------------------------------------------------


def test_update_lifecycle_environment_sets_description_and_gpg_key(client, operator_token):
    env = _create_env(client, operator_token, "dev8")
    r = client.patch(
        f"/lifecycle-environments/{env['id']}",
        json={"description": "now described", "gpg_key_id": "B" * 40},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["description"] == "now described"
    assert body["gpg_key_id"] == "B" * 40


def test_update_lifecycle_environment_partial_leaves_other_field_untouched(client, operator_token):
    env = _create_env(client, operator_token, "dev9", gpg_key_id="C" * 40)
    r = client.patch(
        f"/lifecycle-environments/{env['id']}",
        json={"description": "only this changed"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["description"] == "only this changed"
    assert body["gpg_key_id"] == "C" * 40  # untouched, not cleared


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
# GET /lifecycle-environments (list + promotable_for_content_view_id)
# ---------------------------------------------------------------------------


def test_list_lifecycle_environments_paginated_and_filtered(client, operator_token, viewer_token):
    dev = _create_env(client, operator_token, "dev11")
    _create_env(client, operator_token, "staging11", prior_environment_id=dev["id"])

    r = client.get(
        "/lifecycle-environments", params={"path_name": dev["path_name"]}, headers=auth_headers(viewer_token)
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) == 2


def test_list_lifecycle_environments_content_view_id_excludes_never_promoted(client, operator_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "le-repo12")
    cv = _create_cv(client, operator_token, repo, "le-cv12")
    version_id = _version_id(client, operator_token, cv)
    linked = _create_env(client, operator_token, "linked12")
    client.post(
        f"/lifecycle-environments/{linked['id']}/promote",
        json={"content_view_version_id": version_id, "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )
    _create_env(client, operator_token, "unlinked12")

    r = client.get(
        "/lifecycle-environments", params={"content_view_id": cv["id"]}, headers=auth_headers(operator_token)
    )
    names = {e["name"] for e in r.json()}
    assert names == {"linked12"}  # exact-match only — excludes the never-promoted one


def test_list_lifecycle_environments_promotable_includes_never_promoted(client, operator_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "le-repo13")
    cv = _create_cv(client, operator_token, repo, "le-cv13")
    version_id = _version_id(client, operator_token, cv)
    linked = _create_env(client, operator_token, "linked13")
    client.post(
        f"/lifecycle-environments/{linked['id']}/promote",
        json={"content_view_version_id": version_id, "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )
    _create_env(client, operator_token, "unlinked13")

    # A THIRD environment linked to a DIFFERENT content view must be excluded.
    other_repo = _create_repo(client, operator_token, "le-repo13b")
    other_cv = _create_cv(client, operator_token, other_repo, "le-cv13b")
    other_version_id = _version_id(client, operator_token, other_cv)
    other_env = _create_env(client, operator_token, "other13")
    client.post(
        f"/lifecycle-environments/{other_env['id']}/promote",
        json={"content_view_version_id": other_version_id, "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )

    r = client.get(
        "/lifecycle-environments",
        params={"promotable_for_content_view_id": cv["id"]},
        headers=auth_headers(operator_token),
    )
    names = {e["name"] for e in r.json()}
    assert names == {"linked13", "unlinked13"}
    assert "other13" not in names


def test_get_gpg_key_404_when_not_configured(client, operator_token, viewer_token):
    env = _create_env(client, operator_token, "dev14")
    r = client.get(f"/lifecycle-environments/{env['id']}/gpg-key", headers=auth_headers(viewer_token))
    assert r.status_code == 404, r.text


def test_get_gpg_key_environment_not_found(client, viewer_token):
    r = client.get(
        "/lifecycle-environments/00000000-0000-0000-0000-000000000000/gpg-key", headers=auth_headers(viewer_token)
    )
    assert r.status_code == 404, r.text


# ---------------------------------------------------------------------------
# POST /{id}/promote — first promote (derives content_view_id/release/publish_prefix)
# ---------------------------------------------------------------------------


def test_first_promote_requires_content_view_version_id(client, operator_token):
    env = _create_env(client, operator_token, "dev15")
    r = client.post(f"/lifecycle-environments/{env['id']}/promote", json={}, headers=auth_headers(operator_token))
    assert r.status_code == 422, r.text


def test_first_promote_requires_signing_choice(client, operator_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    repo = _create_repo(client, operator_token, "le-repo16")
    cv = _create_cv(client, operator_token, repo, "le-cv16")
    version_id = _version_id(client, operator_token, cv)
    env = _create_env(client, operator_token, "dev16")

    r = client.post(
        f"/lifecycle-environments/{env['id']}/promote",
        json={"content_view_version_id": version_id},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 422, r.text


def test_first_promote_derives_release_publish_prefix_and_content_view(client, operator_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "le-repo17")
    cv = _create_cv(client, operator_token, repo, "le-cv17")
    version_id = _version_id(client, operator_token, cv)
    env = _create_env(client, operator_token, "dev17")

    r = client.post(
        f"/lifecycle-environments/{env['id']}/promote",
        json={"content_view_version_id": version_id, "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["current_version_id"] == version_id
    assert body["publish_prefix"] == "dev17"
    mock_aptly.publish_snapshot.assert_called_once()

    envs = client.get(
        "/lifecycle-environments", params={"content_view_id": cv["id"]}, headers=auth_headers(operator_token)
    ).json()
    linked = next(e for e in envs if e["id"] == env["id"])
    assert linked["content_view_id"] == cv["id"]
    assert linked["release"] == "jammy"  # from repo's distribution


def test_first_promote_gpg_key_already_set_skips_allow_unsigned(client, operator_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "le-repo18")
    cv = _create_cv(client, operator_token, repo, "le-cv18")
    version_id = _version_id(client, operator_token, cv)
    env = _create_env(client, operator_token, "dev18", gpg_key_id="D" * 40)

    r = client.post(
        f"/lifecycle-environments/{env['id']}/promote",
        json={"content_view_version_id": version_id},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 200, r.text


def test_second_promote_omits_version_and_reuses_locked_content_view(client, operator_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "le-repo19")
    cv = _create_cv(client, operator_token, repo, "le-cv19")
    version_id = _version_id(client, operator_token, cv)
    env = _create_env(client, operator_token, "dev19")

    client.post(
        f"/lifecycle-environments/{env['id']}/promote",
        json={"content_view_version_id": version_id, "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )

    mock_aptly.publish_exists.return_value = True
    r = client.post(f"/lifecycle-environments/{env['id']}/promote", json={}, headers=auth_headers(operator_token))
    assert r.status_code == 200, r.text
    # Still the same version (do_publish is a no-op — nothing changed).
    assert r.json()["current_version_id"] == version_id


def test_promote_environment_as_viewer_forbidden(client, operator_token, viewer_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = []
    repo = _create_repo(client, operator_token, "le-repo20")
    cv = _create_cv(client, operator_token, repo, "le-cv20")
    version_id = _version_id(client, operator_token, cv)
    env = _create_env(client, operator_token, "dev20")

    r = client.post(
        f"/lifecycle-environments/{env['id']}/promote",
        json={"content_view_version_id": version_id, "allow_unsigned": True},
        headers=auth_headers(viewer_token),
    )
    assert r.status_code == 403, r.text


def test_promote_environment_not_found(client, operator_token):
    r = client.post(
        "/lifecycle-environments/00000000-0000-0000-0000-000000000000/promote",
        json={},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_promote_environment_path_order_enforced(client, operator_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "le-repo21")
    cv = _create_cv(client, operator_token, repo, "le-cv21")
    version_id = _version_id(client, operator_token, cv)
    dev = _create_env(client, operator_token, "dev21")
    staging = _create_env(client, operator_token, "staging21", prior_environment_id=dev["id"])

    # staging attempts to promote first — dev (position 0) has never had
    # anything live, so staging (position 1) must be rejected.
    r = client.post(
        f"/lifecycle-environments/{staging['id']}/promote",
        json={"content_view_version_id": version_id, "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 409, r.text

    # dev promotes first, then staging succeeds with the same version.
    dev_promote = client.post(
        f"/lifecycle-environments/{dev['id']}/promote",
        json={"content_view_version_id": version_id, "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )
    assert dev_promote.status_code == 200, dev_promote.text

    r2 = client.post(
        f"/lifecycle-environments/{staging['id']}/promote",
        json={"content_view_version_id": version_id, "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )
    assert r2.status_code == 200, r2.text


def test_promote_environment_aptly_unreachable_returns_502(db_session, mock_aptly, mock_aptly_unreachable):
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
            env = _create_env(c, token, "dev22")
    finally:
        app.dependency_overrides.clear()

    app.dependency_overrides[get_aptly_client] = lambda: mock_aptly_unreachable
    try:
        with TestClient(app) as c:
            r = c.post(
                f"/lifecycle-environments/{env['id']}/promote",
                json={"content_view_version_id": version_id, "allow_unsigned": True},
                headers=auth_headers(token),
            )
            assert r.status_code == 502, r.text
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /{id}/rollback
# ---------------------------------------------------------------------------


def test_rollback_environment_requires_previously_live_version(client, operator_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "le-repo23")
    cv = _create_cv(client, operator_token, repo, "le-cv23")
    v1 = _version_id(client, operator_token, cv)
    env = _create_env(client, operator_token, "dev23")

    client.post(
        f"/lifecycle-environments/{env['id']}/promote",
        json={"content_view_version_id": v1, "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )

    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.19.0-1", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = True
    v2 = client.post(
        f"/lifecycle-environments/{env['id']}/promote", json={}, headers=auth_headers(operator_token)
    ).json()["current_version_id"]
    assert v2 != v1

    r = client.post(
        f"/lifecycle-environments/{env['id']}/rollback",
        json={"content_view_version_id": v1},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["current_version_id"] == v1


def test_rollback_environment_rejects_never_live_version(client, operator_token, db_session, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "le-repo24")
    cv = _create_cv(client, operator_token, repo, "le-cv24")
    version_id = _version_id(client, operator_token, cv)
    env = _create_env(client, operator_token, "dev24")

    client.post(
        f"/lifecycle-environments/{env['id']}/promote",
        json={"content_view_version_id": version_id, "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )

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
        f"/lifecycle-environments/{env['id']}/rollback",
        json={"content_view_version_id": str(phantom.id)},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 409, r.text


def test_rollback_environment_as_viewer_forbidden(client, operator_token, viewer_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "le-repo25")
    cv = _create_cv(client, operator_token, repo, "le-cv25")
    version_id = _version_id(client, operator_token, cv)
    env = _create_env(client, operator_token, "dev25")
    v1 = client.post(
        f"/lifecycle-environments/{env['id']}/promote",
        json={"content_view_version_id": version_id, "allow_unsigned": True},
        headers=auth_headers(operator_token),
    ).json()["current_version_id"]

    r = client.post(
        f"/lifecycle-environments/{env['id']}/rollback",
        json={"content_view_version_id": v1},
        headers=auth_headers(viewer_token),
    )
    assert r.status_code == 403, r.text


def test_rollback_environment_not_found(client, operator_token):
    r = client.post(
        "/lifecycle-environments/00000000-0000-0000-0000-000000000000/rollback",
        json={"content_view_version_id": "00000000-0000-0000-0000-000000000000"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text
