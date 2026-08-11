from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_role
from app.database import get_db
from app.models import ComplianceCheckLog, Job, Role, User
from app.schemas import ComplianceTrendPoint, JobTrendPoint

router = APIRouter()

_MAX_DAYS = 90


def _day_buckets(days: int) -> list[date]:
    today = datetime.now(timezone.utc).date()
    return [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]


@router.get("/jobs", response_model=list[JobTrendPoint])
def get_job_trends(
    days: int = Query(default=14, ge=1, le=_MAX_DAYS),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    """Daily job counts by terminal status, oldest first. Computed from Job
    rows directly (created_at, status) — no separate time-series storage;
    Job history already is the time series. Bucketed in Python, not SQL
    date_trunc, to stay portable and match this table's modest expected row
    count (jobs are triggered by human/scheduled action, not high-frequency
    telemetry).
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    jobs = list(db.execute(select(Job.created_at, Job.status).where(Job.created_at >= since)).all())

    counts: dict[date, dict[str, int]] = {
        day: {"success": 0, "failed": 0, "running": 0, "pending": 0} for day in _day_buckets(days)
    }
    for created_at, status_ in jobs:
        day = created_at.date()
        if day in counts:
            counts[day][status_.value] += 1

    return [
        JobTrendPoint(
            date=day,
            success=counts[day]["success"],
            failed=counts[day]["failed"],
            running=counts[day]["running"],
            pending=counts[day]["pending"],
        )
        for day in sorted(counts)
    ]


@router.get("/compliance", response_model=list[ComplianceTrendPoint])
def get_compliance_trends(
    days: int = Query(default=14, ge=1, le=_MAX_DAYS),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    """Daily outdated-package counts, summed across every ComplianceCheckLog
    row (any server, on-demand or the weekly scheduled scan) whose
    checked_at falls in the window. drift is a plain JSON column (not
    JSONB), so counting per-status entries happens in Python rather than a
    JSON-path SQL query — ComplianceCheckLog rows are bounded (one per
    check, not per package), so this stays cheap at the 90-day cap.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    logs = list(
        db.execute(
            select(ComplianceCheckLog.checked_at, ComplianceCheckLog.drift).where(
                ComplianceCheckLog.checked_at >= since
            )
        ).all()
    )

    counts: dict[date, dict[str, int]] = {
        day: {"outdated": 0, "up_to_date": 0, "checks": 0} for day in _day_buckets(days)
    }
    for checked_at, drift in logs:
        day = checked_at.date()
        if day not in counts:
            continue
        counts[day]["checks"] += 1
        for entry in drift:
            entry_status = entry.get("status")
            if entry_status == "outdated":
                counts[day]["outdated"] += 1
            elif entry_status == "up_to_date":
                counts[day]["up_to_date"] += 1

    return [
        ComplianceTrendPoint(
            date=day,
            outdated=counts[day]["outdated"],
            up_to_date=counts[day]["up_to_date"],
            checks=counts[day]["checks"],
        )
        for day in sorted(counts)
    ]
