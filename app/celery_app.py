from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "groundctl",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # Tasks return small confirmation values only — log_output always lives
    # in Postgres via the Job row, never in Celery's result backend.
    result_expires=3600,
    beat_schedule={
        "sync-all-repositories-nightly": {
            "task": "app.tasks.scheduled_sync_all_repositories",
            "schedule": crontab(hour=3, minute=0),
        },
        "compliance-scan-weekly": {
            "task": "app.tasks.scheduled_compliance_scan",
            "schedule": crontab(day_of_week=0, hour=4, minute=0),
        },
        # Errata publish more frequently than repository content changes —
        # daily, not nightly-is-plenty like repository sync. Staggered by
        # 30 minutes so both don't hit external services simultaneously.
        "ingest-usn-errata-daily": {
            "task": "app.tasks.ingest_usn_errata",
            "schedule": crontab(hour=2, minute=0),
        },
        "ingest-dsa-errata-daily": {
            "task": "app.tasks.ingest_dsa_errata",
            "schedule": crontab(hour=2, minute=30),
        },
        "flag-stale-servers-daily": {
            "task": "app.tasks.scheduled_flag_stale_servers",
            "schedule": crontab(hour=5, minute=0),
        },
        # Hourly, not nightly — relay content should reach sites reasonably
        # promptly after a promotion (sync is eventually-consistent, not
        # promotion-triggered; see docs/limitations.md). rsync only
        # transfers changed content, so hourly is cheap when nothing changed.
        "sync-relays-hourly": {
            "task": "app.tasks.scheduled_sync_relays",
            "schedule": crontab(minute=15),
        },
        "flag-stale-relays-daily": {
            "task": "app.tasks.scheduled_flag_stale_relays",
            "schedule": crontab(hour=5, minute=30),
        },
        "purge-audit-logs-daily": {
            "task": "app.tasks.scheduled_purge_audit_logs",
            "schedule": crontab(hour=6, minute=0),
        },
        # Weekly, not daily — aptly db cleanup can be a heavier operation
        # (scans the whole pool) and disk usage doesn't change fast enough
        # to need daily checks. Sunday, after every other daily task's
        # 02:00-06:00 window.
        "aptly-maintenance-weekly": {
            "task": "app.tasks.scheduled_aptly_maintenance",
            "schedule": crontab(day_of_week=0, hour=6, minute=30),
        },
    },
)
