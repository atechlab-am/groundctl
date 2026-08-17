"""Shared Redis locking helper — extracted out of app/tasks.py so a
synchronous router endpoint can take the same per-resource lock a
background Job task would, without a circular import (routers/*.py is
imported BY tasks.py, so tasks.py can never be imported back from a
router). Originally Celery-task-only; lifecycle_environments.py's
promote_environment needs it too now that both the synchronous /promote
endpoint and the async publish_and_promote_task can perform an
environment's first-promote derive-and-lock (content_view_id/release/
publish_prefix), and only one of them was actually taking this lock.
"""

import redis

from app.config import settings

_redis = redis.from_url(settings.redis_url)

# Matches AptlyClient's own convention for long-running operations against a
# large fleet (see aptly_client.py's 1800s sync/publish timeouts).
LOCK_TIMEOUT_SECONDS = 1800


def acquire_lock(key: str):
    lock = _redis.lock(key, timeout=LOCK_TIMEOUT_SECONDS, blocking=False)
    return lock if lock.acquire(blocking=False) else None
