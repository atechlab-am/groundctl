# Metrics

`GET /metrics` exposes Prometheus text-exposition format, unauthenticated
(matching Prometheus's own scrape-endpoint convention — metrics aren't
secrets, and requiring auth would need Prometheus itself to carry a
token, an unusual scrape-config burden).

## What's exposed

| Metric | Type | Labels | What it tells you |
|---|---|---|---|
| `groundctl_http_requests_total` | Counter | `method`, `path`, `status` | Request volume and error rate by endpoint |
| `groundctl_http_request_duration_seconds` | Histogram | `method`, `path` | Latency by endpoint |
| `groundctl_jobs_total` | Counter | `job_type`, `status` | Job outcomes — `success` vs `failed` by type, over time |
| `groundctl_active_servers` | Gauge | — | Servers with `status != unreachable`, computed at scrape time |
| `groundctl_unreachable_servers` | Gauge | — | Servers with `status == unreachable`, computed at scrape time |
| `groundctl_aptly_disk_usage_bytes` | Gauge | — | Bytes used on `/var/lib/groundctl/aptly`, updated by the weekly `scheduled_aptly_maintenance` task (not live at scrape time — see below) |
| `groundctl_aptly_disk_usage_percent` | Gauge | — | Same, as a percentage |

`path` labels use the route template (`/api/servers/{server_id}`), not the
resolved URL — so per-server request volume doesn't fragment into one
label series per UUID.

## Why disk usage is cached, not live

Every other gauge is computed fresh on every `/metrics` scrape (cheap
`COUNT(*)` queries). Disk usage is different — `scheduled_aptly_maintenance`
(weekly, `app/celery_app.py`) sets these gauges as a side effect of its own
disk check; scraping doesn't trigger a fresh `shutil.disk_usage()` call.
Between scheduled runs, these two gauges reflect the last check, not
real-time usage — acceptable for something that doesn't change fast
enough to need per-scrape freshness, but worth knowing if you're
debugging "why hasn't this gauge moved."

## Example PromQL

```promql
# Job failure rate over the last hour, by type
rate(groundctl_jobs_total{status="failed"}[1h])

# p95 request latency for the promote endpoint
histogram_quantile(0.95, rate(groundctl_http_request_duration_seconds_bucket{path="/lifecycle-environments/{environment_id}/promote"}[5m]))

# Alert when the aptly data volume is over 90%
groundctl_aptly_disk_usage_percent > 90
```

## What's NOT exposed

aptly's own metrics (if its version exposes any) are not proxied through
`/metrics` — matches CLAUDE.md's rule that no endpoint here forwards
arbitrary aptly calls. Operators wanting aptly-level metrics scrape aptly
directly; since aptly is loopback-only (`127.0.0.1:8090`, unauthenticated),
this requires the operator to explicitly decide to expose it, not a
default this project makes for you.
