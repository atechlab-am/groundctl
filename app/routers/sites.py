import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth import require_role
from app.database import get_db
from app.models import AuditAction, AuditLog, LifecycleEnvironment, Relay, Role, Site, SiteEnvironment, User
from app.schemas import (
    LifecycleEnvironmentRead,
    RelayCreate,
    RelayRead,
    SiteCreate,
    SiteEnvironmentsUpdate,
    SiteRead,
)

router = APIRouter()


@router.post("", response_model=SiteRead, status_code=status.HTTP_201_CREATED)
def create_site(
    payload: SiteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    existing = db.execute(select(Site).where(Site.name == payload.name)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="site name already in use")

    site = Site(name=payload.name, description=payload.description)
    db.add(site)
    db.flush()
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.create_site,
            resource_type="site",
            resource_id=str(site.id),
        )
    )
    db.commit()
    db.refresh(site)
    return site


@router.get("", response_model=list[SiteRead])
def list_sites(
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    query = select(Site).order_by(Site.name).limit(limit).offset(offset)
    return list(db.execute(query).scalars())


@router.get("/{site_id}", response_model=SiteRead)
def get_site(
    site_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    site = db.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="site not found")
    return site


@router.post("/{site_id}/relay", response_model=RelayRead, status_code=status.HTTP_201_CREATED)
def create_relay(
    site_id: uuid.UUID,
    payload: RelayCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    site = db.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="site not found")

    existing = db.execute(select(Relay).where(Relay.site_id == site_id)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="this site already has a relay")

    relay = Relay(site_id=site_id, hostname=payload.hostname, ssh_user=payload.ssh_user)
    db.add(relay)
    db.flush()
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.create_relay,
            resource_type="relay",
            resource_id=str(relay.id),
            detail={"site_id": str(site_id)},
        )
    )
    db.commit()
    db.refresh(relay)
    return relay


@router.get("/{site_id}/relay", response_model=RelayRead)
def get_relay(
    site_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    if db.get(Site, site_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="site not found")

    relay = db.execute(select(Relay).where(Relay.site_id == site_id)).scalar_one_or_none()
    if relay is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="this site has no relay yet")
    return relay


@router.get("/{site_id}/environments", response_model=list[LifecycleEnvironmentRead])
def list_site_environments(
    site_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    if db.get(Site, site_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="site not found")

    return list(
        db.execute(
            select(LifecycleEnvironment)
            .join(SiteEnvironment, SiteEnvironment.environment_id == LifecycleEnvironment.id)
            .where(SiteEnvironment.site_id == site_id)
            .order_by(LifecycleEnvironment.name)
            .limit(limit)
            .offset(offset)
        ).scalars()
    )


@router.put("/{site_id}/environments", response_model=list[LifecycleEnvironmentRead])
def replace_site_environments(
    site_id: uuid.UUID,
    payload: SiteEnvironmentsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    if db.get(Site, site_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="site not found")

    environments = list(
        db.execute(select(LifecycleEnvironment).where(LifecycleEnvironment.id.in_(payload.environment_ids))).scalars()
    )
    found_ids = {e.id for e in environments}
    missing = set(payload.environment_ids) - found_ids
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"environment ids not found: {sorted(str(m) for m in missing)}",
        )

    existing_ids = {
        row.environment_id
        for row in db.execute(select(SiteEnvironment).where(SiteEnvironment.site_id == site_id)).scalars()
    }
    added = found_ids - existing_ids
    removed = existing_ids - found_ids

    db.execute(delete(SiteEnvironment).where(SiteEnvironment.site_id == site_id))
    for environment_id in found_ids:
        db.add(SiteEnvironment(site_id=site_id, environment_id=environment_id))

    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.update_site_environments,
            resource_type="site",
            resource_id=str(site_id),
            detail={"added": [str(i) for i in added], "removed": [str(i) for i in removed]},
        )
    )
    db.commit()
    return environments
