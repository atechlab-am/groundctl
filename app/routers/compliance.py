import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.aptly_client import AptlyClient, AptlyError, get_aptly_client
from app.auth import require_role
from app.database import get_db
from app.models import (
    ComplianceCheckLog,
    ComplianceRecord,
    ContentViewVersion,
    LifecycleEnvironment,
    Role,
    Server,
    User,
)
from app.schemas import ComplianceCheckResult, PackageDrift, PackageSearchResponse, PackageSearchResult
from app.version_compare import dpkg_compare

router = APIRouter()


def _highest_version_per_name_arch(packages: list[dict]) -> dict[tuple[str, str | None], str]:
    # aptly's ?format=details entries use "Package" (not "Name") for the
    # package name — verified against a real aptly 1.6.3 instance.
    # Architecture is occasionally absent on real entries, hence str | None.
    highest: dict[tuple[str, str | None], str] = {}
    for pkg in packages:
        name = pkg.get("Package")
        arch = pkg.get("Architecture")
        version = pkg.get("Version")
        if not name or not version:
            continue
        key = (name, arch)
        current = highest.get(key)
        if current is None or dpkg_compare(version, current) > 0:
            highest[key] = version
    return highest


class ComplianceDataNotReadyError(Exception):
    """No facts gathered yet, or the server's environment isn't published."""


def do_check_compliance(server: Server, db: Session, aptly: AptlyClient) -> ComplianceCheckResult:
    """Shared by the on-demand check endpoint and the weekly scheduled scan.
    Raises ComplianceDataNotReadyError if gather-facts hasn't run yet or the
    environment isn't published — callers decide how to surface that (422 for
    the endpoint, skip-and-log for the scheduled scan). Writes a
    ComplianceCheckLog row; caller commits.
    """
    record = db.execute(
        select(ComplianceRecord)
        .where(ComplianceRecord.server_id == server.id)
        .order_by(ComplianceRecord.gathered_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if record is None:
        raise ComplianceDataNotReadyError("no compliance data for this server yet — run gather-facts first")

    environment = db.get(LifecycleEnvironment, server.environment_id)
    if environment is None or environment.current_version_id is None:
        raise ComplianceDataNotReadyError("server's environment has not been published yet")

    version = db.get(ContentViewVersion, environment.current_version_id)
    if version is None:
        raise ComplianceDataNotReadyError("environment's published content view version no longer exists")

    # A content view version can aggregate snapshots from multiple
    # repositories — fetch each and merge before ranking, rather than the
    # single get_snapshot_packages call this had when one environment mapped
    # to exactly one mirror.
    snapshot_names = {entry["snapshot_name"] for entry in version.snapshots}
    snapshot_packages: list[dict] = []
    for snapshot_name in snapshot_names:
        snapshot_packages.extend(aptly.get_snapshot_packages(snapshot_name))

    available = _highest_version_per_name_arch(snapshot_packages)
    installed_by_name_arch = {(p["name"], p.get("arch")): p.get("version") for p in record.installed_packages}

    drift: list[PackageDrift] = []
    for (name, arch), installed_version in installed_by_name_arch.items():
        available_version = available.get((name, arch))
        pkg_status: Literal["outdated", "up_to_date", "not_in_environment"]
        if available_version is None:
            pkg_status = "not_in_environment"
        elif installed_version is None:
            pkg_status = "outdated"
        elif dpkg_compare(installed_version, available_version) < 0:
            pkg_status = "outdated"
        else:
            pkg_status = "up_to_date"

        drift.append(
            PackageDrift(
                name=name,
                installed_version=installed_version,
                available_version=available_version,
                status=pkg_status,
            )
        )

    checked_at = datetime.now(timezone.utc)
    db.add(ComplianceCheckLog(server_id=server.id, drift=[d.model_dump(mode="json") for d in drift]))
    return ComplianceCheckResult(server_id=server.id, checked_at=checked_at, drift=drift)


@router.post("/servers/{server_id}/check", response_model=ComplianceCheckResult)
def check_compliance(
    server_id: uuid.UUID,
    db: Session = Depends(get_db),
    aptly: AptlyClient = Depends(get_aptly_client),
    current_user: User = Depends(require_role(Role.operator)),
):
    server = db.get(Server, server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="server not found")

    try:
        result = do_check_compliance(server, db, aptly)
    except ComplianceDataNotReadyError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except AptlyError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    db.commit()
    return result


_COMPARATORS = {
    "lt": lambda cmp: cmp < 0,
    "le": lambda cmp: cmp <= 0,
    "eq": lambda cmp: cmp == 0,
    "ge": lambda cmp: cmp >= 0,
    "gt": lambda cmp: cmp > 0,
}


@router.get("/packages/search", response_model=PackageSearchResponse)
def search_packages(
    package_name: str,
    operator: Literal["lt", "le", "eq", "ge", "gt"] | None = None,
    compare_version: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    """Who has `package_name` installed, optionally filtered by version
    comparison (e.g. "who has openssl < 3.0.0-1"). Same N+1
    latest-ComplianceRecord-per-server pattern as do_check_compliance and
    errata.py's affected-servers — see docs/limitations.md for the scale
    tradeoff versus a normalized child table.
    """
    servers = list(db.execute(select(Server)).scalars())
    matches: list[PackageSearchResult] = []

    for server in servers:
        record = db.execute(
            select(ComplianceRecord)
            .where(ComplianceRecord.server_id == server.id)
            .order_by(ComplianceRecord.gathered_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if record is None:
            continue

        installed_version = next(
            (p.get("version") for p in record.installed_packages if p.get("name") == package_name), None
        )
        if installed_version is None:
            continue
        if operator is not None and compare_version is not None:
            if not _COMPARATORS[operator](dpkg_compare(installed_version, compare_version)):
                continue

        matches.append(
            PackageSearchResult(server_id=server.id, hostname=server.hostname, installed_version=installed_version)
        )

    return PackageSearchResponse(
        package_name=package_name, operator=operator, compare_version=compare_version, matches=matches
    )
