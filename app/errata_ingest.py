import re
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Erratum, ErratumPackage, ErratumSource

USN_NOTICES_URL = "https://ubuntu.com/security/notices.json"
DSA_LIST_URL = (
    "https://salsa.debian.org/security-tracker-team/security-tracker/-/raw/master/data/DSA/list"
)


def parse_usn_notice(notice: dict) -> tuple[dict, list[dict]] | None:
    """Parse one entry from notices.json's "notices" array into an
    Erratum-shaped dict and a list of ErratumPackage-shaped dicts. Returns
    None for entries missing required fields (defensive — the feed is
    external and not schema-guaranteed).

    Real shape (verified against a live fetch of
    https://ubuntu.com/security/notices.json this session):
        {"id": "USN-8620-4", "published": "2026-07-31T15:00:56.127396",
         "title": "...", "cves": [{"id": "CVE-2026-45912", ...}, ...],
         "release_packages": {"jammy": [{"name": "...", "version": "...",
                                          "is_source": true, ...}, ...]}}
    """
    advisory_id = notice.get("id")
    published_raw = notice.get("published")
    if not advisory_id or not published_raw:
        return None

    published_at = datetime.fromisoformat(published_raw)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)

    cves = [c["id"] for c in notice.get("cves", []) if c.get("id")]
    title = notice.get("title", advisory_id)

    packages: list[dict] = []
    for release, entries in notice.get("release_packages", {}).items():
        for entry in entries:
            name = entry.get("name")
            version = entry.get("version")
            if not name or not version:
                continue
            packages.append({"release": release, "package_name": name, "fixed_version": version})

    erratum = {
        "advisory_id": advisory_id,
        "source": ErratumSource.usn,
        "title": title,
        "cves": cves,
        "severity": None,  # not present in notices.json — see docs/limitations.md
        "published_at": published_at,
    }
    return erratum, packages


# DSA-6410-1 libssh - security update
_DSA_HEADER_RE = re.compile(r"^\[(?P<date>\d{2} \w{3} \d{4})\]\s+(?P<id>DSA-\d+-\d+)\s+(?P<title>.+)$")
# {CVE-2026-0964 CVE-2026-0965 ...}
_DSA_CVE_RE = re.compile(r"^\{(?P<cves>[^}]*)\}$")
# [trixie] - libssh 0.11.5-0+deb13u1
_DSA_PACKAGE_RE = re.compile(r"^\[(?P<release>\w+)\]\s+-\s+(?P<package>\S+)\s+(?P<version>\S+)$")


def parse_dsa_list(text: str) -> list[tuple[dict, list[dict]]]:
    """Parse the plain-text data/DSA/list format into (Erratum-shaped dict,
    list[ErratumPackage-shaped dict]) tuples, one per advisory block.

    Real format (verified against a live fetch this session):
        [02 Aug 2026] DSA-6410-1 libssh - security update
        \t{CVE-2026-0964 CVE-2026-0965 ...}
        \t[trixie] - libssh 0.11.5-0+deb13u1

    Deliberately NOT using dsa.rdf (that feed has no CVE/package/version
    data, title+link+date only — confirmed by inspecting it this session)
    and NOT the 10MB+ CVE-keyed tracker/data/json (wrong shape, wrong size
    for this use case).
    """
    results: list[tuple[dict, list[dict]]] = []
    current_erratum: dict | None = None
    current_packages: list[dict] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        header_match = _DSA_HEADER_RE.match(line)
        if header_match:
            if current_erratum is not None:
                results.append((current_erratum, current_packages))
            published_at = datetime.strptime(header_match.group("date"), "%d %b %Y").replace(
                tzinfo=timezone.utc
            )
            current_erratum = {
                "advisory_id": header_match.group("id"),
                "source": ErratumSource.dsa,
                "title": header_match.group("title"),
                "cves": [],
                "severity": None,  # not present in data/DSA/list — see docs/limitations.md
                "published_at": published_at,
            }
            current_packages = []
            continue

        if current_erratum is None:
            continue  # stray line before the first header — ignore

        cve_match = _DSA_CVE_RE.match(line)
        if cve_match:
            current_erratum["cves"] = cve_match.group("cves").split()
            continue

        package_match = _DSA_PACKAGE_RE.match(line)
        if package_match:
            current_packages.append(
                {
                    "release": package_match.group("release"),
                    "package_name": package_match.group("package"),
                    "fixed_version": package_match.group("version"),
                }
            )
            continue
        # Unrecognized line (e.g. a NOTE:/TODO: annotation some entries carry)
        # — ignore rather than fail the whole parse over one advisory's extra
        # line.

    if current_erratum is not None:
        results.append((current_erratum, current_packages))

    return results


def _upsert_erratum(db: Session, erratum_data: dict, packages_data: list[dict]) -> None:
    """Idempotent upsert keyed on advisory_id. Advisories are mutable
    upstream (revised CVE lists, corrected versions) — existing rows are
    updated in place, and their ErratumPackage children are fully replaced
    (delete+recreate) rather than diffed, matching how ContentViewVersion
    treats its snapshot list as one unit. Caller commits.
    """
    existing = db.execute(
        select(Erratum).where(Erratum.advisory_id == erratum_data["advisory_id"])
    ).scalar_one_or_none()

    if existing is None:
        erratum = Erratum(**erratum_data)
        db.add(erratum)
        db.flush()
    else:
        erratum = existing
        erratum.title = erratum_data["title"]
        erratum.cves = erratum_data["cves"]
        erratum.severity = erratum_data["severity"]
        erratum.published_at = erratum_data["published_at"]
        for existing_package in list(erratum.packages):
            db.delete(existing_package)
        db.flush()

    for package_data in packages_data:
        db.add(ErratumPackage(erratum_id=erratum.id, **package_data))


def fetch_and_upsert_usn(db: Session) -> tuple[int, int]:
    """Fetch notices.json, upsert every parseable notice. Returns
    (upserted_count, skipped_count).
    """
    response = httpx.get(USN_NOTICES_URL, timeout=30.0)
    response.raise_for_status()
    notices = response.json().get("notices", [])

    upserted = 0
    skipped = 0
    for notice in notices:
        parsed = parse_usn_notice(notice)
        if parsed is None:
            skipped += 1
            continue
        erratum_data, packages_data = parsed
        _upsert_erratum(db, erratum_data, packages_data)
        upserted += 1

    return upserted, skipped


def fetch_and_upsert_dsa(db: Session) -> tuple[int, int]:
    """Fetch data/DSA/list, upsert every parsed advisory. Returns
    (upserted_count, skipped_count) — skipped is always 0 here since
    parse_dsa_list only emits fully-formed blocks, kept for symmetry with
    fetch_and_upsert_usn's return shape.
    """
    response = httpx.get(DSA_LIST_URL, timeout=30.0)
    response.raise_for_status()

    upserted = 0
    for erratum_data, packages_data in parse_dsa_list(response.text):
        _upsert_erratum(db, erratum_data, packages_data)
        upserted += 1

    return upserted, 0
