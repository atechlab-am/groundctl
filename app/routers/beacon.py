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

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.apt_sources import render_apt_source, resolve_environment_components
from app.auth import get_current_beacon_server
from app.database import get_db
from app.models import ContentViewVersion, LifecycleEnvironment, Server, ServerBeaconState, ServerStatus
from app.schemas import (
    BeaconAptSource,
    BeaconCheckinRequest,
    BeaconCheckinResponse,
    BeaconEnvironmentInfo,
)
from app.tasks import resolve_published_base_url

router = APIRouter()

# Server-controlled — a beacon reads this from every checkin response
# rather than hardcoding its own interval, so the fleet-wide cadence can
# be retuned centrally without touching any host.
_CHECKIN_INTERVAL_SECONDS = 300


def _get_or_create_beacon_state(db: Session, server: Server) -> ServerBeaconState:
    state = db.get(ServerBeaconState, server.id)
    if state is None:
        state = ServerBeaconState(server_id=server.id)
        db.add(state)
        db.flush()
    return state


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
    would be 288 rows/host/day; full facts are pushed separately (Phase D)
    on a much slower schedule.
    """
    environment = db.get(LifecycleEnvironment, server.environment_id)
    if environment is None:
        # Same "environment no longer exists" condition bootstrap_task
        # guards against — shouldn't happen (environments aren't hard
        # deleted), but a beacon with nothing coherent to reconcile
        # against should fail loudly rather than get a malformed response.
        raise RuntimeError(f"server {server.id}'s environment no longer exists")

    version = (
        db.get(ContentViewVersion, environment.current_version_id)
        if environment.current_version_id is not None
        else None
    )
    components = resolve_environment_components(version.snapshots if version is not None else None)

    base_url = resolve_published_base_url(db, server)
    apt_source = render_apt_source(
        environment_name=environment.name,
        published_repo_base_url=base_url,
        publish_prefix=environment.publish_prefix,
        release=environment.release,
        components=components,
        gpg_key_id=environment.gpg_key_id,
    )

    now = datetime.now(timezone.utc)
    server.last_seen_at = now
    if server.status == ServerStatus.unreachable:
        server.status = ServerStatus.bootstrapped

    state = _get_or_create_beacon_state(db, server)
    state.last_checkin_at = now
    state.agent_version = payload.agent_version

    db.commit()

    return BeaconCheckinResponse(
        server_id=server.id,
        hostname=server.hostname,
        config_serial=state.config_serial,
        environment=BeaconEnvironmentInfo(
            id=environment.id,
            name=environment.name,
            release=environment.release,
            publish_prefix=environment.publish_prefix,
            components=components,
            gpg_key_id=environment.gpg_key_id,
        ),
        apt_source=BeaconAptSource(
            filename=apt_source.filename,
            contents=apt_source.contents,
            keyring_filename=apt_source.keyring_filename,
        ),
        gpg_public_key=None,  # wired up in Phase C alongside local reconciliation
        stale_source_filenames=[],  # wired up in Phase C
        checkin_interval_seconds=_CHECKIN_INTERVAL_SECONDS,
        facts_requested=False,  # wired up in Phase D
        actions=[],  # wired up in Phase E
    )
