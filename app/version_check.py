import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.models import VersionCheck

logger = logging.getLogger("groundctl.version_check")

GITHUB_RELEASES_LATEST_URL = "https://api.github.com/repos/atechlab-am/groundctl/releases/latest"

VERSION_CHECK_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")

# Sibling of app/, same resolution pattern as docs_content.py's _DOCS_DIR —
# repo root in a dev checkout, /opt/groundctl in production
# (scripts/lib/app.sh's sync_app_code copies VERSION/CHANGELOG.md there
# explicitly).
_VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"
_CHANGELOG_FILE = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def get_current_version() -> str:
    """Reads this deploy's own VERSION file. Raises if missing/unreadable —
    a deploy without VERSION deployed alongside app/ is missing something
    sync_app_code is supposed to have copied; that's worth a loud 500, not
    a silent 'unknown'.
    """
    return _VERSION_FILE.read_text().strip()


def get_changelog() -> str:
    """Reads this deploy's own CHANGELOG.md, same sibling-of-app/ posture
    as get_current_version. Returns the full file — the frontend renders
    it as markdown rather than the backend parsing out a single version's
    section, so a user can scroll through history in one view instead of
    only ever seeing "what changed since last time."
    """
    return _CHANGELOG_FILE.read_text(encoding="utf-8", errors="replace")


class VersionCheckError(Exception):
    """Raised for both transport failures and unparseable GitHub responses."""


def fetch_latest_release_version(timeout: float = 10.0) -> str:
    """Returns the tag_name of the latest GitHub release, with a leading 'v'
    stripped if present (release.yml — docs/releasing.md — tags as vX.Y.Z;
    VERSION itself has no 'v' prefix, so strip it here for a like-for-like
    compare against VERSION's contents).
    """
    try:
        response = httpx.get(
            GITHUB_RELEASES_LATEST_URL,
            timeout=timeout,
            headers={"Accept": "application/vnd.github+json"},
        )
        response.raise_for_status()
        body = response.json()
    except httpx.HTTPError as exc:
        raise VersionCheckError(f"could not reach GitHub releases API: {exc}") from exc

    tag_name = body.get("tag_name")
    if not isinstance(tag_name, str) or not tag_name:
        raise VersionCheckError(f"unexpected GitHub releases response shape: {body!r}")
    return tag_name.removeprefix("v")


def _parse_semver(value: str) -> tuple[int, int, int] | None:
    parts = value.split(".")
    if len(parts) != 3:
        return None
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None


def refresh_version_check(db: Session) -> VersionCheck:
    """Fetches the latest GitHub release and writes it to the shared
    VersionCheck row — the one place both scheduled_check_for_new_version
    (app/tasks.py, daily via Celery Beat) and POST /version/check-now
    (app/routers/version.py, on-demand admin trigger) update this cache,
    so the two call sites can't drift in behavior. A failed check
    preserves whatever latest_version a prior successful check found
    (check_failed=True is set regardless, so the age of that cached value
    is visible via checked_at) rather than wiping it out — a transient
    GitHub outage shouldn't make an already-known update disappear from
    the UI. Caller commits.
    """
    row = db.get(VersionCheck, VERSION_CHECK_ID)
    if row is None:
        row = VersionCheck(id=VERSION_CHECK_ID)
        db.add(row)

    try:
        row.latest_version = fetch_latest_release_version()
        row.check_failed = False
    except VersionCheckError as exc:
        row.check_failed = True
        logger.warning("version check failed: %s", exc)

    row.checked_at = datetime.now(timezone.utc)
    return row


def is_newer(candidate: str, current: str) -> bool:
    """True if candidate is a strictly newer MAJOR.MINOR.PATCH than current.
    Plain integer-tuple comparison, not dpkg_compare (version_compare.py) —
    that's for Debian package version ordering (epochs, tildes), a
    different domain from this app's own plain-semver VERSION file.
    Unparseable input (either side isn't strict X.Y.Z) returns False rather
    than raising — a malformed tag from GitHub must never surface a false
    "update available".
    """
    candidate_tuple = _parse_semver(candidate)
    current_tuple = _parse_semver(current)
    if candidate_tuple is None or current_tuple is None:
        return False
    return candidate_tuple > current_tuple
