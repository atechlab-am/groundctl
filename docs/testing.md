# Running the test suite

## Real Postgres, not SQLite

CLAUDE.md previously suggested "SQLite via `DATABASE_URL` override for
speed" — that doesn't actually work against this schema. The model layer
uses `postgresql.UUID` (50+ columns) and Postgres `ARRAY` (a handful of
columns), and SQLite has no native equivalent for either —
`Base.metadata.create_all()` against `sqlite:///:memory:` fails outright
with `CompileError: can't render element of type ARRAY`. Tests run
against a real scratch Postgres instead, matching this project's own
demonstrated preference for real infrastructure over mocks wherever
feasible (see `docs/limitations.md` for every phase's live-verification
precedent).

## One-time setup

```bash
# Postgres 16 (any recent Postgres works — this matches production)
createuser groundctl_test --login --pwprompt --superuser   # password: testpass
createdb groundctl_test --owner=groundctl_test

# Redis — used by the rate limiter (Phase 6) and Celery, both exercised
# indirectly by the test suite
redis-server --daemonize yes
```

## Running

```bash
pip install -r requirements.txt
python -m pytest tests/ -v
```

`tests/conftest.py` sets `DATABASE_URL` (defaulting to
`postgresql+psycopg://groundctl_test:testpass@127.0.0.1:5432/groundctl_test`,
overridable via `TEST_DATABASE_URL`) before any `app.*` import — required,
since `app/database.py`'s engine binds at module import time. A
session-scoped fixture runs the real Alembic migration chain once
(`alembic upgrade head` — exercising the actual migration path is the
point, not a shortcut via `create_all()`); each test gets a
`TRUNCATE ... CASCADE` of every table afterward, mirroring the manual
cleanup pattern used throughout this project's live-verification sessions,
now automated.

## What's mocked vs. real

- **`AptlyClient`** is always mocked (`app.dependency_overrides
  [get_aptly_client]`) — tests never hit a real aptly instance or the
  network, per CLAUDE.md's existing rule. Two fixtures: `mock_aptly`
  (sane defaults) and `mock_aptly_unreachable` (every method raises
  `AptlyError`, for exercising the "aptly unreachable" → `502` path every
  aptly-touching endpoint needs to handle).
- **Postgres, Redis, JWT auth, RBAC, rate limiting** are all real — no
  mocking. A `client` fixture provides a fully-wired `TestClient`, and
  `admin_token`/`operator_token`/`viewer_token` fixtures seed one real
  `User` per role and log in for real to get a real JWT.
- **Celery tasks are never actually executed** — there's no worker
  running in the test environment. Job-triggering endpoints are tested up
  to `.delay()` (confirm the `Job` row exists at the right status), not
  through to actual Ansible execution — that's still validated by this
  project's live-verification practice against real Docker/SSH
  infrastructure per phase, not by the automated suite.

## CI

`.github/workflows/ci.yml` runs the same suite against a `postgres:16`
service container — no local setup needed for CI runs, only for running
tests locally.
