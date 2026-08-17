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
    LifecycleEnvironment,
    Repository,
    Role,
    Server,
    ServerBeaconState,
    User,
)
from app.routers.content_views import do_publish
from app.schemas import (
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
    environment's publish_prefix even though no Server.environment_id
    changed — every beacon-managed server currently assigned to this
    environment needs to know its apt metadata is stale and re-run
    `apt-get update`, same "pending reconciliation" signal
    assign_server_environment (servers.py) already sets on reassignment.
    Only touches servers that already have a ServerBeaconState row (i.e.
    have checked in at least once) — an SSH-only server has nothing to
    notify.
    """
    server_ids = db.execute(select(Server.id).where(Server.environment_id == environment_id)).scalars().all()
    if not server_ids:
        return
    for state in db.execute(
        select(ServerBeaconState).where(ServerBeaconState.server_id.in_(server_ids))
    ).scalars():
        state.config_serial += 1


def derive_release_for_content_view(db: Session, content_view_id: uuid.UUID) -> str:
    """An environment's `release` (the apt suite/distribution name in its
    rendered deb line) is derived from its content view's first member
    repository, ordered by name — same ordering do_publish itself uses
    when cutting a version, so "first repo" means the same thing in both
    places. Only called once, at an environment's first-ever promote
    (do_promote below); every later promote reuses the locked-in value.
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


def _check_path_order(db: Session, environment: LifecycleEnvironment, version_id: uuid.UUID) -> None:
    """Position 0 (always Library, see create_content_view) has no
    predecessor and is always allowed. Position N requires the target
    version to currently be live (current_version_id) at position N-1 in
    the same path — a version must move through the path in order,
    matching Satellite's promotion-follows-the-path behavior. Scoped to
    content_view_id — path_name alone isn't unique across content views
    (every content view's root path is named "Library"), so an unscoped
    query could match a same-named path belonging to a DIFFERENT content
    view entirely.
    """
    if environment.position == 0:
        return

    predecessor = db.execute(
        select(LifecycleEnvironment).where(
            LifecycleEnvironment.content_view_id == environment.content_view_id,
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


def create_library_environment(
    db: Session, content_view: ContentView, version: ContentViewVersion, aptly: AptlyClient, user: User
) -> LifecycleEnvironment:
    """Every content view gets exactly one of these, created here
    (called from create_content_view, never via POST /lifecycle-
    environments — that endpoint explicitly rejects is_library) alongside
    version 1, and immediately promoted to it (a real aptly publish call,
    same do_promote every other promote uses — Library is genuinely live,
    not just a DB placeholder). Matches Satellite: a content view's
    Library is implicit, always exists, and is never something an
    operator creates by hand.

    release is derived immediately (not deferred to a later first-promote
    the way non-Library environments work) since content_view_id — the
    only prerequisite derive_release_for_content_view needs — is already
    known here. publish_prefix is "<content-view-name>/library", not the
    literal name "Library" every content view's root shares — publish_prefix
    stays globally unique (it's a flat aptly/nginx URL path, not scoped by
    content view), so the literal name would collide on the second
    content view.
    """
    library = LifecycleEnvironment(
        name="Library",
        path_name="Library",
        position=0,
        content_view_id=content_view.id,
        is_library=True,
        release=derive_release_for_content_view(db, content_view.id),
        publish_prefix=f"{content_view.name}/library",
    )
    db.add(library)
    db.flush()
    return do_promote(library, version, db, aptly, user)


@router.post("", response_model=LifecycleEnvironmentRead, status_code=status.HTTP_201_CREATED)
def create_lifecycle_environment(
    payload: LifecycleEnvironmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    """Matches Satellite's "New Environment" dialog — name, description,
    prior. Every content view's Library root is auto-created instead (see
    create_content_view/create_library_environment) — this endpoint is
    for every OTHER environment, always explicitly chained onto an
    existing one (Library or otherwise) via prior_environment_id, or
    given content_view_id directly to start a second, independent path on
    that same content view. release/publish_prefix are left null and get
    derived/locked in on this environment's first promote (see do_promote
    below) instead of collected here — content_view_id, unlike those, is
    always known up front now (inherited from prior, or explicit).
    """
    if payload.prior_environment_id is not None:
        prior = db.get(LifecycleEnvironment, payload.prior_environment_id)
        if prior is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="prior environment not found")
        if payload.content_view_id is not None and payload.content_view_id != prior.content_view_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="content_view_id, if given, must match the prior environment's content view",
            )
        content_view_id = prior.content_view_id
        path_name = prior.path_name
        position = prior.position + 1
    else:
        # payload's own validator guarantees content_view_id is set here.
        assert payload.content_view_id is not None
        if db.get(ContentView, payload.content_view_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="content view not found")
        content_view_id = payload.content_view_id
        # No prior — starts a brand-new path on this content view. Never
        # "Library" (reserved for the auto-created root) and never
        # position 0 sharing that reserved path_name.
        path_name = payload.name
        position = 0

    existing = db.execute(
        select(LifecycleEnvironment).where(
            LifecycleEnvironment.content_view_id == content_view_id,
            (LifecycleEnvironment.name == payload.name)
            | ((LifecycleEnvironment.path_name == path_name) & (LifecycleEnvironment.position == position)),
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="environment name already in use on this content view, or the prior environment already has a successor",
        )

    environment = LifecycleEnvironment(
        name=payload.name,
        description=payload.description,
        path_name=path_name,
        position=position,
        content_view_id=content_view_id,
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


@router.patch("/{environment_id}", response_model=LifecycleEnvironmentRead)
def update_lifecycle_environment(
    environment_id: uuid.UUID,
    payload: LifecycleEnvironmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    """Sets description and/or gpg_key_id — the two fields simplified
    creation deliberately doesn't force a choice on up front. In
    particular, this is how an operator adds a signing key to an
    environment before its first promote (otherwise the only way to
    proceed is passing allow_unsigned=true explicitly to the promote
    call). Everything else (content_view_id/release/publish_prefix) stays
    locked once set by a promote — this endpoint never touches them.
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
    content_view_id: uuid.UUID | None = None,
    # Valid PROMOTE TARGETS for a content view: environments already tied
    # to it (content_view_id matches) OR never promoted anywhere yet
    # (content_view_id is still null — any content view can be their
    # first). Deliberately separate from content_view_id above, which
    # keeps its exact-match-only semantics for callers that want exactly
    # what's currently tied to one content view, nothing else.
    promotable_for_content_view_id: uuid.UUID | None = None,
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
    if promotable_for_content_view_id is not None:
        query = query.where(
            (LifecycleEnvironment.content_view_id == promotable_for_content_view_id)
            | (LifecycleEnvironment.content_view_id.is_(None))
        )
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

    armored = export_gpg_public_key(environment.gpg_key_id)
    if armored is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="failed to export configured GPG key — is it present in the server's keyring?",
        )
    return Response(content=armored, media_type="application/pgp-keys")


def do_promote(
    environment: LifecycleEnvironment, version: ContentViewVersion, db: Session, aptly: AptlyClient, user: User
) -> LifecycleEnvironment:
    """Points environment.publish_prefix at `version` via aptly's
    publish/switch-publish call, bumps beacon config_serial for any
    beacon-managed server currently assigned to this environment, and
    writes the AuditAction.switch_publish row. Shared by
    POST /{environment_id}/promote (synchronous, unchanged) and
    publish_and_promote_task (app/tasks.py, ROADMAP-adjacent new
    combined-job flow) — one implementation of "what promoting actually
    does" rather than two copies that could drift.

    Callers MUST resolve publish_prefix/release before calling this —
    both are nullable on the model (deferred to an environment's first
    promote, see promote_environment's is_first_promote branch) but are
    always set by the time do_promote actually runs the aptly call.
    """
    _check_path_order(db, environment, version.id)
    if environment.publish_prefix is None or environment.release is None:
        raise ValueError(
            f"environment {environment.id} has no publish_prefix/release set — "
            "caller must derive these before calling do_promote"
        )

    sources = _sources_from_version(version)
    already_published = aptly.publish_exists(environment.publish_prefix)
    if already_published:
        aptly.switch_publish(
            environment.publish_prefix, environment.release, sources, gpg_key_id=environment.gpg_key_id
        )
    else:
        aptly.publish_snapshot(
            environment.publish_prefix, environment.release, sources, gpg_key_id=environment.gpg_key_id
        )

    from_version_id = environment.current_version_id
    environment.current_version_id = version.id
    _bump_config_serial_for_environment_servers(db, environment.id)
    db.add(
        AuditLog(
            user_id=user.id,
            action=AuditAction.switch_publish,
            resource_type="lifecycle_environment",
            resource_id=str(environment.id),
            detail={"content_view_version_id": str(version.id), "from_version_id": str(from_version_id) if from_version_id else None},
        )
    )
    db.commit()
    db.refresh(environment)
    return environment


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

    # Same per-environment lock publish_and_promote_task takes
    # (app/tasks.py) — both this endpoint and that task can perform an
    # environment's first-promote derive-and-lock (content_view_id/
    # release/publish_prefix), and only one of them taking the lock would
    # leave the other free to race it, silently linking the environment
    # to two different content views depending on commit order.
    lock = acquire_lock(f"groundctl:lock:environment:{environment.id}")
    if lock is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="another job is already running against this environment — retry once it completes",
        )
    try:
        # content_view_id is always set for any environment created going
        # forward (create_lifecycle_environment requires/inherits it, and
        # Library gets it at auto-creation) — only a row from BEFORE this
        # change (deferred-content-view design) could still have it null.
        content_view = db.get(ContentView, environment.content_view_id) if environment.content_view_id else None
        if content_view is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="this environment has no content view — set content_view_id via PATCH first",
            )

        # release/publish_prefix are still deferred to first-promote (not
        # creation) for non-Library environments — this environment's
        # OWN first promote, not "does this content view have a Library
        # yet" (Library already has both, set at auto-creation).
        is_first_promote = environment.release is None

        if is_first_promote and environment.gpg_key_id is None and not payload.allow_unsigned:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "this environment has no signing key configured — set one via PATCH, or pass "
                    "allow_unsigned=true explicitly to publish unsigned (see docs/gpg-signing.md)"
                ),
            )

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

        if is_first_promote:
            environment.release = derive_release_for_content_view(db, content_view.id)
            # name is already validated against the same charset publish_prefix
            # requires (validate_aptly_name, schemas.py) — no separate
            # slugification needed, and this keeps the two visually identical
            # for the common case where an operator never renames anything.
            environment.publish_prefix = environment.name

        try:
            environment = do_promote(environment, version, db, aptly, current_user)
        except AptlyError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    finally:
        lock.release()

    # do_promote guarantees this is set (raises ValueError otherwise) —
    # narrows the type for the response below.
    assert environment.publish_prefix is not None

    return PromoteResponse(
        id=environment.id,
        current_version_id=version.id,
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
    # Guaranteed set — the ever_live check above only passes for a version
    # this environment already had live at least once, which is only
    # possible after publish_prefix/release were derived on a prior
    # promote (see promote_environment's is_first_promote branch).
    if environment.publish_prefix is None or environment.release is None:
        raise ValueError(f"environment {environment.id} has ever_live history but no publish_prefix/release set")

    sources = _sources_from_version(version)
    try:
        aptly.switch_publish(
            environment.publish_prefix, environment.release, sources, gpg_key_id=environment.gpg_key_id
        )
    except AptlyError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    from_version_id = environment.current_version_id
    environment.current_version_id = version.id
    _bump_config_serial_for_environment_servers(db, environment.id)
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
