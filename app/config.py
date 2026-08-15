from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://changeme_user:changeme_password@changeme_host:5432/changeme_db"
    aptly_api_url: str = "http://changeme_aptly_host:8080"
    published_repo_base_url: str = "https://changeme_fleet_hostname:8080"
    # The FastAPI app's own externally-reachable URL — distinct from
    # published_repo_base_url (nginx serving the published repo tree).
    # bootstrap_client.yml fetches the environment's GPG key and (if using
    # the default self-signed cert) the TLS CA cert from here, over the
    # initial bootstrap SSH connection rather than over HTTPS itself —
    # avoids the chicken-and-egg problem of needing to already trust HTTPS
    # to fetch the thing that makes HTTPS trusted. See docs/https.md.
    groundctl_api_base_url: str = "https://changeme_fleet_hostname:8000"
    jwt_secret: str = "changeme_generate_a_real_secret"
    jwt_algorithm: str = "HS256"
    # Short-lived on purpose — POST /auth/refresh (backed by RefreshToken,
    # a separate DB-backed revocable credential) is how a session actually
    # stays alive. A 24h access token with no refresh mechanism meant a
    # disclosed token stayed valid for a full day with no way to revoke it;
    # 15 minutes bounds that exposure window sharply.
    jwt_expire_minutes: int = 15
    refresh_token_expire_days: int = 14
    # install.sh always writes this explicitly (see scripts/lib/app.sh's
    # write_groundctl_env). Default matches what a real install sets.
    ansible_private_key_path: str = "/etc/groundctl/ansible-keys/id_ed25519"
    # Per-host keys live under this directory, one subdirectory per Server.id
    # (see docs/limitations.md — the shared key above remains the fallback
    # for hosts bootstrapped before this feature and for the initial
    # bootstrap connection itself, which installs the per-host key).
    ansible_host_keys_dir: str = "/etc/groundctl/ansible-keys/hosts"
    tls_cert_path: str = "/etc/groundctl/tls/cert.pem"
    tls_key_path: str = "/etc/groundctl/tls/key.pem"
    audit_log_retention_days: int = 365
    # Celery broker + result backend. No auth on Redis in this deployment —
    # it's bound to loopback/internal network only, same posture as aptly's
    # unauthenticated API.
    redis_url: str = "redis://changeme_redis_host:6379/0"
    # Fallback TTL applied server-side when ActivationKeyCreate.expires_at is
    # omitted — an activation key with no expiry at all is a standing risk
    # (see docs/limitations.md), so "no expiry supplied" still gets a bound.
    activation_key_default_ttl_hours: int = 24 * 30
    # A server that hasn't completed a successful groundctl-triggered job in
    # this long is flagged by the daily staleness sweep (see docs/limitations.md
    # — last_seen_at is not a heartbeat, only groundctl activity moves it).
    stale_checkin_hours: int = 24 * 7
    # Fire-and-forget alert delivery for server.stale/server.unreachable
    # events (app/webhooks.py). Unset = alerting stays queryable via
    # AuditLog only, no HTTP delivery attempted.
    webhook_url: str | None = None
    webhook_secret: str | None = None
    # A relay whose last_sync_time exceeds this is considered stale for
    # bootstrap/job-routing fallback purposes (see tasks.py's
    # resolve_published_base_url / _relay_proxy_for_servers) and gets
    # flagged by the daily staleness sweep. Deliberately much shorter than
    # stale_checkin_hours (7 days) — a relay silently going stale for a
    # week means its whole site falls back to WAN traffic against the
    # primary, which should surface fast.
    relay_stale_threshold_hours: int = 24
    # A repository whose last_synced_at exceeds this is shown as "stale" in
    # the UI's health indicator — display-only (unlike stale_checkin_hours/
    # relay_stale_threshold_hours above, this doesn't drive a scheduled
    # sweep or a webhook, just a computed field on GET /repositories).
    repository_stale_threshold_hours: int = 24 * 2
    # Root logger level for app/logging_config.py's JSON formatter.
    log_level: str = "INFO"
    # scheduled_aptly_maintenance (app/tasks.py) fires a disk.usage_high
    # webhook when /var/lib/groundctl/aptly crosses this percent-used
    # threshold — aptly's pool grows unbounded otherwise (see
    # docs/limitations.md).
    disk_usage_warn_percent: float = 85.0

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


settings = Settings()
