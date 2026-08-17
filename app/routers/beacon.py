"""Beacon-facing endpoints — see ROADMAP.md Phase 9.

These are authenticated by `get_current_beacon_server` (app/auth.py), NOT
`get_current_user` — a beacon holds a per-host BeaconToken, not a human
JWT. This is a second, deliberate auth path, kept in its own router file
for the same reason enrollment.py is: so the property is grep-able rather
than interleaved with human-authenticated endpoints.

Unlike POST /enrollment/register, these endpoints are NOT unauthenticated
— every one requires a valid, non-revoked, non-expired BeaconToken bound
to a specific Server, and a beacon can only ever read or write data for
ITS OWN server. There is deliberately no endpoint here that accepts a
server_id parameter of any kind; the server identity always comes from
the token, never from the request body. This is the single most
important security invariant of this subsystem.
"""

import shlex
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.apt_sources import export_gpg_public_key, render_apt_source, resolve_environment_components
from app.auth import get_current_beacon_server
from app.config import settings
from app.database import get_db
from app.limiter import limiter
from app.models import (
    BeaconAction,
    BeaconActionStatus,
    ComplianceRecord,
    ContentView,
    ContentViewVersion,
    EnvironmentContentView,
    LifecycleEnvironment,
    Server,
    ServerBeaconState,
    ServerFact,
    ServerStatus,
)
from app.schemas import (
    BeaconAction as BeaconActionSchema,
)
from app.schemas import (
    BeaconAptSource,
    BeaconCheckinRequest,
    BeaconCheckinResponse,
    BeaconContentViewInfo,
    BeaconFactsRequest,
    BeaconFactsResponse,
    BeaconReportRequest,
    BeaconReportResponse,
)
from app.tasks import _finalize_job_if_resolvable, resolve_published_base_url

router = APIRouter()

# Server-controlled — a beacon reads this from every checkin response
# rather than hardcoding its own interval, so the fleet-wide cadence can
# be retuned centrally without touching any host.
_CHECKIN_INTERVAL_SECONDS = 300

# Free-form apt output/error text from /report — capped so one verbose
# failure can't grow ServerBeaconState.last_apply_detail unboundedly.
_REPORT_DETAIL_MAX_CHARS = 16_384

# Full facts (installed packages, disk, services) are pushed on a much
# slower cadence than the 5-minute checkin — a complete package list is
# meaningfully bigger than a checkin payload, and this data doesn't
# change often enough to justify checkin-frequency writes into an
# append-only table (user-confirmed: 6h, not the checkin interval).
_FACTS_PUSH_INTERVAL = timedelta(hours=6)


def _get_or_create_beacon_state(db: Session, server: Server) -> ServerBeaconState:
    state = db.get(ServerBeaconState, server.id)
    if state is None:
        state = ServerBeaconState(server_id=server.id)
        db.add(state)
        db.flush()
    return state


def _facts_push_is_due(state: ServerBeaconState, now: datetime) -> bool:
    if state.last_facts_pushed_at is None:
        return True
    return now - state.last_facts_pushed_at >= _FACTS_PUSH_INTERVAL


@router.post("/checkin", response_model=BeaconCheckinResponse)
def checkin(
    payload: BeaconCheckinRequest,
    db: Session = Depends(get_db),
    server: Server = Depends(get_current_beacon_server),
):
    """The combined poll. Side effects: Server.last_seen_at becomes a real
    heartbeat for this host (see the comment on that column), status
    recovers from unreachable if it was set, and ServerBeaconState tracks
    last_checkin_at/agent_version. Deliberately does NOT write a
    ServerFact row here — a 5-minute poll into that append-only table
    would be 288 rows/host/day; full facts are pushed separately via
    POST /facts, on a much slower schedule (facts_requested is true once
    every ~6h, or immediately after a first-ever checkin, so a
    freshly-installed host reports in without waiting up to 6h).

    Deliberately does NOT tell the beacon which stale files to remove —
    groundctl has no visibility into what's actually on the host's disk
    (that would mean server-side tracking of per-host filesystem state,
    exactly what the "thin, stateless, rebuildable from scratch" design
    principle avoids). Instead the beacon globs groundctl-* itself in
    /etc/apt/sources.list.d and /etc/apt/keyrings and removes anything
    that isn't THIS checkin's own apt_source.filename/keyring_filename —
    same logic bootstrap_client.yml already runs over SSH, just executed
    locally by the agent instead of by Ansible.
    """
    environment = db.get(LifecycleEnvironment, server.environment_id)
    if environment is None:
        # Same "environment no longer exists" condition bootstrap_task
        # guards against — shouldn't happen (environments aren't hard
        # deleted), but a beacon with nothing coherent to reconcile
        # against should fail loudly rather than get a malformed response.
        raise RuntimeError(f"server {server.id}'s environment no longer exists")

    # Any number of content views can be assigned to this environment now
    # (EnvironmentContentView, models.py) — build one apt source entry per
    # assignment that's actually been published; never-promoted
    # assignments are skipped rather than failing the whole checkin.
    ecvs = list(
        db.execute(select(EnvironmentContentView).where(EnvironmentContentView.environment_id == environment.id)).scalars()
    )
    published_ecvs = [ecv for ecv in ecvs if ecv.publish_prefix is not None and ecv.release is not None]

    base_url = resolve_published_base_url(db, server)
    content_view_infos: list[BeaconContentViewInfo] = []
    for ecv in published_ecvs:
        content_view = db.get(ContentView, ecv.content_view_id)
        content_view_name = content_view.name if content_view is not None else str(ecv.content_view_id)
        version = db.get(ContentViewVersion, ecv.current_version_id) if ecv.current_version_id is not None else None
        components = resolve_environment_components(version.snapshots if version is not None else None)
        assert ecv.publish_prefix is not None and ecv.release is not None  # filtered by published_ecvs above
        apt_source = render_apt_source(
            environment_name=environment.name,
            content_view_name=content_view_name,
            published_repo_base_url=base_url,
            publish_prefix=ecv.publish_prefix,
            release=ecv.release,
            components=components,
            gpg_key_id=ecv.gpg_key_id,
        )
        content_view_infos.append(
            BeaconContentViewInfo(
                id=ecv.id,
                content_view_id=ecv.content_view_id,
                content_view_name=content_view_name,
                release=ecv.release,
                publish_prefix=ecv.publish_prefix,
                components=components,
                gpg_key_id=ecv.gpg_key_id,
                apt_source=BeaconAptSource(
                    filename=apt_source.filename,
                    contents=apt_source.contents,
                    keyring_filename=apt_source.keyring_filename,
                ),
                gpg_public_key=export_gpg_public_key(ecv.gpg_key_id) if ecv.gpg_key_id else None,
            )
        )

    now = datetime.now(timezone.utc)
    server.last_seen_at = now
    if server.status == ServerStatus.unreachable:
        server.status = ServerStatus.bootstrapped

    state = _get_or_create_beacon_state(db, server)
    state.last_checkin_at = now
    state.agent_version = payload.agent_version

    pending_actions = list(
        db.execute(
            select(BeaconAction).where(
                BeaconAction.server_id == server.id,
                BeaconAction.status.in_([BeaconActionStatus.pending, BeaconActionStatus.delivered]),
            )
        ).scalars()
    )
    for action in pending_actions:
        if action.status == BeaconActionStatus.pending:
            action.status = BeaconActionStatus.delivered
            action.delivered_at = now

    db.commit()

    return BeaconCheckinResponse(
        server_id=server.id,
        hostname=server.hostname,
        config_serial=state.config_serial,
        environment_name=environment.name,
        content_views=content_view_infos,
        checkin_interval_seconds=_CHECKIN_INTERVAL_SECONDS,
        facts_requested=_facts_push_is_due(state, now),
        actions=[
            BeaconActionSchema(id=action.id, type=action.type, params=action.params) for action in pending_actions
        ],
    )


@router.post("/facts", response_model=BeaconFactsResponse)
def facts(
    payload: BeaconFactsRequest,
    db: Session = Depends(get_db),
    server: Server = Depends(get_current_beacon_server),
):
    """Full facts push — writes exactly the same two rows
    gather_facts_task (SSH path) already writes, ComplianceRecord and
    ServerFact, with source="beacon" instead of the default "ssh". Every
    existing consumer (do_check_compliance, GET /servers/{id}/facts,
    the weekly scan, trends) works unchanged against these rows — the
    source column is the only thing distinguishing how a given row was
    gathered.

    The weekly SSH-based scheduled_compliance_scan/gather_facts_task
    keeps running unconditionally regardless of whether a server also
    has a beacon (user-confirmed, ROADMAP.md Phase 9) — no skip-logic
    here or there. Redundant on a beacon-managed host, but harmless.
    """
    compliance_record = ComplianceRecord(
        server_id=server.id,
        installed_packages=payload.installed_packages,
        source="beacon",
    )
    db.add(compliance_record)
    server_fact = ServerFact(
        server_id=server.id,
        os_distribution=payload.os_distribution,
        os_version=payload.os_version,
        kernel=payload.kernel,
        uptime_seconds=payload.uptime_seconds,
        disk=payload.disk,
        services=payload.services,
        source="beacon",
    )
    db.add(server_fact)
    db.flush()

    state = _get_or_create_beacon_state(db, server)
    state.last_facts_pushed_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(compliance_record)
    db.refresh(server_fact)

    return BeaconFactsResponse(
        accepted=True,
        compliance_record_id=compliance_record.id,
        server_fact_id=server_fact.id,
    )


@router.post("/report", response_model=BeaconReportResponse)
def report(
    payload: BeaconReportRequest,
    db: Session = Depends(get_db),
    server: Server = Depends(get_current_beacon_server),
):
    """Outcome of the beacon's own local reconciliation attempt (writing
    sources.list/keyring, running apt-get update — see
    beacon/groundctl_beacon.py), OR of a dispatched BeaconAction
    (action_id set) — e.g. apply-updates queued by
    POST /jobs/apply-updates against a beacon-managed server. Either way
    this is the beacon's only way to report back; the two are
    distinguished solely by whether action_id is present.

    Failure semantics (user-confirmed): on outcome="failed",
    applied_config_serial is deliberately NOT bumped — the host stays
    visibly "pending reconciliation" (config_serial != applied_config_serial)
    until a future checkin succeeds. On "success"/"no_change",
    applied_config_serial is set to the serial the beacon just reconciled
    against, closing the gap for this host.

    When action_id is set, this also resolves that BeaconAction
    (succeeded/failed — a dispatched action has no "no_change" outcome)
    and, if every BeaconAction belonging to the parent Job has now reached
    a terminal state, closes out that Job — same shape _mark_job already
    uses for the SSH path, just triggered from here instead of a
    Celery task completing synchronously.
    """
    state = _get_or_create_beacon_state(db, server)

    detail = payload.detail
    if detail is not None and len(detail) > _REPORT_DETAIL_MAX_CHARS:
        detail = detail[:_REPORT_DETAIL_MAX_CHARS]

    state.last_apply_status = payload.outcome
    state.last_apply_detail = detail
    if payload.outcome in ("success", "no_change"):
        state.applied_config_serial = payload.config_serial

    job_id_to_finalize = None
    if payload.action_id is not None:
        action = db.get(BeaconAction, payload.action_id)
        # Ownership check mirrors every other invariant in this router —
        # a beacon can only ever resolve its OWN server's actions.
        if action is not None and action.server_id == server.id:
            action.status = BeaconActionStatus.succeeded if payload.outcome == "success" else BeaconActionStatus.failed
            action.resolved_at = datetime.now(timezone.utc)
            job_id_to_finalize = action.job_id

    db.commit()

    if job_id_to_finalize is not None:
        _finalize_job_if_resolvable(db, job_id_to_finalize)

    return BeaconReportResponse(accepted=True)


# ---------------------------------------------------------------------------
# Install rollout (ROADMAP.md Phase 9) — these two endpoints are
# deliberately NOT behind get_current_beacon_server: a brand-new host has
# no BeaconToken yet, that's the whole point of installing one. Same
# posture as enrollment.get_enrollment_script: unauthenticated/self-
# contained, gated only by the beacon token embedded in the generated
# script (minted beforehand via POST /servers/{id}/beacon-token or by
# install_beacon_task), never validated at generation time here.
# ---------------------------------------------------------------------------

_AGENT_FILE_PATH = Path(__file__).resolve().parent.parent.parent / "beacon" / "groundctl_beacon.py"


@router.get("/agent", response_class=PlainTextResponse)
def get_agent_binary():
    """Serves beacon/groundctl_beacon.py itself — the install script curls
    this to /usr/local/bin/groundctl-beacon. Single-file, stdlib-only (see
    that file's own docstring), so "serving" it is just returning the raw
    source; no build step, no packaging.
    """
    try:
        return PlainTextResponse(content=_AGENT_FILE_PATH.read_text(encoding="utf-8"))
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="beacon agent file not available on this server"
        ) from exc


@router.get("/install-script", response_class=PlainTextResponse)
@limiter.limit("20/minute")
def get_install_script(request: Request, token: str):
    """Generates a self-contained install script for an EXISTING,
    already-registered host (unlike enrollment's /script, which registers
    a brand-new one) — installs the beacon binary, writes
    /etc/groundctl/beacon.conf (0600 — the token is the one real secret
    here, delivered this way specifically so it never passes through
    Ansible extra_vars/Job.log_output when run via install_beacon_task),
    installs the systemd service+timer, and runs one immediate checkin so
    the host shows up in ServerBeaconState.last_checkin_at right away
    instead of waiting up to 5 minutes.

    token is not validated here, same posture as get_enrollment_script —
    an invalid/revoked token still produces a script; it fails with 401
    when actually run.
    """
    api_base_url = settings.groundctl_api_base_url.rstrip("/")
    quoted_token = shlex.quote(token)

    script = f"""#!/usr/bin/env bash
# groundctl Beacon install script — generated for one beacon token.
# Installs the beacon agent + systemd units on an already-registered host.
# Run as root (or via sudo).
set -euo pipefail

GROUNDCTL_API_BASE_URL={shlex.quote(api_base_url)}
GROUNDCTL_BEACON_TOKEN={quoted_token}

if [[ "${{EUID}}" -ne 0 ]]; then
    echo "[groundctl-beacon-install] must be run as root (try: sudo bash)" >&2
    exit 1
fi

echo "[groundctl-beacon-install] fetching agent..."
curl -sSf "${{GROUNDCTL_API_BASE_URL}}/api/beacon/agent" -o /usr/local/bin/groundctl-beacon
chmod 0755 /usr/local/bin/groundctl-beacon

echo "[groundctl-beacon-install] writing /etc/groundctl/beacon.conf..."
install -d -m 0755 /etc/groundctl
cat > /etc/groundctl/beacon.conf <<EOF
GROUNDCTL_API_BASE_URL=${{GROUNDCTL_API_BASE_URL}}
GROUNDCTL_BEACON_TOKEN=${{GROUNDCTL_BEACON_TOKEN}}
EOF
chmod 0600 /etc/groundctl/beacon.conf

echo "[groundctl-beacon-install] installing systemd units..."
curl -sSf "${{GROUNDCTL_API_BASE_URL}}/api/beacon/systemd-service" -o /etc/systemd/system/groundctl-beacon.service
curl -sSf "${{GROUNDCTL_API_BASE_URL}}/api/beacon/systemd-timer" -o /etc/systemd/system/groundctl-beacon.timer
systemctl daemon-reload
systemctl enable --now groundctl-beacon.timer

echo "[groundctl-beacon-install] running first checkin..."
/usr/local/bin/groundctl-beacon --once --config /etc/groundctl/beacon.conf

echo "[groundctl-beacon-install] done — beacon is now checking in every 5 minutes."
"""
    return PlainTextResponse(content=script, media_type="text/x-shellscript")


@router.get("/systemd-service", response_class=PlainTextResponse)
def get_systemd_service():
    return PlainTextResponse(content=_read_systemd_template("groundctl-beacon.service.template"))


@router.get("/systemd-timer", response_class=PlainTextResponse)
def get_systemd_timer():
    return PlainTextResponse(content=_read_systemd_template("groundctl-beacon.timer.template"))


def _read_systemd_template(filename: str) -> str:
    path = Path(__file__).resolve().parent.parent.parent / "systemd" / filename
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"{filename} not available on this server"
        ) from exc
