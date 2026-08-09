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

## [0.14.0] - 2026-08-06

### Added: instance settings — admin-managed branding (logo/favicon/colors) and full user management, plus self-service password change

- New **Settings** sidebar item, every user: **My Account** tab shows
  identity (username/email/role, read-only) and lets any user change
  their own password (`PUT /api/auth/me/password`, requires the current
  password — no admin-driven reset path exists, see `docs/limitations.md`).
- New **Settings > Users** tab (admin-only): list every user, create new
  ones (wires up the existing `POST /api/auth/register`, which had no UI
  before now), edit email/role inline, deactivate/reactivate. New `User.active`
  column (migration `bf3d347ed1d3`) — deactivation, not deletion, matching
  `Server`'s decommission/`ActivationKey`'s revoked posture elsewhere in
  this app: the row and everything it's a foreign-key target for
  (`AuditLog.user_id`, etc.) stays intact, but a deactivated user can no
  longer log in (`get_current_user` now rejects `active=False` even on an
  otherwise-still-valid access token, not just at login) and their
  audit-log history remains attributable.
- New **Settings > Appearance** tab (admin-only): primary/accent color
  pickers and logo/favicon upload. Applied instantly for every user via
  CSS custom-property overrides (`ui/src/lib/branding.ts` — converts an
  admin-entered hex color into the `H S% L%` triplet `index.css`'s Fluent
  tokens expect) and a live favicon swap. New `Branding` table (single
  shared row, image bytes stored in Postgres — not on disk, so the
  existing `pg_dump`-based backup (`docs/backup.md`) covers this with no
  changes needed anywhere).
- `GET /api/branding` (+ `/logo`, `/favicon`) are deliberately
  unauthenticated — the login screen and browser tab need to render
  custom branding before any session exists, same reasoning already
  established for `GET /api/enrollment/ssh-public-key`. Every *write*
  endpoint (`PUT /branding/colors`, `POST /branding/logo`,
  `POST /branding/favicon`) stays admin-only. Uploads are capped at 2 MB
  and restricted to a small raster-format allowlist — SVG deliberately
  excluded (script/event-handler injection risk, since uploaded content
  isn't sanitized before being served back via `<img>`).
- Last-admin-lockout guards on both user-management mutations: `PATCH
  /api/users/{id}` refuses to demote the only active admin out of the
  admin role, and `POST /api/users/{id}/deactivate` refuses to deactivate
  them (or to deactivate your own account at all, regardless of admin
  count) — verified live via two disposable-admin test scenarios, since
  getting this wrong means an install with no way back into its own admin
  role.
- 5 new `AuditAction` values (`update_user`, `deactivate_user`,
  `reactivate_user`, `change_own_password`, `update_branding`) — added via
  `ALTER TYPE audit_action ADD VALUE` inside an `autocommit_block()`
  (Postgres can't add and use a new enum value in the same transaction a
  normal Alembic migration runs in). Verified both directions: applied
  cleanly against the test database and the corresponding `downgrade()`
  correctly drops the new table/column (enum values are intentionally
  left in place on downgrade — Postgres has no `ALTER TYPE ... DROP
  VALUE`, and the values are inert if the app code that writes them is
  also reverted).

### Fixed: `sync_app_code` left stale compiled `.pyc` bytecode in place across every redeploy, silently serving old code even after a full upgrade

- Found live on a real host, after this version's own docs-viewer feature
  landed: `GET /api/docs` returned the SPA's `index.html` instead of real
  JSON, matching `SPAStaticFiles`'s deep-link fallback — but every file
  on disk (`/opt/groundctl/app/main.py`, the systemd unit, the checkout)
  was confirmed current and correct. `sudo ss -tlnp` confirmed only one
  process was bound to port 443, and it matched `groundctl.service`'s own
  reported PID. The actual cause: `sync_app_code`'s `rsync -a --delete`
  only removes destination files/directories that are genuinely absent
  from the *source* tree it's mirroring — `__pycache__/*.pyc` is never
  present in the source checkout at all (gitignored, generated at
  runtime only in `/opt/groundctl`), so rsync has nothing to compare it
  against and silently leaves old compiled bytecode in place forever,
  even across a full `--delete` sync of every real `.py` file. A host
  that had been running long enough to compile `app/main.py` before the
  `/api` prefix change (`0.13.0`) landed was still *executing* that
  stale compiled version after multiple subsequent real upgrades — the
  `.py` source was current, the running code wasn't, and nothing about
  inspecting the checkout, the unit file, or even the exact file on disk
  could reveal it without actually clearing the cache and retesting.
- Fixed by having `sync_app_code` explicitly clear every `__pycache__`
  directory under `/opt/groundctl/app` after every sync
  (`find /opt/groundctl/app -depth -name "__pycache__" -exec rm -rf {} +`),
  forcing Python to recompile from the just-synced source on next start.
  Runs on both `install.sh` and `groundctl-maintain upgrade` (both call
  `sync_app_code`), so this is fixed going forward for every future
  redeploy, not just as a one-time manual workaround. Verified live: a
  disposable directory tree with simulated stale `.pyc` files at two
  nesting depths had both `__pycache__` directories removed while real
  `.py` files were left untouched, and the same command exits cleanly
  (code 0) when no `__pycache__` exists at all (the normal fresh-install
  case).

## [0.13.2] - 2026-08-05

### Added: documentation is now readable from the web UI itself, not just the repo

- New sidebar item **Documentation** (`/documentation`, `/documentation/{slug}`)
  renders `docs/*.md` as formatted HTML right inside the SPA via
  `react-markdown` + `@tailwindcss/typography` — no separate GitHub/repo
  access needed, works fully air-gapped.
- New `GET /api/docs` (list, title extracted from each file's first `# H1`)
  and `GET /api/docs/{filename}` (content), gated at `require_role(viewer)`
  like every other read endpoint. Filenames are validated against
  `^[a-z0-9][a-z0-9-]*\.md$` — a fixed, closed shape that can never
  traverse outside the docs directory regardless of what's passed,
  verified with a dedicated path-traversal test.
- `docs/*.md` previously only existed in the git checkout — nothing
  copied them into what the running app actually serves.
  `sync_app_code` (`scripts/lib/app.sh`) now also syncs `docs/` into
  `/opt/groundctl/docs` (sibling to `app/`, not nested inside it, so the
  relative layout the endpoint resolves against — `Path(__file__)`-relative,
  same pattern `app/main.py` already uses for `app/static` — is identical
  in a dev checkout and in production).
  A `groundctl-maintain upgrade` or fresh `install.sh` run is needed to
  pick this up on an already-installed host.
- Deliberately routed the SPA page at `/documentation`, not `/docs` —
  FastAPI's own Swagger UI is already served, unprefixed, at bare `/docs`,
  registered server-side ahead of the SPA's catch-all; an SPA route at
  that same path would have hit real Swagger on a hard refresh instead of
  ever reaching the SPA, the exact bug class the `/api` prefix work
  earlier in this same version was written to prevent.
- Caught a second instance of that same bug class before shipping:
  `SPAStaticFiles`'s deep-link fallback deliberately treats any path
  whose last segment contains a `.` as a missing-asset request, not a
  client route (correct for real assets — a genuinely missing JS/CSS
  file must stay a real 404). A route like `/documentation/install.md`
  would have looked identical to that case, 404ing for real on a hard
  refresh instead of loading the SPA. Fixed by routing on a
  dot-free slug (`/documentation/install`, `.md` stripped/re-added at
  the API-call boundary — `slugFor`/`filenameForSlug` in
  `DocumentationPage.tsx`) instead of teaching the shared fallback logic
  a per-feature exception.
- New `tests/test_docs_content.py` (RBAC, list/detail, path-traversal and
  invalid-filename rejection) needed the same `reset_login_rate_limit`
  autouse fixture every other multi-token test file already carries —
  `POST /auth/login` is rate-limited to 5/minute, and 6 tests each
  independently minting a `viewer_token` exceeded that within the same
  test run, caught by a real (not isolated-file) run of the full suite.

### Added: `docs/first-environment.md` — web-UI walkthrough for the repository → content view → environment → server chain

- New doc covering the full required dependency chain (a lifecycle
  environment needs a published content view; a content view needs at
  least one repository) purely through the web UI's own screens, mirroring
  `docs/quickstart.md`'s `curl` walkthrough for anyone clicking through
  instead of scripting. Includes a field-by-field table for
  `LifecycleEnvironmentCreate` (path name/position/content view/distro/
  release/publish prefix/GPG signing) and covers both self-enrollment
  (activation key + generated script) and manual server creation for
  adding a server, cross-linking `docs/quickstart.md`'s activation-key
  field reference rather than duplicating it.
- Cross-linked from `README.md`, `docs/quickstart.md`, and `docs/web-ui.md`.

### Fixed: `groundctl-maintain upgrade` couldn't repair a stale systemd unit when the checkout had no new commits to redeploy

- Found live immediately after the `0.13.1` fix: a host's checkout was
  already at the latest commit (the `tls.sh`-sourcing fix from `0.13.1`
  itself), but `groundctl.service` was still the *old* unit
  (`--port 8000`) written before the port-443 change existed — `upgrade`
  correctly reported "already up to date" (nothing changed since the
  `0.13.1` pull) and, because `install_groundctl_service` was still
  gated behind that same "did the commit move" check, never re-rendered
  the unit to repair it. Only a full `install.sh` re-run (which
  unconditionally rewrites the unit) fixed it, on the same host used to
  verify `0.13.0`'s port-443 rollout.
- Same shape as `0.10.4`'s `install_maintain_script` fix, applied to the
  systemd units too: `install_groundctl_service`/`install_groundctl_worker_service`/
  `install_groundctl_beat_service` now run unconditionally, before the
  commit-diff gate — cheap and self-limiting, since `_install_app_service`
  already does its own content-diff internally (render to a temp file,
  `cmp` against what's installed, only restart if it actually differs or
  the service isn't running). The expensive part of an upgrade (apt,
  `npm ci`, venv rebuild, migrations) still only runs when `main` actually
  moved; the now-redundant second call to the three `install_*_service`
  functions after that block was removed in favor of a direct
  `systemctl restart` (the units themselves don't change between the
  pre-gate render and the end of a real upgrade — only the app code they
  point at does).
- Verified against three live disposable-checkout scenarios: a stale unit
  with no new commits is now repaired and reports "already up to date"
  for everything else; re-running immediately with the unit already
  correct and the service already active correctly no-ops (no restart);
  a genuine version bump still performs the full redeploy and restarts
  all three services exactly once, not twice.

## [0.13.1] - 2026-08-05

### Fixed: `groundctl-maintain upgrade` crashed with "TLS_CERT_PATH: unbound variable" — `cmd_upgrade` never sourced `scripts/lib/tls.sh`

- Found live on a real host running `sudo groundctl-maintain upgrade`:
  `install_groundctl_service` (via `_install_app_service`) has always
  referenced `TLS_CERT_PATH`/`TLS_KEY_PATH` to render
  `groundctl.service.template` — those are only ever defined in
  `scripts/lib/tls.sh`, which `cmd_upgrade` never sourced (unlike
  `cmd_regen_cert`, which already did). Pre-existing since the very first
  commit, but silently never triggered: `upgrade` used to only reach
  `install_groundctl_service` on a genuine `VERSION` bump, and until now
  that only ever happened either right after `install.sh` itself (which
  *does* source `tls.sh`, in the same process) or never at all in
  practice. The `0.12.1` fix that made `upgrade` redeploy on any new
  commit — not just a version bump — is what finally made a bare
  `groundctl-maintain upgrade` (no prior `install.sh` in that process)
  exercise this path for the first time on a real host, under
  `set -euo pipefail`, aborting mid-upgrade.
- Fixed by sourcing `scripts/lib/tls.sh` in `cmd_upgrade` alongside
  `os.sh`/`app.sh`, matching what `cmd_regen_cert` already does. Verified
  by isolating `_install_app_service` in a minimal harness: reproduced
  the exact `TLS_CERT_PATH: unbound variable` failure with the old
  sourcing, then confirmed a clean run with the fix, including the
  rendered `groundctl.service` unit correctly showing
  `--ssl-certfile /etc/groundctl/tls/cert.pem --ssl-keyfile
  /etc/groundctl/tls/key.pem`.

## [0.13.0] - 2026-08-05

### Fixed: web UI pages returned raw `{"detail":"Not authenticated"}` on hard refresh — every resource API endpoint now lives under `/api`

- Root cause: several SPA page paths (`/servers`, `/jobs`, `/errata`,
  `/sites`, `/activation-keys`) were identical to real API router
  prefixes, and `app.include_router(...)` mounted those endpoints at the
  bare path — matched by FastAPI *before* the SPA's catch-all
  `StaticFiles` fallback ever saw the request (see `SPAStaticFiles`).
  Refreshing the browser on, say, `/servers` sent a real `GET /servers`
  straight to the API (no `Authorization` header, since the browser is
  navigating, not the SPA's fetch wrapper), which correctly 401'd —
  but that raw JSON is what rendered instead of the app ever loading.
- Fixed by mounting every resource router under a new `/api` prefix
  (`app/main.py`'s `api_router`) — `/health`/`/metrics`/`/docs` stay
  unprefixed (infra/tooling endpoints, no collision risk). Updated in
  lockstep: the web UI's fetch client (`ui/src/api/client.ts`'s
  `API_PREFIX`), the standalone CLI (`cli/groundctl_cli/client.py`
  appends `/api` to the configured `api_url`), the generated enrollment
  script (`GET /api/enrollment/register`, `/api/enrollment/ssh-public-key`),
  `vite.config.ts`'s dev-server proxy (collapsed from 12 individually
  listed prefixes to one `/api` rule — which also fixed a pre-existing
  gap where `/enrollment` was missing from that list entirely), and every
  `curl`/URL example across `docs/*.md`.
- Caught and fixed a second bug this same change would otherwise have
  introduced: the web UI's httpOnly refresh-token cookie was scoped to
  path `/auth`, which no longer matches where those endpoints actually
  live (`/api/auth/ui-refresh`, etc.) — a mismatch here means the browser
  silently never sends the cookie back at all. Moved
  `UI_REFRESH_COOKIE_PATH` to `/api/auth` (`app/routers/auth.py`).
- Test suite fix: ~400 existing `client.get/post/put/delete("/...")` calls
  across `tests/*.py` predate the `/api` prefix and use bare resource
  paths. Rather than rewrite every call site, `tests/conftest.py` now
  defines a `TestClient` subclass overriding `_merge_url` to transparently
  prepend `/api` (matching what the real frontend/CLI clients now do)
  unless the path already targets `/api/...` or one of the genuinely
  unprefixed routes. Every test file constructing `TestClient` directly
  now imports it from `tests.conftest` instead of `fastapi.testclient`.
  Verified: full suite passes unchanged (224 passed, 24 skipped).

### Added: the API + web UI now listen on port 443 — no port needed to browse to the fleet hostname

- `groundctl.service` moves from `:8000` to `:443` (`GROUNDCTL_PORT` in
  `scripts/lib/app.sh`, templated into `systemd/groundctl.service.template`
  as `__GROUNDCTL_PORT__`). nginx's own port for published apt repos is
  unchanged (still configurable, default `8080`) — this only affects the
  API/UI.
- Binding a privileged port from the unprivileged `groundctl` user (no
  service here runs as root) uses `CAP_NET_BIND_SERVICE` via `setcap` on
  the venv's own `python3` binary (`grant_bind_low_ports`), called after
  `setup_venv` in both `install.sh` and `groundctl-maintain upgrade`.
  Requires `libcap2-bin` (added to `install_app_prereqs`).
- Caught a real problem before shipping it: `python3 -m venv` normally
  makes `bin/python3` a **symlink** to the system interpreter, not its
  own binary. `setcap` on a symlink either fails outright or — if
  followed — grants the capability to the *system-wide* `python3`,
  meaning every other script on the host invoked via that same
  interpreter could also bind privileged ports. Fixed by creating the
  venv with `--copies` (a real, independent ~30MB binary), with
  `setup_venv` detecting and one-time-recreating any existing venv still
  in symlink form (from before this change) so `setcap` never targets
  the system interpreter.
- `write_groundctl_env`'s `GROUNDCTL_API_BASE_URL` (used by
  `bootstrap_client.yml` to fetch the GPG key / TLS CA cert over the
  bootstrap SSH connection) drops its hardcoded `:8000` — `https://` with
  no port already means 443.
- `install.sh`'s final summary and every `docs/*.md` walkthrough updated
  from `https://<host>:8000` to `https://<host>`.

### Added: `.claude/context/` scaffold, mirroring the sibling suite apps' Claude working-rules layout

- New `.claude/context/MEMORY.md` + `feedback_*.md`/`project_*.md`/
  `security-standards.md` files — the same structure used by the ATech
  suite's other 8 projects (see `GitHub/CLAUDE.md`), adapted rather than
  copied verbatim: points at `/CLAUDE.md`/`docs/*.md`/`ROADMAP.md` instead
  of duplicating their content (which would just drift), and
  `security-standards.md` reflects groundctl's actual security surface
  (aptly name validation, sources.list injection, RBAC tiers, the new
  `/api` routing rule above) rather than dispatch's XSS/PDF-template
  concerns, which don't apply here.
- Includes the same `feedback_docs_update.md`/`feedback_todo_sync.md`/
  `feedback_memory_sync.md`/`feedback_caveman_mode.md`/
  `feedback_edit_permission.md` working-rules the other suite apps use —
  `ROADMAP.md` fills the `todo.md` role (already existed, already
  live-updated per phase) rather than a new duplicate file.

## [0.12.1] - 2026-08-04

### Fixed: `groundctl-maintain upgrade` silently skipped redeploying app code and restarting services when `main` moved but `VERSION` didn't

- Found live, immediately after `v0.12.0` shipped: a host's checkout was
  already sitting on the correct `VERSION` (`0.12.0`) after a prior
  `upgrade`, but a `POST /repositories/probe` call still returned "method
  not allowed" — the running `groundctl.service` process was serving
  *older* code than what was actually on disk in the checkout.
  `cmd_upgrade` gated the entire redeploy (`sync_app_code`,
  `install_groundctl_service`, restarting `groundctl`/`-worker`/`-beat`,
  etc.) on `before_version == after_version` — comparing `VERSION` before
  and after `git reset --hard origin/main`. But `VERSION` only bumps on a
  release; ordinary fix commits can land on `main` in between (this
  session's own `0.12.0` → CI-fix commits are exactly that case). When
  that happens, `git reset --hard` genuinely pulls new app code, but
  `VERSION` reads the same before and after, so `cmd_upgrade` reported
  "already up to date" and skipped `sync_app_code`/the service restart
  entirely — leaving the running process on stale code indefinitely,
  invisible until an operator manually restarted `groundctl.service` (as
  happened here) or went looking. Same shape as the `0.10.4` fix to this
  same function's `install_maintain_script` gating, but hitting the
  running service itself instead of the `groundctl-maintain` binary.
  Fixed by gating on whether `HEAD` actually moved (`git rev-parse HEAD`
  before/after the reset), not on `VERSION` — the real signal for "is
  there new code to deploy." Verified against three live disposable git
  remote scenarios: no new commits still correctly reports "already up to
  date" and touches nothing; new commits with `VERSION` unchanged now
  correctly redeploys (`sync_app_code`, service restarts, etc.) instead of
  silently skipping; a genuine version bump still upgrades and reports
  correctly, and a follow-up re-run correctly no-ops.

## [0.11.0] - 2026-08-04

### Added: browse an upstream archive and multi-select distributions to mirror, instead of creating repositories one at a time

- New `POST /repositories/probe` — given an `archive_url`, fetches its
  `dists/` directory listing (the standard Apache/nginx autoindex every
  apt archive publishes) and returns the distribution names found (e.g.
  `jammy`, `jammy-updates`, `jammy-security`). Read-only, one outbound
  HTTP GET, nothing persisted; gated at `require_role(operator)` — the
  same role already required to actually create a mirror from that
  archive_url, since probing is strictly less powerful than mirroring.
  New `app/archive_probe.py` parses the listing HTML directly (aptly has
  no "browse an archive" concept of its own, so this doesn't go through
  `AptlyClient`); response size is capped and the parent-directory link
  is excluded. Verified live against `archive.ubuntu.com/ubuntu` (55
  real distributions parsed correctly).
- New `POST /repositories/batch` — given the same `archive_url` plus a
  list of selected distributions and shared components/architectures,
  creates one `Repository` (aptly mirror) per distribution, named after
  the distribution itself. Failures are reported per-item
  (`RepositoryBatchCreateResult.errors`) rather than aborting the whole
  batch — one distribution's name already existing, or aptly rejecting
  one of several mirrors, shouldn't discard the others that succeeded.
- Web UI: "New repository" is now a two-step flow — enter an archive
  URL and browse it, then check off which distributions to mirror
  (shared components/architectures for the batch) — replacing the old
  single-distribution form that required already knowing the exact
  distribution name, components, and architectures to type in by hand.
- The single-repository `POST /repositories` endpoint is unchanged and
  still available (e.g. for scripting against one exact mirror
  directly); the batch/probe endpoints are additive.

## [0.12.0] - 2026-08-04

### Added: generated one-shot server enrollment script — Satellite "Global Registration" equivalent

- New `GET /enrollment/script?token=<activation-key-token>` — returns a
  ready-to-run shell script (`text/x-shellscript`) for a brand-new host:
  it calls the existing `POST /enrollment/register` (creating the
  `Server` row, inheriting the activation key's environment/host group —
  see `docs/quickstart.md` step 13, previously only documented as a raw
  `curl` command run by hand) and then installs groundctl's shared fleet
  SSH public key into `/root/.ssh/authorized_keys`, closing the gap
  where self-registration created the DB row but never actually SSHed
  to the host — an operator had to separately, manually copy the fleet
  key over before `POST /jobs/bootstrap` would work. Same auth posture
  as `/enrollment/register` itself: unauthenticated beyond the
  activation-key token, which *is* the credential (see
  `docs/limitations.md` — a leaked token now grants standing SSH access
  via this path, not just a bogus `Server` row, documented there).
- New `GET /enrollment/ssh-public-key` — the fleet SSH public key as
  plain text, unauthenticated (a public key isn't a secret — same trust
  model as GitHub's `/user.keys`). The generated script fetches this at
  run time rather than embedding a copy, so it always installs the
  current key even if the fleet key is rotated after the script was
  downloaded/saved.
- Web UI: the activation-key creation dialog now shows a ready-to-copy
  `curl -sSL .../enrollment/script?token=... | sudo bash` command
  alongside the raw token, matching Satellite's registration-command
  copy button.
- Verified live end-to-end (`tests/test_enrollment.py`): a real
  uvicorn-served instance, the actual generated script executed via
  `bash` (not just `bash -n` syntax-checked), confirming it genuinely
  registers the host over HTTP and genuinely writes the fleet key into
  `authorized_keys` — plus a defensive-quoting test confirming a
  maximally hostile token value can't break the generated script's
  syntax.

### Fixed: CI failures in the repository-batch-create endpoint and the repositories UI, caught after this version's other changes landed

- `mypy app/` (CI): `create_repositories_batch` (`app/routers/repositories.py`)
  collected raw `Repository` ORM objects into a list typed for
  `RepositoryBatchCreateResult.created: list[RepositoryRead]`. It worked
  at runtime (FastAPI serializes ORM objects via `response_model`'s
  `from_attributes`), but the static type was wrong. Fixed by converting
  each `Repository` to `RepositoryRead.model_validate(...)` before
  appending. Verified with `mypy app/` (clean) and the full
  `test_repositories.py` suite (20/20, unaffected).
- `npm run build` (CI, `tsc -b`): `RepositoriesPage.tsx`'s batch-create
  success toast indexed `result.created[0]` inside a `.length > 0`
  check — with `noUncheckedIndexedAccess` enabled, TypeScript can't
  narrow an index access from a separate `.length` check, so it's still
  typed as possibly `undefined`. Fixed by checking `result.created[0]`
  directly rather than relying on the length check to imply it.
  Verified with the actual CI command, `npm run build` (`tsc -b && vite
  build`), not just `tsc --noEmit` (which doesn't catch project-reference
  build-mode errors) — confirmed passing end-to-end.

### Fixed: `groundctl-maintain upgrade` skipped reinstalling itself when VERSION hadn't changed, even if the script's content had

- `install_maintain_script` (re-copying `scripts/groundctl-maintain.sh`
  to `/usr/local/bin/groundctl-maintain`) only ran inside the "something
  changed" branch of `cmd_upgrade`, gated on comparing `VERSION` before
  and after the `git reset --hard origin/main`. Found live, immediately
  after `0.10.3` shipped `regen-cert`: a real host's checkout had already
  landed on `v0.10.3` from an earlier pull (before `regen-cert` itself
  was pushed in a later, non-version-bumping commit within the same
  `0.10.3` cycle), so a subsequent `groundctl-maintain upgrade` correctly
  saw no `VERSION` diff and reported "already up to date" — but silently
  skipped reinstalling `/usr/local/bin/groundctl-maintain`, leaving the
  *installed* binary without the `regen-cert` subcommand the checkout's
  own `scripts/groundctl-maintain.sh` already had. `sudo groundctl-maintain
  regen-cert` failed with "unknown command" until a full `install.sh`
  re-run (which unconditionally reinstalls it) was run instead. `VERSION`
  not changing does not mean the script's content didn't change — this
  project doesn't bump `VERSION` on every single commit. Fixed by moving
  `install_maintain_script` outside the version-diff gate so it always
  runs (cheap — a single `install`), before the "already up to date"
  early return. Verified against two real disposable git remotes: a
  checkout already sitting on the latest `VERSION` still gets
  `groundctl-maintain` reinstalled and correctly reports "already up to
  date" with every other provisioning step skipped; a checkout genuinely
  behind still performs the full upgrade with `install_maintain_script`
  called exactly once, not duplicated.

## [0.10.3] - 2026-08-04

### Added: `groundctl-maintain regen-cert` — regenerate the self-signed TLS cert without a full reinstall

- New subcommand alongside `upgrade`. Reads the fleet hostname back from
  `/etc/groundctl/groundctl.env`'s `PUBLISHED_REPO_BASE_URL` (no
  re-prompting), backs up the existing cert/key pair to
  `/etc/groundctl/tls/backup-<timestamp>/`, regenerates via the same
  `_generate_tls_cert` helper `install.sh`'s `ensure_tls_cert` uses
  (factored out of it, no duplicated openssl/chown/chmod logic), and
  restarts `groundctl` + `nginx` to pick up the new cert. Direct
  motivation: `ensure_tls_cert` never overwrites an existing cert on its
  own (by design, to avoid clobbering a swapped-in CA-issued cert on a
  routine re-run) — after `0.10.2`'s ED25519→P-256 fix, there was no
  supported way to force a regeneration short of manually deleting the
  cert files and re-running all of `install.sh`. Directly motivated by a
  real deployed host that pulled the P-256 fix via `groundctl-maintain
  upgrade` but kept failing with `ERR_SSL_VERSION_OR_CIPHER_MISMATCH` —
  `upgrade` never touches an already-existing cert file, so the fix alone
  wasn't enough to actually resolve a live instance without this.
  Verified live (stubbed root/systemctl calls, real hostname-parsing/
  backup/regeneration logic): the fleet hostname is parsed correctly from
  a real `groundctl.env`, an existing cert is genuinely backed up
  (confirmed by reading back the backed-up file's own CN/key-type) before
  being overwritten, and the regenerated cert has the correct new CN and
  key type.

## [0.10.2] - 2026-08-04

### Fixed: self-signed TLS cert unusable in Chrome (ERR_SSL_VERSION_OR_CIPHER_MISMATCH)

- `ensure_tls_cert` (`scripts/lib/tls.sh`, shared by `install.sh` and
  `install-relay.sh`) generated a self-signed **ED25519** certificate.
  Found live: Chrome failed to negotiate the connection to the web UI at
  all (`ERR_SSL_VERSION_OR_CIPHER_MISMATCH`) — not the normal "connection
  isn't private" warning a browser shows for an untrusted-but-negotiable
  cert, a hard negotiation failure. `curl`/OpenSSL on the host itself
  handled the same cert fine, which is what let this ship unnoticed —
  ED25519 TLS certificate support is genuinely inconsistent across
  browsers/OS TLS stacks, unlike ECDSA P-256. Fixed by switching to
  `-newkey ec -pkeyopt ec_paramgen_curve:P-256`, still meaningfully
  stronger than RSA at a comparable key size and supported by every
  current browser. Verified the generated cert is valid (`id-ecPublicKey`,
  256-bit) and that the cert/key pair genuinely correspond. Existing
  installs keep their ED25519 cert until manually regenerated (delete
  `/etc/groundctl/tls/{cert.pem,key.pem}` and re-run `install.sh` —
  `ensure_tls_cert` never overwrites an existing cert/key pair on its
  own, matching every other idempotent step's don't-clobber posture).

### Fixed: main silently stopped tracking dev once a version was already tagged

- `.github/workflows/release.yml`'s "Fast-forward main to dev" step was
  gated behind the same `should_release` condition as the tag/release
  step — so once `VERSION`'s value had already been tagged (`v0.10.1`,
  pointing at an older commit), *every* subsequent commit pushed to
  `dev` — including two real, already-released-in-this-changelog fixes —
  never reached `main` at all, silently, until the next `VERSION` bump.
  Found live: a host pulling from what was believed to be an up-to-date
  checkout was still hitting a bug already fixed two commits earlier,
  traced to `main` being stuck two commits behind `dev`. Promoting
  CI-passing code to `main` and cutting a version tag are different
  questions; only the tag should wait on a version bump. Fixed by
  splitting the two: the fast-forward now runs unconditionally on every
  successful CI run on `dev`, moved to the first step in the job.
  Rewritten as a direct `git push origin HEAD:refs/heads/main
  --force-with-lease="main:<expected-sha>"` instead of `git checkout
  main && git merge --ff-only && git push` — checking out `main` in the
  job's own working tree would have left every later step (the `VERSION`
  check, the `CHANGELOG.md` extraction) reading `main`'s stale files
  instead of `dev`'s, a second bug introduced by the split during initial
  implementation and caught before ship via local verification (below),
  not live. `--force-with-lease` scoped to `main`'s exact expected SHA is
  a fast-forward-or-fail, not an actual force-push over unknown state.
  Verified against a real disposable git remote: a clean fast-forward
  succeeds and is a genuine fast-forward (not a rewrite — confirmed via
  git's own `sha1..sha2` vs `+sha1...sha2` push-summary distinction); a
  divergence introduced between the `fetch` and the `push` (simulating a
  hotfix landing directly on `main`) correctly fails with `[rejected]
  (stale info)`, exit 1, rather than overwriting the divergent commit.

## [0.10.1] - 2026-08-04

### Added: install.sh creates the first admin user, closing the fresh-install-to-usable-login gap

- `POST /auth/register` is admin-only (real, enforced RBAC), so a fresh
  install previously had zero users and no way to create one via the
  API — the only path was a manual Python one-liner run by hand on the
  box (`docs/quickstart.md`'s old step 1), and the web UI's login screen
  gave no hint this was required. Found via a real first-time install.
  New `ensure_first_admin_user` (`scripts/lib/app.sh`), called from
  `install.sh`'s `main()` after migrations run: prompts for username
  (default `admin`) and email via the existing `prompt_if_unset` helper,
  and for a password via a masked (echo-disabled) prompt entered twice
  to catch typos, validated for a mismatch and a minimum 8-character
  length with a re-ask loop on either failure. Flags aren't offered for
  these (a password must never appear in shell history/process list) —
  `GROUNDCTL_ADMIN_USERNAME`/`GROUNDCTL_ADMIN_EMAIL`/
  `GROUNDCTL_ADMIN_PASSWORD` env vars bypass the prompts for scripted
  installs, matching the existing `GROUNDCTL_FLEET_HOSTNAME` convention.
  If no password is supplied and stdin isn't a real terminal (piped/cron/
  CI), a random password is generated (`openssl rand -base64 18` —
  already a hard dependency) and printed exactly once in the final
  install summary rather than hanging on an unanswerable prompt.
  Idempotent like every other install step: silently skipped if any
  `role=admin` user already exists, so re-running `install.sh` after a
  `git pull` never re-prompts for credentials already set. Credentials
  are passed to the embedded Python user-creation call via `sys.argv`
  positional arguments, never string-interpolated into the script
  source — the same injection-safety pattern just applied to
  `release.yml`'s `RELEASE_NOTES` handling, this time built in
  proactively. Verified live: the full password-prompt loop (mismatch →
  retry, too-short → retry, valid → accept) exercised via `expect`
  against the real script logic; a password containing double quotes,
  single quotes, backticks, `$var`, `$(command)`, and `${braces}` passed
  through the exact `sys.argv` pipeline against a real Postgres instance,
  confirmed to land unmangled and to hash/verify correctly (right
  password accepted, wrong password rejected); the idempotency check
  query confirmed to correctly return empty before a user exists and the
  correct username after.

### Fixed: fresh install failing at SSH keypair generation with "Permission denied"

- `ensure_ansible_keypair` (`scripts/lib/app.sh`) ran `chown
  groundctl:groundctl` on `/etc/groundctl/ansible-keys` *after* calling
  `sudo -u groundctl ssh-keygen -f ${key_dir}/id_ed25519` — but `mkdir -p`
  just above it creates that directory as root (the whole script runs as
  root), so on a genuinely fresh install `ssh-keygen` tried to write into
  a directory the `groundctl` user didn't yet own and failed with
  "Permission denied," aborting `install.sh` mid-`main()` before TLS,
  `groundctl.env`, the Postgres role/db, migrations, or any systemd
  service ever got set up. Only worked by accident on a re-run, once the
  directory already existed with the right owner from a prior successful
  pass. Found via a real first-time install on Ubuntu. Fixed by moving
  the `chown`/`chmod` of the directory to before `ssh-keygen` runs, with
  a final `chown`/`chmod` on the two key files themselves afterward as a
  defensive follow-up (in case `ssh-keygen`'s own umask left them looser
  than intended).

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

[Unreleased]: https://github.com/OWNER/groundctl/compare/v0.14.0...HEAD
[0.14.0]: https://github.com/OWNER/groundctl/releases/tag/v0.14.0
[0.13.2]: https://github.com/OWNER/groundctl/releases/tag/v0.13.2
[0.13.1]: https://github.com/OWNER/groundctl/releases/tag/v0.13.1
[0.13.0]: https://github.com/OWNER/groundctl/releases/tag/v0.13.0
[0.12.1]: https://github.com/OWNER/groundctl/releases/tag/v0.12.1
[0.12.0]: https://github.com/OWNER/groundctl/releases/tag/v0.12.0
[0.11.0]: https://github.com/OWNER/groundctl/releases/tag/v0.11.0
[0.10.3]: https://github.com/OWNER/groundctl/releases/tag/v0.10.3
[0.10.2]: https://github.com/OWNER/groundctl/releases/tag/v0.10.2
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
