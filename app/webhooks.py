import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.instance_settings import get_effective_settings

logger = logging.getLogger("groundctl.webhooks")


def send_webhook(db: Session, event: str, payload: dict) -> None:
    """Best-effort, fire-and-forget delivery for host-alerting events
    (server.stale, server.unreachable) — see docs/limitations.md. No-op if
    webhook_url isn't configured (env default or admin-set override — see
    app/instance_settings.py). Never raises: a down/misconfigured webhook
    endpoint must not fail the job/scheduled task that triggered it.
    """
    effective = get_effective_settings(db)
    if not effective.webhook_url:
        return

    body = json.dumps(
        {"event": event, "data": payload, "timestamp": datetime.now(timezone.utc).isoformat()}
    ).encode()

    headers = {"Content-Type": "application/json"}
    if effective.webhook_secret:
        signature = hmac.new(effective.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        headers["X-Groundctl-Signature"] = f"sha256={signature}"

    try:
        response = httpx.post(effective.webhook_url, content=body, headers=headers, timeout=5.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("webhook delivery failed for event %s: %s", event, exc)
