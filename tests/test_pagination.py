"""Cross-cutting pagination tests: confirm limit/offset actually bound and
page through results (not just accepted as no-op query params) across a
sample of the newly-paginated endpoints. Seeds rows directly via db_session
for speed/determinism rather than driving everything through the API.
"""


import pytest

from tests._rate_limit_helper import reset_login_rate_limit
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    reset_login_rate_limit()
    yield


def test_servers_pagination_bounds_and_pages(client, operator_token, viewer_token, db_session):
    from app.models import ContentView, LifecycleEnvironment, Server

    cv = ContentView(name="pg-cv")
    db_session.add(cv)
    db_session.flush()
    env = LifecycleEnvironment(
        name="pg-env",
        path_name="pg-path",
        position=0,
        content_view_id=cv.id,
        release="jammy",
        publish_prefix="pg-prefix",
        gpg_key_id=None,
    )
    db_session.add(env)
    db_session.flush()

    hostnames = [f"pg-host-{i}.example.com" for i in range(7)]
    for i, hostname in enumerate(hostnames):
        db_session.add(
            Server(
                hostname=hostname,
                ip_address=f"10.0.0.{i+1}",
                ssh_user="ubuntu",
                environment_id=env.id,
            )
        )
    db_session.commit()

    r_all = client.get("/servers", params={"limit": 100, "offset": 0}, headers=auth_headers(viewer_token))
    assert r_all.status_code == 200, r_all.text
    assert len(r_all.json()) == 7

    r_page1 = client.get("/servers", params={"limit": 3, "offset": 0}, headers=auth_headers(viewer_token))
    assert r_page1.status_code == 200, r_page1.text
    page1 = r_page1.json()
    assert len(page1) == 3

    r_page2 = client.get("/servers", params={"limit": 3, "offset": 3}, headers=auth_headers(viewer_token))
    assert r_page2.status_code == 200, r_page2.text
    page2 = r_page2.json()
    assert len(page2) == 3

    r_page3 = client.get("/servers", params={"limit": 3, "offset": 6}, headers=auth_headers(viewer_token))
    assert r_page3.status_code == 200, r_page3.text
    page3 = r_page3.json()
    assert len(page3) == 1

    # Different offsets must return different rows, not the same page again.
    page1_ids = {s["id"] for s in page1}
    page2_ids = {s["id"] for s in page2}
    page3_ids = {s["id"] for s in page3}
    assert page1_ids.isdisjoint(page2_ids)
    assert page2_ids.isdisjoint(page3_ids)
    assert page1_ids.isdisjoint(page3_ids)
    assert page1_ids | page2_ids | page3_ids <= {s["id"] for s in r_all.json()}


def test_jobs_pagination_bounds_and_pages(client, operator_token, admin_token, db_session):
    from app.models import ContentView, Job, JobStatus, JobTargetType, JobType, LifecycleEnvironment, Server

    cv = ContentView(name="pgjobs-cv")
    db_session.add(cv)
    db_session.flush()
    env = LifecycleEnvironment(
        name="pgjobs-env",
        path_name="pgjobs-path",
        position=0,
        content_view_id=cv.id,
        release="jammy",
        publish_prefix="pgjobs-prefix",
        gpg_key_id=None,
    )
    db_session.add(env)
    db_session.flush()
    server = Server(hostname="pgjobs-host.example.com", ip_address="10.0.1.1", ssh_user="ubuntu", environment_id=env.id)
    db_session.add(server)
    db_session.flush()

    for _ in range(6):
        db_session.add(
            Job(
                job_type=JobType.gather_facts,
                status=JobStatus.success,
                target_type=JobTargetType.server,
                server_id=server.id,
            )
        )
    db_session.commit()

    r_all = client.get("/jobs", params={"limit": 100, "offset": 0}, headers=auth_headers(admin_token))
    assert r_all.status_code == 200, r_all.text
    total = len(r_all.json())
    assert total >= 6

    r_page1 = client.get("/jobs", params={"limit": 2, "offset": 0}, headers=auth_headers(admin_token))
    assert r_page1.status_code == 200, r_page1.text
    assert len(r_page1.json()) == 2

    r_page2 = client.get("/jobs", params={"limit": 2, "offset": 2}, headers=auth_headers(admin_token))
    assert r_page2.status_code == 200, r_page2.text
    assert len(r_page2.json()) == 2

    page1_ids = {j["id"] for j in r_page1.json()}
    page2_ids = {j["id"] for j in r_page2.json()}
    assert page1_ids.isdisjoint(page2_ids)


def test_audit_logs_pagination_bounds_and_pages(client, admin_token, db_session):
    from app.models import AuditAction, AuditLog

    for i in range(6):
        db_session.add(
            AuditLog(
                action=AuditAction.create_repository,
                resource_type="repository",
                resource_id=f"pg-audit-repo-{i}",
            )
        )
    db_session.commit()

    r_all = client.get(
        "/audit-logs", params={"action": "create_repository", "limit": 100, "offset": 0}, headers=auth_headers(admin_token)
    )
    assert r_all.status_code == 200, r_all.text
    assert len(r_all.json()) == 6

    r_page1 = client.get(
        "/audit-logs", params={"action": "create_repository", "limit": 2, "offset": 0}, headers=auth_headers(admin_token)
    )
    assert r_page1.status_code == 200, r_page1.text
    assert len(r_page1.json()) == 2

    r_page2 = client.get(
        "/audit-logs", params={"action": "create_repository", "limit": 2, "offset": 2}, headers=auth_headers(admin_token)
    )
    assert r_page2.status_code == 200, r_page2.text
    assert len(r_page2.json()) == 2

    r_page3 = client.get(
        "/audit-logs", params={"action": "create_repository", "limit": 2, "offset": 4}, headers=auth_headers(admin_token)
    )
    assert r_page3.status_code == 200, r_page3.text
    assert len(r_page3.json()) == 2

    ids1 = {r["id"] for r in r_page1.json()}
    ids2 = {r["id"] for r in r_page2.json()}
    ids3 = {r["id"] for r in r_page3.json()}
    assert ids1.isdisjoint(ids2)
    assert ids2.isdisjoint(ids3)
    assert ids1.isdisjoint(ids3)


def test_repositories_pagination_bounds_and_pages(client, operator_token, viewer_token):
    for i in range(5):
        r = client.post(
            "/repositories",
            json={
                "name": f"pg-repo-{i}",
                "archive_url": "http://archive.ubuntu.com/ubuntu",
                "distribution": "jammy",
                "components": ["main"],
                "architectures": ["amd64"],
            },
            headers=auth_headers(operator_token),
        )
        assert r.status_code == 201, r.text

    r_page1 = client.get("/repositories", params={"limit": 2, "offset": 0}, headers=auth_headers(viewer_token))
    assert r_page1.status_code == 200, r_page1.text
    page1 = r_page1.json()
    assert len(page1) == 2

    r_page2 = client.get("/repositories", params={"limit": 2, "offset": 2}, headers=auth_headers(viewer_token))
    assert r_page2.status_code == 200, r_page2.text
    page2 = r_page2.json()
    assert len(page2) == 2

    page1_names = {r["name"] for r in page1}
    page2_names = {r["name"] for r in page2}
    assert page1_names.isdisjoint(page2_names)
