# groundctl-beacon

Optional pull-based agent for a groundctl-managed content host. See
[`docs/beacon.md`](../docs/beacon.md) for the full design and
[`ROADMAP.md`](../ROADMAP.md)'s Phase 9 for what's built so far.

A single stdlib-only Python 3 file — no build step, no dependencies. Copy
`groundctl_beacon.py` to `/usr/local/bin/groundctl-beacon` on a managed
host, write `/etc/groundctl/beacon.conf`, and run it.

## `/etc/groundctl/beacon.conf`

```
GROUNDCTL_API_BASE_URL=https://groundctl.example.com:8000
GROUNDCTL_BEACON_TOKEN=<token from POST /servers/{id}/beacon-token>
```

Mode `0600` — `GROUNDCTL_BEACON_TOKEN` is the one real secret here.

## Running it

```
# One checkin, for debugging:
groundctl-beacon --once --config /etc/groundctl/beacon.conf

# Loop forever, polling on the server-controlled interval
# (checkin_interval_seconds in the checkin response, 300s by default):
groundctl-beacon --config /etc/groundctl/beacon.conf
```

In production, `groundctl-beacon.service`/`.timer`
(`systemd/groundctl-beacon.*.template`) run it as a `oneshot` service on a
timer rather than a persistent loop — matches the agent's own "no
long-lived state, rebuildable from scratch" design (see `docs/beacon.md`).

## Issuing a token for a server

```
POST /api/servers/{server_id}/beacon-token
Authorization: Bearer <operator or admin JWT>

{"name": "primary"}
```

Returns the raw token exactly once. Store it in `beacon.conf` on that
server; it's never shown again (`GET /api/servers/{id}/beacon-tokens`
lists metadata only).

## What it does today (Phase B)

Authenticates and polls `POST /api/beacon/checkin`, logging what it
received. It does not yet write any files, run `apt`, or push facts back
— see `ROADMAP.md` Phase 9 for what's coming (local `sources.list`
reconciliation, facts/telemetry push, dispatched actions like
apply-updates).
