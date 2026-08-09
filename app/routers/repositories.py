import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.aptly_client import AptlyClient, AptlyError, get_aptly_client
from app.archive_probe import ArchiveProbeError, probe_distributions
from app.auth import require_role
from app.database import get_db
from app.models import AuditAction, AuditLog, Repository, Role, User
from app.schemas import (
    APTLY_NAME_RE,
    RepositoryBatchCreate,
    RepositoryBatchCreateError,
    RepositoryBatchCreateResult,
    RepositoryCreate,
    RepositoryProbeRequest,
    RepositoryProbeResult,
    RepositoryRead,
)

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


def _create_one_repository(
    name: str,
    archive_url: str,
    distribution: str,
    components: list[str],
    architectures: list[str],
    db: Session,
    aptly: AptlyClient,
    current_user: User,
) -> Repository:
    """Shared by create_repository and create_repositories_batch — mirrors
    the aptly object, then the local Repository row + audit log, in that
    order (matches the original single-create endpoint's behavior: don't
    record a repository groundctl doesn't actually have a working mirror
    for). Raises HTTPException(409) or lets AptlyError propagate to the
    caller, which decides how to report it (batch turns it into a per-item
    error instead of failing the whole request).
    """
    existing = db.execute(select(Repository).where(Repository.name == name)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="repository name already exists")

    aptly.create_mirror(
        name=name,
        archive_url=archive_url,
        distribution=distribution,
        components=components,
        architectures=architectures,
    )

    repository = Repository(
        name=name,
        archive_url=archive_url,
        distribution=distribution,
        components=components,
        architectures=architectures,
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
    return repository


@router.post("", response_model=RepositoryRead, status_code=status.HTTP_201_CREATED)
def create_repository(
    payload: RepositoryCreate,
    db: Session = Depends(get_db),
    aptly: AptlyClient = Depends(get_aptly_client),
    current_user: User = Depends(require_role(Role.operator)),
):
    try:
        repository = _create_one_repository(
            name=payload.name,
            archive_url=str(payload.archive_url),
            distribution=payload.distribution,
            components=payload.components,
            architectures=payload.architectures,
            db=db,
            aptly=aptly,
            current_user=current_user,
        )
    except AptlyError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    db.commit()
    db.refresh(repository)
    return repository


@router.post("/probe", response_model=RepositoryProbeResult)
def probe_repository_archive(
    payload: RepositoryProbeRequest,
    current_user: User = Depends(require_role(Role.operator)),
):
    """Lists the distributions published under <archive_url>/dists/ so the
    UI can offer a multi-select instead of requiring the operator to already
    know an exact distribution name. Read-only — makes one outbound HTTP GET
    to the given archive_url, nothing is persisted. Gated at the same
    require_role(operator) as actually creating a mirror from that same
    archive_url below, since this call is strictly less powerful (a small
    metadata fetch vs. mirroring real package data).
    """
    try:
        distributions = probe_distributions(str(payload.archive_url))
    except ArchiveProbeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return RepositoryProbeResult(distributions=distributions)


@router.post("/batch", response_model=RepositoryBatchCreateResult, status_code=status.HTTP_201_CREATED)
def create_repositories_batch(
    payload: RepositoryBatchCreate,
    db: Session = Depends(get_db),
    aptly: AptlyClient = Depends(get_aptly_client),
    current_user: User = Depends(require_role(Role.operator)),
):
    """Creates one Repository per selected distribution, named after the
    distribution itself. Partial failure is expected and reported per-item
    rather than aborting the whole batch — e.g. one distribution's name
    already exists, or aptly rejects one of several mirrors — the operator
    picked several independent distributions and a failure on one shouldn't
    discard progress on the rest.
    """
    created: list[RepositoryRead] = []
    errors: list[RepositoryBatchCreateError] = []

    for distribution in payload.distributions:
        try:
            repository = _create_one_repository(
                name=distribution,
                archive_url=str(payload.archive_url),
                distribution=distribution,
                components=payload.components,
                architectures=payload.architectures,
                db=db,
                aptly=aptly,
                current_user=current_user,
            )
        except HTTPException as exc:
            db.rollback()
            errors.append(RepositoryBatchCreateError(distribution=distribution, detail=str(exc.detail)))
            continue
        except AptlyError as exc:
            db.rollback()
            errors.append(RepositoryBatchCreateError(distribution=distribution, detail=str(exc)))
            continue

        db.commit()
        db.refresh(repository)
        created.append(RepositoryRead.model_validate(repository))

    return RepositoryBatchCreateResult(created=created, errors=errors)


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
