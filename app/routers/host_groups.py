import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_role
from app.database import get_db
from app.models import AuditAction, AuditLog, HostGroup, HostGroupServer, Role, Server, User
from app.schemas import HostGroupCreate, HostGroupMembershipUpdate, HostGroupRead, ServerRead

router = APIRouter()


@router.post("", response_model=HostGroupRead, status_code=status.HTTP_201_CREATED)
def create_host_group(
    payload: HostGroupCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    existing = db.execute(select(HostGroup).where(HostGroup.name == payload.name)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="host group name already in use")

    group = HostGroup(
        name=payload.name,
        description=payload.description,
        default_environment_id=payload.default_environment_id,
    )
    db.add(group)
    db.flush()
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.create_host_group,
            resource_type="host_group",
            resource_id=str(group.id),
        )
    )
    db.commit()
    db.refresh(group)
    return group


@router.get("", response_model=list[HostGroupRead])
def list_host_groups(
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    query = select(HostGroup).order_by(HostGroup.name).limit(limit).offset(offset)
    return list(db.execute(query).scalars())


@router.get("/{host_group_id}", response_model=HostGroupRead)
def get_host_group(
    host_group_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    group = db.get(HostGroup, host_group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="host group not found")
    return group


@router.get("/{host_group_id}/members", response_model=list[ServerRead])
def list_host_group_members(
    host_group_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    if db.get(HostGroup, host_group_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="host group not found")
    query = (
        select(Server)
        .join(HostGroupServer, HostGroupServer.server_id == Server.id)
        .where(HostGroupServer.host_group_id == host_group_id)
        .order_by(Server.hostname)
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(query).scalars())


@router.put("/{host_group_id}/members", response_model=list[ServerRead])
def replace_host_group_members(
    host_group_id: uuid.UUID,
    payload: HostGroupMembershipUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    group = db.get(HostGroup, host_group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="host group not found")

    servers = list(db.execute(select(Server).where(Server.id.in_(payload.server_ids))).scalars())
    found_ids = {s.id for s in servers}
    missing = set(payload.server_ids) - found_ids
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"server ids not found: {sorted(str(m) for m in missing)}",
        )

    existing_ids = {
        row.server_id
        for row in db.execute(
            select(HostGroupServer).where(HostGroupServer.host_group_id == host_group_id)
        ).scalars()
    }
    added = found_ids - existing_ids
    removed = existing_ids - found_ids

    db.execute(
        HostGroupServer.__table__.delete().where(HostGroupServer.host_group_id == host_group_id)
    )
    for server_id in found_ids:
        db.add(HostGroupServer(host_group_id=host_group_id, server_id=server_id))

    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.update_host_group_membership,
            resource_type="host_group",
            resource_id=str(host_group_id),
            detail={"added": [str(i) for i in added], "removed": [str(i) for i in removed]},
        )
    )
    db.commit()
    db.refresh(group)
    return group.servers
