from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_role
from app.database import get_db
from app.models import ComplianceRecord, Erratum, ErratumPackage, ErratumSource, Role, Server, User
from app.schemas import AffectedServer, AffectedServersResponse, ErratumRead
from app.version_compare import dpkg_compare

router = APIRouter()


@router.get("", response_model=list[ErratumRead])
def list_errata(
    source: ErratumSource | None = None,
    cve: str | None = None,
    published_since: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    query = select(Erratum)
    if source is not None:
        query = query.where(Erratum.source == source)
    if published_since is not None:
        query = query.where(Erratum.published_at >= published_since)
    query = query.order_by(Erratum.published_at.desc())

    # limit/offset applied after the cve filter (not at the SQL level) since
    # cve matching happens in Python against the stored array — applying
    # limit/offset before that would paginate rows the cve filter hasn't
    # even looked at yet.
    if cve is not None:
        errata = [e for e in db.execute(query).scalars() if cve in e.cves]
        return errata[offset : offset + limit]
    return list(db.execute(query.limit(limit).offset(offset)).scalars())


@router.get("/{advisory_id}", response_model=ErratumRead)
def get_erratum(
    advisory_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    erratum = db.execute(select(Erratum).where(Erratum.advisory_id == advisory_id)).scalar_one_or_none()
    if erratum is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="erratum not found")
    return erratum


@router.get("/{advisory_id}/affected-servers", response_model=AffectedServersResponse)
def get_affected_servers(
    advisory_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    """A server is "affected" if its latest gathered installed version of a
    package this advisory touches is older than the advisory's fixed
    version — computed on read from ComplianceRecord, same posture as
    compliance/check (not continuously maintained state).
    """
    erratum = db.execute(select(Erratum).where(Erratum.advisory_id == advisory_id)).scalar_one_or_none()
    if erratum is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="erratum not found")

    packages = list(
        db.execute(select(ErratumPackage).where(ErratumPackage.erratum_id == erratum.id)).scalars()
    )
    fixed_version_by_package = {p.package_name: p.fixed_version for p in packages}
    if not fixed_version_by_package:
        return AffectedServersResponse(advisory_id=advisory_id, affected=[])

    servers = list(db.execute(select(Server)).scalars())
    affected: list[AffectedServer] = []

    for server in servers:
        record = db.execute(
            select(ComplianceRecord)
            .where(ComplianceRecord.server_id == server.id)
            .order_by(ComplianceRecord.gathered_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if record is None:
            continue

        installed_by_name = {p["name"]: p.get("version") for p in record.installed_packages}
        for package_name, fixed_version in fixed_version_by_package.items():
            installed_version = installed_by_name.get(package_name)
            if installed_version is None:
                continue
            if dpkg_compare(installed_version, fixed_version) < 0:
                affected.append(
                    AffectedServer(
                        server_id=server.id,
                        hostname=server.hostname,
                        package_name=package_name,
                        installed_version=installed_version,
                        fixed_version=fixed_version,
                    )
                )

    return AffectedServersResponse(advisory_id=advisory_id, affected=affected)
