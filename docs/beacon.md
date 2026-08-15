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
- Once local reconciliation lands (Phase 9, later item): writes/removes
  only `groundctl-*` files in `/etc/apt/sources.list.d/` and
  `/etc/apt/keyrings/`, runs `apt-get update`.
- Reports facts (installed packages, disk, services) back to groundctl —
  written into the same `ComplianceRecord`/`ServerFact` tables
  `gather_facts_task` already writes, so every existing consumer
  (`do_check_compliance`, the weekly scan, `GET /servers/{id}/facts`)
  works unchanged.
- Executes a task groundctl explicitly dispatches to it (e.g.
  apply-updates) and reports the outcome, closing the same `Job` row an
  SSH-driven run of the same task would have closed.

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
itself and manual setup. `GET /api/beacon/install-script` (planned) will
generate a self-contained install script the same way
`GET /api/enrollment/script` does for initial host enrollment, and an
SSH-triggered `install_beacon.yml` job (planned) will let an operator roll
Beacon out to an existing fleet using the SSH access already in place —
neither is built yet; see `ROADMAP.md` Phase 9.
