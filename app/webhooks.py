import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

import httpx

from app.config import settings

logger = logging.getLogger("groundctl.webhooks")


def send_webhook(event: str, payload: dict) -> None:
    """Best-effort, fire-and-forget delivery for host-alerting events
    (server.stale, server.unreachable) — see docs/limitations.md. No-op if
    webhook_url isn't configured. Never raises: a down/misconfigured webhook
    endpoint must not fail the job/scheduled task that triggered it.
    """
    if not settings.webhook_url:
        return

    body = json.dumps(
        {"event": event, "data": payload, "timestamp": datetime.now(timezone.utc).isoformat()}
    ).encode()

    headers = {"Content-Type": "application/json"}
    if settings.webhook_secret:
        signature = hmac.new(settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        headers["X-Groundctl-Signature"] = f"sha256={signature}"

    try:
        response = httpx.post(settings.webhook_url, content=body, headers=headers, timeout=5.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("webhook delivery failed for event %s: %s", event, exc)
