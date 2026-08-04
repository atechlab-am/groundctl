# Quickstart

This walks through the API once groundctl is installed and running. If you
haven't installed it yet, see [`docs/install.md`](install.md) first.

The examples below use `<HOST>` for the address groundctl is listening on
(the host you ran `install.sh` on, port 8000 — `install.sh`'s own output
prints this at the end). Groundctl serves HTTPS with a self-signed cert by
default (see [`docs/https.md`](https.md)) — add `-k`/`--insecure` to the
`curl` examples below unless you've swapped in a CA-issued cert, or trust
the primary's cert locally first.

## 1. Create your first user

`POST /auth/register` is **admin-only** (RBAC is enforced — see
[`docs/limitations.md`](limitations.md)), so the very first user has to be
created directly against the database, once, before any API call can
create further users:

```bash
sudo -u groundctl /opt/groundctl/venv/bin/python3 -c "
from app.database import SessionLocal
from app.models import User, Role
from app.auth import hash_password
db = SessionLocal()
db.add(User(username='anthony', email='you@example.com', hashed_password=hash_password('...'), role=Role.admin))
db.commit()
"
```

From there, log in and use that admin token to create any further users via
the API:

```bash
curl -sk -X POST https://<HOST>:8000/auth/login \
  -d 'username=anthony&password=...'
# {"access_token": "...", "refresh_token": "...", "token_type": "bearer"}
# access tokens are short-lived (15 min default) — save the refresh_token too
export TOKEN=<access_token from above>

curl -sk -X POST https://<HOST>:8000/auth/register \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"username":"opuser","email":"ops@example.com","password":"...","role":"operator"}'
```

When the access token expires, exchange the refresh token for a new pair
(refresh tokens rotate on every use — the old one stops working):

```bash
curl -sk -X POST https://<HOST>:8000/auth/refresh \
  -d '{"refresh_token": "'$REFRESH_TOKEN'"}'
# {"access_token": "...", "refresh_token": "...", ...} — update both saved values
```

Or just open `https://<HOST>:8000/docs` — FastAPI's interactive Swagger UI, which handles the auth flow for you (after the first admin user exists).

**Roles**: `viewer` (read-only), `operator` (day-to-day fleet ops — sync
repos, promote environments, trigger jobs, create servers/groups/keys),
`admin` (`run-command`, user registration, audit log export — everything
`operator` can do, plus these). Hierarchical: an `admin` can call anything
an `operator` or `viewer` can.

## 2. Pull a repo

```bash
curl -X POST https://<HOST>:8000/repositories \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
    "name": "ubuntu-jammy",
    "archive_url": "http://archive.ubuntu.com/ubuntu/",
    "distribution": "jammy",
    "components": ["main", "universe"],
    "architectures": ["amd64"]
  }'

curl -X POST https://<HOST>:8000/repositories/ubuntu-jammy/sync -H "Authorization: Bearer $TOKEN"
# this downloads the actual package files — can take a while on first run
```

Repeat for as many repositories as you want in your fleet — e.g. a second `ubuntu-jammy-security` repository pointed at `http://security.ubuntu.com/ubuntu/`.

## 3. Create a content view

A **content view** aggregates one or more repositories into a single publishable, versionable unit — this is how you combine `jammy` + `jammy-security` into one patch stream.

```bash
curl -X POST https://<HOST>:8000/content-views \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
    "name": "jammy-baseline",
    "repository_ids": ["'$REPO_ID'"]
  }'
# save the returned "id" as $CV_ID
```

## 4. Publish a version

Publishing cuts an immutable **content view version** — a snapshot of every member repository's current contents, frozen together. Publishing again with no upstream changes is a fast no-op; it never wastes a snapshot on unchanged content.

```bash
curl -X POST https://<HOST>:8000/content-views/$CV_ID/publish -H "Authorization: Bearer $TOKEN"
# {"content_view_version": {"id": "...", "version": 1, ...}, "version_cut": true}
```

## 5. Create a lifecycle environment and promote into it

A **lifecycle environment** is a named slot in an ordered **path** (e.g. `library` → `dev` → `qa` → `prod`, all sharing one `path_name`, each with an incrementing `position`). Promoting points an environment's publish prefix at a specific content view version.

GPG signing is on by default (see [`docs/gpg-signing.md`](gpg-signing.md))
— creating an environment requires `gpg_key_id` unless you explicitly pass
`allow_unsigned: true`. This example opts out for simplicity; for anything
beyond a lab, generate a real signing key first and pass its fingerprint
as `gpg_key_id` instead.

```bash
curl -X POST https://<HOST>:8000/lifecycle-environments \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
    "name": "jammy-library",
    "path_name": "default",
    "position": 0,
    "content_view_id": "'$CV_ID'",
    "distro": "ubuntu",
    "release": "jammy",
    "publish_prefix": "jammy-library",
    "allow_unsigned": true
  }'
# save the returned "id" as $ENV_ID

curl -X POST https://<HOST>:8000/lifecycle-environments/$ENV_ID/promote \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{}'
# omitting content_view_version_id promotes the content view's latest version
# — jammy-library is now live at https://<FLEET_HOSTNAME>:8080/jammy-library/
# (8080 is install.sh's default nginx port, self-signed HTTPS by default —
# see docs/install.md and docs/https.md)
```

**Path enforcement**: an environment at `position` N can only be promoted into once the environment at `position` N-1 in the same `path_name` already has that version live. `position=0` has no such gate. Create a second environment at `position=1` and promote the same way — skipping straight to `position=2` before `position=1` has ever had the version returns `409`.

## 6. Add a server

```bash
curl -X POST https://<HOST>:8000/servers \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
    "hostname": "web01.atechlab.net",
    "ip_address": "10.10.20.30",
    "ssh_user": "root",
    "environment_id": "'$ENV_ID'"
  }'
# save returned "id" as $SERVER_ID
```

## 7. Bootstrap it

```bash
curl -X POST https://<HOST>:8000/jobs/bootstrap/$SERVER_ID -H "Authorization: Bearer $TOKEN"
# returns a job id immediately — this runs in the background
curl https://<HOST>:8000/jobs/<job_id> -H "Authorization: Bearer $TOKEN"
# poll until status is "success" or "failed"; log_output has the full ansible run
```

This points the server's apt sources at your `jammy-library` endpoint. From here, `apt install`/`apt upgrade` on that box only see what you've published to its environment.

## 8. Patch an environment

Sync your repositories, publish a new content view version, then promote it into an environment:

```bash
curl -X POST https://<HOST>:8000/repositories/ubuntu-jammy/sync -H "Authorization: Bearer $TOKEN"
curl -X POST https://<HOST>:8000/content-views/$CV_ID/publish -H "Authorization: Bearer $TOKEN"
curl -X POST https://<HOST>:8000/lifecycle-environments/$ENV_ID/promote \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{}'
```

Every server assigned to this environment now sees the new packages on their next `apt update` — no per-server action required. Trigger it fleet-wide with:

```bash
curl -X POST "https://<HOST>:8000/jobs/apply-updates?environment_id=$ENV_ID" -H "Authorization: Bearer $TOKEN"
```

## 9. Roll back

Environments can be rolled back to any content view version they've previously had live — no re-sync, no re-cut, just an immediate switch to already-published, already-immutable content:

```bash
curl -X POST https://<HOST>:8000/lifecycle-environments/$ENV_ID/rollback \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"content_view_version_id": "'$OLD_VERSION_ID'"}'
```

Rolling back to a version this specific environment never actually ran (e.g. one that only ever ran in a different environment) returns `409`.

## 10. Check compliance drift

```bash
curl -X POST "https://<HOST>:8000/jobs/gather-facts?environment_id=$ENV_ID" -H "Authorization: Bearer $TOKEN"
# wait for job to finish, then:
curl -X POST https://<HOST>:8000/compliance/servers/$SERVER_ID/check -H "Authorization: Bearer $TOKEN"
```

## Content view filters

Include/exclude specific packages from a content view's published content:

```bash
curl -X POST https://<HOST>:8000/content-views/$CV_ID/filters \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"filter_type": "exclude", "pattern": "snapd"}'
```

Filters apply on the next publish. See [`docs/limitations.md`](limitations.md) — the aptly integration behind filters is less battle-tested than the rest of this flow.

## 11. Security errata

Groundctl ingests Ubuntu Security Notices (USN) and Debian Security Advisories
(DSA) daily via Celery Beat and exposes them read-only:

```bash
curl "https://<HOST>:8000/errata?source=usn" -H "Authorization: Bearer $TOKEN"
curl "https://<HOST>:8000/errata?cve=CVE-2026-1234" -H "Authorization: Bearer $TOKEN"
curl https://<HOST>:8000/errata/USN-8620-4 -H "Authorization: Bearer $TOKEN"
```

Find which servers are still running a package version an advisory fixed —
computed on read from each server's latest gathered facts, the same way
`/compliance/servers/{id}/check` works:

```bash
curl https://<HOST>:8000/errata/USN-8620-4/affected-servers -H "Authorization: Bearer $TOKEN"
```

You can also scope a content view to only include packages fixed by errata
published on or after a given date, instead of listing packages by name:

```bash
curl -X POST https://<HOST>:8000/content-views/$CV_ID/filters \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"filter_type": "errata_since", "pattern": "2026-01-01"}'
```

Errata ingestion is Beat-scheduled only — there's no endpoint to trigger it
on demand yet. See [`docs/limitations.md`](limitations.md) for what's not
covered (severity data, the `errata_since` filter's aptly query shape).

## 12. Host groups and bulk actions

A **host group** is a many-to-many collection of servers, independent of
`environment_id` — a server's environment still comes from its own
`environment_id`, groups are purely a targeting mechanism for bulk actions.

```bash
curl -X POST https://<HOST>:8000/host-groups \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name": "web-tier", "default_environment_id": "'$ENV_ID'"}'
# save returned "id" as $GROUP_ID

curl -X PUT https://<HOST>:8000/host-groups/$GROUP_ID/members \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"server_ids": ["'$SERVER_ID_1'", "'$SERVER_ID_2'"]}'
```

Run updates against the whole group, or against an ad-hoc list of server IDs
instead — exactly one of `host_group_id`/`server_ids` per request:

```bash
curl -X POST https://<HOST>:8000/jobs/bulk-apply-updates \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"host_group_id": "'$GROUP_ID'"}'
```

Run an ad-hoc command across a selection (root, via `ansible.builtin.command`
— no shell interpolation). This is the single most dangerous endpoint in
groundctl, so it requires `admin`, not just `operator` — every other
mutation in this walkthrough only needed `operator`:

```bash
curl -X POST https://<HOST>:8000/jobs/run-command \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"host_group_id": "'$GROUP_ID'", "command": "systemctl restart nginx"}'
```

## 13. Self-registration via activation key

Instead of a human running `POST /servers` for a host groundctl doesn't know
about yet, issue an activation key and let the host register itself — the
Satellite `subscription-manager register --activationkey` equivalent:

```bash
curl -X POST https://<HOST>:8000/activation-keys \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name": "web-tier-key", "environment_id": "'$ENV_ID'", "host_group_id": "'$GROUP_ID'", "max_uses": 50}'
# response includes "token" — copy it now, it is never shown again
```

On the new host — this is the **one unauthenticated mutating endpoint** in
groundctl; the token itself is the credential:

```bash
curl -X POST https://<HOST>:8000/enrollment/register \
  -H 'Content-Type: application/json' \
  -d '{"token": "'$TOKEN'", "hostname": "web05.example.net", "ip_address": "10.10.20.35", "ssh_user": "root"}'
```

This creates the `Server` row (inheriting the key's environment and host
group) but does **not** SSH to it — bootstrap it the same as any other
server once its SSH key is in place:

```bash
curl -X POST https://<HOST>:8000/jobs/bootstrap/$SERVER_ID -H "Authorization: Bearer $TOKEN"
```

Re-running the same registration (e.g. a re-run bootstrap script) is
idempotent — it updates `ip_address`/`ssh_user` on the existing `Server` row
rather than creating a duplicate, and never touches `environment_id` on an
existing server.

## 14. Facts, package search, and per-host package management

```bash
curl https://<HOST>:8000/servers/$SERVER_ID/facts -H "Authorization: Bearer $TOKEN"
# {"os_distribution": "Debian", "os_version": "12.15", "kernel": "6.12...",
#  "uptime_seconds": 45213, "disk": [...], "services": [...], "gathered_at": "..."}

curl "https://<HOST>:8000/compliance/packages/search?package_name=openssl&operator=lt&compare_version=3.0.10-0ubuntu1" \
  -H "Authorization: Bearer $TOKEN"

curl -X POST https://<HOST>:8000/jobs/manage-package \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"server_id": "'$SERVER_ID'", "package_name": "htop", "action": "install"}'
```

## 15. Stale-host alerting via webhook

If `webhook_url` is set in `install.env`, a daily sweep POSTs a signed JSON
payload for every server that hasn't completed a successful groundctl job
in `stale_checkin_hours` (default 7 days), and for every server a job just
marked `unreachable`:

```json
{
  "event": "server.stale",
  "data": {"server_id": "...", "hostname": "web05.example.net", "last_seen_at": "2026-07-25T02:00:00+00:00"},
  "timestamp": "2026-08-01T05:00:00+00:00"
}
```

If `webhook_secret` is also set, the request carries
`X-Groundctl-Signature: sha256=<hmac>` (HMAC-SHA256 over the raw request
body) so the receiver can verify authenticity. Delivery is fire-and-forget —
see [`docs/limitations.md`](limitations.md) for what happens when it fails.

## 16. Multi-site relays

For a multi-site fleet, a **relay** mirrors a subset of published content
to a remote site so hosts there pull packages over LAN instead of over a
WAN link to the primary:

```bash
curl -X POST https://<HOST>:8000/sites \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name": "na2"}'
curl -X POST https://<HOST>:8000/sites/$SITE_ID/relay \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"hostname": "relay-na2.example.net", "ssh_user": "groundctl-sync"}'
curl -X PUT https://<HOST>:8000/sites/$SITE_ID/environments \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"environment_ids": ["'$ENV_ID'"]}'
```

Assign servers to the site (`site_id` on `POST /servers`, or
`POST /servers/{id}/assign-site?site_id=...`) and both bootstrap URLs and
Ansible job execution automatically route through the relay, falling back
to the primary if it's unhealthy or stale. See
[`docs/relays.md`](relays.md) for the full setup walkthrough including the
relay-side install script.
