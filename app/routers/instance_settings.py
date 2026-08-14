from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import require_role
from app.database import get_db
from app.instance_settings import get_effective_settings, get_instance_settings, get_or_create_instance_settings
from app.models import AuditAction, AuditLog, Role, User
from app.schemas import InstanceSettingsRead, InstanceSettingsUpdate

router = APIRouter()

_OVERRIDABLE_FIELDS = (
    "audit_log_retention_days",
    "activation_key_default_ttl_hours",
    "stale_checkin_hours",
    "relay_stale_threshold_hours",
    "repository_stale_threshold_hours",
    "disk_usage_warn_percent",
    "webhook_url",
)


def _read(db: Session) -> InstanceSettingsRead:
    effective = get_effective_settings(db)
    row = get_instance_settings(db)
    overridden = {field: bool(row is not None and getattr(row, field) is not None) for field in _OVERRIDABLE_FIELDS}
    overridden["webhook_secret"] = bool(row is not None and row.webhook_secret is not None)
    return InstanceSettingsRead(
        audit_log_retention_days=effective.audit_log_retention_days,
        activation_key_default_ttl_hours=effective.activation_key_default_ttl_hours,
        stale_checkin_hours=effective.stale_checkin_hours,
        relay_stale_threshold_hours=effective.relay_stale_threshold_hours,
        repository_stale_threshold_hours=effective.repository_stale_threshold_hours,
        disk_usage_warn_percent=effective.disk_usage_warn_percent,
        webhook_url=effective.webhook_url,
        has_webhook_secret=effective.webhook_secret is not None,
        overridden=overridden,
        updated_at=row.updated_at if row is not None else None,
    )


@router.get("", response_model=InstanceSettingsRead)
def get_instance_settings_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.admin)),
):
    """Admin-only, unlike GET /branding — these are operational tunables
    (retention windows, staleness thresholds, webhook target), not
    something every authenticated user's UI needs to render.
    """
    return _read(db)


@router.put("", response_model=InstanceSettingsRead)
def update_instance_settings(
    payload: InstanceSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.admin)),
):
    row = get_or_create_instance_settings(db)
    fields = payload.model_dump(exclude_unset=True)

    audit_detail: dict = {}
    for field in _OVERRIDABLE_FIELDS:
        if field in fields:
            setattr(row, field, fields[field])
            audit_detail[field] = fields[field]

    # webhook_secret never appears in audit_detail or any response — same
    # write-only posture as a password. "set" vs "cleared" is the only
    # thing worth recording, not the value itself.
    if "webhook_secret" in fields:
        row.webhook_secret = fields["webhook_secret"]
        audit_detail["webhook_secret"] = "cleared" if fields["webhook_secret"] is None else "set"

    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.update_instance_settings,
            resource_type="instance_settings",
            resource_id=str(row.id),
            detail=audit_detail,
        )
    )
    db.commit()
    return _read(db)
