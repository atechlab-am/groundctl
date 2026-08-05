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


def _env_payload(cv, name="dev", path_name="main", position=0, publish_prefix="dev", allow_unsigned=True, gpg_key_id=None):
    payload = {
        "name": name,
        "path_name": path_name,
        "position": position,
        "content_view_id": cv["id"],
        "distro": "ubuntu",
        "release": "jammy",
        "publish_prefix": publish_prefix,
        "allow_unsigned": allow_unsigned,
    }
    if gpg_key_id is not None:
        payload["gpg_key_id"] = gpg_key_id
        payload["allow_unsigned"] = False
    return payload


def test_create_lifecycle_environment_with_allow_unsigned(client, operator_token):
    repo = _create_repo(client, operator_token, "le-repo1")
    cv = _create_cv(client, operator_token, repo, "le-cv1")
    r = client.post(
        "/lifecycle-environments", json=_env_payload(cv, "dev1", "path1", 0, "dev1"), headers=auth_headers(operator_token)
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "dev1"
    assert body["gpg_key_id"] is None


def test_create_lifecycle_environment_missing_gpg_and_unsigned_422(client, operator_token):
    repo = _create_repo(client, operator_token, "le-repo2")
    cv = _create_cv(client, operator_token, repo, "le-cv2")
    payload = _env_payload(cv, "dev2", "path2", 0, "dev2")
    payload["allow_unsigned"] = False
    r = client.post("/lifecycle-environments", json=payload, headers=auth_headers(operator_token))
    assert r.status_code == 422, r.text


def test_create_lifecycle_environment_with_gpg_key_id(client, operator_token):
    repo = _create_repo(client, operator_token, "le-repo3")
    cv = _create_cv(client, operator_token, repo, "le-cv3")
    payload = _env_payload(cv, "dev3", "path3", 0, "dev3", gpg_key_id="A" * 40)
    r = client.post("/lifecycle-environments", json=payload, headers=auth_headers(operator_token))
    assert r.status_code == 201, r.text
    assert r.json()["gpg_key_id"] == "A" * 40


def test_create_lifecycle_environment_as_viewer_forbidden(client, operator_token, viewer_token):
    repo = _create_repo(client, operator_token, "le-repo4")
    cv = _create_cv(client, operator_token, repo, "le-cv4")
    r = client.post(
        "/lifecycle-environments", json=_env_payload(cv, "dev4", "path4", 0, "dev4"), headers=auth_headers(viewer_token)
    )
    assert r.status_code == 403, r.text


def test_create_lifecycle_environment_content_view_not_found(client, operator_token):
    payload = {
        "name": "orphan",
        "path_name": "pathx",
        "position": 0,
        "content_view_id": "00000000-0000-0000-0000-000000000000",
        "distro": "ubuntu",
        "release": "jammy",
        "publish_prefix": "orphan",
        "allow_unsigned": True,
    }
    r = client.post("/lifecycle-environments", json=payload, headers=auth_headers(operator_token))
    assert r.status_code == 404, r.text


def test_list_lifecycle_environments_paginated_and_filtered(client, operator_token, viewer_token):
    repo = _create_repo(client, operator_token, "le-repo5")
    cv = _create_cv(client, operator_token, repo, "le-cv5")
    client.post(
        "/lifecycle-environments", json=_env_payload(cv, "dev5", "path5", 0, "dev5"), headers=auth_headers(operator_token)
    )
    client.post(
        "/lifecycle-environments",
        json=_env_payload(cv, "staging5", "path5", 1, "staging5"),
        headers=auth_headers(operator_token),
    )

    r = client.get("/lifecycle-environments", params={"path_name": "path5"}, headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    assert len(r.json()) == 2

    r2 = client.get(
        "/lifecycle-environments", params={"content_view_id": cv["id"], "limit": 1}, headers=auth_headers(viewer_token)
    )
    assert r2.status_code == 200, r2.text
    assert len(r2.json()) == 1


def test_get_gpg_key_404_when_not_configured(client, operator_token, viewer_token):
    repo = _create_repo(client, operator_token, "le-repo6")
    cv = _create_cv(client, operator_token, repo, "le-cv6")
    env = client.post(
        "/lifecycle-environments", json=_env_payload(cv, "dev6", "path6", 0, "dev6"), headers=auth_headers(operator_token)
    ).json()

    r = client.get(f"/lifecycle-environments/{env['id']}/gpg-key", headers=auth_headers(viewer_token))
    assert r.status_code == 404, r.text


def test_get_gpg_key_environment_not_found(client, viewer_token):
    r = client.get(
        "/lifecycle-environments/00000000-0000-0000-0000-000000000000/gpg-key", headers=auth_headers(viewer_token)
    )
    assert r.status_code == 404, r.text


def test_promote_environment_publishes_and_sets_current_version(client, operator_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "le-repo7")
    cv = _create_cv(client, operator_token, repo, "le-cv7")
    env = client.post(
        "/lifecycle-environments", json=_env_payload(cv, "dev7", "path7", 0, "dev7"), headers=auth_headers(operator_token)
    ).json()

    r = client.post(f"/lifecycle-environments/{env['id']}/promote", json={}, headers=auth_headers(operator_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["current_version_id"] is not None
    assert body["publish_prefix"] == "dev7"
    mock_aptly.publish_snapshot.assert_called_once()


def test_promote_environment_as_viewer_forbidden(client, operator_token, viewer_token):
    repo = _create_repo(client, operator_token, "le-repo8")
    cv = _create_cv(client, operator_token, repo, "le-cv8")
    env = client.post(
        "/lifecycle-environments", json=_env_payload(cv, "dev8", "path8", 0, "dev8"), headers=auth_headers(operator_token)
    ).json()

    r = client.post(f"/lifecycle-environments/{env['id']}/promote", json={}, headers=auth_headers(viewer_token))
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
    repo = _create_repo(client, operator_token, "le-repo9")
    cv = _create_cv(client, operator_token, repo, "le-cv9")
    dev = client.post(
        "/lifecycle-environments", json=_env_payload(cv, "dev9", "path9", 0, "dev9"), headers=auth_headers(operator_token)
    ).json()
    staging = client.post(
        "/lifecycle-environments",
        json=_env_payload(cv, "staging9", "path9", 1, "staging9"),
        headers=auth_headers(operator_token),
    ).json()

    # Cut a version via dev's promote first.
    dev_promote = client.post(
        f"/lifecycle-environments/{dev['id']}/promote", json={}, headers=auth_headers(operator_token)
    )
    assert dev_promote.status_code == 200, dev_promote.text
    version_id = dev_promote.json()["current_version_id"]

    # Now cut a second version (change package content) without promoting
    # dev to it — staging should be rejected for jumping ahead of dev.
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.19.0-1", "Architecture": "amd64"}
    ]
    r = client.post(
        f"/lifecycle-environments/{staging['id']}/promote",
        json={},
        headers=auth_headers(operator_token),
    )
    # do_publish inside promote will cut version 2 for staging's attempt,
    # but path-order check compares against dev's current (still v1) —
    # since staging has no version specified, it publishes-if-needed then
    # tries to use the newly cut v2, which dev hasn't reached yet.
    assert r.status_code == 409, r.text

    # Promoting staging explicitly to the version dev already has succeeds.
    r2 = client.post(
        f"/lifecycle-environments/{staging['id']}/promote",
        json={"content_view_version_id": version_id},
        headers=auth_headers(operator_token),
    )
    assert r2.status_code == 200, r2.text


def test_promote_environment_aptly_unreachable_returns_502(db_session, mock_aptly, mock_aptly_unreachable):
    from tests.conftest import TestClient

    from app.aptly_client import get_aptly_client
    from app.main import app
    from tests.conftest import Role, _token_for

    app.dependency_overrides[get_aptly_client] = lambda: mock_aptly
    try:
        with TestClient(app) as c:
            token = _token_for(c, db_session, Role.operator)
            repo = _create_repo(c, token, "le-repo10")
            cv = _create_cv(c, token, repo, "le-cv10")
            env = c.post(
                "/lifecycle-environments",
                json=_env_payload(cv, "dev10", "path10", 0, "dev10"),
                headers=auth_headers(token),
            ).json()
    finally:
        app.dependency_overrides.clear()

    app.dependency_overrides[get_aptly_client] = lambda: mock_aptly_unreachable
    try:
        with TestClient(app) as c:
            r = c.post(f"/lifecycle-environments/{env['id']}/promote", json={}, headers=auth_headers(token))
            assert r.status_code == 502, r.text
    finally:
        app.dependency_overrides.clear()


def test_rollback_environment_requires_previously_live_version(client, operator_token, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.18.0-6", "Architecture": "amd64"}
    ]
    mock_aptly.publish_exists.return_value = False
    repo = _create_repo(client, operator_token, "le-repo11")
    cv = _create_cv(client, operator_token, repo, "le-cv11")
    env = client.post(
        "/lifecycle-environments", json=_env_payload(cv, "dev11", "path11", 0, "dev11"), headers=auth_headers(operator_token)
    ).json()

    v1 = client.post(
        f"/lifecycle-environments/{env['id']}/promote", json={}, headers=auth_headers(operator_token)
    ).json()["current_version_id"]

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
    repo = _create_repo(client, operator_token, "le-repo12")
    cv = _create_cv(client, operator_token, repo, "le-cv12")
    env = client.post(
        "/lifecycle-environments", json=_env_payload(cv, "dev12", "path12", 0, "dev12"), headers=auth_headers(operator_token)
    ).json()

    client.post(f"/lifecycle-environments/{env['id']}/promote", json={}, headers=auth_headers(operator_token))

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
    repo = _create_repo(client, operator_token, "le-repo13")
    cv = _create_cv(client, operator_token, repo, "le-cv13")
    env = client.post(
        "/lifecycle-environments", json=_env_payload(cv, "dev13", "path13", 0, "dev13"), headers=auth_headers(operator_token)
    ).json()
    v1 = client.post(
        f"/lifecycle-environments/{env['id']}/promote", json={}, headers=auth_headers(operator_token)
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
