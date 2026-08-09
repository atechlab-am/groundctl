# CLI

ROADMAP Phase 8's last item: a standalone command-line client, `groundctl`,
covering the same API surface as the web UI (see `docs/web-ui.md`) for
scripting and day-to-day terminal use. Lives at `cli/` — an independently
installable Python package, not part of the control-plane deployment
(`install.sh` never touches it; it's meant to run on an operator's own
workstation against a remote groundctl server).

## Install

```bash
git clone <this repo> && cd groundctl
pip install ./cli          # or: pipx install ./cli
```

No published package yet (matches `install.sh`'s own no-published-release
posture) — install from a checkout.

## Auth

```bash
groundctl auth login --api-url https://groundctl.example.com --username myuser
groundctl auth whoami
groundctl auth logout
```

`auth login` always prompts for the password interactively (never accept
it as a plain argument — shell history would leak it) and calls the
existing `POST /api/auth/login` — the same JSON-body flow used by any
non-browser client, unrelated to the web UI's cookie-based `/api/auth/ui-*`
endpoints. Only the **refresh token** is persisted, to
`~/.config/groundctl/config.toml` (directory `0700`, file `0600`); the
15-minute access token lives in memory for the duration of one command and
is never written to disk.

Every command other than `auth login` calls `POST /api/auth/refresh` once at
the start of the invocation and **immediately persists the rotated
refresh token** it gets back, before making the actual API call — refresh
tokens are single-use/rotating server-side (`app/auth.py`'s
`consume_refresh_token`), so skipping that write would revoke the stored
token on first use and lock the CLI out after exactly one command. This
was the highest-risk piece of the implementation and is covered by both a
unit test (`cli/tests/test_client.py`, using `httpx.MockTransport`, no
real network) and live verification (five-plus real commands run back to
back against a real backend with zero 401s).

If `/api/auth/refresh` itself is rate-limited (the server allows 5/minute,
same limit as login), the CLI reports that distinctly from "not logged
in" rather than prompting a spurious re-login — a real bug found and
fixed during live verification (the two failure modes look identical at
the HTTP layer unless the 429 status is checked explicitly before falling
through to the generic auth-failure path).

## Commands

Command shape mirrors the API 1:1 — domain vocabulary stays exactly as
CLAUDE.md mandates (`content-view`, `lifecycle environment`, etc.), no
invented synonyms.

| Group | Commands |
|---|---|
| `auth` | `login`, `logout`, `whoami` |
| `repository` | `create`, `list`, `sync` |
| `content-view` | `create`, `publish`, `add-filter`, `versions` |
| `environment` | `create`, `list`, `promote`, `rollback`, `gpg-key` |
| `server` | `register`, `list`, `show`, `decommission`, `assign-site` |
| `job` | `list`, `show`, `trigger-bootstrap`, `apply-updates`, `gather-facts`, `bulk-apply-updates`, `run-command`, `manage-package`, `cancel` |
| `compliance` | `check`, `search` |
| `errata` | `list`, `show`, `affected-servers` |
| `host-group` | `create`, `list`, `show`, `set-members` |
| `activation-key` | `create`, `list`, `show`, `revoke` |
| `site` | `create`, `list`, `show`, `set-relay`, `set-environments` |
| `audit-log` | `list`, `export` (admin-only) |

Every list/show command supports `--output table` (default) or `--output
json` (raw JSON, for piping into `jq`/scripts). RBAC is enforced entirely
server-side — a role that can't perform an action gets a clean one-line
`HTTP 403: requires operator role or higher` (or similar) error and a
non-zero exit code, not a traceback.

`groundctl activation-key create` prints the raw activation-key token
exactly once, immediately after creation (matching the backend's
hash-only storage — it can never be retrieved again) — same show-once
behavior as the web UI's equivalent dialog.

## Known gap

**No `GET /content-views` list or detail endpoint exists on the
backend** (same gap the web UI hit and documented in `docs/web-ui.md`).
Content views can only be created — the CLI's `content-view` commands
require an explicit content-view ID (printed by `create`) rather than a
name-based lookup, and this is called out directly in
`groundctl content-view --help`. No backend endpoint was added to work
around this; add `GET /content-views` if it becomes a real pain point.

## Development

```bash
cd cli
pip install -e ".[test]"
pytest tests/ -v          # 15 tests, httpx.MockTransport only — no real backend
```
