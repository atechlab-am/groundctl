import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import settings
from app.models import InstanceSetting

# Single shared row — same fixed-id singleton pattern as
# app/routers/branding.py's _BRANDING_ID.
INSTANCE_SETTINGS_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


@dataclass(frozen=True)
class EffectiveSettings:
    audit_log_retention_days: int
    activation_key_default_ttl_hours: int
    stale_checkin_hours: int
    relay_stale_threshold_hours: int
    disk_usage_warn_percent: float
    webhook_url: str | None
    webhook_secret: str | None


def get_instance_settings(db: Session) -> InstanceSetting | None:
    return db.get(InstanceSetting, INSTANCE_SETTINGS_ID)


def get_or_create_instance_settings(db: Session) -> InstanceSetting:
    row = get_instance_settings(db)
    if row is None:
        row = InstanceSetting(id=INSTANCE_SETTINGS_ID)
        db.add(row)
        db.flush()
    return row


def get_effective_settings(db: Session) -> EffectiveSettings:
    """Resolves the 7 runtime-tunable operational settings, DB override
    (InstanceSetting, admin-editable via /api/instance-settings) falling
    back to the config.py/env-var default per field — a NULL column means
    "not overridden". Every call site that used to read these directly off
    the module-level `settings` object should go through this instead, so
    an admin's change takes effect without a restart. Connection/secret-
    shaped config (database_url, jwt_secret, aptly_api_url, TLS/SSH key
    paths) is deliberately not part of this — those stay env-only, see
    InstanceSetting's docstring.
    """
    row = get_instance_settings(db)
    return EffectiveSettings(
        audit_log_retention_days=(
            row.audit_log_retention_days if row and row.audit_log_retention_days is not None
            else settings.audit_log_retention_days
        ),
        activation_key_default_ttl_hours=(
            row.activation_key_default_ttl_hours if row and row.activation_key_default_ttl_hours is not None
            else settings.activation_key_default_ttl_hours
        ),
        stale_checkin_hours=(
            row.stale_checkin_hours if row and row.stale_checkin_hours is not None
            else settings.stale_checkin_hours
        ),
        relay_stale_threshold_hours=(
            row.relay_stale_threshold_hours if row and row.relay_stale_threshold_hours is not None
            else settings.relay_stale_threshold_hours
        ),
        disk_usage_warn_percent=(
            row.disk_usage_warn_percent if row and row.disk_usage_warn_percent is not None
            else settings.disk_usage_warn_percent
        ),
        webhook_url=(row.webhook_url if row and row.webhook_url is not None else settings.webhook_url),
        webhook_secret=(row.webhook_secret if row and row.webhook_secret is not None else settings.webhook_secret),
    )
