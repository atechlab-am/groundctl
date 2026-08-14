import csv
import io
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_role
from app.database import get_db
from app.models import AuditAction, AuditLog, Role, User
from app.schemas import AuditLogRead

router = APIRouter()

# Audit data is itself sensitive — who-did-what is exactly what an attacker
# who's already compromised a lesser account wants to see or scrub. Both
# endpoints below are admin-gated, unlike the mostly-viewer-gated read
# endpoints elsewhere in the app.


def _filtered_query(
    user_id: uuid.UUID | None,
    action: AuditAction | None,
    resource_type: str | None,
    since: datetime | None,
    until: datetime | None,
):
    query = select(AuditLog)
    if user_id is not None:
        query = query.where(AuditLog.user_id == user_id)
    if action is not None:
        query = query.where(AuditLog.action == action)
    if resource_type is not None:
        query = query.where(AuditLog.resource_type == resource_type)
    if since is not None:
        query = query.where(AuditLog.created_at >= since)
    if until is not None:
        query = query.where(AuditLog.created_at <= until)
    return query.order_by(AuditLog.created_at.desc())


@router.get("", response_model=list[AuditLogRead])
def list_audit_logs(
    user_id: uuid.UUID | None = None,
    action: AuditAction | None = None,
    resource_type: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.admin)),
):
    query = _filtered_query(user_id, action, resource_type, since, until).limit(limit).offset(offset)
    return list(db.execute(query).scalars())


@router.get("/export")
def export_audit_logs(
    user_id: uuid.UUID | None = None,
    action: AuditAction | None = None,
    resource_type: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.admin)),
):
    rows = list(db.execute(_filtered_query(user_id, action, resource_type, since, until)).scalars())

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "user_id", "action", "resource_type", "resource_id", "detail", "created_at"])
    for row in rows:
        writer.writerow(
            [
                str(row.id),
                str(row.user_id) if row.user_id else "",
                row.action.value,
                row.resource_type,
                row.resource_id or "",
                row.detail or "",
                row.created_at.isoformat(),
            ]
        )
    buffer.seek(0)

    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.export_audit_log,
            resource_type="audit_log",
            resource_id=None,
            detail={"row_count": len(rows)},
        )
    )
    db.commit()

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit-log-export.csv"},
    )
