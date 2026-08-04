import subprocess
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.aptly_client import AptlyClient, AptlyError, get_aptly_client
from app.auth import require_role
from app.config import settings
from app.database import get_db
from app.models import AuditAction, AuditLog, ContentView, ContentViewVersion, LifecycleEnvironment, Role, User
from app.routers.content_views import do_publish
from app.schemas import (
    LifecycleEnvironmentCreate,
    LifecycleEnvironmentRead,
    PromoteRequest,
    PromoteResponse,
    RollbackRequest,
)

router = APIRouter()


def _sources_from_version(version: ContentViewVersion) -> list[tuple[str, str]]:
    return [(entry["snapshot_name"], entry["component"]) for entry in version.snapshots]


def _check_path_order(db: Session, environment: LifecycleEnvironment, version_id: uuid.UUID) -> None:
    """Position 0 in a path has no predecessor and is always allowed. Position
    N requires the target version to currently be live (current_version_id)
    at position N-1 in the same path — a version must move through the path
    in order, matching Satellite's promotion-follows-the-path behavior.
    """
    if environment.position == 0:
        return

    predecessor = db.execute(
        select(LifecycleEnvironment).where(
            LifecycleEnvironment.path_name == environment.path_name,
            LifecycleEnvironment.position == environment.position - 1,
        )
    ).scalar_one_or_none()

    if predecessor is None:
        # No environment occupies the preceding slot yet — nothing to gate against.
        return

    if predecessor.current_version_id != version_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"version must be promoted through '{predecessor.name}' "
                f"(path '{environment.path_name}', position {predecessor.position}) first"
            ),
        )


@router.post("", response_model=LifecycleEnvironmentRead, status_code=status.HTTP_201_CREATED)
def create_lifecycle_environment(
    payload: LifecycleEnvironmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    content_view = db.get(ContentView, payload.content_view_id)
    if content_view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="content view not found")

    existing = db.execute(
        select(LifecycleEnvironment).where(
            (LifecycleEnvironment.name == payload.name)
            | (LifecycleEnvironment.publish_prefix == payload.publish_prefix)
            | (
                (LifecycleEnvironment.path_name == payload.path_name)
                & (LifecycleEnvironment.position == payload.position)
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="environment name, publish_prefix, or path_name+position already in use",
        )

    environment = LifecycleEnvironment(
        name=payload.name,
        path_name=payload.path_name,
        position=payload.position,
        content_view_id=payload.content_view_id,
        distro=payload.distro,
        release=payload.release,
        publish_prefix=payload.publish_prefix,
        gpg_key_id=payload.gpg_key_id,
    )
    db.add(environment)
    db.flush()
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.create_lifecycle_environment,
            resource_type="lifecycle_environment",
            resource_id=str(environment.id),
        )
    )
    db.commit()
    db.refresh(environment)
    return environment


@router.get("", response_model=list[LifecycleEnvironmentRead])
def list_lifecycle_environments(
    path_name: str | None = None,
    content_view_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    query = select(LifecycleEnvironment)
    if path_name is not None:
        query = query.where(LifecycleEnvironment.path_name == path_name)
    if content_view_id is not None:
        query = query.where(LifecycleEnvironment.content_view_id == content_view_id)
    query = query.order_by(LifecycleEnvironment.path_name, LifecycleEnvironment.position).limit(limit).offset(offset)
    return list(db.execute(query).scalars())


@router.get("/{environment_id}/gpg-key")
def get_environment_gpg_key(
    environment_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    """Serves the environment's signing public key, ASCII-armored, so
    managed hosts can fetch it during bootstrap and install it under
    /etc/apt/keyrings before apt trusts [signed-by=...] entries (see
    bootstrap_client.yml and docs/gpg-signing.md). Requires the key to
    already exist in the local GPG keyring — key generation itself
    (gpg --full-generate-key) is a manual, one-time operator step, not
    automated here (see docs/gpg-signing.md).
    """
    environment = db.get(LifecycleEnvironment, environment_id)
    if environment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="environment not found")
    if environment.gpg_key_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="this environment has no signing key configured")

    proc = subprocess.run(
        ["gpg", "--export", "--armor", environment.gpg_key_id],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="failed to export configured GPG key — is it present in the server's keyring?",
        )
    return Response(content=proc.stdout, media_type="application/pgp-keys")


@router.post("/{environment_id}/promote", response_model=PromoteResponse)
def promote_environment(
    environment_id: uuid.UUID,
    payload: PromoteRequest,
    db: Session = Depends(get_db),
    aptly: AptlyClient = Depends(get_aptly_client),
    current_user: User = Depends(require_role(Role.operator)),
):
    environment = db.get(LifecycleEnvironment, environment_id)
    if environment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="environment not found")

    content_view = db.get(ContentView, environment.content_view_id)
    if content_view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="environment's content view no longer exists")

    if payload.content_view_version_id is not None:
        version = db.get(ContentViewVersion, payload.content_view_version_id)
        if version is None or version.content_view_id != content_view.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="content view version not found for this environment's content view",
            )
    else:
        # No version specified: publish-if-needed, then promote the latest —
        # preserves v0's "first promote call cuts+publishes" convenience.
        version, _cut = do_publish(content_view, db, aptly, current_user)

    _check_path_order(db, environment, version.id)

    sources = _sources_from_version(version)
    try:
        already_published = aptly.publish_exists(environment.publish_prefix)
        if already_published:
            aptly.switch_publish(
                environment.publish_prefix, environment.release, sources, gpg_key_id=environment.gpg_key_id
            )
        else:
            aptly.publish_snapshot(
                environment.publish_prefix, environment.release, sources, gpg_key_id=environment.gpg_key_id
            )
    except AptlyError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    from_version_id = environment.current_version_id
    environment.current_version_id = version.id
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.switch_publish,
            resource_type="lifecycle_environment",
            resource_id=str(environment.id),
            detail={"content_view_version_id": str(version.id), "from_version_id": str(from_version_id) if from_version_id else None},
        )
    )
    db.commit()
    db.refresh(environment)

    return PromoteResponse(
        id=environment.id,
        current_version_id=environment.current_version_id,
        publish_prefix=environment.publish_prefix,
        published_url=f"{settings.published_repo_base_url}/{environment.publish_prefix}/",
    )


@router.post("/{environment_id}/rollback", response_model=PromoteResponse)
def rollback_environment(
    environment_id: uuid.UUID,
    payload: RollbackRequest,
    db: Session = Depends(get_db),
    aptly: AptlyClient = Depends(get_aptly_client),
    current_user: User = Depends(require_role(Role.operator)),
):
    environment = db.get(LifecycleEnvironment, environment_id)
    if environment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="environment not found")

    version = db.get(ContentViewVersion, payload.content_view_version_id)
    if version is None or version.content_view_id != environment.content_view_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="content view version not found for this environment's content view",
        )

    # Rollback bypasses path-order checks entirely — it only allows returning
    # to a version THIS environment has actually had live before, never an
    # arbitrary version from elsewhere in the content view.
    ever_live = db.execute(
        select(AuditLog).where(
            AuditLog.resource_type == "lifecycle_environment",
            AuditLog.resource_id == str(environment.id),
            AuditLog.action.in_([AuditAction.switch_publish, AuditAction.rollback_environment]),
        )
    ).scalars()
    ever_live_version_ids = {
        entry.detail.get("content_view_version_id") for entry in ever_live if entry.detail
    }
    if str(version.id) not in ever_live_version_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="can only roll back to a version this environment has previously had live",
        )

    sources = _sources_from_version(version)
    try:
        aptly.switch_publish(
            environment.publish_prefix, environment.release, sources, gpg_key_id=environment.gpg_key_id
        )
    except AptlyError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    from_version_id = environment.current_version_id
    environment.current_version_id = version.id
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.rollback_environment,
            resource_type="lifecycle_environment",
            resource_id=str(environment.id),
            detail={"content_view_version_id": str(version.id), "from_version_id": str(from_version_id) if from_version_id else None},
        )
    )
    db.commit()
    db.refresh(environment)

    return PromoteResponse(
        id=environment.id,
        current_version_id=environment.current_version_id,
        publish_prefix=environment.publish_prefix,
        published_url=f"{settings.published_repo_base_url}/{environment.publish_prefix}/",
    )
