"""Shared Prometheus registry/metric objects. Split out from app/main.py so
app/tasks.py (Celery, imported by app/routers/jobs.py, imported by
app/main.py) can increment job metrics without a circular import.
"""

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

registry = CollectorRegistry()

REQUESTS_TOTAL = Counter(
    "groundctl_http_requests_total", "Total HTTP requests", ["method", "path", "status"], registry=registry
)
REQUEST_DURATION = Histogram(
    "groundctl_http_request_duration_seconds", "HTTP request duration", ["method", "path"], registry=registry
)
JOBS_TOTAL = Counter(
    "groundctl_jobs_total", "Total jobs by type and final status", ["job_type", "status"], registry=registry
)
ACTIVE_SERVERS = Gauge("groundctl_active_servers", "Servers with status != unreachable", registry=registry)
UNREACHABLE_SERVERS = Gauge("groundctl_unreachable_servers", "Servers with status=unreachable", registry=registry)
APTLY_DISK_USAGE_BYTES = Gauge("groundctl_aptly_disk_usage_bytes", "Bytes used on the aptly data volume", registry=registry)
APTLY_DISK_USAGE_PERCENT = Gauge(
    "groundctl_aptly_disk_usage_percent", "Percent used on the aptly data volume", registry=registry
)
# ROADMAP.md Phase 9 — fleet-level Beacon health, computed live at scrape
# time in app/main.py's /metrics endpoint, same pattern as
# ACTIVE_SERVERS/UNREACHABLE_SERVERS above.
BEACON_ENABLED_SERVERS = Gauge(
    "groundctl_beacon_enabled_servers", "Servers with at least one non-revoked BeaconToken", registry=registry
)
BEACON_CHECKED_IN_RECENTLY = Gauge(
    "groundctl_beacon_checked_in_recently",
    "Beacon-enabled servers whose last checkin was within 2x the checkin interval (10 min)",
    registry=registry,
)
BEACON_PENDING_RECONCILIATION = Gauge(
    "groundctl_beacon_pending_reconciliation",
    "Beacon-enabled servers where config_serial != applied_config_serial",
    registry=registry,
)
