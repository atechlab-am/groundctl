# Beacon

Beacon is an **optional**, pull-based agent for a groundctl-managed
content host — the `katello-agent`/`goferd` analogue (see `CLAUDE.md`'s
component table). Nothing about groundctl requires it: SSH/Ansible
remains the primary mechanism for every existing operation, and stays
available as a fallback on beacon-managed hosts indefinitely. Beacon
exists to make two things faster and cheaper at fleet scale: getting an
environment reassignment onto a host without an SSH round trip, and
collecting facts/telemetry without paying SSH-per-poll cost.

See `ROADMAP.md`'s Phase 9 section for what's built vs. planned.

## Design principle: thin, stateless, rebuildable from scratch

Same posture as Relay (`ROADMAP.md` Phase 5): Beacon holds no
authoritative state and makes no decisions of its own. It has a token and
the last config serial it successfully applied — nothing else survives a
reinstall. Every desired-state fact (which environment, which apt source
line, which packages to install) is re-fetched from groundctl on every
poll, never cached beyond that poll, and always driven by groundctl's own
`Job`/Celery system, never invented locally.

## What Beacon does

- Polls `POST /api/beacon/checkin` on a server-controlled interval
  (`checkin_interval_seconds` in the response, 300s by default).
- Writes the current apt source line + keyring, and removes every other
  `groundctl-*` file it finds via its own local glob of
  `/etc/apt/sources.list.d/` and `/etc/apt/keyrings/` (the server never
  tells it which filenames to delete — see the design principle above),
  then runs `apt-get update` with a bounded local retry. Reports the
  outcome via `POST /api/beacon/report`; a failed attempt does not
  advance `applied_config_serial`, so the host stays visibly "pending
  reconciliation" until a future checkin succeeds.
- Pushes full facts (installed packages, disk, services) via
  `POST /api/beacon/facts` roughly every 6h (separate cadence from the
  5-minute checkin) — written into the same `ComplianceRecord`/
  `ServerFact` tables `gather_facts_task` already writes (new `source`
  column: `"ssh"` vs `"beacon"`), so every existing consumer
  (`do_check_compliance`, the weekly scan, `GET /servers/{id}/facts`)
  works unchanged. The weekly SSH-based scan keeps running regardless of
  beacon status — no skip-logic, mixed-source history for one server is
  expected.
- Executes a task groundctl explicitly dispatches to it (currently
  `apply_updates` — `apt-get update && apt-get upgrade -y`) and reports
  the outcome via `POST /api/beacon/report` with that action's `action_id`,
  closing the same `Job` row an SSH-driven run of the same task would
  have closed. `POST /jobs/apply-updates`/the bulk variant pick beacon vs.
  SSH transport per target server transparently; a Job with any
  beacon-dispatched targets stays `running` until every dispatched
  `BeaconAction` resolves (via `/report` or a 30-minute timeout sweep) —
  see `ROADMAP.md` Phase 9's dispatched-actions item.

## What Beacon does NOT do

This is the load-bearing safety property of the whole subsystem — stated
explicitly because it's easy to accidentally erode one endpoint at a time:

- **No arbitrary command execution.** `run_command_task` (SSH/Ansible,
  admin-only) stays the one place arbitrary commands run. No beacon
  endpoint returns a command string of any kind.
- **No arbitrary file or service management.** Configuration management
  is explicitly out of scope for this project (see `CLAUDE.md`). Beacon's
  file-write surface is a hardcoded allowlist — the `groundctl-*` prefix
  in exactly two directories — enforced in the agent's own code, not
  merely by what the server happens to send it.
- **Runs `apt-get upgrade`/installs packages only when groundctl
  explicitly dispatches that as a task.** Its own poll schedule only ever
  runs `apt-get update` (metadata refresh) — no unattended fleet-wide
  patching.
- **No local decision-making or persistent state.** Everything is
  re-fetched every poll; a reinstalled beacon with the same token behaves
  identically to the one it replaced.
- **Never acts for any server but its own.** No endpoint in
  `app/routers/beacon.py` accepts a `server_id` parameter — identity
  always comes from the presented `BeaconToken`, never the request body.
  A compromised checkin response can move a host to a different apt
  source (which groundctl can already do today via Ansible) but cannot
  use the beacon channel as remote-exec.

## Reading beacon state

`GET /servers/{id}/beacon-state` (viewer-gated) — the operator-facing read
endpoint for `ServerBeaconState`: `config_serial`/`applied_config_serial`,
a computed `pending_reconciliation` boolean (same NULL-safe comparison
`app/metrics.py`'s `groundctl_beacon_pending_reconciliation` gauge uses),
`last_checkin_at`, `last_apply_status`/`last_apply_detail`,
`last_facts_pushed_at`, `agent_version`. 404 if the server has never
checked in (no beacon state row — not beacon-managed), same "nothing to
show yet" semantics as `GET /servers/{id}/facts` before any facts exist.
Surfaced in the web UI's server detail page (Beacon tab) and via
`groundctl server beacon-state <id>` in the CLI.

## Auth

Each server gets its own `BeaconToken` (`POST /servers/{id}/beacon-token`,
operator-only), a `secrets.token_urlsafe(32)` value hashed with the same
SHA-256 scheme as `ActivationKey`/`RefreshToken`
(`app.auth.hash_opaque_token`). Non-expiring by design — cut off only by
explicit revocation
(`POST /servers/{id}/beacon-tokens/{token_id}/revoke`), since an
auto-expiring credential would mean a silently-dead host with no
self-recovery path. Multiple non-revoked tokens per server are allowed,
enabling rotation without a downtime window.

Every `/api/beacon/*` endpoint requires a valid token via
`Authorization: Bearer <token>`, resolved by `get_current_beacon_server`
(`app/auth.py`) — a second, deliberate, non-JWT auth dependency, kept
alongside `get_current_user`/`require_role` but never mixed with them (a
beacon token can never carry a `Role`).

## Installing it

See [`beacon/README.md`](../beacon/README.md) for the single-file agent
itself and manual setup. Two ways to install it on an already-registered
host:

- **`GET /api/beacon/install-script?token=...`** — generates a
  self-contained install script the same way `GET /api/enrollment/script`
  does for initial host enrollment. Requires a token already minted via
  `POST /servers/{id}/beacon-token`. Fetches the agent (`GET
  /api/beacon/agent`) and systemd unit/timer (`GET
  /api/beacon/systemd-service`/`-timer`), writes `/etc/groundctl/beacon.conf`
  (0600), enables the timer, and runs one immediate checkin.
- **`POST /jobs/install-beacon/{server_id}`** (operator-gated) — rolls
  Beacon out to an existing, already-bootstrapped host over the SSH access
  already in place, via a new `install_beacon` Job type and
  `install_beacon.yml` playbook (modeled on `manage_package.yml`). The
  `BeaconToken` is minted server-side, inside the Celery task, and
  delivered via `ansible.builtin.copy` with `no_log: true` — never through
  `extra_vars`, which lands verbatim in `Job.log_output`.

`.deb` packaging is not built — lowest-priority polish item, not required
for either path above; see `ROADMAP.md` Phase 9.
