import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.aptly_client import AptlyClient, AptlyError, get_aptly_client
from app.archive_probe import ArchiveProbeError, estimate_repository_size_bytes, probe_distributions
from app.auth import require_role
from app.database import get_db
from app.models import (
    AuditAction,
    AuditLog,
    ContentView,
    ContentViewRepository,
    Job,
    JobTargetType,
    JobType,
    Repository,
    Role,
    User,
)
from app.schemas import (
    APTLY_NAME_RE,
    JobRead,
    RepositoryAutoSyncUpdate,
    RepositoryBatchCreate,
    RepositoryBatchCreateError,
    RepositoryBatchCreateResult,
    RepositoryCreate,
    RepositoryEstimateSizeRequest,
    RepositoryEstimateSizeResult,
    RepositoryProbeRequest,
    RepositoryProbeResult,
    RepositoryRead,
    RepositoryUpdate,
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


@router.post("/estimate-size", response_model=RepositoryEstimateSizeResult)
def estimate_repository_size(
    payload: RepositoryEstimateSizeRequest,
    current_user: User = Depends(require_role(Role.operator)),
):
    """Best-effort pre-create size estimate, fetched straight from the
    upstream archive's Packages files (see archive_probe.py) — nothing is
    mirrored or persisted. Same require_role(operator) gate as /probe,
    for the same reason: a metadata fetch no more powerful than the probe
    endpoint that already sits at this role.
    """
    try:
        size_bytes = estimate_repository_size_bytes(
            str(payload.archive_url),
            payload.distribution,
            payload.components,
            payload.architectures,
        )
    except ArchiveProbeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return RepositoryEstimateSizeResult(size_bytes=size_bytes)


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


def _get_repository_or_404(db: Session, name: str) -> Repository:
    if not APTLY_NAME_RE.fullmatch(name):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid repository name")
    repository = db.execute(select(Repository).where(Repository.name == name)).scalar_one_or_none()
    if repository is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="repository not found")
    return repository


def _referencing_content_view_names(db: Session, repository: Repository) -> list[str]:
    return list(
        db.execute(
            select(ContentView.name)
            .join(ContentViewRepository, ContentViewRepository.content_view_id == ContentView.id)
            .where(ContentViewRepository.repository_id == repository.id)
            .order_by(ContentView.name)
        ).scalars()
    )


@router.get("/{name}", response_model=RepositoryRead)
def get_repository(
    name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    """Single-repository detail — the archive_url/distribution/components/
    architectures a list row truncates aren't otherwise inspectable without
    going through the CLI or the database directly.
    """
    return _get_repository_or_404(db, name)


@router.patch("/{name}/auto-sync", response_model=RepositoryRead)
def update_repository_auto_sync(
    name: str,
    payload: RepositoryAutoSyncUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    """Toggles whether the nightly scheduled sweep
    (scheduled_sync_all_repositories, app/tasks.py) includes this
    repository — DB-only, no aptly call, unlike the sync/edit/delete
    endpoints above. Manual sync (POST .../sync) is unaffected either way.
    """
    repository = _get_repository_or_404(db, name)
    repository.auto_sync_enabled = payload.auto_sync_enabled
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.update_repository,
            resource_type="repository",
            resource_id=repository.name,
            detail={"auto_sync_enabled": payload.auto_sync_enabled},
        )
    )
    db.commit()
    db.refresh(repository)
    return repository


@router.delete("/{name}", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def delete_repository(
    name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    """Triggers an async delete_repository_task (app/tasks.py) instead of
    deleting inline — confirmed live against a real instance that aptly's
    mirror delete can take long enough to blow both the default client
    timeout and the reverse proxy's own timeout (502 Bad Gateway before
    aptly ever responded). Same rationale as sync_repository's earlier move
    to a tracked Job. Blocked (409) here, before a Job is even created, if
    any ContentView still references this repository — deleting the mirror
    out from under a ContentView whose snapshot was cut from it would leave
    that ContentView pointing at deleted data, and aptly's own snapshot
    reference check doesn't know about groundctl's ContentView concept.
    The task itself re-checks this guard immediately before the actual
    delete, closing the race window between this request and the task
    running.
    """
    from app.tasks import delete_repository_task

    repository = _get_repository_or_404(db, name)

    referencing = _referencing_content_view_names(db, repository)
    if referencing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"repository is used by content view(s): {', '.join(referencing)}",
        )

    job = Job(
        job_type=JobType.delete_repository,
        target_type=JobTargetType.repository,
        repository_id=repository.id,
        created_by_user_id=current_user.id,
    )
    db.add(job)
    db.flush()
    # Set even though the row is about to be deleted server-side — the
    # window between this request returning and delete_repository_task
    # actually running is exactly when a reload needs to find this job.
    repository.last_job_id = job.id
    db.commit()
    db.refresh(job)

    delete_repository_task.delay(str(job.id))
    return job


@router.put("/{name}", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def update_repository(
    name: str,
    payload: RepositoryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    """Triggers an async update_repository_task (app/tasks.py) instead of
    editing inline — "editing" a repository deletes the old aptly mirror
    and creates a new one with the given settings under the same
    Repository row (aptly has no in-place way to change ArchiveURL/
    Distribution/Components, see RepositoryUpdate's docstring), carrying
    the exact same slow-delete timeout/502 risk confirmed live for plain
    delete. Same 409 ContentView guard as delete, for the same reason: this
    is a delete under the hood. last_synced_at/size_bytes/last_sync_job_id
    reset once the task actually runs — the new mirror has synced nothing
    yet.
    """
    from app.tasks import update_repository_task

    repository = _get_repository_or_404(db, name)

    referencing = _referencing_content_view_names(db, repository)
    if referencing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"repository is used by content view(s): {', '.join(referencing)}",
        )

    job = Job(
        job_type=JobType.update_repository,
        target_type=JobTargetType.repository,
        repository_id=repository.id,
        created_by_user_id=current_user.id,
    )
    db.add(job)
    db.flush()
    repository.last_job_id = job.id
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.update_repository,
            resource_type="repository",
            resource_id=str(job.id),
            detail={
                "archive_url": str(payload.archive_url),
                "distribution": payload.distribution,
                "components": payload.components,
                "architectures": payload.architectures,
            },
        )
    )
    db.commit()
    db.refresh(job)

    update_repository_task.delay(str(job.id))
    return job


@router.post("/{name}/sync", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def sync_repository(
    name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    """Triggers an async sync_repository_task (app/tasks.py) instead of
    syncing inline — a first-run mirror sync can take many minutes
    (aptly_client.py's sync_mirror), too long for a request/response cycle,
    and the old inline call left the operator with no way to check progress
    or know the request was still alive. Returns the Job so the UI can link
    straight to its status (GET /jobs/{id}).
    """
    # Deferred import: app.tasks imports do_sync_repository from this module,
    # so importing app.tasks at module load time here would be circular.
    from app.tasks import sync_repository_task

    repository = _get_repository_or_404(db, name)

    job = Job(
        job_type=JobType.sync_repository,
        target_type=JobTargetType.repository,
        repository_id=repository.id,
        created_by_user_id=current_user.id,
    )
    db.add(job)
    db.flush()
    repository.last_sync_job_id = job.id
    repository.last_job_id = job.id
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.sync_repository,
            resource_type="repository",
            resource_id=repository.name,
        )
    )
    db.commit()
    db.refresh(job)

    sync_repository_task.delay(str(job.id))
    return job
