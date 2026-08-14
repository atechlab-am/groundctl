"""Shared helper for clearing the /auth/login rate limit between tests.

POST /auth/login is rate-limited to 5/minute (see app/routers/auth.py,
app/limiter.py), keyed by remote address in real Redis — not reset by
db_session's per-test TRUNCATE, and not scoped per-test at all. Any test
file that mints more than 5 tokens per minute (e.g. via the admin_token /
operator_token / viewer_token fixtures, or _token_for called directly)
will start getting 429s from its own earlier logins.

conftest.py is off-limits to edit (see task constraints), so each test
file that needs many tokens imports reset_login_rate_limit and applies it
as an autouse fixture locally. Deliberately narrow — deletes only the
login-limiter key(s), not FLUSHDB, so it doesn't disturb Celery or other
Redis state shared with the rest of this session.
"""

import os

import redis as redis_lib


def reset_login_rate_limit() -> None:
    r = redis_lib.from_url(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
    for key in r.keys("LIMITS:LIMITER/*/auth/login/*"):
        r.delete(key)
