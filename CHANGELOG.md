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

Each `### Added`/`### Fixed`/`### Changed`/`### Known gaps` heading carries a
short summary after a colon, e.g. `### Fixed: bump GitHub Actions to Node
24-native majors` — written to double as a git commit subject line.

Versions below map 1:1 to [`ROADMAP.md`](ROADMAP.md)'s phases. All of them
share one date because groundctl's git history begins from a single
"Initial commit" with no earlier per-phase commit trail to date each entry
from individually — the dates are honestly today's, not reconstructed
history, even though the phases were built sequentially.

## [Unreleased]

## [0.10.1] - 2026-08-04

### Fixed: release.yml's own release step failing because CHANGELOG content was being executed as a shell script

- `.github/workflows/release.yml`'s "Tag and create GitHub Release" step
  interpolated `${{ steps.changelog.outputs.notes }}` directly into a
  `run:` block's `--notes "..."` argument. GitHub Actions substitutes
  `${{ }}` expressions into the script's source text *before* the shell
  ever runs it — so the multi-line CHANGELOG excerpt (containing its own
  quotes, backticks, and text that happens to look like shell tokens —
  `install.sh`, `--fleet-hostname`, `/etc/groundctl/maintain.conf`, etc.)
  broke out of the intended string argument and got executed as a
  sequence of separate shell commands, each failing with "command not
  found." Same latent issue existed one step earlier for `VERSION`
  (interpolated the same way, just with lower-risk single-line content).
  Fixed by passing both through `env:` instead — an environment variable
  is data the shell only ever reads via `"${VAR}"`, never re-parsed as
  code, regardless of its content. Verified by reproducing the argument
  count locally (multi-line notes containing quotes/backticks/flags stay
  exactly one shell argument via the `env:` + `"${RELEASE_NOTES}"`
  pattern, versus fragmenting into many when interpolated directly).
- **Follow-up, same day**: after this fix landed, a re-run of the release
  job still showed the exact pre-fix failure — traced to the re-run
  executing against the *stale, pre-fix* workflow file rather than the
  fixed one (GitHub's "re-run" for a `workflow_run`-triggered job appears
  pinned to the original triggering commit, not the branch's current
  HEAD — confirmed by diffing the failing run's own logged `env:` block,
  which only listed `GH_TOKEN`, against this fix's `env:` block, which
  also lists `VERSION`/`RELEASE_NOTES`; they didn't match). No `v0.10.x`
  tag was ever actually created. Separately hardened `--notes
  "${RELEASE_NOTES}"` to `--notes-file - <<< "${RELEASE_NOTES}"`
  (stdin instead of a constructed CLI argument) — confirmed locally that
  bash's `"${VAR}"` expansion does *not* re-tokenize embedded quotes (so
  the original form was not actually broken), but stdin sidesteps
  argument-quoting reasoning entirely for free-form changelog prose that
  will keep containing quotes/backticks release over release. Requires a
  genuinely new push (not a re-run of an old job) to exercise for real.

## [0.10.0] - 2026-08-04

### Added: interactive install.sh prompts and a standalone `groundctl-maintain upgrade` command

- `install.sh` now prompts interactively for the fleet hostname and nginx
  port when run with no `--fleet-hostname`/`--nginx-port` flags and no
  `GROUNDCTL_FLEET_HOSTNAME`/`GROUNDCTL_NGINX_PORT` env vars set — new
  `prompt_if_unset` helper (`scripts/lib/os.sh`). Flags/env vars still
  fully bypass the prompt (unchanged precedence); a non-TTY invocation
  (piped input, cron, CI) falls back to the default silently rather than
  hanging on `read`.
- New standalone command `groundctl-maintain`, installed to
  `/usr/local/bin` by `install.sh` (`install_maintain_script`,
  `scripts/lib/app.sh`). **Deliberately a separate script from
  `install.sh`, not a wrapper around it** — `install.sh` is for
  first-time provisioning and config changes (fleet hostname, nginx
  port, TLS); `groundctl-maintain upgrade` is the standing command for
  routine code upgrades: `git fetch`/`checkout`s the install's own
  checkout to the latest `main` (via a new `/etc/groundctl/maintain.conf`
  recording the checkout path), then rebuilds the web UI, resyncs app
  code, updates Python deps, applies pending migrations, and restarts
  `groundctl`/`groundctl-worker`/`groundctl-beat` — by sourcing and
  calling the same `scripts/lib/app.sh` functions `install.sh` itself
  uses, not a duplicated implementation. Deliberately never touches
  one-time provisioning or config (Postgres/Redis/aptly/nginx install,
  TLS cert, fleet hostname/port) — an upgrade can't accidentally reset
  `PUBLISHED_REPO_BASE_URL` to a placeholder.
- Verified live: `prompt_if_unset`'s three paths (env-preset/no-prompt,
  non-TTY/default-fallback, real interactive input via `expect`) all
  behave correctly; a full `groundctl-maintain upgrade` run against a
  real scratch git remote correctly detected a version bump, updated the
  checkout, called every expected provisioning function in order, left
  config/one-time-provisioning functions uncalled, and correctly
  no-op'd ("already up to date") on a second immediate run; all error
  paths (missing `maintain.conf`, a `maintain.conf` pointing at a
  non-git directory, an unknown subcommand) produce clean messages and
  exit 1, not tracebacks.

## [0.9.2] - 2026-08-04

### Fixed: bump GitHub Actions to Node 24-native majors, fixing the Node 20 deprecation warning on every CI job

- Bumped `actions/checkout` (v4→v5), `actions/setup-python` (v5→v6), and
  `actions/setup-node` (v4→v5) across `.github/workflows/ci.yml` and
  `release.yml` — the pinned versions bundled Node 20, which GitHub's
  runners now force-upgrade to Node 24 at runtime with a deprecation
  warning on every job; the newer action majors support Node 24 natively.

## [0.9.1] - 2026-08-04

### Fixed: resolve all 48 mypy errors surfaced by CI's typecheck job

- Resolved all 48 mypy errors surfaced by CI's (non-blocking) typecheck
  job. Not cosmetic — a handful were real gaps worth closing:
  - `app/aptly_client.py`: 7 methods (`cleanup_db`, `create_mirror`,
    `sync_mirror`, `create_snapshot_from_mirror`, `publish_snapshot`,
    `switch_publish`, `create_filtered_snapshot`) declared `-> dict` while
    sharing a helper that can return `dict | list` — added
    `_json_object_or_empty`, which asserts the response really is a JSON
    object (true for all 7 of aptly's documented endpoints here) instead
    of silently widening every caller's type.
  - `app/tasks.py`: several task bodies dereferenced `db.get(...)` results
    (`Server`, `LifecycleEnvironment`, `Job`) without a `None` check —
    foreign keys guarantee these in the paths that dispatch each task
    today, but a dangling/deleted row was previously an unguarded
    `AttributeError` instead of a clear error. Added explicit checks
    (new `_get_job_or_raise` helper, reused across 4 call sites) and a
    `TypeGuard` on `_relay_is_usable` so mypy can see the narrowing that
    was already true at runtime.
  - `app/routers/compliance.py`: `do_check_compliance` didn't guard
    against its `ContentViewVersion` lookup returning `None` (a dangling
    FK); `_highest_version_per_name_arch`'s return type claimed
    `arch: str` when aptly entries can genuinely omit `Architecture`.
  - `app/routers/lifecycle_environments.py`: `promote_environment` didn't
    guard against its `ContentView` lookup returning `None`.
  - `app/routers/sites.py`, `app/routers/host_groups.py`:
    `Model.__table__.delete()` isn't typed by SQLAlchemy's stubs the way
    `delete(Model)` is — switched to the latter (also more idiomatic
    SQLAlchemy 2.0), no behavior change.
  - `app/routers/content_views.py`: passed an ORM `ContentViewVersion`
    directly into a field typed `ContentViewVersionRead`, relying on
    implicit pydantic coercion — made explicit with `.model_validate()`.
  - `app/routers/jobs.py`: `Job.server_ids` is a response-only attribute
    with no mapped column (attached at request time for `JobRead` to
    serialize) — annotated instead of left for mypy to flag as missing.
  - `app/main.py`: one remaining error is a genuine `slowapi`/Starlette
    stub-typing mismatch in a third-party function signature, not
    fixable from groundctl's side — suppressed with a documented
    `# type: ignore[arg-type]`.
  - Full pytest suite reconfirmed green after every fix (211 passed, 24
    skipped — no regressions).

## [0.9.0] - 2026-08-04

ROADMAP Phase 8 — Interface.

### Added: full-featured web UI and groundctl CLI, covering every resource with RBAC-aware auth

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

### Fixed: SPA deep-link 404s, a CLI rate-limit misreport, and Rich swallowing help text

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

### Known gaps: no content-views list/detail endpoint on the backend

- No `GET /content-views` list/detail endpoint exists on the backend;
  both the web UI and CLI work around this client-side (explicit IDs /
  localStorage accumulation) rather than growing a new backend endpoint.

## [0.8.0] - 2026-08-04

ROADMAP Phase 7 — Operations.

### Added: migrations, a real test suite + CI, pagination, structured logging, metrics, backups, health checks

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

### Fixed: logging config being silently clobbered by Alembic and uvicorn, and an untestable health check

- Alembic's `fileConfig()` silently reconfigured the root logger on every
  migration run, clobbering the JSON formatter on every app startup —
  fixed by skipping it when the app's own formatter is already installed.
- uvicorn's own default logging config bypassed the JSON formatter
  entirely for its own startup/access logs — fixed with a dedicated
  `--log-config` passed at startup.
- `GET /health` called `get_aptly_client()` directly instead of via
  `Depends()`, bypassing `app.dependency_overrides` and making the
  negative (aptly-unreachable) test path untestable.

### Changed: corrected CLAUDE.md's testing guidance from SQLite to real Postgres

- Corrected prior guidance in `CLAUDE.md`: SQLite cannot render this
  schema's `postgresql.UUID`/`ARRAY` column types at all — tests run
  against a real scratch Postgres, not SQLite as previously documented.

## [0.7.0] - 2026-08-04

ROADMAP Phase 6 — Security hardening.

### Added: enforced RBAC, GPG signing and HTTPS on by default, per-host SSH keys, refresh tokens, audit coverage

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

### Fixed: a silently-skipped pydantic validator and a broken Ansible authorized_key task

- `LifecycleEnvironmentCreate.allow_unsigned`'s validator never actually
  ran when the field was omitted from the request body (the exact case
  it exists to catch) — pydantic v2 skips validators for defaulted
  fields unless `validate_default=True`.
- `ansible.posix.authorized_key` failed unconditionally in playbook
  execution mode on this ansible-core/Python combination — switched the
  per-host-key install task to `ansible.builtin.lineinfile`.

## [0.6.0] - 2026-08-04

ROADMAP Phase 5 — Relays (multi-site content distribution).

### Added: Relay/Site model and thin-relay content sync with SSH ProxyJump job routing

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

### Fixed: ProxyJump's inner SSH hop not inheriting StrictHostKeyChecking

- The bare `-o ProxyJump=` SSH shorthand does not propagate
  `StrictHostKeyChecking` to its own implicit inner hop — fixed with an
  explicit `ProxyCommand=` instead of the shorthand.

## [0.5.0] - 2026-08-04

ROADMAP Phase 4 — Host management.

### Added: host groups, activation-key self-registration, extended facts, staleness alerting, ad-hoc execution

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

### Fixed: multi-task fact gathering silently overwriting instead of merging results

- `ansible_runner_utils.run_playbook`'s fact capture overwrote rather
  than merged `ansible_facts` across multiple `runner_on_ok` events in
  one playbook run — only the last fact-gathering task's data survived
  until this was fixed to merge instead of assign.

## [0.4.0] - 2026-08-04

ROADMAP Phase 3 — Errata and security intelligence.

### Added: USN/DSA errata ingestion, errata-to-host mapping, errata-aware content view filters

- Ubuntu Security Notice (USN) and Debian Security Advisory (DSA)
  ingestion (`app/errata_ingest.py`), daily via Celery Beat.
- `Erratum`/`ErratumPackage` models — advisory ID, source, title, CVEs,
  publication date, affected package + fixed version (normalized, not a
  JSON blob).
- `GET /errata/{advisory_id}/affected-servers` — errata-to-host mapping
  via the same `dpkg --compare-versions` logic compliance checks use
  (extracted to a shared `app/version_compare.py`).
- Errata-aware content view filters (`FilterType.errata_since`).

### Known gaps: no errata severity data, no applicable-vs-installable distinction

- `Erratum.severity` is never populated — neither upstream feed provides
  it — so no severity-based filtering/dashboards were built against it.
- Applicable-vs-installable package distinction not modeled.

## [0.3.0] - 2026-08-04

ROADMAP Phase 2 — Job execution that survives restarts.

### Added: Celery + Redis job execution with retries, locking, cancellation, and progressive log streaming

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

### Fixed: tasks silently falling back to Celery's unconfigured default app, and jobs stuck at running forever

- `@shared_task` resolved against Celery's unconfigured default app
  (AMQP) when dispatched from a request handler under
  `run_in_threadpool` — fixed by binding tasks via `@celery_app.task`.
- Celery 5.6 re-raises the original exception on final retry exhaustion
  rather than `MaxRetriesExceededError` — jobs could get stuck at
  `running` forever without an explicit retry-count check.

## [0.2.0] - 2026-08-04

ROADMAP Phase 1 — Content model parity.

### Added: Repository/ContentView/ContentViewVersion model with ordered, enforced environment promotion

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

### Known gaps: no composite content views, content view filters unverified against live aptly

- Composite content views (a view built from other views) not modeled.
- Content view filters not verified against a live aptly instance.

## [0.1.0] - 2026-08-04

ROADMAP Phase 0 — Correctness (blocking bug fixes underlying everything
else).

### Fixed: promotion cutting a fresh snapshot on every call instead of only when content actually changed

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

### Known gaps: single-mirror-per-environment, superseded by Phase 1's Repository/ContentView model

- Multiple repositories per content view deferred to (and properly
  solved by) Phase 1's `Repository`/`ContentView` model.

[Unreleased]: https://github.com/OWNER/groundctl/compare/v0.10.1...HEAD
[0.10.1]: https://github.com/OWNER/groundctl/releases/tag/v0.10.1
[0.10.0]: https://github.com/OWNER/groundctl/releases/tag/v0.10.0
[0.9.2]: https://github.com/OWNER/groundctl/releases/tag/v0.9.2
[0.9.1]: https://github.com/OWNER/groundctl/releases/tag/v0.9.1
[0.9.0]: https://github.com/OWNER/groundctl/releases/tag/v0.9.0
[0.8.0]: https://github.com/OWNER/groundctl/releases/tag/v0.8.0
[0.7.0]: https://github.com/OWNER/groundctl/releases/tag/v0.7.0
[0.6.0]: https://github.com/OWNER/groundctl/releases/tag/v0.6.0
[0.5.0]: https://github.com/OWNER/groundctl/releases/tag/v0.5.0
[0.4.0]: https://github.com/OWNER/groundctl/releases/tag/v0.4.0
[0.3.0]: https://github.com/OWNER/groundctl/releases/tag/v0.3.0
[0.2.0]: https://github.com/OWNER/groundctl/releases/tag/v0.2.0
[0.1.0]: https://github.com/OWNER/groundctl/releases/tag/v0.1.0
