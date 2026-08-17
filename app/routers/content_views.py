import hashlib
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.aptly_client import AptlyClient, AptlyError, get_aptly_client
from app.auth import require_role
from app.database import get_db
from app.models import (
    AuditAction,
    AuditLog,
    ContentView,
    ContentViewFilter,
    ContentViewRepository,
    ContentViewVersion,
    Erratum,
    ErratumPackage,
    FilterType,
    Job,
    JobTargetType,
    JobType,
    LifecycleEnvironment,
    Repository,
    Role,
    User,
)
from app.schemas import (
    ContentViewCreate,
    ContentViewFilterCreate,
    ContentViewFilterRead,
    ContentViewRead,
    ContentViewVersionRead,
    ContentViewVersionUpdate,
    JobRead,
    PublishAndPromoteRequest,
    PublishRequest,
    PublishResponse,
)

router = APIRouter()


def _content_view_repository_ids(db: Session, content_view_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        db.execute(
            select(ContentViewRepository.repository_id)
            .where(ContentViewRepository.content_view_id == content_view_id)
        ).scalars()
    )


def _read_content_view(db: Session, content_view: ContentView) -> ContentViewRead:
    return ContentViewRead(
        id=content_view.id,
        name=content_view.name,
        description=content_view.description,
        repository_ids=_content_view_repository_ids(db, content_view.id),
        created_at=content_view.created_at,
        updated_at=content_view.updated_at,
    )


def _get_content_view_or_404(db: Session, content_view_id: uuid.UUID) -> ContentView:
    content_view = db.get(ContentView, content_view_id)
    if content_view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="content view not found")
    return content_view


def _referencing_lifecycle_environment_names(db: Session, content_view_id: uuid.UUID) -> list[str]:
    return list(
        db.execute(
            select(LifecycleEnvironment.name)
            .where(LifecycleEnvironment.content_view_id == content_view_id)
            .order_by(LifecycleEnvironment.name)
        ).scalars()
    )


def _content_view_repositories(db: Session, content_view_id: uuid.UUID) -> list[Repository]:
    return list(
        db.execute(
            select(Repository)
            .join(ContentViewRepository, ContentViewRepository.repository_id == Repository.id)
            .where(ContentViewRepository.content_view_id == content_view_id)
            .order_by(Repository.name)
        ).scalars()
    )


def _hash_repo_packages(repo_name: str, packages: list[dict]) -> str:
    # aptly's ?format=details entries use "Package" (not "Name") — verified
    # against a real aptly 1.6.3 instance (see app/routers/compliance.py's
    # identical note). Prefixed with repo_name so two repos that happen to
    # share identical package content still hash distinctly.
    entries = sorted(
        f"{p.get('Package', '')}|{p.get('Version', '')}|{p.get('Architecture', '')}" for p in packages
    )
    return f"{repo_name}:" + hashlib.sha256("\n".join(entries).encode()).hexdigest()


def _errata_since_query(db: Session, repo: Repository, since: date) -> str:
    """Resolve an errata_since filter into an aptly include-query covering
    exactly the package@fixed_version pairs from every Erratum published on
    or after `since`, scoped to this repository's release (matching
    ErratumPackage.release against repo.distribution — e.g. only DSA
    packages tagged "trixie" apply to a repo whose distribution is
    "trixie"; a USN's "jammy" packages never match a Debian repo and vice
    versa, since the release strings simply won't intersect).

    UNVERIFIED against live aptly — same posture as the existing
    include/exclude branch below, compounded by this being new, more complex
    query construction (potentially many package@version OR-clauses instead
    of one Name pattern). See docs/limitations.md.
    """
    since_dt = datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc)
    packages = list(
        db.execute(
            select(ErratumPackage)
            .join(Erratum, Erratum.id == ErratumPackage.erratum_id)
            .where(Erratum.published_at >= since_dt, ErratumPackage.release == repo.distribution)
        ).scalars()
    )
    if not packages:
        # No matching errata for this repo's release — an empty include
        # query would (per aptly's query grammar) most likely match
        # nothing, which is the semantically correct outcome here (nothing
        # to include), not an error condition.
        return "Name (~ $^)"  # matches no real package name

    clauses = [f"(Name (= {p.package_name}), Version (>= {p.fixed_version}))" for p in packages]
    return " | ".join(clauses)


def _filter_to_aptly_query(db: Session, repo: Repository, content_filter: ContentViewFilter) -> str:
    # Translates our simple ContentViewFilter.pattern into aptly's package
    # query syntax. UNVERIFIED against live aptly — see
    # AptlyClient.create_filtered_snapshot's docstring and docs/limitations.md.
    if content_filter.filter_type == FilterType.errata_since:
        since = date.fromisoformat(content_filter.pattern)
        return _errata_since_query(db, repo, since)
    if content_filter.filter_type == FilterType.include:
        return f"Name (~ {content_filter.pattern})"
    return f"!Name (~ {content_filter.pattern})"


@router.post("", response_model=ContentViewRead, status_code=status.HTTP_201_CREATED)
def create_content_view(
    payload: ContentViewCreate,
    db: Session = Depends(get_db),
    aptly: AptlyClient = Depends(get_aptly_client),
    current_user: User = Depends(require_role(Role.operator)),
):
    """Cuts version 1 immediately, from the member repositories' current
    package state, in the same request — matches Satellite, where a newly
    created content view already has an initial version rather than
    existing as an empty shell an operator has to remember to publish
    separately. If aptly is unreachable when cutting that version, the
    whole creation is rolled back (502) rather than left as a content
    view with zero versions to promote — same "no dangling half-created
    state" posture as every other aptly-backed endpoint in this router.
    """
    existing = db.execute(select(ContentView).where(ContentView.name == payload.name)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="content view name already in use")

    repos = list(
        db.execute(select(Repository).where(Repository.id.in_(payload.repository_ids))).scalars()
    )
    found_ids = {r.id for r in repos}
    missing = set(payload.repository_ids) - found_ids
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"repository ids not found: {sorted(str(m) for m in missing)}"
        )

    content_view = ContentView(name=payload.name, description=payload.description)
    db.add(content_view)
    db.flush()
    for repo_id in payload.repository_ids:
        db.add(ContentViewRepository(content_view_id=content_view.id, repository_id=repo_id))
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.create_content_view,
            resource_type="content_view",
            resource_id=str(content_view.id),
        )
    )
    db.commit()
    db.refresh(content_view)

    do_publish(content_view, db, aptly, current_user, force=True)

    return _read_content_view(db, content_view)


@router.get("", response_model=list[ContentViewRead])
def list_content_views(
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    content_views = list(
        db.execute(select(ContentView).order_by(ContentView.name).limit(limit).offset(offset)).scalars()
    )
    return [_read_content_view(db, cv) for cv in content_views]


@router.get("/{content_view_id}", response_model=ContentViewRead)
def get_content_view(
    content_view_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    content_view = _get_content_view_or_404(db, content_view_id)
    return _read_content_view(db, content_view)


@router.delete("/{content_view_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_content_view(
    content_view_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    """Blocked (409) if any LifecycleEnvironment still references this
    content view — same reasoning as Repository's delete guard against
    ContentView references: deleting the content view out from under an
    environment would leave that environment pointing at a nonexistent
    parent, and there's no cascade that makes sense here (an environment
    always needs a content view). ContentViewVersion rows and
    ContentViewFilter rows belonging to this content view are deleted
    alongside it — versions are historical snapshots of THIS content
    view specifically and have no meaning once it's gone; unlike
    Repository, no other resource references a ContentViewVersion by id.
    """
    content_view = _get_content_view_or_404(db, content_view_id)

    referencing = _referencing_lifecycle_environment_names(db, content_view_id)
    if referencing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"content view is used by lifecycle environment(s): {', '.join(referencing)}",
        )

    db.execute(delete(ContentViewRepository).where(ContentViewRepository.content_view_id == content_view_id))
    db.execute(delete(ContentViewFilter).where(ContentViewFilter.content_view_id == content_view_id))
    db.execute(delete(ContentViewVersion).where(ContentViewVersion.content_view_id == content_view_id))
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.delete_content_view,
            resource_type="content_view",
            resource_id=content_view.name,
        )
    )
    db.delete(content_view)
    db.commit()


@router.get("/{content_view_id}/versions", response_model=list[ContentViewVersionRead])
def list_content_view_versions(
    content_view_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    _get_content_view_or_404(db, content_view_id)

    return list(
        db.execute(
            select(ContentViewVersion)
            .where(ContentViewVersion.content_view_id == content_view_id)
            .order_by(ContentViewVersion.version.desc())
            .limit(limit)
            .offset(offset)
        ).scalars()
    )


@router.patch("/{content_view_id}/versions/{version_id}", response_model=ContentViewVersionRead)
def update_content_view_version(
    content_view_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: ContentViewVersionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    """Sets an operator-facing description on an already-published version
    — annotation only. The version NUMBER stays the canonical, immutable
    identifier (matches Satellite: versions are numbered, never renamed).
    Never touches snapshots/content_hash/package_count, all of which stay
    write-once at publish time.
    """
    _get_content_view_or_404(db, content_view_id)

    version = db.get(ContentViewVersion, version_id)
    if version is None or version.content_view_id != content_view_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="content view version not found")

    version.description = payload.description
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.update_content_view_version,
            resource_type="content_view_version",
            resource_id=str(version.id),
            detail={"version": version.version, "description": payload.description},
        )
    )
    db.commit()
    db.refresh(version)
    return version


def version_ever_promoted(db: Session, version_id: uuid.UUID) -> bool:
    """True if this version is currently live on any environment, OR was
    ever live in the past (still reachable via POST /rollback). Matches
    rollback_environment's own "ever_live" check (lifecycle_environments.py)
    but across ALL environments, not just one — deleting a version that's
    rollback-able anywhere would silently break that environment's
    rollback history. A version that was never promoted anywhere has no
    AuditAction.switch_publish/rollback_environment row referencing it and
    is not any environment's current_version_id.
    """
    if db.execute(
        select(LifecycleEnvironment.id).where(LifecycleEnvironment.current_version_id == version_id)
    ).first():
        return True
    # resource_id on these actions is the ENVIRONMENT id, not the version
    # id (see promote_environment/rollback_environment), so the only way
    # to scope this is by the version id embedded inside detail — pushed
    # down as a JSON-path comparison rather than pulling every
    # switch_publish/rollback_environment row in the installation's
    # history into Python and filtering there (real cost on an install
    # with a long promotion history, since this runs on every version
    # delete request and the task's own re-check).
    return (
        db.execute(
            select(AuditLog.id)
            .where(
                AuditLog.action.in_([AuditAction.switch_publish, AuditAction.rollback_environment]),
                AuditLog.detail["content_view_version_id"].as_string() == str(version_id),
            )
            .limit(1)
        ).first()
        is not None
    )


@router.post(
    "/{content_view_id}/versions/{version_id}/delete", response_model=JobRead, status_code=status.HTTP_201_CREATED
)
def trigger_delete_content_view_version(
    content_view_id: uuid.UUID,
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    """Deletes a content view version — the aptly snapshots it cut (see
    ContentViewVersion.all_snapshot_names) and the row itself — as a
    tracked Job, since aptly snapshot deletion is a real network call
    (see AptlyClient.delete_snapshot). Blocked (409), before a Job is even
    created, if the version is live on any environment right now OR was
    ever promoted in the past (still reachable via rollback) — matches
    Satellite: a published/promoted version is locked in as part of
    environment history, only a version that was cut but never promoted
    anywhere can be deleted. The task itself re-checks this guard
    immediately before the actual delete, closing the race window between
    this request and the task running (same pattern as
    delete_repository_task's ContentView-reference re-check).
    """
    from app.tasks import delete_content_view_version_task

    content_view = _get_content_view_or_404(db, content_view_id)

    version = db.get(ContentViewVersion, version_id)
    if version is None or version.content_view_id != content_view.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="content view version not found")

    if version_ever_promoted(db, version.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="version has been promoted to an environment (currently or in the past) and cannot be deleted",
        )

    job = Job(
        job_type=JobType.delete_content_view_version,
        target_type=JobTargetType.content_view,
        created_by_user_id=current_user.id,
    )
    db.add(job)
    db.flush()
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.trigger_delete_content_view_version,
            resource_type="job",
            resource_id=str(job.id),
            detail={"content_view_id": str(content_view.id), "version_id": str(version.id), "version": version.version},
        )
    )
    db.commit()
    db.refresh(job)

    delete_content_view_version_task.delay(str(job.id))
    return job


@router.get("/{content_view_id}/filters", response_model=list[ContentViewFilterRead])
def list_content_view_filters(
    content_view_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    _get_content_view_or_404(db, content_view_id)

    return list(
        db.execute(
            select(ContentViewFilter)
            .where(ContentViewFilter.content_view_id == content_view_id)
            .order_by(ContentViewFilter.created_at)
        ).scalars()
    )


@router.delete("/{content_view_id}/filters/{filter_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_content_view_filter(
    content_view_id: uuid.UUID,
    filter_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    _get_content_view_or_404(db, content_view_id)

    content_filter = db.get(ContentViewFilter, filter_id)
    if content_filter is None or content_filter.content_view_id != content_view_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="filter not found")

    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.delete_content_view_filter,
            resource_type="content_view",
            resource_id=str(content_view_id),
            detail={"filter_type": content_filter.filter_type.value, "pattern": content_filter.pattern},
        )
    )
    db.delete(content_filter)
    db.commit()


@router.post("/{content_view_id}/filters", response_model=ContentViewFilterRead, status_code=status.HTTP_201_CREATED)
def create_content_view_filter(
    content_view_id: uuid.UUID,
    payload: ContentViewFilterCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    _get_content_view_or_404(db, content_view_id)

    content_filter = ContentViewFilter(
        content_view_id=content_view_id,
        filter_type=payload.filter_type,
        pattern=payload.pattern,
    )
    db.add(content_filter)
    db.flush()
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.create_content_view_filter,
            resource_type="content_view",
            resource_id=str(content_view_id),
            detail={"filter_type": payload.filter_type.value, "pattern": payload.pattern},
        )
    )
    db.commit()
    db.refresh(content_filter)
    return content_filter


def do_publish(
    content_view: ContentView, db: Session, aptly: AptlyClient, user: User, force: bool = False
) -> tuple[ContentViewVersion, bool]:
    """Cut a new ContentViewVersion if any member repository's package
    content has changed since the latest version; otherwise return the
    existing latest version unchanged — unless force=True, which always
    cuts a new version (new number, new snapshots, new published_at) even
    when content_hash is identical to the latest version. A version is
    also a promotion checkpoint, not purely a content-change record: an
    operator may want a version they can promote to one environment today
    that's distinct from whatever's already promoted elsewhere, even with
    nothing new to snapshot (matches Satellite's own "Publish New Version"
    always being available). Never touches any LifecycleEnvironment — see
    do_promote in lifecycle_environments.py for that half.
    """
    repos = _content_view_repositories(db, content_view.id)
    if not repos:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="content view has no repositories"
        )

    filters = list(
        db.execute(select(ContentViewFilter).where(ContentViewFilter.content_view_id == content_view.id)).scalars()
    )

    per_repo_packages: dict[uuid.UUID, list[dict]] = {}
    hash_parts: list[str] = []
    for repo in repos:
        try:
            packages = aptly.get_mirror_packages(repo.name)
        except AptlyError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        per_repo_packages[repo.id] = packages
        hash_parts.append(_hash_repo_packages(repo.name, packages))

    content_hash = hashlib.sha256("\n".join(sorted(hash_parts)).encode()).hexdigest()

    latest = db.execute(
        select(ContentViewVersion)
        .where(ContentViewVersion.content_view_id == content_view.id)
        .order_by(ContentViewVersion.version.desc())
        .limit(1)
    ).scalar_one_or_none()

    if not force and latest is not None and latest.content_hash == content_hash:
        return latest, False

    next_version = 1 if latest is None else latest.version + 1
    timestamp = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    snapshots: list[dict] = []
    # Every snapshot this cut creates, including intermediates never
    # referenced by `snapshots` (the raw pre-filter snapshot, and any
    # intermediate filter-chain steps) — lets a later version delete
    # clean up everything this publish created, not just the final names.
    # See ContentViewVersion.all_snapshot_names' docstring.
    all_snapshot_names: list[str] = []

    for repo in repos:
        raw_snapshot_name = f"{content_view.name}-v{next_version}-{repo.name}-{timestamp}"
        try:
            aptly.create_snapshot_from_mirror(repo.name, raw_snapshot_name)
        except AptlyError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        all_snapshot_names.append(raw_snapshot_name)

        snapshot_name = raw_snapshot_name
        if filters:
            filtered_name = f"{raw_snapshot_name}-filtered"
            # Multiple filters compose as successive aptly queries — cut
            # sequentially, filtering the previous filter's output.
            current_source = raw_snapshot_name
            for i, content_filter in enumerate(filters):
                dest = filtered_name if i == len(filters) - 1 else f"{filtered_name}-{i}"
                try:
                    aptly.create_filtered_snapshot(
                        current_source, dest, _filter_to_aptly_query(db, repo, content_filter)
                    )
                except AptlyError as exc:
                    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
                current_source = dest
                all_snapshot_names.append(dest)
            snapshot_name = current_source

        for component in repo.components:
            snapshots.append(
                {
                    "repository_id": str(repo.id),
                    "repository_name": repo.name,
                    "snapshot_name": snapshot_name,
                    "component": component,
                }
            )

    # Counted from the actual final snapshot each entry points at (post-
    # filter), not the source mirror — a content view with an
    # include/exclude filter publishes fewer packages than its repos hold,
    # and this number should reflect what a client actually gets. One
    # get_snapshot_packages call per UNIQUE snapshot name, not per
    # (repo, component) entry — a repo with multiple components reuses the
    # same snapshot_name across several `snapshots` entries (see the loop
    # above), and counting per-entry would double/triple-count it.
    unique_snapshot_names = {entry["snapshot_name"] for entry in snapshots}
    package_count = 0
    for name in unique_snapshot_names:
        try:
            package_count += len(aptly.get_snapshot_packages(name))
        except AptlyError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    version = ContentViewVersion(
        content_view_id=content_view.id,
        version=next_version,
        snapshots=snapshots,
        content_hash=content_hash,
        package_count=package_count,
        all_snapshot_names=all_snapshot_names,
        created_by_user_id=user.id,
    )
    db.add(version)
    db.flush()
    db.add(
        AuditLog(
            user_id=user.id,
            action=AuditAction.cut_snapshot,
            resource_type="content_view",
            resource_id=str(content_view.id),
            detail={
                "version": next_version,
                "snapshot_count": len(snapshots),
                "forced": force and latest is not None and latest.content_hash == content_hash,
            },
        )
    )
    db.commit()
    db.refresh(version)
    return version, True


@router.post("/{content_view_id}/publish", response_model=PublishResponse, status_code=status.HTTP_201_CREATED)
def publish_content_view(
    content_view_id: uuid.UUID,
    payload: PublishRequest | None = None,
    db: Session = Depends(get_db),
    aptly: AptlyClient = Depends(get_aptly_client),
    current_user: User = Depends(require_role(Role.operator)),
):
    content_view = _get_content_view_or_404(db, content_view_id)

    force = payload.force if payload is not None else False
    version, cut = do_publish(content_view, db, aptly, current_user, force=force)
    return PublishResponse(content_view_version=ContentViewVersionRead.model_validate(version), version_cut=cut)


@router.post(
    "/{content_view_id}/publish-and-promote", response_model=JobRead, status_code=status.HTTP_201_CREATED
)
def trigger_publish_and_promote(
    content_view_id: uuid.UUID,
    payload: PublishAndPromoteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    """Cuts a new version (with an optional description) and immediately
    promotes it to an environment, as ONE tracked Job — the combined
    "create version + promote" popup's backing endpoint. Unlike
    POST /{content_view_id}/publish and POST /lifecycle-environments/
    {id}/promote (both still synchronous, unchanged), aptly's
    publish/switch-publish call can genuinely run long (see
    aptly_client.py's 1800s timeouts) — same "long-running work belongs
    in a Job" rule as every other job-backed endpoint, now applied here
    too, but ONLY for this new combined flow. The plain publish/promote
    buttons keep their existing synchronous behavior.
    """
    # Deferred import: app.tasks imports do_publish/do_promote from this
    # module and lifecycle_environments.py, so importing app.tasks at
    # module load time here would be circular (same pattern
    # repositories.py's sync_repository endpoint already uses).
    from app.tasks import publish_and_promote_task

    content_view = _get_content_view_or_404(db, content_view_id)

    environment = db.get(LifecycleEnvironment, payload.environment_id)
    # None matches too — an environment's content_view_id is deferred
    # until its first-ever promote (lifecycle_environments.py's
    # promote_environment); this may BE that first promote, in which case
    # do_promote/publish_and_promote_task locks the environment to THIS
    # content view. Once set, every later promote must match it exactly,
    # same as before.
    if environment is None or (
        environment.content_view_id is not None and environment.content_view_id != content_view.id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="lifecycle environment not found for this content view",
        )

    if environment.content_view_id is None and environment.gpg_key_id is None and not payload.allow_unsigned:
        # Fail fast, before a Job is even created — same "validate before
        # dispatching work" posture promote_environment uses for the
        # equivalent synchronous case.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "this environment has no signing key configured — set one via PATCH, or pass "
                "allow_unsigned=true explicitly to publish unsigned (see docs/gpg-signing.md)"
            ),
        )

    job = Job(
        job_type=JobType.publish_and_promote,
        target_type=JobTargetType.environment,
        environment_id=environment.id,
        created_by_user_id=current_user.id,
    )
    db.add(job)
    db.flush()
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.trigger_publish_and_promote,
            resource_type="job",
            resource_id=str(job.id),
            detail={
                "content_view_id": str(content_view.id),
                "environment_id": str(environment.id),
                "force": payload.force,
                "description": payload.description,
                "allow_unsigned": payload.allow_unsigned,
            },
        )
    )
    db.commit()
    db.refresh(job)

    publish_and_promote_task.delay(str(job.id))
    return job
