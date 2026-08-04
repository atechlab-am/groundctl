# Groundctl

**Version:** [0.10.2](CHANGELOG.md#0102---2026-08-04) · see [`CHANGELOG.md`](CHANGELOG.md) for release history and [`docs/releasing.md`](docs/releasing.md) for how releases are cut.

**A self-hosted content-view and patch-level manager for Debian/Ubuntu fleets — mirror repos, snapshot them, stage different package versions to different environments, and manage servers from one place.**

Not a Foreman/Katello clone. Purpose-built, smaller surface area, does exactly four things:

1. **Pull repos** — mirrors upstream Ubuntu/Debian archives locally
2. **Content views** — freezes a mirror at a point in time as a named, immutable snapshot
3. **Patch levels** — publishes different snapshots to different named environments (`dev`, `staging`, `prod`, or whatever you call them); promoting = pointing an environment at a newer snapshot
4. **Fleet management** — register servers, assign each to an environment, push config, trigger updates, track compliance drift — all from one control-plane server

## Components

- **Groundctl** — the control plane. Owns fleet inventory, the content lifecycle, job execution, and compliance state.
- **Relay** — a remote node that mirrors published content to a distant site and serves that site's clients locally, so upgrades don't traverse the WAN. *Planned — see [`ROADMAP.md`](ROADMAP.md) Phase 5.*

Domain vocabulary (repository, content view, lifecycle environment, activation key) follows Satellite/Foreman conventions, so the concepts should be familiar if you've used either.

## Architecture

```
                    ┌───────────────────────────────────────────┐
                    │            groundctl control plane          │
                    │                                             │
                    │  ┌─────────────┐        ┌────────────────┐ │
                    │  │  FastAPI    │◄──────►│  Postgres       │ │
                    │  │  API + UI   │        │  (inventory,    │ │
                    │  └──────┬──────┘        │   jobs, audit)  │ │
                    │         │               └────────────────┘ │
                    │         │ REST                              │
                    │         ▼                                   │
                    │  ┌─────────────┐        ┌────────────────┐ │
                    │  │  aptly      │───────►│  nginx          │ │
                    │  │  (mirror,   │        │  (serves        │ │
                    │  │  snapshot,  │        │  published      │ │
                    │  │  publish)   │        │  repos over     │ │
                    │  └─────────────┘        │  HTTP)          │ │
                    │         ▲               └────────┬───────┘ │
                    │         │ ansible-runner          │         │
                    └─────────┼──────────────────────────┼────────┘
                              │ SSH                       │ apt sources.list
                    ┌─────────┴─────────┐         ┌───────┴────────┐
                    │  Ubuntu/Debian     │         │  Ubuntu/Debian  │
                    │  server (prod)     │         │  server (dev)   │
                    └────────────────────┘         └─────────────────┘
```

- **aptly** does the actual repo mirroring, snapshotting, and publishing. It's run in API mode (`aptly api serve`) so the control plane talks to it over HTTP instead of shelling out to a CLI.
- **nginx** serves the published repo trees as plain apt-compatible HTTP endpoints — this is what ends up in each server's `/etc/apt/sources.list.d/`.
- **FastAPI app** is the actual product: server inventory, environment/content-view management, job orchestration, patch compliance dashboard, audit log.
- **Ansible** (via `ansible-runner`, called from the API) does the SSH-side work: writing sources.list on managed hosts, running `apt update && apt upgrade`, and gathering installed-package facts back for the compliance view.

Everything is open source: FastAPI (MIT), aptly (MIT), Ansible (GPLv3), Postgres (PostgreSQL License), nginx (BSD-2). No subscriptions, no license servers.

## Install

`install.sh` provisions everything natively via systemd on a Debian/Ubuntu host — no containers:

```bash
git clone <this repo> && cd groundctl
sudo ./install.sh --fleet-hostname repo.example.com
```

See [`docs/install.md`](docs/install.md) for the full walkthrough, then [`docs/quickstart.md`](docs/quickstart.md) for the API tour (register a user, mirror a repo, promote an environment).

## Interfaces

- **Web UI** — a full-featured console (dashboard, every resource's CRUD/action screens, RBAC-aware) served by the control plane itself at the same HTTPS origin as the API. See [`docs/web-ui.md`](docs/web-ui.md).
- **CLI** (`groundctl`) — a standalone client package at [`cli/`](cli/) covering the same API surface for scripting/day-to-day terminal use. See [`docs/cli.md`](docs/cli.md).
- **REST API** — the source of truth both interfaces are built on; Swagger/OpenAPI docs at `/docs` on a running instance.

## Status

Core flows implemented: mirror → snapshot → publish, server registration, environment assignment, patch job triggering, package-drift dashboard, RBAC (enforced per-endpoint, hierarchical viewer/operator/admin), Alembic migrations, a pytest suite, structured logging/metrics, backups, a web UI, and a CLI. See [`ROADMAP.md`](ROADMAP.md) for what's next and [`docs/limitations.md`](docs/limitations.md) for known gaps.
