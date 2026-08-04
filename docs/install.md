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

All services run as a dedicated, non-root `groundctl` system user.

## Prerequisites

- A fresh Debian 12+ or Ubuntu 22.04+ host, reachable over the network you intend your managed fleet to use.
- Root/sudo access.
- A checked-out copy of this repo on the target host — `install.sh` does **not** clone the repo itself (there's no published release yet). `git clone` this repo, then run the script from inside it.
- Outbound internet access during install: `install.sh` installs `nodejs`/`npm` from the distro's own apt repos and runs `npm ci` to build the web UI. Node/npm are a **build-time** dependency only — nothing Node-related runs as a service afterward.

## Usage

```bash
sudo ./install.sh --fleet-hostname repo.example.com --nginx-port 8080
```

Or via environment variables (see `install.env.example`):

```bash
cp install.env.example install.env  # edit values
set -a; source install.env; set +a
sudo -E ./install.sh
```

`--fleet-hostname` must be an address every managed host can actually reach — it gets baked into `PUBLISHED_REPO_BASE_URL`, which is what `bootstrap_client.yml` writes into each managed host's `sources.list.d/groundctl.list`. Getting this wrong doesn't break the control plane, but it does mean fleet hosts can't reach their published repos — the script warns if you leave it at the `groundctl.local` placeholder.

## Re-running

The script is idempotent — safe to re-run after `git pull`ing changes, to pick up config changes, or just to confirm state matches what's expected:

- Generated secrets (Postgres password, JWT secret) are read back from the existing `/etc/groundctl/groundctl.env` and never regenerated.
- An existing Ansible SSH keypair is never overwritten — overwriting it would break every already-authorized managed host.
- Already-healthy services aren't unnecessarily bounced; they only restart if their config actually changed.

To pick up new app code after a `git pull`, just re-run `install.sh` — it copies the updated `app/` into `/opt/groundctl` and restarts the `groundctl` service.

## Layout on disk

| Path | Purpose |
|---|---|
| `/opt/groundctl/` | App code + Python venv |
| `/etc/groundctl/groundctl.env` | Resolved config/secrets — not repo-tracked |
| `/etc/groundctl/aptly.conf` | aptly config |
| `/etc/groundctl/ansible-keys/` | Shared fleet SSH keypair (initial bootstrap connections) |
| `/etc/groundctl/ansible-keys/hosts/<server-id>/` | Per-host SSH keypairs, generated at bootstrap time (Phase 6) |
| `/etc/groundctl/tls/{cert.pem,key.pem}` | Self-signed TLS cert (default) — see `docs/https.md` for swapping in a CA-issued one |
| `/var/lib/groundctl/aptly/` | aptly's data root (mirrors, snapshots, published pool) — **grows unbounded**, put it on a volume with real headroom |
| `/etc/systemd/system/{groundctl,groundctl-worker,groundctl-beat,aptly}.service` | systemd units |

## After install

1. Authorize `/etc/groundctl/ansible-keys/id_ed25519.pub` on every host you plan to manage (append to that host's `~/.ssh/authorized_keys` for the user groundctl will SSH in as) — this is the shared fleet key used for initial bootstrap; Phase 6 per-host keys take over from there (see `docs/limitations.md`).
2. Create the first admin user directly against the database (`POST /auth/register` is admin-only — see `docs/quickstart.md`'s step 1), then follow the rest of `docs/quickstart.md`'s API walkthrough against `https://<this-host>:8000` — create a mirror, sync, create an environment, promote.

## Known limitation

`Restart=on-failure` on `groundctl-worker.service` restarts the worker process after a crash, but a job that was `running` when it crashed isn't automatically resumed — it's picked up by the stuck-job reaper on `groundctl.service`'s *next* startup (see `docs/limitations.md`), not immediately. Restart `groundctl` if you need a stuck job reaped right away.
