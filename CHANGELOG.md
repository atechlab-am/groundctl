# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/):
given a version number `MAJOR.MINOR.PATCH`, `MAJOR` is incompatible/breaking
changes, `MINOR` is backwards-compatible functionality, `PATCH` is
backwards-compatible bug fixes.

The current version lives in [`VERSION`](VERSION) — that file, not this one,
is what CI reads to decide what to tag and release. Every version bump here
must have a matching `VERSION` change in the same commit/PR; see
[`docs/releasing.md`](docs/releasing.md).

Versions below map 1:1 to [`ROADMAP.md`](ROADMAP.md)'s phases. All of them
share one date because groundctl's git history begins from a single
"Initial commit" with no earlier per-phase commit trail to date each entry
from individually — the dates are honestly today's, not reconstructed
history, even though the phases were built sequentially.

## [Unreleased]

## [0.9.0] - 2026-08-04

ROADMAP Phase 8 — Interface.

### Added

- Full-featured web UI (`ui/`, Vite + React + TypeScript) covering every
  resource router with real list/detail/action screens — repositories,
  content views, lifecycle environments (promote/rollback), servers, jobs
  (trigger/cancel/log viewer), compliance, errata, host groups, activation
  keys, sites, audit logs. Served same-origin by the control plane via a
  custom `SPAStaticFiles` mount — no CORS, no new nginx routing.
- Cookie-based UI auth (`POST /auth/ui-login`/`ui-refresh`/`ui-logout`,
  `GET /auth/me`) alongside the existing Bearer-only API — refresh token
  as an httpOnly/Secure cookie, 15-minute access token in memory only.
  RBAC-aware nav/actions mirror server-side `require_role()` tiers.
- Dashboard: fleet status counts, environments and their current
  published version, recent jobs — composed client-side from existing
  list endpoints.
- `groundctl` CLI (`cli/`, Typer + httpx + rich), a standalone installable
  package with full parity to the web UI's resource coverage across all
  12 command groups, `--output table|json`. Config-file-backed auth
  (`~/.config/groundctl/config.toml`, `0700`/`0600`) using the existing
  JSON-body `/auth/login`/`refresh`/`logout` flow, with rotating refresh
  tokens persisted immediately after every use.
- `docs/web-ui.md`, `docs/cli.md`.

### Fixed

- Starlette's `StaticFiles(html=True)` does not provide SPA deep-link
  fallback the way it's commonly assumed to — it only serves `index.html`
  for a directory-shaped miss, and raises `HTTPException(404)` rather
  than returning a `Response` for a bare client route like `/login`.
  Fixed with a `SPAStaticFiles` subclass that catches the exception and
  retries against `index.html`, scoped to route-shaped paths only (a
  missing asset still 404s for real).
- CLI: `/auth/refresh` being rate-limited (5/minute) was indistinguishable
  from a dead/revoked refresh token and was misreported as "not logged
  in" — now checks for HTTP 429 explicitly first.
- CLI: Rich's console markup silently swallowed bracketed regex text
  (`[a-zA-Z0-9._-]`) in six commands' `--help` output — help text
  rephrased to avoid bracket syntax.

### Known gaps

- No `GET /content-views` list/detail endpoint exists on the backend;
  both the web UI and CLI work around this client-side (explicit IDs /
  localStorage accumulation) rather than growing a new backend endpoint.

## [0.8.0] - 2026-08-04

ROADMAP Phase 7 — Operations.

### Added

- Alembic migrations replacing `Base.metadata.create_all()` — a baseline
  migration (`0001_initial`) capturing the full schema, verified
  byte-for-byte identical to a fresh `create_all()`-produced schema.
- pytest test suite (`tests/`, real Postgres) covering every router:
  happy paths, RBAC boundaries, aptly-unreachable → 502 paths. CI
  (`.github/workflows/ci.yml`): lint (ruff), typecheck (mypy,
  non-blocking), test, build (static sweeps).
- Pagination (`limit`/`offset`) on every list endpoint; three previously
  missing list endpoints added (`GET /repositories`,
  `GET /lifecycle-environments`, `GET /jobs`).
- Structured JSON logging with correlation IDs
  (`app/logging_config.py`, `CorrelationIdMiddleware`).
- Prometheus metrics (`GET /metrics`) — request/job/server/disk gauges.
- Backup/restore procedure (`scripts/backup.sh`) covering Postgres and
  the aptly content pool.
- Disk-usage monitoring and scheduled aptly DB cleanup.
- Real dependency-aware health checks (`GET /health`) — actual
  operations against Postgres, aptly, and Redis, not liveness pings.

### Fixed

- Alembic's `fileConfig()` silently reconfigured the root logger on every
  migration run, clobbering the JSON formatter on every app startup —
  fixed by skipping it when the app's own formatter is already installed.
- uvicorn's own default logging config bypassed the JSON formatter
  entirely for its own startup/access logs — fixed with a dedicated
  `--log-config` passed at startup.
- `GET /health` called `get_aptly_client()` directly instead of via
  `Depends()`, bypassing `app.dependency_overrides` and making the
  negative (aptly-unreachable) test path untestable.

### Changed

- Corrected prior guidance in `CLAUDE.md`: SQLite cannot render this
  schema's `postgresql.UUID`/`ARRAY` column types at all — tests run
  against a real scratch Postgres, not SQLite as previously documented.

## [0.7.0] - 2026-08-04

ROADMAP Phase 6 — Security hardening.

### Added

- Enforced hierarchical RBAC (`require_role(min_role)`,
  admin > operator > viewer) across every endpoint, replacing the
  previous pass-through stub.
- GPG signing on by default — `LifecycleEnvironmentCreate` requires a
  `gpg_key_id` unless `allow_unsigned: true` is explicit;
  `GET /lifecycle-environments/{id}/gpg-key`; managed hosts trust
  `[signed-by=...]` instead of `[trusted=yes]`.
- HTTPS by default for both the API and published repos — self-signed
  certs generated at install time, CA-issued cert a documented swap-in.
- Documented secrets-at-rest opt-in (sops/age) and hardened
  `write_groundctl_env()` permission handling.
- Per-host SSH keys instead of one shared fleet key, with fallback.
- Rate limiting on auth endpoints (`slowapi`, Redis-backed).
- Short-lived (15-minute) access tokens with a DB-backed, revocable,
  rotating `RefreshToken` model (14-day expiry).
- Audit log coverage for `login`/`login_failed`, `GET /audit-logs`
  (filterable, admin-only), CSV export, retention/purge.

### Fixed

- `LifecycleEnvironmentCreate.allow_unsigned`'s validator never actually
  ran when the field was omitted from the request body (the exact case
  it exists to catch) — pydantic v2 skips validators for defaulted
  fields unless `validate_default=True`.
- `ansible.posix.authorized_key` failed unconditionally in playbook
  execution mode on this ansible-core/Python combination — switched the
  per-host-key install task to `ansible.builtin.lineinfile`.

## [0.6.0] - 2026-08-04

ROADMAP Phase 5 — Relays (multi-site content distribution).

### Added

- `Site` and `Relay` models — a relay mirrors published content to a
  remote site and serves that site's clients locally, deliberately thin
  (aptly-free: nginx serving a static rsync'd tree, no control-plane
  state of its own).
- `install-relay.sh` + `scripts/lib/relay.sh` — native systemd relay
  deployment artifact.
- Primary-initiated rsync-over-SSH content sync
  (`scheduled_sync_relays`, hourly, via the existing Ansible job
  machinery).
- Selective per-site environment sync (`SiteEnvironment` allowlist).
- Site-aware bootstrap — hosts resolve their published-repo URL through
  their site's relay, with graceful fallback to the primary.
- Relay health/sync-lag/disk-usage monitoring and staleness alerting.
- Job execution routed through relays via SSH ProxyJump (not a
  relay-resident agent — keeps relays stateless and rebuildable).

### Fixed

- The bare `-o ProxyJump=` SSH shorthand does not propagate
  `StrictHostKeyChecking` to its own implicit inner hop — fixed with an
  explicit `ProxyCommand=` instead of the shorthand.

## [0.5.0] - 2026-08-04

ROADMAP Phase 4 — Host management.

### Added

- Host groups (`HostGroup`/`HostGroupServer`) as an independent
  many-to-many targeting mechanism for bulk actions.
- Bulk actions across a group (`POST /jobs/bulk-apply-updates`,
  `POST /jobs/run-command`).
- Token-based self-registration and activation keys
  (`ActivationKey`, hash-only token storage, `POST /enrollment/register`
  — the one deliberately unauthenticated mutating endpoint).
- Extended host facts beyond packages (`ServerFact` — OS, kernel, disk,
  services) via `ansible.builtin.setup`/`service_facts`.
- Host lifecycle states, `last_seen_at`/`unreachable` staleness tracking,
  and real webhook delivery (`server.stale`/`server.unreachable`).
- Ad-hoc remote command execution (`run_command.yml`), fully audited,
  admin-gated ahead of the rest of Phase 6's RBAC work given its blast
  radius.
- Fleet-wide package search (`GET /compliance/packages/search`).
- Per-host package install/remove (`JobType.manage_package`).

### Fixed

- `ansible_runner_utils.run_playbook`'s fact capture overwrote rather
  than merged `ansible_facts` across multiple `runner_on_ok` events in
  one playbook run — only the last fact-gathering task's data survived
  until this was fixed to merge instead of assign.

## [0.4.0] - 2026-08-04

ROADMAP Phase 3 — Errata and security intelligence.

### Added

- Ubuntu Security Notice (USN) and Debian Security Advisory (DSA)
  ingestion (`app/errata_ingest.py`), daily via Celery Beat.
- `Erratum`/`ErratumPackage` models — advisory ID, source, title, CVEs,
  publication date, affected package + fixed version (normalized, not a
  JSON blob).
- `GET /errata/{advisory_id}/affected-servers` — errata-to-host mapping
  via the same `dpkg --compare-versions` logic compliance checks use
  (extracted to a shared `app/version_compare.py`).
- Errata-aware content view filters (`FilterType.errata_since`).

### Known gaps

- `Erratum.severity` is never populated — neither upstream feed provides
  it — so no severity-based filtering/dashboards were built against it.
- Applicable-vs-installable package distinction not modeled.

## [0.3.0] - 2026-08-04

ROADMAP Phase 2 — Job execution that survives restarts.

### Added

- Job execution moved to Celery + Redis, replacing `BackgroundTasks`.
- Job cancellation (`POST /jobs/{id}/cancel`) — running jobs are
  actually revoked/terminated, not just marked failed in the DB.
- Retry with backoff on transient SSH failures
  (`AnsibleUnreachableError`, `autoretry_for`).
- Stuck-job reaper on API startup, cross-referencing `running` jobs
  against Celery's live task registry.
- Per-environment and per-server concurrency locks (Redis-based,
  fail-fast, not blocking).
- Progressive job log streaming during a run, not just at completion.
- Scheduled/recurring jobs via Celery Beat (nightly repo sync, weekly
  compliance scan) plus a `ComplianceCheckLog` model persisting scan
  results.

### Fixed

- `@shared_task` resolved against Celery's unconfigured default app
  (AMQP) when dispatched from a request handler under
  `run_in_threadpool` — fixed by binding tasks via `@celery_app.task`.
- Celery 5.6 re-raises the original exception on final retry exhaustion
  rather than `MaxRetriesExceededError` — jobs could get stuck at
  `running` forever without an explicit retry-count check.

## [0.2.0] - 2026-08-04

ROADMAP Phase 1 — Content model parity.

### Added

- `Repository` model, decoupled from `Environment` (replaces the old
  single-mirror-per-environment shape).
- `ContentView` model aggregating N repositories
  (`ContentViewRepository`), the actual fix for mirroring
  `jammy`+`jammy-updates`+`jammy-security` together.
- `ContentViewVersion` — immutable, one aptly snapshot per member
  repository, a `content_hash`, incrementing version number per view.
- `LifecycleEnvironment` with an ordered path and enforced promotion
  order (an environment can only be promoted into once its predecessor
  in the path currently has the target version live).
- `POST /lifecycle-environments/{id}/rollback` — pure `switch_publish`
  to an already-cut prior version, restricted to versions that specific
  environment actually had live before.
- Content view filters (`ContentViewFilter`, include/exclude).

### Known gaps

- Composite content views (a view built from other views) not modeled.
- Content view filters not verified against a live aptly instance.

## [0.1.0] - 2026-08-04

ROADMAP Phase 0 — Correctness (blocking bug fixes underlying everything
else).

### Fixed

- **Promotion no longer cuts a fresh snapshot on every call.** `promote`
  now hashes the mirror's current package contents and only cuts a new
  snapshot when that hash changes; every call re-points the publish
  prefix at the current snapshot. This was the core immutability
  guarantee groundctl exists to provide.
- `bootstrap_client.yml` no longer hardcodes the `main` component —
  components flow from the mirror's actual `components` list.
- Real Debian version comparison (`dpkg --compare-versions`) in
  `compliance.py`, replacing string/lexicographic comparison.
- Package-availability map now keeps the highest version per
  `(name, arch)` using real version comparison, not last-seen-wins.
- `ansible-runner` does not resolve an absolute playbook path the way
  expected — fixed by pointing `project_dir` directly at the playbooks
  directory.
- Additive bootstrap mode — `bootstrap_client.yml`'s sources.list.d
  filename is now derived per-environment, so a host can be bootstrapped
  against multiple environments without one overwriting another.
- `datetime.utcnow()` replaced with timezone-aware
  `datetime.now(timezone.utc)` throughout.
- Deprecated `db.query(M).get(id)` replaced with `db.get(M, id)`
  throughout.

### Known gaps

- Multiple repositories per content view deferred to (and properly
  solved by) Phase 1's `Repository`/`ContentView` model.

[Unreleased]: https://github.com/OWNER/groundctl/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/OWNER/groundctl/releases/tag/v0.9.0
[0.8.0]: https://github.com/OWNER/groundctl/releases/tag/v0.8.0
[0.7.0]: https://github.com/OWNER/groundctl/releases/tag/v0.7.0
[0.6.0]: https://github.com/OWNER/groundctl/releases/tag/v0.6.0
[0.5.0]: https://github.com/OWNER/groundctl/releases/tag/v0.5.0
[0.4.0]: https://github.com/OWNER/groundctl/releases/tag/v0.4.0
[0.3.0]: https://github.com/OWNER/groundctl/releases/tag/v0.3.0
[0.2.0]: https://github.com/OWNER/groundctl/releases/tag/v0.2.0
[0.1.0]: https://github.com/OWNER/groundctl/releases/tag/v0.1.0
