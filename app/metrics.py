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
