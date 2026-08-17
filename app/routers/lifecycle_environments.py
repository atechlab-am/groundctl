import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.apt_sources import export_gpg_public_key
from app.aptly_client import AptlyClient, AptlyError, get_aptly_client
from app.auth import require_role
from app.config import settings
from app.database import get_db
from app.locking import acquire_lock
from app.models import (
    AuditAction,
    AuditLog,
    ContentView,
    ContentViewRepository,
    ContentViewVersion,
    EnvironmentContentView,
    LifecycleEnvironment,
    Repository,
    Role,
    Server,
    ServerBeaconState,
    User,
)
from app.routers.content_views import do_publish
from app.schemas import (
    EnvironmentContentViewCreate,
    EnvironmentContentViewRead,
    LifecycleEnvironmentCreate,
    LifecycleEnvironmentRead,
    LifecycleEnvironmentUpdate,
    PromoteRequest,
    PromoteResponse,
    RollbackRequest,
)

router = APIRouter()


def _sources_from_version(version: ContentViewVersion) -> list[tuple[str, str]]:
    return [(entry["snapshot_name"], entry["component"]) for entry in version.snapshots]


def _bump_config_serial_for_environment_servers(db: Session, environment_id: uuid.UUID) -> None:
    """A promote/rollback changes what's actually published at this
    environment for one of its assigned content views, even though no
    Server.environment_id changed — every beacon-managed server currently
    assigned to this environment needs to know its apt metadata is stale
    and re-run `apt-get update`, same "pending reconciliation" signal
    assign_server_environment (servers.py) already sets on reassignment.
    Only touches servers that already have a ServerBeaconState row (i.e.
    have checked in at least once) — an SSH-only server has nothing to
    notify. Keys only on environment_id — correct as-is under the new
    multi-content-view model: ANY content view's promote/rollback within
    this environment should invalidate every server assigned to it, not
    just servers somehow tied to that one content view.
    """
    server_ids = db.execute(select(Server.id).where(Server.environment_id == environment_id)).scalars().all()
    if not server_ids:
        return
    for state in db.execute(
        select(ServerBeaconState).where(ServerBeaconState.server_id.in_(server_ids))
    ).scalars():
        state.config_serial += 1


def derive_release_for_content_view(db: Session, content_view_id: uuid.UUID) -> str:
    """An EnvironmentContentView's `release` (the apt suite/distribution
    name in its rendered deb line) is derived from its content view's
    first member repository, ordered by name — same ordering do_publish
    itself uses when cutting a version, so "first repo" means the same
    thing in both places. Only called once, at a pair's first-ever
    promote (create_environment_content_view below); every later promote
    reuses the locked-in value.
    """
    repo = db.execute(
        select(Repository)
        .join(ContentViewRepository, ContentViewRepository.repository_id == Repository.id)
        .where(ContentViewRepository.content_view_id == content_view_id)
        .order_by(Repository.name)
        .limit(1)
    ).scalar_one_or_none()
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="content view has no repositories — cannot derive a release for this environment",
        )
    return repo.distribution


def _check_path_order(db: Session, ecv: EnvironmentContentView, environment: LifecycleEnvironment, version_id: uuid.UUID) -> None:
    """Position 0 has no predecessor and is always allowed. Position N
    requires THIS SAME content view's current_version_id to already equal
    `version_id` at position N-1 in the same path — a version must move
    through the path in order, matching Satellite's promotion-follows-the-
    path behavior. The predecessor environment is looked up by
    (path_name, position - 1) — environments are globally unique on that
    pair now — then its EnvironmentContentView row for THIS content_view_id
    is what actually gets checked, since path-order is enforced per
    content view, not per environment as a whole (a different content view
    may be at a different stage of the same path).
    """
    if environment.position == 0:
        return

    predecessor_env = db.execute(
        select(LifecycleEnvironment).where(
            LifecycleEnvironment.path_name == environment.path_name,
            LifecycleEnvironment.position == environment.position - 1,
        )
    ).scalar_one_or_none()

    if predecessor_env is None:
        # No environment occupies the preceding slot yet — nothing to gate against.
        return

    predecessor_ecv = db.execute(
        select(EnvironmentContentView).where(
            EnvironmentContentView.environment_id == predecessor_env.id,
            EnvironmentContentView.content_view_id == ecv.content_view_id,
        )
    ).scalar_one_or_none()

    predecessor_current_version_id = predecessor_ecv.current_version_id if predecessor_ecv is not None else None
    if predecessor_current_version_id != version_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"this content view's version must be promoted through '{predecessor_env.name}' "
                f"(path '{environment.path_name}', position {predecessor_env.position}) first"
            ),
        )


@router.post("", response_model=LifecycleEnvironmentRead, status_code=status.HTTP_201_CREATED)
def create_lifecycle_environment(
    payload: LifecycleEnvironmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    """Matches Satellite's "New Environment" dialog — name, description,
    prior (predecessor in the promotion path). An environment is pure path
    structure, with NO content view association at creation time — content
    views are assigned to it afterward, any number of them, via
    POST /{environment_id}/content-views.
    """
    if payload.prior_environment_id is not None:
        prior = db.get(LifecycleEnvironment, payload.prior_environment_id)
        if prior is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="prior environment not found")
        path_name = prior.path_name
        position = prior.position + 1
    else:
        path_name = payload.name
        position = 0

    existing = db.execute(
        select(LifecycleEnvironment).where(
            (LifecycleEnvironment.name == payload.name)
            | ((LifecycleEnvironment.path_name == path_name) & (LifecycleEnvironment.position == position))
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="environment name already in use, or the prior environment already has a successor",
        )

    environment = LifecycleEnvironment(
        name=payload.name,
        description=payload.description,
        path_name=path_name,
        position=position,
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


@router.patch("/{environment_id}", response_model=LifecycleEnvironmentRead)
def update_lifecycle_environment(
    environment_id: uuid.UUID,
    payload: LifecycleEnvironmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    """Sets description only — name/path_name/position stay fixed once
    created (renaming would silently move the environment's identity out
    from under any AuditLog/EnvironmentContentView history keyed by name
    elsewhere).
    """
    environment = db.get(LifecycleEnvironment, environment_id)
    if environment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="environment not found")

    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(environment, field, value)

    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.update_lifecycle_environment,
            resource_type="lifecycle_environment",
            resource_id=str(environment.id),
            detail=changes,
        )
    )
    db.commit()
    db.refresh(environment)
    return environment


@router.get("", response_model=list[LifecycleEnvironmentRead])
def list_lifecycle_environments(
    path_name: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    query = select(LifecycleEnvironment)
    if path_name is not None:
        query = query.where(LifecycleEnvironment.path_name == path_name)
    query = query.order_by(LifecycleEnvironment.path_name, LifecycleEnvironment.position).limit(limit).offset(offset)
    return list(db.execute(query).scalars())


def do_promote(
    ecv: EnvironmentContentView,
    environment: LifecycleEnvironment,
    version: ContentViewVersion,
    db: Session,
    aptly: AptlyClient,
    user: User,
) -> EnvironmentContentView:
    """Points ecv.publish_prefix at `version` via aptly's publish/switch-
    publish call, bumps beacon config_serial for any beacon-managed server
    currently assigned to `environment`, and writes the
    AuditAction.switch_publish row. Shared by
    POST /{environment_id}/content-views (first promote),
    POST /{environment_id}/content-views/{content_view_id}/promote (later
    promotes), and publish_and_promote_task (app/tasks.py) — one
    implementation of "what promoting actually does" rather than several
    copies that could drift.

    Callers MUST resolve publish_prefix/release before calling this — both
    are nullable on the model (deferred to a pair's first promote) but are
    always set by the time do_promote actually runs the aptly call.
    """
    _check_path_order(db, ecv, environment, version.id)
    if ecv.publish_prefix is None or ecv.release is None:
        raise ValueError(
            f"environment_content_view {ecv.id} has no publish_prefix/release set — "
            "caller must derive these before calling do_promote"
        )

    sources = _sources_from_version(version)
    already_published = aptly.publish_exists(ecv.publish_prefix)
    if already_published:
        aptly.switch_publish(ecv.publish_prefix, ecv.release, sources, gpg_key_id=ecv.gpg_key_id)
    else:
        aptly.publish_snapshot(ecv.publish_prefix, ecv.release, sources, gpg_key_id=ecv.gpg_key_id)

    from_version_id = ecv.current_version_id
    ecv.current_version_id = version.id
    _bump_config_serial_for_environment_servers(db, environment.id)
    db.add(
        AuditLog(
            user_id=user.id,
            action=AuditAction.switch_publish,
            resource_type="environment_content_view",
            resource_id=str(ecv.id),
            detail={
                "environment_id": str(environment.id),
                "content_view_id": str(ecv.content_view_id),
                "content_view_version_id": str(version.id),
                "from_version_id": str(from_version_id) if from_version_id else None,
            },
        )
    )
    db.commit()
    db.refresh(ecv)
    return ecv


@router.get("/{environment_id}/content-views", response_model=list[EnvironmentContentViewRead])
def list_environment_content_views(
    environment_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    environment = db.get(LifecycleEnvironment, environment_id)
    if environment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="environment not found")
    return list(
        db.execute(
            select(EnvironmentContentView)
            .where(EnvironmentContentView.environment_id == environment_id)
            .order_by(EnvironmentContentView.created_at)
        ).scalars()
    )


@router.post(
    "/{environment_id}/content-views", response_model=EnvironmentContentViewRead, status_code=status.HTTP_201_CREATED
)
def create_environment_content_view(
    environment_id: uuid.UUID,
    payload: EnvironmentContentViewCreate,
    db: Session = Depends(get_db),
    aptly: AptlyClient = Depends(get_aptly_client),
    current_user: User = Depends(require_role(Role.operator)),
):
    """Assigns a content view to an environment AND performs its first
    promote in one call — there's no useful "assigned but never published"
    state worth exposing separately (matches how a plain environment's
    first promote already worked before this session's multi-content-view
    redesign). Every LATER promote for this same pair goes through
    POST /{environment_id}/content-views/{content_view_id}/promote instead.
    """
    environment = db.get(LifecycleEnvironment, environment_id)
    if environment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="environment not found")
    content_view = db.get(ContentView, payload.content_view_id)
    if content_view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="content view not found")

    existing = db.execute(
        select(EnvironmentContentView).where(
            EnvironmentContentView.environment_id == environment_id,
            EnvironmentContentView.content_view_id == payload.content_view_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="this content view is already assigned to this environment"
        )

    if payload.gpg_key_id is None and not payload.allow_unsigned:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "no signing key configured for this assignment — pass gpg_key_id, or allow_unsigned=true "
                "explicitly to publish unsigned (see docs/gpg-signing.md)"
            ),
        )

    version = db.get(ContentViewVersion, payload.content_view_version_id)
    if version is None or version.content_view_id != content_view.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="content view version not found for this content view"
        )

    lock = acquire_lock(f"groundctl:lock:environment-content-view:{environment_id}:{payload.content_view_id}")
    if lock is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="another job is already running against this assignment — retry once it completes",
        )
    try:
        ecv = EnvironmentContentView(
            environment_id=environment_id,
            content_view_id=payload.content_view_id,
            gpg_key_id=payload.gpg_key_id,
            release=derive_release_for_content_view(db, content_view.id),
            publish_prefix=f"{environment.name}/{content_view.name}",
        )
        db.add(ecv)
        db.flush()
        db.add(
            AuditLog(
                user_id=current_user.id,
                action=AuditAction.assign_content_view_to_environment,
                resource_type="environment_content_view",
                resource_id=str(ecv.id),
                detail={"environment_id": str(environment_id), "content_view_id": str(payload.content_view_id)},
            )
        )
        # Deliberately NOT committed here — do_promote below re-checks
        # path order (_check_path_order) and can reject with a 409. If the
        # assignment row were already committed at that point, a rejected
        # first-promote would still leave a phantom, never-published
        # EnvironmentContentView behind (permanently blocking any retry
        # with "already assigned"). Flushed so do_promote's own query for
        # this row's predecessor lookups sees it, but the whole thing only
        # actually persists once do_promote's own commit succeeds.
        try:
            ecv = do_promote(ecv, environment, version, db, aptly, current_user)
        except AptlyError as exc:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        except HTTPException:
            db.rollback()
            raise
    finally:
        lock.release()

    return ecv


@router.delete("/{environment_id}/content-views/{content_view_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_environment_content_view(
    environment_id: uuid.UUID,
    content_view_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    """Unassigns a content view from an environment — removes the row
    only, never un-publishes the aptly prefix itself (matches this
    codebase's existing pattern of soft/logical removal over destructive
    external calls unless explicitly asked for).
    """
    ecv = db.execute(
        select(EnvironmentContentView).where(
            EnvironmentContentView.environment_id == environment_id,
            EnvironmentContentView.content_view_id == content_view_id,
        )
    ).scalar_one_or_none()
    if ecv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="this content view is not assigned to this environment")

    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.unassign_content_view_from_environment,
            resource_type="environment_content_view",
            resource_id=str(ecv.id),
            detail={"environment_id": str(environment_id), "content_view_id": str(content_view_id)},
        )
    )
    db.delete(ecv)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{environment_id}/content-views/{content_view_id}/gpg-key")
def get_environment_content_view_gpg_key(
    environment_id: uuid.UUID,
    content_view_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    """Serves the (environment, content view) pair's signing public key,
    ASCII-armored, so managed hosts can fetch it during bootstrap and
    install it under /etc/apt/keyrings before apt trusts [signed-by=...]
    entries (see bootstrap_client.yml and docs/gpg-signing.md). Requires
    the key to already exist in the local GPG keyring — key generation
    itself (gpg --full-generate-key) is a manual, one-time operator step,
    not automated here (see docs/gpg-signing.md).
    """
    ecv = db.execute(
        select(EnvironmentContentView).where(
            EnvironmentContentView.environment_id == environment_id,
            EnvironmentContentView.content_view_id == content_view_id,
        )
    ).scalar_one_or_none()
    if ecv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="this content view is not assigned to this environment")
    if ecv.gpg_key_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="this assignment has no signing key configured")

    armored = export_gpg_public_key(ecv.gpg_key_id)
    if armored is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="failed to export configured GPG key — is it present in the server's keyring?",
        )
    return Response(content=armored, media_type="application/pgp-keys")


@router.post("/{environment_id}/content-views/{content_view_id}/promote", response_model=PromoteResponse)
def promote_environment_content_view(
    environment_id: uuid.UUID,
    content_view_id: uuid.UUID,
    payload: PromoteRequest,
    db: Session = Depends(get_db),
    aptly: AptlyClient = Depends(get_aptly_client),
    current_user: User = Depends(require_role(Role.operator)),
):
    """Every promote AFTER the pair's first (see
    create_environment_content_view) — signing/release/publish_prefix are
    already locked in, so this only needs a version (or omits it to
    publish-if-needed and promote the latest).
    """
    environment = db.get(LifecycleEnvironment, environment_id)
    if environment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="environment not found")
    content_view = db.get(ContentView, content_view_id)
    if content_view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="content view not found")

    lock = acquire_lock(f"groundctl:lock:environment-content-view:{environment_id}:{content_view_id}")
    if lock is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="another job is already running against this assignment — retry once it completes",
        )
    try:
        ecv = db.execute(
            select(EnvironmentContentView).where(
                EnvironmentContentView.environment_id == environment_id,
                EnvironmentContentView.content_view_id == content_view_id,
            )
        ).scalar_one_or_none()
        if ecv is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="this content view is not assigned to this environment"
            )

        if payload.content_view_version_id is not None:
            version = db.get(ContentViewVersion, payload.content_view_version_id)
            if version is None or version.content_view_id != content_view.id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="content view version not found for this content view"
                )
        else:
            version, _cut = do_publish(content_view, db, aptly, current_user)

        try:
            ecv = do_promote(ecv, environment, version, db, aptly, current_user)
        except AptlyError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    finally:
        lock.release()

    assert ecv.publish_prefix is not None
    return PromoteResponse(
        id=ecv.id,
        current_version_id=version.id,
        publish_prefix=ecv.publish_prefix,
        published_url=f"{settings.published_repo_base_url}/{ecv.publish_prefix}/",
    )


@router.post("/{environment_id}/content-views/{content_view_id}/rollback", response_model=PromoteResponse)
def rollback_environment_content_view(
    environment_id: uuid.UUID,
    content_view_id: uuid.UUID,
    payload: RollbackRequest,
    db: Session = Depends(get_db),
    aptly: AptlyClient = Depends(get_aptly_client),
    current_user: User = Depends(require_role(Role.operator)),
):
    ecv = db.execute(
        select(EnvironmentContentView).where(
            EnvironmentContentView.environment_id == environment_id,
            EnvironmentContentView.content_view_id == content_view_id,
        )
    ).scalar_one_or_none()
    if ecv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="this content view is not assigned to this environment")

    version = db.get(ContentViewVersion, payload.content_view_version_id)
    if version is None or version.content_view_id != content_view_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="content view version not found for this content view"
        )

    # Rollback bypasses path-order checks entirely — it only allows returning
    # to a version THIS pair has actually had live before, never an
    # arbitrary version from elsewhere in the content view.
    ever_live = db.execute(
        select(AuditLog).where(
            AuditLog.resource_type == "environment_content_view",
            AuditLog.resource_id == str(ecv.id),
            AuditLog.action.in_([AuditAction.switch_publish, AuditAction.rollback_environment]),
        )
    ).scalars()
    ever_live_version_ids = {entry.detail.get("content_view_version_id") for entry in ever_live if entry.detail}
    if str(version.id) not in ever_live_version_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="can only roll back to a version this content view has previously had live in this environment",
        )
    # Guaranteed set — the ever_live check above only passes for a version
    # this pair already had live at least once, which is only possible
    # after publish_prefix/release were derived on a prior promote.
    if ecv.publish_prefix is None or ecv.release is None:
        raise ValueError(f"environment_content_view {ecv.id} has ever_live history but no publish_prefix/release set")

    sources = _sources_from_version(version)
    try:
        aptly.switch_publish(ecv.publish_prefix, ecv.release, sources, gpg_key_id=ecv.gpg_key_id)
    except AptlyError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    from_version_id = ecv.current_version_id
    ecv.current_version_id = version.id
    _bump_config_serial_for_environment_servers(db, environment_id)
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.rollback_environment,
            resource_type="environment_content_view",
            resource_id=str(ecv.id),
            detail={
                "environment_id": str(environment_id),
                "content_view_id": str(content_view_id),
                "content_view_version_id": str(version.id),
                "from_version_id": str(from_version_id) if from_version_id else None,
            },
        )
    )
    db.commit()
    db.refresh(ecv)

    return PromoteResponse(
        id=ecv.id,
        current_version_id=ecv.current_version_id,
        publish_prefix=ecv.publish_prefix,
        published_url=f"{settings.published_repo_base_url}/{ecv.publish_prefix}/",
    )
