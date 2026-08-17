import shutil

import pytest

from tests._rate_limit_helper import reset_login_rate_limit
from tests.conftest import auth_headers

# app/compliance.py's drift/search logic calls app/version_compare.py's
# dpkg_compare(), which shells out to the real `dpkg` binary (Debian/
# Ubuntu-only — see CLAUDE.md's "Version comparison" rule: never compare
# Debian versions with string/</> comparison, always dpkg --compare-versions
# or apt_pkg.version_compare). This test host is macOS and has no dpkg, so
# any test that actually drives a version comparison is skipped here rather
# than faked with a reimplemented comparator. Same rationale/pattern as
# tests/test_version_compare.py. Runs for real on Debian/Ubuntu CI.
requires_dpkg = pytest.mark.skipif(
    shutil.which("dpkg") is None,
    reason="dpkg binary not available on this host (macOS) — compliance drift logic shells out to real dpkg",
)


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


def _library(client, operator_token):
    # Position 0 is always Library and never path-order-gated. A freshly
    # created environment with no prior_environment_id now lands at
    # position 1+ (chained after auto-seeded Library), so any env this
    # file wants to assign+promote directly must chain onto Library
    # explicitly. Seeds Library via a throwaway create if it doesn't
    # exist yet in this test's fresh DB.
    listed = client.get("/lifecycle-environments", headers=auth_headers(operator_token)).json()
    library = next((e for e in listed if e["name"] == "Library"), None)
    if library is not None:
        return library
    client.post("/lifecycle-environments", json={"name": "_seed"}, headers=auth_headers(operator_token))
    listed = client.get("/lifecycle-environments", headers=auth_headers(operator_token)).json()
    return next(e for e in listed if e["name"] == "Library")


def _create_env(client, operator_token, cv, name="dev", path_name="main", position=0, publish_prefix="dev"):
    # An environment is now pure path structure with NO content view of its
    # own (LifecycleEnvironmentCreate takes only name/description/
    # prior_environment_id) — content views are assigned to it afterward
    # via POST /{id}/content-views, which also performs that pair's first
    # promote in the same call. This helper chains the new environment
    # directly after Library (position 1, immediately assignable since
    # Library's position 0 is gate-free) then assigns+promotes the content
    # view's already-published version 1, so callers keep getting back a
    # fully linked, published environment exactly like before. No caller
    # in this file uses position>0, so further chaining isn't needed here.
    library = _library(client, operator_token)
    r = client.post(
        "/lifecycle-environments",
        json={"name": name, "prior_environment_id": library["id"]},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 201, r.text
    env = r.json()

    versions_r = client.get(f"/content-views/{cv['id']}/versions", headers=auth_headers(operator_token))
    version_id = versions_r.json()[0]["id"]
    assign_r = client.post(
        f"/lifecycle-environments/{env['id']}/content-views",
        json={"content_view_id": cv["id"], "content_view_version_id": version_id, "allow_unsigned": True},
        headers=auth_headers(operator_token),
    )
    assert assign_r.status_code == 201, assign_r.text

    return env


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


def _seed_full_chain(client, operator_token, suffix):
    repo = _create_repo(client, operator_token, f"repo-{suffix}")
    cv = _create_cv(client, operator_token, repo, f"cv-{suffix}")
    env = _create_env(client, operator_token, cv, f"env-{suffix}", f"path-{suffix}", 0, f"prefix-{suffix}")
    server = _create_server(client, operator_token, env, f"host-{suffix}.example.com")
    return repo, cv, env, server


def _seed_compliance_record(db_session, server_id, installed_packages):
    from app.models import ComplianceRecord

    record = ComplianceRecord(server_id=server_id, installed_packages=installed_packages)
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)
    return record


def _publish_env(client, operator_token, cv, mock_aptly, env):
    # Publishing the content view alone doesn't move the
    # EnvironmentContentView pair's current_version_id — must promote too,
    # via the nested per-content-view route now that promotion is scoped
    # per (environment, content view) pair rather than per environment.
    r = client.post(
        f"/lifecycle-environments/{env['id']}/content-views/{cv['id']}/promote",
        json={},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_check_compliance_no_data_yet_422(client, operator_token):
    _, _, _, server = _seed_full_chain(client, operator_token, "nodata")
    r = client.post(f"/compliance/servers/{server['id']}/check", headers=auth_headers(operator_token))
    assert r.status_code == 422, r.text


def test_check_compliance_server_not_found(client, operator_token):
    r = client.post(
        "/compliance/servers/00000000-0000-0000-0000-000000000000/check",
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 404, r.text


def test_check_compliance_environment_not_published_422(client, operator_token, db_session):
    # Deliberately NOT using _create_env — that helper now creates AND
    # assigns+promotes a content view (so other tests get a fully-linked,
    # published environment by default), but this test specifically needs
    # zero published EnvironmentContentView assignments. An environment is
    # pure path structure now (LifecycleEnvironmentCreate takes only
    # name/description/prior_environment_id) — no content view is required
    # at creation at all, so simply never assigning one reproduces the
    # "nothing published to check against" 422 directly.
    env_r = client.post(
        "/lifecycle-environments",
        json={"name": "env-unpub"},
        headers=auth_headers(operator_token),
    )
    assert env_r.status_code == 201, env_r.text
    env = env_r.json()
    server = _create_server(client, operator_token, env, "host-unpub.example.com")

    _seed_compliance_record(db_session, server["id"], [{"name": "nginx", "version": "1.18.0-6", "arch": "amd64"}])

    r = client.post(f"/compliance/servers/{server['id']}/check", headers=auth_headers(operator_token))
    assert r.status_code == 422, r.text


@requires_dpkg
def test_check_compliance_reports_outdated_and_up_to_date(client, operator_token, db_session, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.19.0-1", "Architecture": "amd64"}
    ]
    repo, cv, env, server = _seed_full_chain(client, operator_token, "drift")
    _publish_env(client, operator_token, cv, mock_aptly, env)

    mock_aptly.get_snapshot_packages.return_value = [
        {"Package": "nginx", "Version": "1.19.0-1", "Architecture": "amd64"}
    ]
    _seed_compliance_record(
        db_session,
        server["id"],
        [
            {"name": "nginx", "version": "1.18.0-6", "arch": "amd64"},
            {"name": "curl", "version": "7.81.0-1", "arch": "amd64"},
        ],
    )

    r = client.post(f"/compliance/servers/{server['id']}/check", headers=auth_headers(operator_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["server_id"] == server["id"]
    drift_by_name = {d["name"]: d for d in body["drift"]}
    assert drift_by_name["nginx"]["status"] == "outdated"
    assert drift_by_name["nginx"]["available_version"] == "1.19.0-1"
    assert drift_by_name["curl"]["status"] == "not_in_environment"


@requires_dpkg
def test_check_compliance_up_to_date_package(client, operator_token, db_session, mock_aptly):
    mock_aptly.get_mirror_packages.return_value = [
        {"Package": "nginx", "Version": "1.19.0-1", "Architecture": "amd64"}
    ]
    repo, cv, env, server = _seed_full_chain(client, operator_token, "uptodate")
    _publish_env(client, operator_token, cv, mock_aptly, env)

    mock_aptly.get_snapshot_packages.return_value = [
        {"Package": "nginx", "Version": "1.19.0-1", "Architecture": "amd64"}
    ]
    _seed_compliance_record(
        db_session, server["id"], [{"name": "nginx", "version": "1.19.0-1", "arch": "amd64"}]
    )

    r = client.post(f"/compliance/servers/{server['id']}/check", headers=auth_headers(operator_token))
    assert r.status_code == 200, r.text
    drift = r.json()["drift"]
    assert len(drift) == 1
    assert drift[0]["status"] == "up_to_date"


def test_check_compliance_as_viewer_forbidden(client, operator_token, viewer_token):
    _, _, _, server = _seed_full_chain(client, operator_token, "rbac")
    r = client.post(f"/compliance/servers/{server['id']}/check", headers=auth_headers(viewer_token))
    assert r.status_code == 403, r.text


def test_check_compliance_aptly_unreachable_returns_502(db_session, mock_aptly, mock_aptly_unreachable):
    from app.aptly_client import get_aptly_client
    from app.main import app
    from tests.conftest import Role, TestClient, _token_for

    app.dependency_overrides[get_aptly_client] = lambda: mock_aptly
    try:
        with TestClient(app) as c:
            token = _token_for(c, db_session, Role.operator)
            mock_aptly.get_mirror_packages.return_value = [
                {"Package": "nginx", "Version": "1.19.0-1", "Architecture": "amd64"}
            ]
            repo, cv, env, server = _seed_full_chain(c, token, "unreachable")
            _publish_env(c, token, cv, mock_aptly, env)
            _seed_compliance_record(
                db_session, server["id"], [{"name": "nginx", "version": "1.18.0-6", "arch": "amd64"}]
            )
    finally:
        app.dependency_overrides.clear()

    app.dependency_overrides[get_aptly_client] = lambda: mock_aptly_unreachable
    try:
        with TestClient(app) as c:
            r = c.post(f"/compliance/servers/{server['id']}/check", headers=auth_headers(token))
            assert r.status_code == 502, r.text
    finally:
        app.dependency_overrides.clear()


def test_search_packages_basic_match(client, operator_token, db_session):
    _, _, _, server = _seed_full_chain(client, operator_token, "search1")
    _seed_compliance_record(
        db_session, server["id"], [{"name": "openssl", "version": "3.0.2-0ubuntu1", "arch": "amd64"}]
    )

    r = client.get(
        "/compliance/packages/search",
        params={"package_name": "openssl"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["package_name"] == "openssl"
    assert len(body["matches"]) == 1
    assert body["matches"][0]["server_id"] == server["id"]
    assert body["matches"][0]["installed_version"] == "3.0.2-0ubuntu1"


@requires_dpkg
def test_search_packages_with_version_comparator(client, operator_token, db_session):
    _, _, _, server_old = _seed_full_chain(client, operator_token, "search-old")
    _, _, _, server_new = _seed_full_chain(client, operator_token, "search-new")
    _seed_compliance_record(
        db_session, server_old["id"], [{"name": "openssl", "version": "3.0.1-0ubuntu1", "arch": "amd64"}]
    )
    _seed_compliance_record(
        db_session, server_new["id"], [{"name": "openssl", "version": "3.0.5-0ubuntu1", "arch": "amd64"}]
    )

    r = client.get(
        "/compliance/packages/search",
        params={"package_name": "openssl", "operator": "lt", "compare_version": "3.0.2-0ubuntu1"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 200, r.text
    matches = r.json()["matches"]
    assert len(matches) == 1
    assert matches[0]["server_id"] == server_old["id"]


def test_search_packages_no_matches(client, operator_token, db_session):
    _, _, _, server = _seed_full_chain(client, operator_token, "search-none")
    _seed_compliance_record(
        db_session, server["id"], [{"name": "curl", "version": "7.81.0-1", "arch": "amd64"}]
    )

    r = client.get(
        "/compliance/packages/search",
        params={"package_name": "openssl"},
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["matches"] == []


def test_search_packages_viewer_allowed(client, operator_token, viewer_token, db_session):
    _, _, _, server = _seed_full_chain(client, operator_token, "search-viewer")
    _seed_compliance_record(
        db_session, server["id"], [{"name": "curl", "version": "7.81.0-1", "arch": "amd64"}]
    )

    r = client.get(
        "/compliance/packages/search",
        params={"package_name": "curl"},
        headers=auth_headers(viewer_token),
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["matches"]) == 1
