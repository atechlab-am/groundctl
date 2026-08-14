import hashlib
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
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
    PublishResponse,
)

router = APIRouter()


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
    current_user: User = Depends(require_role(Role.operator)),
):
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

    content_view = ContentView(name=payload.name)
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

    return ContentViewRead(
        id=content_view.id,
        name=content_view.name,
        repository_ids=list(payload.repository_ids),
        created_at=content_view.created_at,
        updated_at=content_view.updated_at,
    )


@router.get("/{content_view_id}/versions", response_model=list[ContentViewVersionRead])
def list_content_view_versions(
    content_view_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    content_view = db.get(ContentView, content_view_id)
    if content_view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="content view not found")

    return list(
        db.execute(
            select(ContentViewVersion)
            .where(ContentViewVersion.content_view_id == content_view_id)
            .order_by(ContentViewVersion.version.desc())
            .limit(limit)
            .offset(offset)
        ).scalars()
    )


@router.post("/{content_view_id}/filters", response_model=ContentViewFilterRead, status_code=status.HTTP_201_CREATED)
def create_content_view_filter(
    content_view_id: uuid.UUID,
    payload: ContentViewFilterCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    content_view = db.get(ContentView, content_view_id)
    if content_view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="content view not found")

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
    content_view: ContentView, db: Session, aptly: AptlyClient, user: User
) -> tuple[ContentViewVersion, bool]:
    """Cut a new ContentViewVersion if any member repository's package
    content has changed since the latest version; otherwise return the
    existing latest version unchanged. Never touches any LifecycleEnvironment
    — see do_promote in lifecycle_environments.py for that half.
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

    if latest is not None and latest.content_hash == content_hash:
        return latest, False

    next_version = 1 if latest is None else latest.version + 1
    timestamp = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    snapshots: list[dict] = []

    for repo in repos:
        raw_snapshot_name = f"{content_view.name}-v{next_version}-{repo.name}-{timestamp}"
        try:
            aptly.create_snapshot_from_mirror(repo.name, raw_snapshot_name)
        except AptlyError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

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

    version = ContentViewVersion(
        content_view_id=content_view.id,
        version=next_version,
        snapshots=snapshots,
        content_hash=content_hash,
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
            detail={"version": next_version, "snapshot_count": len(snapshots)},
        )
    )
    db.commit()
    db.refresh(version)
    return version, True


@router.post("/{content_view_id}/publish", response_model=PublishResponse, status_code=status.HTTP_201_CREATED)
def publish_content_view(
    content_view_id: uuid.UUID,
    db: Session = Depends(get_db),
    aptly: AptlyClient = Depends(get_aptly_client),
    current_user: User = Depends(require_role(Role.operator)),
):
    content_view = db.get(ContentView, content_view_id)
    if content_view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="content view not found")

    version, cut = do_publish(content_view, db, aptly, current_user)
    return PublishResponse(content_view_version=ContentViewVersionRead.model_validate(version), version_cut=cut)
