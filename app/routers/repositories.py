import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.aptly_client import AptlyClient, AptlyError, get_aptly_client
from app.auth import require_role
from app.database import get_db
from app.models import AuditAction, AuditLog, Repository, Role, User
from app.schemas import APTLY_NAME_RE, RepositoryCreate, RepositoryRead

router = APIRouter()


def do_sync_repository(repository: Repository, db: Session, aptly: AptlyClient, user_id: uuid.UUID | None) -> None:
    """Shared by the sync endpoint and the nightly scheduled sync task.
    user_id=None represents a system-triggered (Beat) sync — AuditLog.user_id
    is nullable specifically to support this. Caller commits; this function
    only stages changes (matches the endpoint's existing transaction shape).
    """
    aptly.sync_mirror(repository.name)
    repository.last_synced_at = datetime.now(timezone.utc)
    db.add(
        AuditLog(
            user_id=user_id,
            action=AuditAction.sync_repository,
            resource_type="repository",
            resource_id=repository.name,
        )
    )


@router.post("", response_model=RepositoryRead, status_code=status.HTTP_201_CREATED)
def create_repository(
    payload: RepositoryCreate,
    db: Session = Depends(get_db),
    aptly: AptlyClient = Depends(get_aptly_client),
    current_user: User = Depends(require_role(Role.operator)),
):
    existing = db.execute(select(Repository).where(Repository.name == payload.name)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="repository name already exists")

    try:
        aptly.create_mirror(
            name=payload.name,
            archive_url=str(payload.archive_url),
            distribution=payload.distribution,
            components=payload.components,
            architectures=payload.architectures,
        )
    except AptlyError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    repository = Repository(
        name=payload.name,
        archive_url=str(payload.archive_url),
        distribution=payload.distribution,
        components=payload.components,
        architectures=payload.architectures,
    )
    db.add(repository)
    db.flush()
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.create_repository,
            resource_type="repository",
            resource_id=repository.name,
        )
    )
    db.commit()
    db.refresh(repository)
    return repository


@router.get("", response_model=list[RepositoryRead])
def list_repositories(
    distribution: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    query = select(Repository)
    if distribution is not None:
        query = query.where(Repository.distribution == distribution)
    query = query.order_by(Repository.name).limit(limit).offset(offset)
    return list(db.execute(query).scalars())


@router.post("/{name}/sync", response_model=RepositoryRead)
def sync_repository(
    name: str,
    db: Session = Depends(get_db),
    aptly: AptlyClient = Depends(get_aptly_client),
    current_user: User = Depends(require_role(Role.operator)),
):
    if not APTLY_NAME_RE.fullmatch(name):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid repository name")

    repository = db.execute(select(Repository).where(Repository.name == name)).scalar_one_or_none()
    if repository is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="repository not found")

    try:
        do_sync_repository(repository, db, aptly, current_user.id)
    except AptlyError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    db.commit()
    db.refresh(repository)
    return repository
