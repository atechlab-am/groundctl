# Relays

A **Relay** is a thin remote node — nginx + sshd only, no Postgres, no
aptly, no FastAPI app, no Celery — that receives a subset of the primary's
published content over rsync and serves it to a site's hosts over LAN.
Groundctl remains the single source of truth; a relay holds no
authoritative state of its own and can be rebuilt from scratch at any time
by re-running `install-relay.sh` and letting the next scheduled sync
repopulate it.

This is the Satellite Capsule analogue, scoped for a topology like two
sites (e.g. NA1/NA2) where hosts at the remote site should pull packages
over LAN instead of dragging every upgrade across a WAN link to the
primary.

## Setup

### 1. Install the relay

On the relay host itself, from a checked-out copy of this repo:

```bash
sudo ./install-relay.sh --primary-key-file /path/to/primary-id_ed25519.pub
```

`--primary-key-file` must point at a copy of the **primary's**
`/etc/groundctl/ansible-keys/id_ed25519.pub` contents — copy it over
out-of-band (scp, config management, etc.). There is no automated
key-exchange mechanism in this phase; the primary's existing shared fleet
key is reused for the rsync-over-SSH hop and for ProxyJump routing through
this relay to hosts behind it. Phase 6's per-host SSH keys apply to the
final hop to a fleet `Server`, not to a `Relay` — a relay remains
infrastructure trusted via the one shared key, same as before.

This installs nginx and sshd, creates an unprivileged `groundctl-sync`
system user that owns `/var/lib/groundctl/aptly/public`, and authorizes
the primary's public key for that user. No rsync daemon — `rsync -e ssh`
is sufficient.

### 2. Register the relay on the primary

```bash
curl -X POST https://<PRIMARY_HOST>:8000/sites \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name": "na2", "description": "NA2 site"}'
# save the returned "id" as $SITE_ID

curl -X POST https://<PRIMARY_HOST>:8000/sites/$SITE_ID/relay \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"hostname": "relay-na2.example.net", "ssh_user": "groundctl-sync"}'
```

`hostname` must be a name/address the **primary** can reach over SSH.

### 3. Selective sync — allowlist environments for this site

A relay only carries the `LifecycleEnvironment`s explicitly allowlisted for
its site — not the whole content library:

```bash
curl -X PUT https://<PRIMARY_HOST>:8000/sites/$SITE_ID/environments \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"environment_ids": ["'$ENV_ID'"]}'
```

This is an explicit, wholesale-replace allowlist (`PUT`, diffed and
audited) — not derived from which servers happen to be assigned to the
site. You can allowlist an environment for a site before any server is
actually registered there.

### 4. Assign servers to the site

```bash
curl -X POST https://<PRIMARY_HOST>:8000/servers/{id}/assign-site?site_id=$SITE_ID \
  -H "Authorization: Bearer $TOKEN"
```

Or pass `site_id` directly in `POST /servers` at creation time. Once
assigned, bootstrap and Ansible job execution against that server
automatically route through the relay (see below) — no other changes
needed.

## How sync works

A Celery Beat task (`scheduled_sync_relays`, hourly) rsyncs each relay's
allowlisted environments' published content from the primary to the relay,
via a small Ansible playbook (`app/ansible/playbooks/sync_relay.yml`) —
the same job-execution machinery every other groundctl operation uses, so
relay sync gets the same retry/unreachable handling for free. On success,
`Relay.sync_status`/`last_sync_time`/`content_size_bytes` are updated with
real values (`content_size_bytes` from `du -sb` on the relay). On failure,
`sync_status` is set to `failed` and a `relay.sync_failed` webhook fires
(if configured).

Sync is **scheduled, not promotion-triggered** — a promoted environment
reaches its relays on the next hourly run, not immediately. This keeps
promotion fast: aptly's own publish call can already take up to 1800s, and
coupling relay sync into that request would make an already-slow endpoint
slower and more failure-prone per relay. rsync only transfers changed
content, so hourly runs are cheap once a relay is caught up.

## Bootstrap and job-execution routing, with fallback

When a server has `site_id` set:

- **Bootstrap** writes that server's sources.list pointing at its relay's
  URL (`https://<relay hostname>` — relays serve HTTPS with a self-signed
  cert by default too, see [`docs/https.md`](https.md)) instead of the
  primary's `published_repo_base_url` — but only if the relay is `healthy` and its
  `last_sync_time` is within `relay_stale_threshold_hours` (default 24h,
  see `app/config.py`). Otherwise it falls back to the primary's URL — a
  real, exercised code path, not documentation-only.
- **Ansible job execution** (apply-updates, gather-facts, run-command,
  manage-package, etc.) routes that server's SSH connection through the
  relay via `ProxyJump`, so the primary only needs network reachability to
  each site's relay, not to every individual host behind it. Same
  healthy/non-stale gate and fallback — if the relay is down, jobs fall
  straight back to a direct connection attempt (which will simply fail if
  the primary genuinely can't reach that host directly, same as any other
  unreachable host).

A relay whose `last_sync_time` exceeds the staleness threshold is flagged
daily (`scheduled_flag_stale_relays`, mirrors the server staleness sweep
from Phase 4) and fires a `relay.stale` webhook — this is about
visibility, not the fallback mechanism itself, which doesn't depend on
this sweep running.

## Scope of this phase

- **One relay per site.** `Relay.site_id` is unique — no multi-relay
  load-balancing or HA within a site.
- **No multi-hop relay chains.** A relay is never itself routed through
  another relay.
- See [`docs/limitations.md`](limitations.md) for the honest list of
  what's simplified or deferred (eventual-consistency sync timing, shared
  SSH key for the jump hop, no TLS on the relay's nginx, etc).
