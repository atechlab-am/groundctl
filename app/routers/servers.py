import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_role
from app.database import get_db
from app.models import (
    AuditAction,
    AuditLog,
    HostGroupServer,
    LifecycleEnvironment,
    Role,
    Server,
    ServerFact,
    ServerLifecycleState,
    Site,
    User,
)
from app.schemas import ServerCreate, ServerEnvironmentAssign, ServerFactRead, ServerRead

router = APIRouter()


@router.post("", response_model=ServerRead, status_code=status.HTTP_201_CREATED)
def create_server(
    payload: ServerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    environment = db.get(LifecycleEnvironment, payload.environment_id)
    if environment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="environment not found")

    if payload.site_id is not None and db.get(Site, payload.site_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="site not found")

    server = Server(
        hostname=payload.hostname,
        ip_address=str(payload.ip_address),
        ssh_user=payload.ssh_user,
        environment_id=payload.environment_id,
        site_id=payload.site_id,
    )
    db.add(server)
    db.flush()
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.create_server,
            resource_type="server",
            resource_id=str(server.id),
        )
    )
    db.commit()
    db.refresh(server)
    return server


@router.get("", response_model=list[ServerRead])
def list_servers(
    environment_id: uuid.UUID | None = None,
    host_group_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    lifecycle_state: ServerLifecycleState | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    query = select(Server)
    if environment_id is not None:
        query = query.where(Server.environment_id == environment_id)
    if site_id is not None:
        query = query.where(Server.site_id == site_id)
    if lifecycle_state is not None:
        query = query.where(Server.lifecycle_state == lifecycle_state)
    if host_group_id is not None:
        query = query.join(HostGroupServer, HostGroupServer.server_id == Server.id).where(
            HostGroupServer.host_group_id == host_group_id
        )
    query = query.order_by(Server.hostname).limit(limit).offset(offset)
    return list(db.execute(query).scalars())


@router.get("/{server_id}", response_model=ServerRead)
def get_server(
    server_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    server = db.get(Server, server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="server not found")
    return server


@router.get("/{server_id}/facts", response_model=ServerFactRead)
def get_latest_server_facts(
    server_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    if db.get(Server, server_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="server not found")

    fact = db.execute(
        select(ServerFact).where(ServerFact.server_id == server_id).order_by(ServerFact.gathered_at.desc()).limit(1)
    ).scalar_one_or_none()
    if fact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no facts gathered for this server yet")
    return fact


@router.get("/{server_id}/facts/history", response_model=list[ServerFactRead])
def get_server_facts_history(
    server_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    if db.get(Server, server_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="server not found")

    return list(
        db.execute(
            select(ServerFact)
            .where(ServerFact.server_id == server_id)
            .order_by(ServerFact.gathered_at.desc())
            .limit(limit)
            .offset(offset)
        ).scalars()
    )


@router.post("/{server_id}/decommission", response_model=ServerRead)
def decommission_server(
    server_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    server = db.get(Server, server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="server not found")

    server.lifecycle_state = ServerLifecycleState.decommissioned
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.decommission_server,
            resource_type="server",
            resource_id=str(server.id),
        )
    )
    db.commit()
    db.refresh(server)
    return server


@router.post("/{server_id}/assign-site", response_model=ServerRead)
def assign_server_site(
    server_id: uuid.UUID,
    site_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    server = db.get(Server, server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="server not found")
    if site_id is not None and db.get(Site, site_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="site not found")

    server.site_id = site_id
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.assign_server_site,
            resource_type="server",
            resource_id=str(server.id),
            detail={"site_id": str(site_id) if site_id else None},
        )
    )
    db.commit()
    db.refresh(server)
    return server


@router.post("/{server_id}/assign-environment", response_model=ServerRead)
def assign_server_environment(
    server_id: uuid.UUID,
    payload: ServerEnvironmentAssign,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    """The deliberate, human-driven action that changes which lifecycle
    environment a server belongs to — see the comment on
    Server.environment_id and enrollment.py's re-registration note, which
    both point here. Changing the DB row alone doesn't move any packages;
    the host only actually starts pulling from the new environment once
    it re-bootstraps (POST /jobs/bootstrap/{id}, which now replaces rather
    than adds to its groundctl-managed apt source — see
    bootstrap_client.yml) or, once deployed, its next beacon checkin.
    """
    server = db.get(Server, server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="server not found")
    if server.lifecycle_state == ServerLifecycleState.decommissioned:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="server is decommissioned")

    new_environment = db.get(LifecycleEnvironment, payload.environment_id)
    if new_environment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="environment not found")

    if server.environment_id == payload.environment_id:
        return server

    old_environment = db.get(LifecycleEnvironment, server.environment_id)
    server.environment_id = payload.environment_id
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.assign_server_environment,
            resource_type="server",
            resource_id=str(server.id),
            detail={
                "from_environment_id": str(old_environment.id) if old_environment else None,
                "from_environment_name": old_environment.name if old_environment else None,
                "to_environment_id": str(new_environment.id),
                "to_environment_name": new_environment.name,
                "reason": payload.reason,
            },
        )
    )
    db.commit()
    db.refresh(server)
    return server
