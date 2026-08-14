import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_role
from app.celery_app import celery_app
from app.database import get_db
from app.models import (
    AuditAction,
    AuditLog,
    HostGroup,
    Job,
    JobServer,
    JobStatus,
    JobTargetType,
    JobType,
    LifecycleEnvironment,
    Role,
    Server,
    User,
)
from app.schemas import (
    BulkApplyUpdatesRequest,
    BulkTargetSelector,
    JobRead,
    ManagePackageRequest,
    RunCommandRequest,
)
from app.tasks import (
    apply_updates_task,
    bootstrap_task,
    bulk_apply_updates_task,
    gather_facts_task,
    manage_package_task,
    run_command_task,
)

router = APIRouter()

_TASKS = {
    JobType.bootstrap: bootstrap_task,
    JobType.apply_updates: apply_updates_task,
    JobType.gather_facts: gather_facts_task,
}


def _create_job_with_targets(
    db: Session,
    job_type: JobType,
    target_type: JobTargetType,
    servers: list[Server],
    *,
    environment_id: uuid.UUID | None = None,
    host_group_id: uuid.UUID | None = None,
    server_id: uuid.UUID | None = None,
    current_user: User,
    audit_action: AuditAction,
    audit_detail: dict | None = None,
) -> Job:
    job = Job(
        job_type=job_type,
        target_type=target_type,
        server_id=server_id,
        environment_id=environment_id,
        host_group_id=host_group_id,
        created_by_user_id=current_user.id,
    )
    db.add(job)
    db.flush()
    for server in servers:
        db.add(JobServer(job_id=job.id, server_id=server.id))
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=audit_action,
            resource_type="job",
            resource_id=str(job.id),
            detail=audit_detail,
        )
    )
    db.commit()
    db.refresh(job)
    return job


def _resolve_targets(db: Session, selector: BulkTargetSelector) -> tuple[list[Server], uuid.UUID | None, JobTargetType]:
    if bool(selector.host_group_id) == bool(selector.server_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="exactly one of host_group_id or server_ids must be set",
        )
    if selector.host_group_id:
        group = db.get(HostGroup, selector.host_group_id)
        if group is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="host group not found")
        return group.servers, group.id, JobTargetType.host_group

    # The bool(...) == bool(...) check above guarantees server_ids is set
    # (non-None, non-empty) here — this branch is only reached when
    # host_group_id was falsy, so its counterpart must be truthy.
    assert selector.server_ids is not None
    servers = list(db.execute(select(Server).where(Server.id.in_(selector.server_ids))).scalars())
    found_ids = {s.id for s in servers}
    missing = set(selector.server_ids) - found_ids
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"server ids not found: {sorted(str(m) for m in missing)}",
        )
    return servers, None, JobTargetType.adhoc


def _job_with_server_ids(db: Session, job: Job) -> Job:
    # Job has no mapped server_ids column — JobRead (schemas.py) declares
    # one anyway so responses can carry the resolved target-server set
    # (JobServer rows), and this attaches it as a plain, unmapped attribute
    # for from_attributes=True to pick up. Not a column mypy can see.
    job.server_ids = [  # type: ignore[attr-defined]
        row.server_id for row in db.execute(select(JobServer).where(JobServer.job_id == job.id)).scalars()
    ]
    return job


@router.get("", response_model=list[JobRead])
def list_jobs(
    job_type: JobType | None = None,
    status_: JobStatus | None = Query(default=None, alias="status"),
    environment_id: uuid.UUID | None = None,
    server_id: uuid.UUID | None = None,
    repository_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    query = select(Job)
    if job_type is not None:
        query = query.where(Job.job_type == job_type)
    if status_ is not None:
        query = query.where(Job.status == status_)
    if environment_id is not None:
        query = query.where(Job.environment_id == environment_id)
    if server_id is not None:
        query = query.where(Job.server_id == server_id)
    if repository_id is not None:
        query = query.where(Job.repository_id == repository_id)
    query = query.order_by(Job.created_at.desc()).limit(limit).offset(offset)
    jobs_ = list(db.execute(query).scalars())
    return [_job_with_server_ids(db, job) for job in jobs_]


@router.post("/bootstrap/{server_id}", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def trigger_bootstrap(
    server_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    server = db.get(Server, server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="server not found")

    job = _create_job_with_targets(
        db,
        JobType.bootstrap,
        JobTargetType.server,
        [server],
        server_id=server.id,
        current_user=current_user,
        audit_action=AuditAction.trigger_bootstrap,
    )
    bootstrap_task.delay(str(job.id))
    return _job_with_server_ids(db, job)


@router.post("/apply-updates", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def trigger_apply_updates(
    environment_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    environment = db.get(LifecycleEnvironment, environment_id)
    if environment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="environment not found")

    servers = list(db.execute(select(Server).where(Server.environment_id == environment.id)).scalars())
    job = _create_job_with_targets(
        db,
        JobType.apply_updates,
        JobTargetType.environment,
        servers,
        environment_id=environment.id,
        current_user=current_user,
        audit_action=AuditAction.trigger_apply_updates,
    )
    apply_updates_task.delay(str(job.id))
    return _job_with_server_ids(db, job)


@router.post("/gather-facts", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def trigger_gather_facts(
    environment_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    environment = db.get(LifecycleEnvironment, environment_id)
    if environment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="environment not found")

    servers = list(db.execute(select(Server).where(Server.environment_id == environment.id)).scalars())
    job = _create_job_with_targets(
        db,
        JobType.gather_facts,
        JobTargetType.environment,
        servers,
        environment_id=environment.id,
        current_user=current_user,
        audit_action=AuditAction.trigger_gather_facts,
    )
    gather_facts_task.delay(str(job.id))
    return _job_with_server_ids(db, job)


@router.post("/bulk-apply-updates", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def trigger_bulk_apply_updates(
    payload: BulkApplyUpdatesRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    servers, host_group_id, target_type = _resolve_targets(db, payload)
    job = _create_job_with_targets(
        db,
        JobType.bulk_apply_updates,
        target_type,
        servers,
        host_group_id=host_group_id,
        current_user=current_user,
        audit_action=AuditAction.trigger_bulk_apply_updates,
        audit_detail={"target_hostnames": [s.hostname for s in servers]},
    )
    bulk_apply_updates_task.delay(str(job.id))
    return _job_with_server_ids(db, job)


@router.post("/run-command", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def trigger_run_command(
    payload: RunCommandRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.admin)),
):
    # Admin-only, not operator — arbitrary root command execution across a
    # selection of fleet hosts warrants the highest tier, unlike the other
    # trigger endpoints in this router.
    servers, host_group_id, target_type = _resolve_targets(db, payload)
    job = _create_job_with_targets(
        db,
        JobType.run_command,
        target_type,
        servers,
        host_group_id=host_group_id,
        current_user=current_user,
        audit_action=AuditAction.trigger_run_command,
        # Full audit of the exact command and resolved hosts, same
        # transaction as the Job row — this is the only record of what was
        # actually run, and tasks.py reads the command back from here.
        audit_detail={"command": payload.command, "target_hostnames": [s.hostname for s in servers]},
    )
    run_command_task.delay(str(job.id))
    return _job_with_server_ids(db, job)


@router.post("/manage-package", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def trigger_manage_package(
    payload: ManagePackageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    server = db.get(Server, payload.server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="server not found")

    job = _create_job_with_targets(
        db,
        JobType.manage_package,
        JobTargetType.server,
        [server],
        server_id=server.id,
        current_user=current_user,
        audit_action=AuditAction.trigger_manage_package,
        audit_detail={"package_name": payload.package_name, "action": payload.action.value},
    )
    manage_package_task.delay(str(job.id))
    return _job_with_server_ids(db, job)


@router.get("/{job_id}", response_model=JobRead)
def get_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    return _job_with_server_ids(db, job)


@router.post("/{job_id}/cancel", response_model=JobRead)
def cancel_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")

    if job.status not in (JobStatus.pending, JobStatus.running):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"job is already {job.status.value}")

    if job.status == JobStatus.pending:
        job.log_output = "cancelled before execution"
    else:
        if job.celery_task_id:
            celery_app.control.revoke(job.celery_task_id, terminate=True, signal="SIGTERM")
        job.log_output = "cancelled by user"

    job.status = JobStatus.failed
    job.finished_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    return _job_with_server_ids(db, job)
