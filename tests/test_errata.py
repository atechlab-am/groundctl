import shutil
from datetime import datetime, timedelta, timezone

import pytest

from tests._rate_limit_helper import reset_login_rate_limit
from tests.conftest import auth_headers

# GET /errata/{id}/affected-servers calls app/version_compare.py's
# dpkg_compare() to decide which servers are outdated relative to a fix,
# which shells out to the real `dpkg` binary (Debian/Ubuntu-only — see
# CLAUDE.md's "Version comparison" rule). This test host is macOS and has
# no dpkg, so tests that drive that comparison are skipped here rather than
# faked with a reimplemented comparator. Same pattern as
# tests/test_version_compare.py and tests/test_compliance.py. Runs for real
# on Debian/Ubuntu CI.
requires_dpkg = pytest.mark.skipif(
    shutil.which("dpkg") is None,
    reason="dpkg binary not available on this host (macOS) — affected-servers logic shells out to real dpkg",
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


def _seed_erratum(db_session, advisory_id, cves=None, source="usn", published_at=None, packages=None):
    from app.models import Erratum, ErratumPackage, ErratumSource

    erratum = Erratum(
        advisory_id=advisory_id,
        source=ErratumSource(source),
        title=f"{advisory_id} title",
        cves=cves or [],
        severity=None,
        published_at=published_at or datetime.now(timezone.utc),
    )
    db_session.add(erratum)
    db_session.flush()

    for pkg in packages or []:
        db_session.add(
            ErratumPackage(
                erratum_id=erratum.id,
                release=pkg.get("release", "jammy"),
                package_name=pkg["package_name"],
                fixed_version=pkg["fixed_version"],
            )
        )
    db_session.commit()
    db_session.refresh(erratum)
    return erratum


def _seed_compliance_record(db_session, server_id, installed_packages):
    from app.models import ComplianceRecord

    record = ComplianceRecord(server_id=server_id, installed_packages=installed_packages)
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)
    return record


# ---------------------------------------------------------------------------
# GET /errata
# ---------------------------------------------------------------------------


def test_list_errata_basic(client, operator_token, viewer_token, db_session):
    _seed_erratum(db_session, "USN-1000-1")
    _seed_erratum(db_session, "USN-1001-1")

    r = client.get("/errata", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    advisory_ids = {e["advisory_id"] for e in r.json()}
    assert {"USN-1000-1", "USN-1001-1"} <= advisory_ids


def test_list_errata_filter_by_source(client, viewer_token, db_session):
    _seed_erratum(db_session, "USN-2000-1", source="usn")
    _seed_erratum(db_session, "DSA-2000-1", source="dsa")

    r = client.get("/errata", params={"source": "dsa"}, headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert all(e["source"] == "dsa" for e in body)
    assert any(e["advisory_id"] == "DSA-2000-1" for e in body)


def test_list_errata_filter_by_published_since(client, viewer_token, db_session):
    old = datetime.now(timezone.utc) - timedelta(days=30)
    new = datetime.now(timezone.utc) - timedelta(days=1)
    _seed_erratum(db_session, "USN-3000-1", published_at=old)
    _seed_erratum(db_session, "USN-3001-1", published_at=new)

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    r = client.get(
        "/errata", params={"published_since": cutoff.isoformat()}, headers=auth_headers(viewer_token)
    )
    assert r.status_code == 200, r.text
    advisory_ids = {e["advisory_id"] for e in r.json()}
    assert "USN-3001-1" in advisory_ids
    assert "USN-3000-1" not in advisory_ids


def test_list_errata_limit_offset_without_cve(client, viewer_token, db_session):
    for i in range(5):
        _seed_erratum(db_session, f"USN-4{i:03d}-1")

    r = client.get("/errata", params={"limit": 2, "offset": 0}, headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    assert len(r.json()) == 2


def test_list_errata_cve_filter_applies_limit_offset_after_python_filtering(client, viewer_token, db_session):
    # Router applies the cve filter in Python against the stored array, then
    # slices [offset:offset+limit] on the already-filtered list — NOT a SQL
    # LIMIT/OFFSET applied before the cve match. Seed a mix of matching and
    # non-matching errata, interleaved by published_at ordering, and confirm
    # the returned page only ever contains cve-matching rows, with correct
    # pagination over the filtered set (not the unfiltered one).
    now = datetime.now(timezone.utc)
    # published_at descending is the sort order the router uses.
    _seed_erratum(db_session, "USN-5000-1", cves=["CVE-2024-0001"], published_at=now - timedelta(days=1))
    _seed_erratum(db_session, "USN-5001-1", cves=["CVE-9999-9999"], published_at=now - timedelta(days=2))
    _seed_erratum(db_session, "USN-5002-1", cves=["CVE-2024-0001"], published_at=now - timedelta(days=3))
    _seed_erratum(db_session, "USN-5003-1", cves=["CVE-2024-0001"], published_at=now - timedelta(days=4))

    r = client.get(
        "/errata", params={"cve": "CVE-2024-0001", "limit": 2, "offset": 0}, headers=auth_headers(viewer_token)
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 2
    assert all("CVE-2024-0001" in e["cves"] for e in body)
    assert [e["advisory_id"] for e in body] == ["USN-5000-1", "USN-5002-1"]

    r2 = client.get(
        "/errata", params={"cve": "CVE-2024-0001", "limit": 2, "offset": 2}, headers=auth_headers(viewer_token)
    )
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert len(body2) == 1
    assert body2[0]["advisory_id"] == "USN-5003-1"


def test_list_errata_as_viewer_allowed(client, viewer_token, db_session):
    _seed_erratum(db_session, "USN-6000-1")
    r = client.get("/errata", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# GET /errata/{advisory_id}
# ---------------------------------------------------------------------------


def test_get_erratum_found(client, viewer_token, db_session):
    _seed_erratum(
        db_session,
        "USN-7000-1",
        cves=["CVE-2024-1111"],
        packages=[{"package_name": "nginx", "fixed_version": "1.19.0-1"}],
    )

    r = client.get("/errata/USN-7000-1", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["advisory_id"] == "USN-7000-1"
    assert body["cves"] == ["CVE-2024-1111"]
    assert len(body["packages"]) == 1
    assert body["packages"][0]["package_name"] == "nginx"
    assert body["packages"][0]["fixed_version"] == "1.19.0-1"


def test_get_erratum_not_found(client, viewer_token):
    r = client.get("/errata/USN-DOES-NOT-EXIST", headers=auth_headers(viewer_token))
    assert r.status_code == 404, r.text


# ---------------------------------------------------------------------------
# GET /errata/{advisory_id}/affected-servers
# ---------------------------------------------------------------------------


@requires_dpkg
def test_affected_servers_finds_outdated_server(client, operator_token, viewer_token, db_session):
    repo = _create_repo(client, operator_token, "errata-repo1")
    cv = _create_cv(client, operator_token, repo, "errata-cv1")
    env = _create_env(client, operator_token, cv, "errata-env1", "errata-path1", 0, "errata-prefix1")
    server = _create_server(client, operator_token, env, "affected1.example.com")
    _seed_compliance_record(
        db_session, server["id"], [{"name": "nginx", "version": "1.18.0-6", "arch": "amd64"}]
    )
    _seed_erratum(
        db_session,
        "USN-8000-1",
        packages=[{"package_name": "nginx", "fixed_version": "1.19.0-1"}],
    )

    r = client.get("/errata/USN-8000-1/affected-servers", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["advisory_id"] == "USN-8000-1"
    assert len(body["affected"]) == 1
    assert body["affected"][0]["server_id"] == server["id"]
    assert body["affected"][0]["package_name"] == "nginx"
    assert body["affected"][0]["installed_version"] == "1.18.0-6"
    assert body["affected"][0]["fixed_version"] == "1.19.0-1"


@requires_dpkg
def test_affected_servers_excludes_fixed_server(client, operator_token, viewer_token, db_session):
    repo = _create_repo(client, operator_token, "errata-repo2")
    cv = _create_cv(client, operator_token, repo, "errata-cv2")
    env = _create_env(client, operator_token, cv, "errata-env2", "errata-path2", 0, "errata-prefix2")
    server = _create_server(client, operator_token, env, "fixed1.example.com")
    _seed_compliance_record(
        db_session, server["id"], [{"name": "nginx", "version": "1.19.0-1", "arch": "amd64"}]
    )
    _seed_erratum(
        db_session,
        "USN-8001-1",
        packages=[{"package_name": "nginx", "fixed_version": "1.19.0-1"}],
    )

    r = client.get("/errata/USN-8001-1/affected-servers", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    assert r.json()["affected"] == []


def test_affected_servers_no_compliance_data_excluded(client, operator_token, viewer_token, db_session):
    repo = _create_repo(client, operator_token, "errata-repo3")
    cv = _create_cv(client, operator_token, repo, "errata-cv3")
    env = _create_env(client, operator_token, cv, "errata-env3", "errata-path3", 0, "errata-prefix3")
    _create_server(client, operator_token, env, "nodata1.example.com")
    _seed_erratum(
        db_session,
        "USN-8002-1",
        packages=[{"package_name": "nginx", "fixed_version": "1.19.0-1"}],
    )

    r = client.get("/errata/USN-8002-1/affected-servers", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    assert r.json()["affected"] == []


def test_affected_servers_erratum_with_no_packages(client, operator_token, viewer_token, db_session):
    _seed_erratum(db_session, "USN-8003-1", packages=[])

    r = client.get("/errata/USN-8003-1/affected-servers", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    assert r.json()["affected"] == []


def test_affected_servers_erratum_not_found(client, viewer_token):
    r = client.get("/errata/USN-NOPE/affected-servers", headers=auth_headers(viewer_token))
    assert r.status_code == 404, r.text


def test_affected_servers_as_viewer_allowed(client, viewer_token, db_session):
    _seed_erratum(db_session, "USN-8004-1", packages=[])
    r = client.get("/errata/USN-8004-1/affected-servers", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
