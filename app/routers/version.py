from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import require_role
from app.database import get_db
from app.models import Role, User, VersionCheck
from app.schemas import ChangelogRead, VersionRead
from app.version_check import VERSION_CHECK_ID, get_changelog, get_current_version, is_newer, refresh_version_check

router = APIRouter()


def _read(db: Session) -> VersionRead:
    current_version = get_current_version()
    row = db.get(VersionCheck, VERSION_CHECK_ID)
    latest_version = row.latest_version if row else None

    return VersionRead(
        current_version=current_version,
        latest_version=latest_version,
        update_available=latest_version is not None and is_newer(latest_version, current_version),
        last_checked_at=row.checked_at if row else None,
    )


@router.get("", response_model=VersionRead)
def get_version(db: Session = Depends(get_db)):
    """Unauthenticated, like GET /branding — every logged-in tab polls this
    to show a header "update available" notice, and the current version
    number itself isn't sensitive (same reasoning as branding's logo/colors
    being public). Never calls GitHub itself; only reads the cache
    scheduled_check_for_new_version (app/tasks.py) maintains once a day.
    """
    return _read(db)


@router.post("/check-now", response_model=VersionRead)
def check_version_now(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.admin)),
):
    """On-demand refresh — same GitHub lookup the daily scheduled task
    performs, callable immediately instead of waiting up to 24h for the
    next Celery Beat run. Admin-only and synchronous (a single outbound
    HTTPS call with a bounded timeout, not worth a tracked Job) — unlike
    GET /version above, this one actually calls GitHub, so it isn't left
    unauthenticated.
    """
    refresh_version_check(db)
    db.commit()
    return _read(db)


@router.get("/changelog", response_model=ChangelogRead)
def get_version_changelog(current_user: User = Depends(require_role(Role.viewer))):
    """Serves this deploy's own CHANGELOG.md (see get_changelog) so the
    web UI can show release notes in-app — same reasoning as docs_content.py
    serving docs/*.md instead of sending users to GitHub for documentation.
    Requires auth (unlike GET /version above) since it's not needed by the
    unauthenticated header notice, only by an explicit in-app viewer.
    """
    return ChangelogRead(content=get_changelog())
