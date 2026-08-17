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


def _create_env(client, operator_token, cv, name="dev", description=None, prior_environment_id=None, gpg_key_id=None):
    # content_view_id is required at creation now unless chaining off a
    # prior environment (in which case it's inherited) — see
    # LifecycleEnvironmentCreate's validator. Mirrors the pattern in
    # test_content_views.py / test_compliance.py's own _create_env helpers.
    payload = {
        "name": name,
        "description": description,
        "gpg_key_id": gpg_key_id,
    }
    if prior_environment_id is not None:
        payload["prior_environment_id"] = prior_environment_id
    else:
        payload["content_view_id"] = cv["id"]
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
    repo = _create_repo(client, operator_token, "le-repo1")
    cv = _create_cv(client, operator_token, repo, "le-cv1")
    env = _create_env(client, operator_token, cv, "dev1")
    assert env["name"] == "dev1"
    assert env["description"] is None
    assert env["path_name"] == "dev1"  # no prior -> path_name defaults to own name
    assert env["position"] == 0
    assert env["content_view_id"] == cv["id"]  # now required up front, not deferred
    assert env["is_library"] is False
    assert env["release"] is None
    assert env["publish_prefix"] is None
    assert env["gpg_key_id"] is None


def test_create_lifecycle_environment_requires_content_view_or_prior(client, operator_token):
    # Omitting BOTH content_view_id and prior_environment_id is now rejected
    # at the schema layer — there's nothing to derive content_view_id from.
    r = client.post(
        "/lifecycle-environments", json={"name": "orphan1b"}, headers=auth_headers(operator_token)
    )
    assert r.status_code == 422, r.text


def test_create_lifecycle_environment_with_description_and_gpg_key(client, operator_token):
    repo = _create_repo(client, operator_token, "le-repo2")
    cv = _create_cv(client, operator_token, repo, "le-cv2")
    env = _create_env(client, operator_token, cv, "dev2", description="dev tier", gpg_key_id="A" * 40)
    assert env["description"] == "dev tier"
    assert env["gpg_key_id"] == "A" * 40


def test_create_lifecycle_environment_with_prior_chains_path(client, operator_token):
    repo = _create_repo(client, operator_token, "le-repo3")
    cv = _create_cv(client, operator_token, repo, "le-cv3")
    dev = _create_env(client, operator_token, cv, "dev3")
    staging = _create_env(client, operator_token, cv, "staging3", prior_environment_id=dev["id"])
    assert staging["path_name"] == dev["path_name"]
    assert staging["position"] == dev["position"] + 1
    assert staging["content_view_id"] == cv["id"]  # inherited from prior


def test_create_lifecycle_environment_prior_not_found(client, operator_token):
    r = client.post(
        "/lifecycle-environments",
        json={"name": "orphan4", "prior_environment_id": "00000000-0000-0000-0000-000000000000"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_create_lifecycle_environment_duplicate_name_conflicts(client, operator_token):
    repo = _create_repo(client, operator_token, "le-repo5")
    cv = _create_cv(client, operator_token, repo, "le-cv5")
    _create_env(client, operator_token, cv, "dev5")
    r = client.post(
        "/lifecycle-environments",
        json={"name": "dev5", "content_view_id": cv["id"]},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 409, r.text


def test_create_lifecycle_environment_same_name_different_content_view_allowed(client, operator_token):
    # name uniqueness is scoped to (content_view_id, name) now, not global.
    repo_a = _create_repo(client, operator_token, "le-repo5b-a")
    cv_a = _create_cv(client, operator_token, repo_a, "le-cv5b-a")
    repo_b = _create_repo(client, operator_token, "le-repo5b-b")
    cv_b = _create_cv(client, operator_token, repo_b, "le-cv5b-b")
    env_a = _create_env(client, operator_token, cv_a, "dev5b")
    env_b = _create_env(client, operator_token, cv_b, "dev5b")
    assert env_a["id"] != env_b["id"]
    assert env_a["content_view_id"] != env_b["content_view_id"]


def test_create_lifecycle_environment_prior_already_has_successor_conflicts(client, operator_token):
    repo = _create_repo(client, operator_token, "le-repo6")
    cv = _create_cv(client, operator_token, repo, "le-cv6")
    dev = _create_env(client, operator_token, cv, "dev6")
    _create_env(client, operator_token, cv, "staging6a", prior_environment_id=dev["id"])
    r = client.post(
        "/lifecycle-environments",
        json={"name": "staging6b", "prior_environment_id": dev["id"]},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 409, r.text


def test_create_lifecycle_environment_as_viewer_forbidden(client, operator_token, viewer_token):
    repo = _create_repo(client, operator_token, "le-repo7")
    cv = _create_cv(client, operator_token, repo, "le-cv7")
    r = client.post(
        "/lifecycle-environments",
        json={"name": "dev7", "content_view_id": cv["id"]},
        headers=auth_headers(viewer_token),
    )
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# PATCH /lifecycle-environments/{id}
# ---------------------------------------------------------------------------


def test_update_lifecycle_environment_sets_description_and_gpg_key(client, operator_token):
    repo = _create_repo(client, operator_token, "le-repo8")
    cv = _create_cv(client, operator_token, repo, "le-cv8")
    env = _create_env(client, operator_token, cv, "dev8")
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
    repo = _create_repo(client, operator_token, "le-repo9")
    cv = _create_cv(client, operator_token, repo, "le-cv9")
    env = _create_env(client, operator_token, cv, "dev9", gpg_key_id="C" * 40)
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
    repo = _create_repo(client, operator_token, "le-repo10")
    cv = _create_cv(client, operator_token, repo, "le-cv10")
    env = _create_env(client, operator_token, cv, "dev10")
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
    repo = _create_repo(client, operator_token, "le-repo11")
    cv = _create_cv(client, operator_token, repo, "le-cv11")
    dev = _create_env(client, operator_token, cv, "dev11")
    _create_env(client, operator_token, cv, "staging11", prior_environment_id=dev["id"])

    r = client.get(
        "/lifecycle-environments", params={"path_name": dev["path_name"]}, headers=auth_headers(viewer_token)
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) == 2


def test_list_lifecycle_environments_content_view_id_excludes_other_content_view(client, operator_token, mock_aptly):
    # content_view_id is now required at creation, so every environment
    # belongs to exactly one content view from the start — there's no more
    # "never linked" state to exclude. What content_view_id (exact match)
    # still excludes is environments belonging to a DIFFERENT content view.
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "le-repo12")
    cv = _create_cv(client, operator_token, repo, "le-cv12")
    version_id = _version_id(client, operator_token, cv)
    linked = _create_env(client, operator_token, cv, "linked12")
    client.post(
        f"/lifecycle-environments/{linked['id']}/promote",
        json={"content_view_version_id": version_id, "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )
    _create_env(client, operator_token, cv, "unlinked12")

    other_repo = _create_repo(client, operator_token, "le-repo12b")
    other_cv = _create_cv(client, operator_token, other_repo, "le-cv12b")
    _create_env(client, operator_token, other_cv, "other12")

    r = client.get(
        "/lifecycle-environments", params={"content_view_id": cv["id"]}, headers=auth_headers(operator_token)
    )
    names = {e["name"] for e in r.json()}
    # Both environments on cv match, promoted or not — Library also belongs
    # to cv, so it's included too.
    assert names == {"linked12", "unlinked12", "Library"}
    assert "other12" not in names


def test_list_lifecycle_environments_promotable_includes_never_promoted(client, operator_token, mock_aptly):
    # promotable_for_content_view_id matches content_view_id == target OR
    # content_view_id IS NULL. Legacy-only in practice now (content_view_id
    # is never null on new rows), but a never-promoted environment on the
    # target content view must still show up via the exact-match arm.
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "le-repo13")
    cv = _create_cv(client, operator_token, repo, "le-cv13")
    version_id = _version_id(client, operator_token, cv)
    linked = _create_env(client, operator_token, cv, "linked13")
    client.post(
        f"/lifecycle-environments/{linked['id']}/promote",
        json={"content_view_version_id": version_id, "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )
    _create_env(client, operator_token, cv, "unlinked13")

    # A THIRD environment linked to a DIFFERENT content view must be excluded.
    other_repo = _create_repo(client, operator_token, "le-repo13b")
    other_cv = _create_cv(client, operator_token, other_repo, "le-cv13b")
    other_version_id = _version_id(client, operator_token, other_cv)
    other_env = _create_env(client, operator_token, other_cv, "other13")
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
    assert names == {"linked13", "unlinked13", "Library"}
    assert "other13" not in names


def test_get_gpg_key_404_when_not_configured(client, operator_token, viewer_token):
    repo = _create_repo(client, operator_token, "le-repo14")
    cv = _create_cv(client, operator_token, repo, "le-cv14")
    env = _create_env(client, operator_token, cv, "dev14")
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
    repo = _create_repo(client, operator_token, "le-repo15")
    cv = _create_cv(client, operator_token, repo, "le-cv15")
    env = _create_env(client, operator_token, cv, "dev15")
    r = client.post(f"/lifecycle-environments/{env['id']}/promote", json={}, headers=auth_headers(operator_token))
    assert r.status_code == 422, r.text


def test_first_promote_requires_signing_choice(client, operator_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    repo = _create_repo(client, operator_token, "le-repo16")
    cv = _create_cv(client, operator_token, repo, "le-cv16")
    version_id = _version_id(client, operator_token, cv)
    env = _create_env(client, operator_token, cv, "dev16")

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
    env = _create_env(client, operator_token, cv, "dev17")

    r = client.post(
        f"/lifecycle-environments/{env['id']}/promote",
        json={"content_view_version_id": version_id, "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["current_version_id"] == version_id
    assert body["publish_prefix"] == "dev17"
    # Called twice, not once: _create_cv's auto-created Library environment
    # is itself immediately promoted to version 1 (create_library_environment,
    # lifecycle_environments.py), and this test's own explicit promote of
    # dev17 is a second, independent publish_snapshot call.
    assert mock_aptly.publish_snapshot.call_count == 2
    dev17_call = mock_aptly.publish_snapshot.call_args_list[-1]
    assert dev17_call.args[0] == "dev17"
    assert dev17_call.args[1] == "jammy"

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
    env = _create_env(client, operator_token, cv, "dev18", gpg_key_id="D" * 40)

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
    env = _create_env(client, operator_token, cv, "dev19")

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
    env = _create_env(client, operator_token, cv, "dev20")

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
    dev = _create_env(client, operator_token, cv, "dev21")
    staging = _create_env(client, operator_token, cv, "staging21", prior_environment_id=dev["id"])

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
            env = _create_env(c, token, cv, "dev22")
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
    env = _create_env(client, operator_token, cv, "dev23")

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
    env = _create_env(client, operator_token, cv, "dev24")

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
    env = _create_env(client, operator_token, cv, "dev25")
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
