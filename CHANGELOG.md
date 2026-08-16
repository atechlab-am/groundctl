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

## [0.37.0] - 2026-08-17

### Changed: simplified lifecycle environment creation (BREAKING)

Pre-1.0 — see `docs/releasing.md`, no stability guarantee yet — but this
is a real breaking change to the API/CLI contract, called out explicitly
since it removes previously-required fields rather than just adding
optional ones.

- `POST /lifecycle-environments` now only takes `name`, `description`,
  `prior_environment_id` (replaces `path_name`+`position` — the
  predecessor in the promotion path, instead of raw path bookkeeping),
  and an optional `gpg_key_id` — matches Satellite's own "New Lifecycle
  Environment" dialog. `content_view_id`/`distro`/`release`/
  `publish_prefix` are **removed** from the creation payload entirely.
- `content_view_id`/`release`/`publish_prefix` are now derived and
  permanently locked in on the environment's first promote instead:
  `POST /{id}/promote` now requires `content_view_version_id` explicitly
  when the environment has never been promoted (no more defaulting to
  "the content view's latest version" — there's no "the content view"
  yet), derives `release` from that version's content view's first
  member repository, sets `publish_prefix` to the environment's own
  name, and — if no `gpg_key_id` is set — requires `allow_unsigned: true`
  explicitly (same enforcement creation used to do, moved to the point
  content actually gets published).
- Dropped `LifecycleEnvironment.distro` — write-only, never read
  anywhere in the codebase since `render_apt_source` only ever consumed
  `release`.
- New `PATCH /lifecycle-environments/{id}` (description/gpg_key_id) —
  the only way to add a signing key to an environment before its first
  promote, since creation no longer asks for one.
- New `GET /lifecycle-environments?promotable_for_content_view_id=` —
  environments already tied to a content view OR never promoted
  anywhere yet (valid first-promote targets); separate from the
  existing `content_view_id` filter, which stays exact-match-only.
- `bootstrap_task`/beacon checkin both now fail loudly (not silently
  render a broken apt source line) if a server's environment has never
  been promoted.
- Web UI: environment creation dialog is now three fields. Environments
  with no content view yet get a distinct "Promote…" flow (explicit
  version picker + signing choice) instead of the one-click "Promote
  latest" already-linked environments use.
- CLI: `groundctl environment create` drops `--path-name`/`--position`/
  `--content-view-id`/`--distro`/`--release`/`--publish-prefix` in favor
  of `--prior-environment-id`; new `groundctl environment update`.

## [0.36.0] - 2026-08-17

### Added: content view version deletion

- New `POST /content-views/{id}/versions/{version_id}/delete` — deletes a
  version and the aptly snapshots its publish created, as a tracked Job
  (new `JobType.delete_content_view_version`). Blocked (409), before a
  Job is even created, if the version is live on any environment right
  now OR was ever promoted in the past — still reachable via
  `POST /rollback` — matching Satellite: a published/promoted version is
  locked in as part of environment history; only a version that was cut
  but never promoted anywhere can be deleted. The task re-checks the same
  guard immediately before deleting, closing the race window between the
  request and the task running.
- New `ContentViewVersion.all_snapshot_names` — `do_publish` now records
  every aptly snapshot a cut creates, including intermediates never
  referenced by the existing `snapshots` field (the raw pre-filter
  snapshot and any intermediate filter-chain steps, for content views
  with filters). Without this, deleting a filtered content view's version
  would only remove its final snapshot and leak the intermediates in
  aptly forever. Nullable — versions cut before this column existed fall
  back to deleting just their recorded final snapshot names.
- New `AptlyClient.delete_snapshot`.
- Web UI: version rows in the content view detail page gained a Delete
  action (disabled when the version is live on an environment; the
  past-promoted case surfaces via the server's 409). CLI:
  `groundctl content-view delete-version`.

## [0.35.0] - 2026-08-16

### Added: combined create-version-and-promote job, job progress bars

- New `POST /content-views/{id}/publish-and-promote` — cuts a version
  (with an optional description) and promotes it to an environment as
  ONE tracked `Job` (new `JobType.publish_and_promote`). Unlike
  `POST /{id}/publish` and `POST /lifecycle-environments/{id}/promote`
  (both still synchronous, unchanged), this is the first publish/promote
  path backed by a `Job` — aptly's publish/switch-publish call can
  genuinely run long (see `aptly_client.py`'s 1800s timeouts), the same
  "long-running work belongs in a Job" rule every other job-backed
  endpoint already follows. `do_promote` extracted out of
  `promote_environment` into a reusable function (mirrors `do_publish`)
  so the task and the existing synchronous endpoint share one
  implementation.
- Web UI: the content view detail page's "Create new version" button now
  opens a dialog — description field, and an optional "promote to an
  environment now" checkbox that, when checked, creates the job above and
  navigates straight to its status page.
- New `JobProgressBar` component (extracted from the existing
  `JobStatusIndicator`) — an estimated-progress fill based on the
  average duration of that job type's past successful runs (falls back
  to an indeterminate animation with no history), now also shown on the
  job detail page itself, not just the compact indicator.
- CLI: `groundctl content-view publish-and-promote`.

## [0.34.0] - 2026-08-16

### Added: content view version descriptions

- New `PATCH /content-views/{id}/versions/{version_id}` — sets or clears
  a free-text description on an already-published version. Annotation
  only, matching Satellite: the version NUMBER stays the canonical,
  immutable identifier (never renamed), `snapshots`/`content_hash`/
  `package_count` stay write-once at publish time. Deliberately not part
  of `PublishRequest` — publishing can return an existing unchanged
  version on a no-op (nothing changed since the last cut), which would
  make "set the description" ambiguous with "describe what I just cut."
- Web UI: version history rows in the content view detail page gained an
  "Edit" action (description shown inline once set). CLI:
  `groundctl content-view set-version-description`.

## [0.32.0] - 2026-08-16

### Added: Beacon local reconciliation and facts push (Phase 9 / Beacon, parts 3-4)

- The agent (`beacon/groundctl_beacon.py`) now does real local
  reconciliation, not just checkin logging: writes the current apt source
  line + keyring, removes every other `groundctl-*` file it finds via its
  own local directory glob (hardcoded two-directory, one-prefix
  allowlist — the server never tells it which filenames to delete, since
  that would mean tracking per-host disk state server-side), runs
  `apt-get update` with a bounded local retry (3 attempts), and reports
  the outcome via new `POST /api/beacon/report`. A failed reconciliation
  does not advance `applied_config_serial`, so the host stays visibly
  "pending" until a future checkin succeeds.
- `promote_environment`/`rollback_environment` now bump `config_serial`
  for every beacon-managed server in the affected environment — a
  content-view-version switch means those hosts should re-run
  `apt-get update` even though their source line itself didn't change.
- New `app.apt_sources.export_gpg_public_key`, shared between the
  existing `GET /lifecycle-environments/{id}/gpg-key` endpoint and the
  checkin response's `gpg_public_key` field, instead of two copies of the
  same `gpg --export --armor` subprocess call.
- New `POST /api/beacon/facts` — full facts push (packages, disk,
  services), writing the same `ComplianceRecord`/`ServerFact` rows
  `gather_facts_task` already writes. New `source` column on both tables
  (`"ssh"` default, `"beacon"` here) — every existing consumer
  (`do_check_compliance`, `GET /servers/{id}/facts`, the weekly scan)
  works unchanged, since none of them filter or branch on how a row was
  gathered. Push cadence is ~6h, tracked separately from the 5-minute
  checkin interval; the existing weekly SSH-based compliance scan keeps
  running unconditionally on every host regardless of beacon status.
- New fleet-health Prometheus gauges: `groundctl_beacon_enabled_servers`,
  `groundctl_beacon_checked_in_recently`,
  `groundctl_beacon_pending_reconciliation`.
- Dispatched actions (beacon-executed apply-updates) and the install
  rollout (install script, SSH-triggered fleet install job, `.deb`
  packaging) are not built yet — see `ROADMAP.md` Phase 9 for what's left.

## [0.33.0] - 2026-08-16

### Added: Beacon dispatched actions and install rollout (Phase 9 / Beacon, parts 5-6)

- `POST /jobs/apply-updates` and the bulk variant now pick beacon vs. SSH
  transport per target server: a server with an active `BeaconToken` gets
  a new `BeaconAction` row queued instead of an Ansible run, picked up on
  its next checkin and resolved via `POST /api/beacon/report`. A Job with
  any beacon-dispatched targets stays `running` (a new `"pending_beacon"`
  sentinel status) until every dispatched action reaches a terminal
  state, then closes automatically — `failed`/`timed_out` fails the Job,
  otherwise it succeeds.
- New scheduled task (`scheduled_timeout_stale_beacon_actions`, every 5
  minutes) marks any `BeaconAction` stuck `pending`/`delivered` for more
  than 30 minutes as `timed_out` and finalizes its Job — closes the "Job
  hangs forever if a beacon goes dark mid-dispatch" gap.
- `POST /jobs/{id}/cancel` now also cancels any still-`pending` (not yet
  delivered) `BeaconAction` for that job.
- `beacon/groundctl_beacon.py` now executes dispatched actions from its
  checkin response (`apply_updates` today) and reports each outcome back
  with its `action_id`; it also pushes facts via `POST /api/beacon/facts`
  when the checkin requests it, closing the last gap from 0.32.0's facts
  push.
- New install rollout: `GET /api/beacon/agent` serves the agent file
  itself; `GET /api/beacon/install-script?token=...` (modeled on
  `enrollment.get_enrollment_script`) generates a self-contained install
  script for an already-registered host; `POST
  /jobs/install-beacon/{server_id}` (new `install_beacon` Job type) rolls
  Beacon out to an existing fleet over SSH, minting its `BeaconToken`
  server-side inside the Celery task (new shared `app.auth.mint_beacon_token`,
  also now used by `POST /servers/{id}/beacon-token`) and delivering it via
  `ansible.builtin.copy` with `no_log: true`, never through `extra_vars`.
- `.deb` packaging remains unimplemented — lowest-priority polish item,
  not required for either install path above. Phase 9 is otherwise
  complete; see `ROADMAP.md`.
- New `GET /servers/{id}/beacon-state` (viewer-gated) — the first
  operator-facing read endpoint for `ServerBeaconState`; previously only
  written, never read outside the beacon's own checkin. Returns a
  computed `pending_reconciliation` boolean using the same NULL-safe
  comparison as the Prometheus gauge.
- Web UI: server detail page gained a "Beacon" tab (reconciliation state,
  token issue/list/revoke) and an "Install Beacon" action; a
  pending-reconciliation badge shows next to the existing status badges.
  Job trigger dialog now offers `install_beacon`.
- CLI: `groundctl server assign-environment`, `beacon-state`,
  `beacon-token issue/list/revoke`, and `groundctl job trigger-install-beacon`.

## [0.31.0] - 2026-08-16

### Added: Beacon identity and checkin protocol (Phase 9 / Beacon, part 2)

- New `BeaconToken` model — a per-server credential for the optional
  Beacon agent, deliberately separate from `ActivationKey` (which is
  fleet-wide/multi-use/pre-shared by design; a beacon credential needs to
  be the opposite: bound to exactly one server, individually revocable).
  Same SHA-256 hash-only storage posture as `ActivationKey`/`RefreshToken`
  — the three now share one canonical `app.auth.hash_opaque_token`
  instead of each defining their own hasher. Non-expiring, cut off only
  by explicit revocation. `POST /servers/{id}/beacon-token` (issue,
  operator-only, returns the raw token exactly once),
  `GET /servers/{id}/beacon-tokens` (list metadata, never the hash),
  `POST /servers/{id}/beacon-tokens/{token_id}/revoke`.
- New `get_current_beacon_server` auth dependency (`app/auth.py`) — a
  second, deliberate non-JWT auth path (`HTTPBearer`, not
  `OAuth2PasswordBearer`) for the agent, mirroring `enrollment.py`'s
  existing "isolated, prominently-commented auth exception" precedent. No
  beacon endpoint anywhere accepts a `server_id` parameter — identity
  always comes from the presented token, never the request.
- New `POST /api/beacon/checkin` (`app/routers/beacon.py`) — the agent's
  combined poll. Returns a desired-state document (environment info, a
  server-side-rendered apt source line, a config serial) and makes
  `Server.last_seen_at` a genuine heartbeat for beacon-managed hosts
  (previously true only for SSH-triggered activity). New
  `ServerBeaconState` tracks `config_serial`/`applied_config_serial` — an
  explicit "pending reconciliation" signal, bumped by
  `POST /servers/{id}/assign-environment` when a beacon-enabled server is
  reassigned.
- New `app/apt_sources.py` — the single canonical apt-source-line
  renderer, now shared by both `bootstrap_task` (SSH path) and the
  checkin endpoint, instead of the SSH path's Jinja template and the
  agent's response format inevitably drifting into two divergent
  implementations of the same injection-sensitive string.
- New single-file, stdlib-only agent (`beacon/groundctl_beacon.py`, no
  build step or third-party dependencies) implementing checkin-only mode
  today, plus `groundctl-beacon.service`/`.timer` systemd units (a
  `oneshot` service on a 5-minute timer, not a persistent daemon — matches
  the agent's "no long-lived state" design). See `docs/beacon.md` for the
  full non-goals list (no arbitrary command execution, no general
  configuration management, no unattended `apt-get upgrade` — only what
  groundctl explicitly dispatches).
- Local `sources.list` reconciliation, facts/telemetry push, and
  dispatched actions (e.g. beacon-executed apply-updates) are not built
  yet — see `ROADMAP.md` Phase 9 for what's left. The checkin response
  already carries the fields those will need (`stale_source_filenames`,
  `gpg_public_key`, `facts_requested`, `actions`) so adding them later
  won't be a breaking response-shape change.

## [0.30.0] - 2026-08-15

### Added: server environment reassignment (Phase 9 / Beacon, part 1)

- New `POST /servers/{id}/assign-environment` — the first real, deliberate
  way to change which lifecycle environment an existing server belongs
  to. Previously `Server.environment_id` was set once at
  creation/self-registration and never touched again anywhere in the
  codebase — there was no bug to fix here, the endpoint genuinely didn't
  exist. Operator-gated, blocked on a decommissioned server, idempotent
  no-op if already assigned, audited via new `AuditAction.assign_server_environment`
  with from/to environment ids+names+reason.
- `bootstrap_client.yml` changed from purely-additive to replace-in-place:
  a content host now trusts exactly one groundctl-managed environment at
  a time. Before writing the new `groundctl-<env>.list`, a re-bootstrap
  now removes every other `groundctl-*` source/keyring file already on
  the host — without this, a reassigned server would keep silently
  trusting its old environment's repo alongside the new one, defeating
  the entire point of reassignment.
- This is Phase 9 (see `ROADMAP.md`) of a larger planned addition —
  **Beacon**, an optional pull-based host agent — but the reassignment
  endpoint above is fully useful standalone today via a manual
  `POST /jobs/bootstrap/{id}` re-run; the remaining Beacon work (agent
  checkin, local reconciliation with no SSH round-trip, facts/telemetry
  push, dispatched apply-updates actions) lands in later releases.

## [0.29.0] - 2026-08-15

### Added: content views auto-publish version 1 on creation, and can be named with a description

- New `ContentView.description` (optional) — content views could
  previously only be named, matching Satellite's own create dialog now
  requires a name and offers a description field alongside it.
- Creating a content view now cuts version 1 immediately, from the member
  repositories' current package state, in the same request — previously
  a newly created content view was an empty shell with zero versions
  until someone remembered to hit Publish separately. Matches Satellite,
  where a content view always has an initial version as soon as it's
  created. If aptly is unreachable at that moment, the whole creation
  fails (502) rather than leaving a content view with nothing to
  promote — same posture as every other aptly-backed operation here.

## [0.28.0] - 2026-08-14

### Added: on-demand version check, in-app changelog viewer, GitHub link, and an always-in-sync README

- New admin-only `POST /version/check-now` — runs the same GitHub
  releases lookup `scheduled_check_for_new_version` performs once daily
  via Celery Beat, but synchronously and on demand. The header's version
  badge previously only ever reflected whatever the last scheduled check
  found, with no way to force a fresh look or tell whether Beat had even
  run yet on a given install — this closes that gap and gives an "Update
  available" state a hard "Check now" escape hatch. Both call sites now
  share one `refresh_version_check` implementation
  (`app/version_check.py`) so they can't drift in behavior.
- New `GET /version/changelog` serves this deploy's own `CHANGELOG.md`
  (synced into `/opt/groundctl` by `sync_app_code`, same pattern as
  `VERSION` itself). The header's version area now has a "Changelog"
  button opening an in-app markdown viewer, plus a "GitHub" link to the
  repo — previously the only way to see release notes was clicking
  through to a specific GitHub release tag, and there was no link to the
  repo itself anywhere in the app.
- `README.md`'s `**Version:** [X.Y.Z](CHANGELOG.md#...)` line was 5
  releases stale (hand-maintained, nobody remembers to update it every
  release). Fixed now, and `release.yml` gained a step that rewrites and
  commits that line automatically as part of every release going
  forward — it can't drift again the way it just did.

## [0.27.1] - 2026-08-14

### Changed: "Create new version" always cuts a version, even with nothing changed

- `POST /content-views/{id}/publish` previously always deduped against
  the latest version's content hash — publishing with nothing changed
  since the last version was a no-op that returned the existing version
  unchanged (`version_cut: false`). New optional `force` field on the
  request body always cuts a new version regardless of the hash — a
  version doubles as a promotion checkpoint, not purely a content-change
  record, so an operator may want a fresh one to promote even when
  nothing new was synced. The Content View detail page's button (renamed
  from "Publish" to "Create new version") always sends `force: true`;
  the promote-triggered auto-publish path (`promote_environment`'s
  publish-if-needed-then-promote-latest) is unaffected and still only
  cuts a version when content actually changed.

## [0.27.0] - 2026-08-14

### Added: promote a specific content view version from its version list, with live-package counts

- The backend already supported promoting any specific
  `content_view_version_id` to any environment (`POST
  /lifecycle-environments/{id}/promote`), but nothing in the UI ever
  exposed picking one — the only Promote button (on the Environments
  page) always promoted "latest, publishing first if needed." There was
  no way to do a Satellite-style "promote v1 to prod, v2 to dev." Each
  version row on the Content View detail page now has a "Promote to…"
  action that opens a dialog to pick any environment using that content
  view; each row also shows which environments are currently live on it.
- New `ContentViewVersion.package_count` — total packages across a
  version's final, post-filter snapshots (not the source repositories'
  package count, which would overcount whenever the content view has an
  include/exclude filter). Computed once at publish time from
  `AptlyClient.get_snapshot_packages`, summed per unique snapshot name
  (a repo with multiple components reuses one snapshot across several
  entries — counted once, not per component). The version list now shows
  each version's package count and the +/- delta versus the previous
  version, the same "how did this version change" signal Satellite shows.

## [0.26.0] - 2026-08-14

### Added: content views are now listable, deep-linkable, and deletable

- New `GET /content-views` and `GET /content-views/{id}` — the backend
  previously had no way to list or look up an existing content view at
  all (only creation returned one), a gap the frontend had been working
  around with a `localStorage`-backed "known content views" list, visible
  only to the browser that created each one and lost on a fresh
  profile/device. That workaround (`useKnownContentViews.ts`) is removed.
- New `GET /content-views/{id}/filters` to list a content view's existing
  filters, and `DELETE /content-views/{id}/filters/{filter_id}` to remove
  one — filters could previously only be added, never inspected or
  undone once created.
- New `DELETE /content-views/{id}` — blocked (409) if any
  LifecycleEnvironment still references the content view, same guard
  shape as Repository delete's ContentView-reference check. Deletes the
  content view's filters and version history along with it (they have no
  meaning without their parent).
- Content Views page is now a real list + detail pair
  (`/content-views/:id` is deep-linkable) instead of a single page driven
  by in-memory/localStorage selection state — matches every other
  resource's list/detail pattern in this app.

## [0.25.3] - 2026-08-14

### Fixed: repository detail page's "Sync history" list froze finished jobs at "running"

- `jobsQuery` (`RepositoryDetailPage.tsx`) had no `refetchInterval` — it
  fetched the job list once on page load and never again. The live
  indicator above it (`currentJobQuery`) polls every 3s and correctly
  flipped to success/failed when a job finished, but that same job's row
  in the "Sync history" list below stayed stuck at "running" until a
  manual page reload. Now polls every 3s whenever any job currently in
  the fetched list is still pending/running, same cadence as the rest of
  this page's live-status queries, and stops once everything it knows
  about has reached a terminal state.

## [0.25.2] - 2026-08-14

### Changed: job progress bar eases toward completion instead of sliding indeterminately

- `JobStatusIndicator`'s progress bar was a fixed-width chunk bouncing
  back and forth (CSS `animate-indeterminate`) for the entire duration of
  every in-progress job, regardless of how long that job type usually
  takes — accurate (aptly gives no real percent-complete signal) but read
  as "stuck" rather than "progressing." Now fills gradually: eases toward
  95% over the average duration of that job's own past successful runs of
  the same type (and same target repository, when there is one), using an
  ease-out curve so it moves fastest early and slows as it nears the
  estimate. Never claims 100% before the job's real status does — holds
  at 95% if it runs longer than typical. Jobs with no prior successful
  history to average (a new job type, or the very first run) still fall
  back to the old indeterminate animation, since there's nothing honest
  to pace a fill against yet.

## [0.25.1] - 2026-08-14

### Added: `groundctl-maintain upgrade --force`

- `upgrade` treats "HEAD already matches origin/main" as "nothing to do"
  and skips `build_ui`/`sync_app_code`/service restarts entirely — correct
  in the common case, but found live to go wrong when a checkout's HEAD is
  already at the right commit while the deployed artifacts (built
  `ui/dist`, in this case) are stale for some other reason (an earlier
  `upgrade` interrupted mid-build, or code arriving via a plain `git pull`
  outside `upgrade`). `upgrade` reported "already up to date" and left the
  browser served an old JS bundle with no way to force a redeploy short of
  a no-op commit. New `--force` flag redeploys unconditionally even when
  HEAD didn't move.

## [0.25.0] - 2026-08-14

### Added: repository Products (grouping) and health-status indicator

- New `Product` model — groups related repositories under one named parent
  (Satellite's "Product" concept, e.g. jammy + jammy-security +
  jammy-updates grouped as "Ubuntu 22.04"). Purely organizational: a
  Product has no effect on sync/publish/content-view behavior, which all
  still operate per-Repository exactly as before. A repository belongs to
  at most one Product (nullable FK), defaulting ungrouped. Full CRUD at
  `/api/products`; deleting a Product ungroups its member repositories
  rather than blocking, since nothing content-lifecycle-relevant depends
  on the grouping.
- `Repository.product_id` and a new `PATCH /repositories/{name}/product`
  endpoint to assign/unassign; `GET /repositories` accepts an optional
  `product_id` filter.
- New `RepositoryRead.health_status` (`healthy` / `stale` /
  `never_synced`), computed at read time from `last_synced_at` against a
  new admin-configurable `repository_stale_threshold_hours` instance
  setting (Settings > System, default 48h). Display-only — unlike the
  server/relay staleness sweeps, nothing schedules off this or fires a
  webhook for it.
- New `Repository.package_count`, computed in the same sync pass as
  `size_bytes` (`AptlyClient.get_mirror_size_and_count`, one aptly call
  instead of two) — null until the first successful sync, reset to null
  on edit (same lifecycle as `size_bytes`, which previously wasn't reset
  on edit either — also fixed here).
- Repositories page: grouped-by-Product table sections, package-count and
  health-status columns, a "Manage products" dialog (create/edit/delete),
  and a per-repository "Set product…" action. Repository detail page and
  Settings > System gained matching fields.

## [0.24.1] - 2026-08-14

### Fixed: elapsed-time counter froze between polls, repo list/detail data went stale in the background

- `JobStatusIndicator`'s "running… Xm Ys" counter was a pure function of
  `Date.now()` computed only at render time — with nothing forcing a
  re-render between the 3s data polls, the number sat frozen until the
  next poll happened to land (worse with a backgrounded tab, where
  polling throttles further), reading as stuck even though the job itself
  was progressing normally. New `useNow` hook ticks once a second, only
  while a job is actually in-progress, so the counter now genuinely
  updates every second.
- The Repositories list and repository detail page only refreshed
  `size_bytes`/`last_synced_at`/etc. when a mutation triggered *locally*
  invalidated the query — a job that kept running in the background
  (Celery doesn't care whether any browser has the page open) wouldn't be
  reflected until a manual reload, even though the job itself completed
  correctly. Both pages now poll their own data every 10s so a background
  job's result shows up on its own.

## [0.24.0] - 2026-08-14

### Added: job status survives a page reload for Edit/Delete too, and a "usually takes ~Xm" estimate

- New `Repository.last_job_id` (migration `e5c9a173f2b8`) — the most
  recent Job of any kind (sync/update/delete), unlike the existing
  `last_sync_job_id` which only ever tracked Sync. Closing and reopening
  the browser mid-Sync already showed accurate live status (backed by
  `last_sync_job_id`); mid-Edit or mid-Delete it didn't — that tracking
  only lived in in-memory React state, lost on reload, even though the
  job itself was always safe and unaffected. Both the Repositories list
  and the repository detail page now recover live status after a reload
  regardless of which action was running.
- Repositories list: the "Last synced" column now checks whether
  `last_job_id`'s job is still in progress before falling back to the
  plain date — only shows the live indicator while something's actually
  running, so a long-finished job doesn't leave every row permanently
  showing a status badge.
- No real percentage/ETA is possible for sync/edit/delete — aptly gives
  no progress signal, confirmed repeatedly this cycle (single blocking
  call, nothing to poll mid-operation). Added the honest substitute
  instead: while a sync is running, the repository detail page shows
  "Usually takes ~Xm" — the average duration of that repository's own
  past successful syncs, computed from job history already being fetched
  for the sync-history list (no new query).
- Frontend `JobType` was missing `update_repository`/`delete_repository`
  (backend has had them since 0.21.1) — fixed, since the duration
  estimate needs to compare same-type jobs correctly.

## [0.23.0] - 2026-08-13

### Added: per-repository nightly auto-sync toggle

- New `Repository.auto_sync_enabled` (migration `d84f2a6c1e9b`), defaults
  `true` so existing/new repositories keep syncing on the nightly 3am
  sweep (`scheduled_sync_all_repositories`, Celery Beat) unless explicitly
  turned off — that sweep previously looped over every repository
  unconditionally with no way to opt out. Manual sync (the Sync button /
  `POST .../sync`) is unaffected either way, regardless of the flag.
- New `PATCH /repositories/{name}/auto-sync` — lightweight, DB-only (no
  aptly call), operator-role gated. Checkbox toggle on both the
  Repositories list (new "Nightly sync" column) and the repository detail
  page; viewers see a read-only On/Off instead of the checkbox.

### Fixed: repository size always showed 0 / never updated after sync

- `AptlyClient.get_mirror_size_bytes` summed each package's `Size` field
  expecting a Python `int` — confirmed live against a real aptly 1.6.3
  instance that `Size` is actually a JSON **string** (`"84924"`) in
  `?format=details` responses. The type check silently rejected every
  package's size, so this had been summing to 0 for every repository
  since it was introduced, with no error surfaced anywhere. Now accepts
  numeric strings too. New `tests/test_aptly_client.py` — the first direct
  unit test of `AptlyClient`'s own parsing logic (every existing test only
  mocked the method away entirely, which is exactly why this went
  uncaught).
- `AptlyClient.sync_mirror`/`delete_mirror` timeout raised from 30 minutes
  to 6 hours — a real ~100GB first-run `jammy` sync legitimately took just
  over 30 minutes and hit the old ceiling exactly at that mark. Both calls
  always run inside an async Celery job with nobody waiting on the HTTP
  response, so a generous timeout costs nothing except how long a
  genuinely-stuck sync takes to report failure. Re-syncing after a timeout
  is always safe either way — aptly's mirror sync is incremental, it never
  re-downloads what it already has.

## [0.22.4] - 2026-08-13

### Fixed: `install.sh` failed on a real fresh-install run — redis and Node both broken

- `install_redis` (`scripts/lib/app.sh`): hardcoding `bind 127.0.0.1 -::1`
  made redis fail outright on a host with IPv6 disabled at the kernel
  level (`Could not create server TCP listening socket -::1:6379: Name or
  service not known`) — now conditional on `/proc/net/if_inet6` existing.
  Separately, after a purge+reinstall (see `scripts/uninstall.sh` below),
  `/var/lib/redis` didn't exist yet when systemd started the service
  (`Can't chdir to '/var/lib/redis': No such file or directory`) —
  normally recreated by systemd-tmpfiles at boot, but nothing in this
  install flow can rely on a reboot happening first; now created and
  `chown redis:redis`'d explicitly.
- `install_node_prereqs` (`scripts/lib/app.sh`): Debian/Ubuntu's own
  `nodejs` apt package is too old to build this project's UI at all — jammy
  ships Node 12.x, and TypeScript's compiler needs 14+ just to parse (fails
  with a raw `SyntaxError` on `??`, not a clean version message). Replaced
  with a direct, checksum-verified binary tarball from nodejs.org (avoids
  adding NodeSource's apt repo as a second signing-key trust relationship
  for a build-time-only tool). First pin (20.18.1) still wasn't new enough —
  `ui/package.json`'s vite/rolldown versions require `^20.19.0 || >=22.12.0`
  and Node <20.19 makes rolldown's native-binding resolution fail with an
  error that misleadingly blames an unrelated npm bug (npm/cli#4828). Now
  pinned to 22.12.0 (current LTS, not just the bare floor one dependency
  happens to require).
- `build_ui` (`scripts/lib/app.sh`): now clears `ui/node_modules` and npm's
  cache before every `npm ci` — a stale cache from a box's previous
  (much older) system npm can otherwise poison a rebuild after upgrading
  Node, independent of the version fix above.
- New `scripts/uninstall.sh --yes` — tears down everything `install.sh`
  sets up (services, the Postgres database/role, `/opt/groundctl`,
  `/etc/groundctl`, `/var/lib/groundctl`, the `groundctl`/`groundctl-sync`
  users, the templated systemd units) and purges+reinstalls the
  `redis-server` package itself, so a stuck dev box can get back to a
  genuine fresh-install state without hand-running a dozen commands.

## [0.22.3] - 2026-08-13

### Fixed: `redis-server.service` failed to start after `install.sh` (config/systemd daemonize mismatch)

- Confirmed live: a box whose `/etc/redis/redis.conf` had `daemonize yes`
  made `redis-server` fork on startup despite the systemd unit passing
  `--supervised systemd --daemonize no` on the command line — the config
  file's directive won, redis exited 0 (a normal successful daemonization
  from its own perspective), and systemd — tracking that exited process as
  its supervised child — marked the unit `failed`, even though redis was
  actually running fine in the background. `journalctl -xeu redis-server`
  showed no real error at all, just systemd's own "exited, status=1"
  noise, because nothing had actually gone wrong from redis's side.
  `install_redis` (`scripts/lib/app.sh`) now forces `daemonize no`
  unconditionally, the same way it already forces the `bind` line, so
  config and unit file can never disagree regardless of what the box
  shipped with.
- New `scripts/uninstall.sh --yes` — tears down everything `install.sh`
  sets up (services, the Postgres database/role, `/opt/groundctl`,
  `/etc/groundctl`, `/var/lib/groundctl`, the `groundctl`/`groundctl-sync`
  users, the templated systemd units) and purges+reinstalls the
  `redis-server` package itself, so a stuck dev box can get back to a
  genuine fresh-install state without hand-running a dozen commands.

## [0.22.2] - 2026-08-13

### Fixed: 0.22.1's own fix broke installs under a restrictive sudoers policy

- 0.22.1 fixed a directory-permission warning by adding `sudo --chdir=/tmp`
  to every `sudo -u postgres <cmd>` call. Confirmed live on a real dev
  server: a sudoers policy scoped to exact commands
  (`pg_isready`/`psql`/etc., no extra flags permitted) rejects `sudo`'s own
  `--chdir`/`-D` option outright — `sudo: you are not permitted to use the
  -D option with /usr/bin/pg_isready` — even though the base command was
  allowed, breaking `install.sh` at the very first Postgres-readiness
  check on that host. Replaced with `(cd /tmp && sudo -u postgres <cmd>)`
  — changes the *calling* shell's directory before sudo runs, adding no
  sudo-level flag at all, so it can't collide with a restrictive sudoers
  policy anywhere. Same fix in both `scripts/lib/pg.sh` and
  `scripts/backup.sh`.

## [0.22.1] - 2026-08-12

### Fixed: `install.sh` printed a "Permission denied" warning during Postgres setup

- `sudo -u postgres <cmd>` switches user but not directory — every such
  call in `scripts/lib/pg.sh`/`scripts/backup.sh` inherited the invoking
  operator's cwd (typically their checkout, e.g. `~/groundctl`), which the
  `postgres` system user has no permission to enter. Harmless in practice
  (none of these commands actually needed the cwd) but printed a
  confusing `could not change directory to "..." : Permission denied`
  during every real install. All calls now pin `--chdir=/tmp`, universally
  enterable on any standard Debian/Ubuntu install. `backup.sh`'s
  `pg_dump`/`pg_restore` paths are resolved to absolute first so the
  `--chdir` can never change where a backup/restore file actually lands.

## [0.22.0] - 2026-08-12

### Added: live job status (spinner + elapsed time + log) inline on Sync/Edit/Delete

- New `JobStatusIndicator` component — an indeterminate progress bar (no
  fake percentage; aptly gives no progress stream for sync/delete/edit,
  confirmed earlier this cycle), elapsed time since `started_at` while a
  job is `pending`/`running`, and an expand-to-view-log toggle that shows
  `Job.log_output` inline without navigating to the Jobs page. Polls every
  3s while in progress, same as the existing Job detail page.
- Wired into both the Repositories list (each row now shows this in place
  of "Last synced" while its own triggered job — Sync, Edit, or Delete —
  is active) and the Repository detail page (replaces the page's own
  hand-rolled status card). Previously only Sync's job was tracked via
  `last_sync_job_id`; Edit's job wasn't visible anywhere on these pages,
  and Delete's job became untrackable the moment the Repository row itself
  was deleted. Both pages now track whichever job they most recently
  triggered in local state, independent of the persisted field.

## [0.21.2] - 2026-08-12

### Fixed: CI lint/typecheck false failures, and pinned their tool versions

- `tests/test_repositories.py` had a genuine bug — a stray leftover
  assertion (`r.json()["detail"]`) duplicated into the wrong test, where
  `r` was undefined. Ruff caught this correctly as `F821`.
- What CI actually reported, though, was `invalid-syntax: unexpected token
  NUL` — thousands of them, attributed to `app/routers/repositories.py`
  (a file with no relation to the real bug at all, and zero null bytes
  verified byte-for-byte). Root cause: `ruff check` in CI ran unpinned
  (`pip install ruff`), landing on 0.16.2, which appears to mishandle that
  specific F821 case badly enough to misreport it as tokenizer garbage in
  an unrelated file. Fixing the real bug and re-running the identical
  pinned ruff version locally reproduced a clean pass.
- The `typecheck` job's mypy hit the same class of false positive
  independently and unrelatedly — unpinned `pip install mypy` landed on
  2.3.0, which reported the identical "Source code string cannot contain
  null bytes" error for the same file, also unreproducible against a
  pinned install of the identical version against identical content. This
  job is `continue-on-error: true` (non-blocking, pre-existing), so it
  never actually failed the run, but the false signal was worth silencing.
- Both `ruff` and `mypy` are now version-pinned in `.github/workflows/ci.yml`
  (`ruff==0.16.2`, `mypy==2.3.0`) so a future tool release can't
  reintroduce either kind of misleading failure without a deliberate,
  reviewed version bump.

## [0.21.1] - 2026-08-12

### Fixed: repository Delete and Edit timed out and 502'd against a real, non-trivial mirror

- Confirmed live: `DELETE /repositories/{name}` (and `PUT`, "Edit", which
  deletes-then-recreates the mirror under the hood) blocked the HTTP
  request on `aptly.delete_mirror()`, which took long enough against a
  real, fully-synced repository to blow both `AptlyClient`'s default 30s
  timeout AND the reverse proxy's own timeout — `502 Bad Gateway` before
  aptly ever responded, and the repository was left in limbo (mirror
  possibly deleted, DB row not, or vice versa, depending on exactly where
  the timeout landed). `AptlyClient.delete_mirror` now gets the same 1800s
  timeout `sync_mirror`/`publish_snapshot` already use for this class of
  slow operation.
- Same root cause `sync_repository` was fixed for earlier this cycle: both
  endpoints now dispatch async, tracked `Job`s (new `delete_repository_task`/
  `update_repository_task`, `app/tasks.py`) instead of blocking the
  request — `DELETE`/`PUT /repositories/{name}` now return `201` + the
  `Job` immediately, not `204`/`200` + the finished result. New
  `JobType.delete_repository` / `update_repository` (migration
  `b3f6d29e4a17`). Both re-check the ContentView-reference guard inside
  the task itself, not just at the endpoint, closing the race window
  between the request returning and the task actually running.

## [0.21.0] - 2026-08-11

### Added: version number and update notice in the header

- Header now always shows the running instance's own version
  (`vX.Y.Z`, from `VERSION`) and, when a newer GitHub release exists, a
  badge linking straight to it. New `GET /version` (unauthenticated, same
  reasoning as `GET /branding` — polled by every logged-in tab, nothing
  sensitive in a version number). It never calls GitHub itself — reads a
  cache a new daily Celery Beat task (`scheduled_check_for_new_version`)
  maintains via the GitHub Releases API, so an outage or rate limit there
  degrades to "no update info" rather than a slow/broken header for every
  user. New `VersionCheck` singleton table (migration `a91d5c3e7f04`).
  New `app/version_check.py`: plain-semver tuple comparison
  (`is_newer`), deliberately NOT `version_compare.py`'s `dpkg_compare` —
  that's Debian package-version ordering (epochs/tildes), a different
  domain from this app's own `X.Y.Z` release tags.
- **Fixed a real deploy gap found while building this**: `VERSION` was
  never actually deployed anywhere — `scripts/lib/app.sh`'s
  `sync_app_code` copied `app/` and `docs/` but not `VERSION`, so a
  running instance's own process had no way to read its own version at
  all. Now copied alongside `app/` (same sibling-path pattern
  `docs_content.py` already uses for `docs/`).

### Changed: page content no longer centered/width-capped

- `AppShell`'s `mx-auto max-w-6xl` wrapper removed — every page previously
  centered in a 1152px column regardless of viewport width, wasting space
  on wider screens. Content now uses the full width next to the sidebar.

## [0.20.0] - 2026-08-11

### Added: Monitor sidebar section and a Trends page

- Satellite-inspired "Monitor" surface, scoped to what's real here (no
  Statistics/Subscriptions — not applicable to this product): sidebar
  reorganized into a **Monitor** group (Dashboard, Jobs, Compliance,
  Trends, Audit Logs) versus the content/inventory items below it —
  navigation grouping only, no page moved or renamed.
- New **Trends** page (`/trends`) — daily job-outcome and compliance-drift
  charts over a selectable 7/14/30/90-day range. New `GET /trends/jobs`
  and `GET /trends/compliance`, viewer-role read, computed directly from
  existing `Job`/`ComplianceCheckLog` rows (day-bucketed in Python, no new
  storage — job/compliance-check history already *is* the time series).
  Disk-usage-over-time was considered and dropped: it's Prometheus-gauge-only
  today, nothing in groundctl's own DB holds that history to chart.
- New hand-built `StackedBarChart` component (no charting library added) —
  follows the house dataviz rules: ≤24px bars, 2px stacked-segment gaps,
  legend for multi-series, per-bar hover tooltip, status-token colors.
- Retuned dark-mode `--success`/`--destructive` (`#5bc25f`/`#e8484a`,
  `-foreground` switched to the dark-ink token) — the original dark-mode
  pair measured ΔE 4.1 under deuteranopia simulation (should be ≥8), so a
  colorblind reader couldn't reliably tell a green success bar from a red
  failure bar in the new chart. Light mode was evaluated but left
  unchanged: every candidate that fixed light-mode success-vs-destructive
  separation broke destructive-vs-warning instead, locked against this
  app's existing accent/warning hues — status colors rely on their
  icon+label pairing as the real mitigation here (`StatusBadge` always
  shows text, never color-alone), the same posture the dataviz skill's own
  reference status palette takes.

## [0.19.0] - 2026-08-11

### Added: Settings > System — runtime-editable operational tunables

- Satellite-inspired "Administer" surface, scoped to what's actually
  applicable here (no LDAP/subscriptions/licensing — this isn't RHEL): a
  new **System** tab under Settings (admin-only) for 7 operational
  tunables that previously required an env-var change and a restart —
  `audit_log_retention_days`, `activation_key_default_ttl_hours`,
  `stale_checkin_hours`, `relay_stale_threshold_hours`,
  `disk_usage_warn_percent`, `webhook_url`, `webhook_secret`. New
  `InstanceSetting` singleton table (migration `f2b8d64a1c93`, same
  fixed-id-row pattern as `Branding`) — every column nullable, `NULL`
  means "use the config.py/env-var default." Every call site that used to
  read `settings.X` for these 7 fields now goes through
  `app/instance_settings.py`'s `get_effective_settings(db)`, so a change
  takes effect on the next scheduled task run, no restart needed.
- **Deliberately excluded**: connection/secret-shaped config —
  `database_url`, `jwt_secret`, `aptly_api_url`, TLS/SSH key paths — stays
  env-only. `webhook_secret` is the one secret-shaped exception, handled
  write-only (never echoed back by `GET /instance-settings`, same posture
  as a password hash) since rotating it is a legitimate runtime admin
  operation.
- New `GET`/`PUT /instance-settings`, admin-only (`require_role(admin)`) —
  stricter than `GET /branding`'s no-auth, since these are operational
  internals, not something every page load needs. New
  `AuditAction.update_instance_settings`.

## [0.18.0] - 2026-08-11

### Added: edit a site's name/description

- New `PUT /sites/{site_id}` — sites could be created and viewed but never
  edited; `Site.description` has existed on the model since sites shipped
  with no way to set it after creation. New `SiteUpdate` schema (name +
  description, same shape as `SiteCreate`), 409 on rename into an
  already-used name, new `AuditAction.update_site` (migration
  `e7a3c15f9b2d`). Site detail page gained an Edit button/dialog.

## [0.17.0] - 2026-08-11

### Added: repository detail page with live sync status

- New `/repositories/:name` page — repository name in the list is now a
  link there instead of only reachable via the actions menu. Shows every
  field the list truncates, plus the current/most recent sync job's live
  status (polls every 3s while `pending`/`running`, same as the Jobs
  detail page) and a full sync history list, each entry linking to its
  `Job`. Sync/Edit/Delete actions live here too, not just in the list row's
  menu.
- `sync_repository_task` (`app/tasks.py`) now writes a `log_output` line
  ("syncing `<name>` from `<archive_url>`…") the moment it starts, not only
  at completion — previously the job's log stayed blank for the entire
  sync (aptly's mirror sync is a single blocking call with no progress
  stream to report against, so this is honestly what's knowable: that it's
  running, since when, and against what — not a fake percentage).

## [0.16.0] - 2026-08-11

### Added: repository detail view, edit, and delete

- New `GET /repositories/{name}` — single-repository detail (archive_url,
  distribution, components, architectures, size, sync history), previously
  only inspectable via the list endpoint's truncated table or the DB
  directly. Repositories page now shows the archive URL column so it's
  visible without opening anything.
- New `DELETE /repositories/{name}` — deletes both the aptly mirror
  (`AptlyClient.delete_mirror`) and the `Repository` row. Blocked with
  `409` if any content view still references the repository, since the
  content view's cut snapshot would otherwise be left pointing at deleted
  mirror data. `Job.repository_id` now `ON DELETE SET NULL` (migration
  `c4a1f9b2e7d5`, extended from 0.15.0) so past sync job history survives a
  repository's deletion instead of blocking it.
- New `PUT /repositories/{name}` — "edits" a repository's archive_url/
  distribution/components/architectures. Aptly has no in-place way to
  change a mirror's source, so under the hood this deletes the old aptly
  mirror and creates a new one with the given settings under the same
  `Repository` row (same id/name, so `ContentViewRepository`/`Job`
  references stay valid). Resets `last_synced_at`/`size_bytes` — the new
  mirror hasn't synced anything yet. Same `409` content-view guard as
  delete, for the same reason. Repositories page gained Edit/Delete row
  actions alongside the existing Sync button.

## [0.15.0] - 2026-08-11

### Added: repository size estimate/actual, and async-tracked sync jobs

- New **estimate size before creating** a repository — `POST
  /repositories/estimate-size` fetches upstream `Packages.gz` for the
  chosen distribution/components/architectures and sums each package's
  `Size` field (`app/archive_probe.py`). Best-effort: a missing
  component/arch combination is skipped rather than failing the whole
  estimate. Wired into the "New repository" dialog as a per-distribution
  "Estimate size" button.
- New **actual mirror size** shown after sync — `Repository.size_bytes`
  (migration `c4a1f9b2e7d5`), computed from real package data via
  `AptlyClient.get_mirror_size_bytes`, recorded after every manual and
  nightly-scheduled sync. New "Size" column on the Repositories page.
- **Repository sync is now an async, tracked `Job`** instead of a blocking
  inline aptly call — `POST /repositories/{name}/sync` creates a
  `sync_repository` job and dispatches it via Celery (`sync_repository_task`,
  `app/tasks.py`), returning the `Job` immediately instead of waiting for
  the sync to finish. New `Job.repository_id` / `JobTargetType.repository`
  and `Repository.last_sync_job_id` (migration `c4a1f9b2e7d5`). The
  Repositories page's "Last synced" cell links to the job's status page so
  an in-progress sync can be followed instead of just waiting on a spinner.

### Changed: `POST /repositories/{name}/sync` response shape (breaking)

- Returns `201` + the created `JobRead` (job starts `pending`), not `200` +
  the `RepositoryRead` with `last_synced_at` already set. Callers polling
  this endpoint for a synchronously-updated repository must instead poll
  `GET /jobs/{id}` until `status` is `success`/`failed`. The CLI's
  `groundctl repository sync` and web UI are both updated for this; any
  other script calling this endpoint directly needs to change.

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
