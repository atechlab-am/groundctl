from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings

# Redis-backed — Redis is already a first-class dependency here (Celery
# broker/result backend), so this adds no new infrastructure. Shared single
# instance imported by both main.py (exception handler wiring) and any
# router applying @limiter.limit(...) to a specific endpoint.
limiter = Limiter(key_func=get_remote_address, storage_uri=settings.redis_url)
