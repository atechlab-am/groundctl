from datetime import datetime, timedelta, timezone

import pytest

from app.models import ComplianceCheckLog, Job, JobStatus, JobTargetType, JobType
from tests._rate_limit_helper import reset_login_rate_limit
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def _reset_login_rate_limit():
    reset_login_rate_limit()
    yield


def _make_job(db_session, status: JobStatus, created_at: datetime) -> Job:
    job = Job(
        job_type=JobType.gather_facts,
        target_type=JobTargetType.adhoc,
        status=status,
        created_at=created_at,
    )
    db_session.add(job)
    db_session.commit()
    return job


def test_job_trends_buckets_by_day_and_status(client, viewer_token, db_session):
    now = datetime.now(timezone.utc)
    _make_job(db_session, JobStatus.success, now)
    _make_job(db_session, JobStatus.success, now)
    _make_job(db_session, JobStatus.failed, now)
    _make_job(db_session, JobStatus.success, now - timedelta(days=2))

    r = client.get("/trends/jobs", params={"days": 7}, headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 7
    today = body[-1]
    assert today["success"] == 2
    assert today["failed"] == 1
    two_days_ago = body[-3]
    assert two_days_ago["success"] == 1


def test_job_trends_excludes_outside_window(client, viewer_token, db_session):
    now = datetime.now(timezone.utc)
    _make_job(db_session, JobStatus.success, now - timedelta(days=30))

    r = client.get("/trends/jobs", params={"days": 7}, headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    total = sum(p["success"] + p["failed"] + p["running"] + p["pending"] for p in r.json())
    assert total == 0


def test_job_trends_default_days(client, viewer_token):
    r = client.get("/trends/jobs", headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    assert len(r.json()) == 14


def test_job_trends_rejects_out_of_range_days(client, viewer_token):
    r = client.get("/trends/jobs", params={"days": 999}, headers=auth_headers(viewer_token))
    assert r.status_code == 422, r.text


def test_compliance_trends_counts_drift_statuses(client, operator_token, viewer_token, db_session):
    from tests.test_compliance import _create_cv, _create_env, _create_repo, _create_server

    repo = _create_repo(client, operator_token, "trend-repo")
    cv = _create_cv(client, operator_token, repo, "trend-cv")
    env = _create_env(client, operator_token, cv, name="trend-env", publish_prefix="trend-env")
    server = _create_server(client, operator_token, env, "trend-host.example.com")

    log = ComplianceCheckLog(
        server_id=server["id"],
        drift=[
            {"name": "pkg-a", "installed_version": "1", "available_version": "2", "status": "outdated"},
            {"name": "pkg-b", "installed_version": "1", "available_version": "1", "status": "up_to_date"},
            {"name": "pkg-c", "installed_version": "1", "available_version": "2", "status": "outdated"},
        ],
    )
    db_session.add(log)
    db_session.commit()

    r = client.get("/trends/compliance", params={"days": 7}, headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    today = r.json()[-1]
    assert today["outdated"] == 2
    assert today["up_to_date"] == 1
    assert today["checks"] == 1


def test_compliance_trends_empty_when_no_checks(client, viewer_token):
    r = client.get("/trends/compliance", params={"days": 7}, headers=auth_headers(viewer_token))
    assert r.status_code == 200, r.text
    assert all(p["checks"] == 0 for p in r.json())
