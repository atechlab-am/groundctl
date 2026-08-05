# Native install

`install.sh` provisions groundctl directly on a Debian or Ubuntu host as systemd
services — no containers. This is the only supported way to deploy groundctl.

## What it does

Installs and configures, as native systemd services:

- **postgresql** — via the distro package, `groundctl` role + database created idempotently.
- **redis** — via the distro package, bound to `127.0.0.1` only (no auth — same posture as aptly's own unauthenticated API). Celery broker + result backend.
- **aptly** — binary fetched from GitHub releases, config written, archive GPG keyrings imported, bound to `127.0.0.1:8090` only (its REST API has no authentication of its own — never expose it beyond loopback).
- **nginx** — serves aptly's published repo tree over HTTPS (self-signed cert by default, see `docs/https.md`; plain HTTP on port 80 only exists as a redirect to HTTPS).
- **groundctl** — the FastAPI app (`groundctl.service`, also HTTPS by default), plus a Celery job worker (`groundctl-worker.service`) and scheduler (`groundctl-beat.service`), installed into one Python venv under `/opt/groundctl`. The web UI (`ui/`) is built with `npm` and its static output copied into `app/static/`, served by this same service — see `docs/web-ui.md`.

All services run as a dedicated, non-root `groundctl` system user. `groundctl.service` listens on port **443** (the standard HTTPS port, so `https://<fleet-hostname>` reaches it with no port needed) despite running unprivileged — `install.sh` grants its venv's `python3` binary `CAP_NET_BIND_SERVICE` (via `setcap`) rather than running the service as root; see `scripts/lib/app.sh`'s `grant_bind_low_ports`.

## Prerequisites

- A fresh Debian 12+ or Ubuntu 22.04+ host, reachable over the network you intend your managed fleet to use.
- Root/sudo access.
- A checked-out copy of this repo on the target host — `install.sh` does **not** clone the repo itself (there's no published release yet). `git clone` this repo, then run the script from inside it.
- Outbound internet access during install: `install.sh` installs `nodejs`/`npm` from the distro's own apt repos and runs `npm ci` to build the web UI. Node/npm are a **build-time** dependency only — nothing Node-related runs as a service afterward.

## Usage

```bash
sudo ./install.sh
```

Run with no arguments, `install.sh` prompts interactively for the fleet hostname and nginx port (showing the default in brackets — press Enter to accept it), then — once the database is up and migrated — for the first admin user's username, email, and a password (entered twice, not echoed to the terminal):

```
Fleet hostname (address managed hosts will reach this server at) [groundctl.local]: repo.example.com
nginx published-repo port [8080]:
...
Admin username [admin]:
Admin email [admin@repo.example.com]:
Admin password (min 8 chars):
Confirm password:
```

This is the only user that can exist without another admin creating it (`POST /auth/register` is admin-only, real enforced RBAC — see `docs/limitations.md`) — by the time `install.sh` finishes, you can log into the web UI immediately with these credentials. Re-running `install.sh` after an admin already exists skips this step silently (see "Re-running" below).

For scripted/non-interactive installs, flags or environment variables bypass the prompt entirely (checked first — if either is already set, that value is used silently, no prompt shown). The admin username/email/password can be supplied the same way via `GROUNDCTL_ADMIN_USERNAME`/`GROUNDCTL_ADMIN_EMAIL`/`GROUNDCTL_ADMIN_PASSWORD` (see `install.env.example`) — if no password is supplied and the install isn't running on a real terminal (piped input, cron, CI), a random password is generated and printed once in the final summary rather than the script hanging on a prompt that can never be answered.

```bash
sudo ./install.sh --fleet-hostname repo.example.com --nginx-port 8080
```

Or via environment variables (see `install.env.example`):

```bash
cp install.env.example install.env  # edit values
set -a; source install.env; set +a
sudo -E ./install.sh
```

`--fleet-hostname` must be an address every managed host can actually reach — it gets baked into `PUBLISHED_REPO_BASE_URL`, which is what `bootstrap_client.yml` writes into each managed host's `sources.list.d/groundctl.list`. Getting this wrong doesn't break the control plane, but it does mean fleet hosts can't reach their published repos — the script warns if you leave it at the `groundctl.local` placeholder (whether that placeholder came from an unattended run or from pressing Enter at the prompt).

## Re-running `install.sh`

The script is idempotent — safe to re-run to pick up **config changes** (fleet hostname, nginx port, TLS) or just to confirm state matches what's expected:

- Generated secrets (Postgres password, JWT secret) are read back from the existing `/etc/groundctl/groundctl.env` and never regenerated.
- An existing Ansible SSH keypair is never overwritten — overwriting it would break every already-authorized managed host.
- Already-healthy services aren't unnecessarily bounced; they only restart if their config actually changed.
- The admin-user prompt is skipped silently once any admin user exists — re-running never re-prompts for credentials you already set.

Re-running `install.sh` after a `git pull` also picks up new app code (it copies the updated `app/` into `/opt/groundctl` and restarts services if needed) — but for routine **code upgrades**, prefer `groundctl-maintain upgrade` below, which is a smaller, purpose-built operation.

## Upgrading and maintenance: `groundctl-maintain`

`install.sh` installs a second, standalone command to `/usr/local/bin/groundctl-maintain` — **not a wrapper around `install.sh`**, a separate script, so there's no ambiguity about which one to reach for:

- **`install.sh`** — first-time provisioning, and applying *config* changes (fleet hostname, nginx port) afterward. Run manually from inside a checkout.
- **`groundctl-maintain`** — routine maintenance. Run from anywhere, no checkout path to remember.

### `groundctl-maintain upgrade`

```bash
sudo groundctl-maintain upgrade
```

This does, in order: `git fetch`/`checkout` the checkout it was installed from to the latest `main` (the released/stable branch — see `docs/releasing.md`), rebuilds the web UI, resyncs app code, updates Python dependencies, applies pending database migrations, and restarts `groundctl`/`groundctl-worker`/`groundctl-beat` — whenever `main` actually moved, whether or not `VERSION` itself changed (several ordinary commits can land on `main` between version bumps; gating a redeploy on the version string alone previously let a checkout silently skip syncing/restarting even though it had genuinely pulled newer app code — see `CHANGELOG.md`). Running it again with nothing new to pull reports "already up to date" and touches nothing.

It deliberately does **not** touch one-time provisioning or config — no Postgres/Redis/aptly/nginx reinstall, no TLS cert regeneration, no fleet-hostname/nginx-port changes. If you need any of those, that's `install.sh`'s job (or `groundctl-maintain regen-cert` for TLS specifically, below).

### `groundctl-maintain regen-cert`

```bash
sudo groundctl-maintain regen-cert
```

Regenerates the self-signed TLS cert (fleet hostname read back from `/etc/groundctl/groundctl.env`, no re-prompting) and restarts `groundctl` + `nginx` to pick it up. Backs up the existing cert/key pair first (`/etc/groundctl/tls/backup-<timestamp>/`) — `install.sh`'s own `ensure_tls_cert` never overwrites an existing cert on its own, so this is the supported way to force a regeneration (e.g. after upgrading past a fix to how the cert is generated) without a full reinstall. See [`docs/https.md`](https.md).

`groundctl-maintain` finds its checkout via `/etc/groundctl/maintain.conf` (written by `install.sh`, holds `GROUNDCTL_REPO_ROOT`) — if that file is missing or doesn't point at a valid git checkout, it fails with a clear error rather than guessing.

## Layout on disk

| Path | Purpose |
|---|---|
| `/opt/groundctl/` | App code + Python venv |
| `/etc/groundctl/groundctl.env` | Resolved config/secrets — not repo-tracked |
| `/etc/groundctl/maintain.conf` | `groundctl-maintain`'s own metadata (the git checkout path) — not repo-tracked |
| `/usr/local/bin/groundctl-maintain` | Standalone upgrade/maintenance command — see "Upgrading and maintenance" above |
| `/etc/groundctl/aptly.conf` | aptly config |
| `/etc/groundctl/ansible-keys/` | Shared fleet SSH keypair (initial bootstrap connections) |
| `/etc/groundctl/ansible-keys/hosts/<server-id>/` | Per-host SSH keypairs, generated at bootstrap time (Phase 6) |
| `/etc/groundctl/tls/{cert.pem,key.pem}` | Self-signed TLS cert (default) — see `docs/https.md` for swapping in a CA-issued one |
| `/var/lib/groundctl/aptly/` | aptly's data root (mirrors, snapshots, published pool) — **grows unbounded**, put it on a volume with real headroom |
| `/etc/systemd/system/{groundctl,groundctl-worker,groundctl-beat,aptly}.service` | systemd units |

## After install

1. Authorize `/etc/groundctl/ansible-keys/id_ed25519.pub` on every host you plan to manage (append to that host's `~/.ssh/authorized_keys` for the user groundctl will SSH in as) — this is the shared fleet key used for initial bootstrap; Phase 6 per-host keys take over from there (see `docs/limitations.md`).
2. Log in at `https://<this-host>` with the admin user `install.sh` just created (or via the API — see `docs/quickstart.md`'s walkthrough for `curl` examples), then create a mirror, sync, create an environment, and promote.

## Known limitation

`Restart=on-failure` on `groundctl-worker.service` restarts the worker process after a crash, but a job that was `running` when it crashed isn't automatically resumed — it's picked up by the stuck-job reaper on `groundctl.service`'s *next* startup (see `docs/limitations.md`), not immediately. Restart `groundctl` if you need a stuck job reaped right away.
