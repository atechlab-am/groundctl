import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import VersionCheck
from app.schemas import VersionRead
from app.version_check import get_current_version, is_newer

router = APIRouter()

_VERSION_CHECK_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")


@router.get("", response_model=VersionRead)
def get_version(db: Session = Depends(get_db)):
    """Unauthenticated, like GET /branding — every logged-in tab polls this
    to show a header "update available" notice, and the current version
    number itself isn't sensitive (same reasoning as branding's logo/colors
    being public). Never calls GitHub itself; only reads the cache
    scheduled_check_for_new_version (app/tasks.py) maintains once a day.
    """
    current_version = get_current_version()
    row = db.get(VersionCheck, _VERSION_CHECK_ID)
    latest_version = row.latest_version if row else None

    return VersionRead(
        current_version=current_version,
        latest_version=latest_version,
        update_available=latest_version is not None and is_newer(latest_version, current_version),
        last_checked_at=row.checked_at if row else None,
    )
