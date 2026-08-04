import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone

from app.config import settings

# Set by CorrelationIdMiddleware for the duration of a request; read by
# JsonFormatter so every log line emitted while handling that request
# carries the same id. None outside request context (e.g. Celery tasks —
# see docs/limitations.md for the resulting gap: no cross-process trace
# linking a job dispatch to its eventual Celery execution).
correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)

_RESERVED_LOG_RECORD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": correlation_id_var.get(),
        }
        # Any extra= fields passed to the log call ride along verbatim —
        # LogRecord stores them as plain attributes, so anything not part
        # of the standard set is caller-supplied structured data.
        for key, value in record.__dict__.items():
            if key not in _RESERVED_LOG_RECORD_ATTRS and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(settings.log_level)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
