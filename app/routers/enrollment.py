from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.limiter import limiter
from app.models import ActivationKey, AuditAction, AuditLog, HostGroupServer, Server
from app.routers.activation_keys import _hash_token
from app.schemas import SelfRegisterRequest, SelfRegisterResponse

router = APIRouter()

# This is the one mutating endpoint in the entire app with no
# Depends(get_current_user) — deliberate, not an oversight. A brand-new
# host has no JWT; the activation-key token IS the authentication here,
# the same posture as `subscription-manager register --activationkey`.
# Kept in its own router file specifically so this property is obvious
# and grep-able rather than interleaved with authenticated endpoints.


@router.post("/register", response_model=SelfRegisterResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
def register(
    request: Request,
    payload: SelfRegisterRequest,
    db: Session = Depends(get_db),
):
    key = db.execute(
        select(ActivationKey).where(ActivationKey.token_hash == _hash_token(payload.token))
    ).scalar_one_or_none()
    if key is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid activation key token")
    if key.revoked:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="activation key has been revoked")
    if key.expires_at is not None and key.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="activation key has expired")
    if key.max_uses is not None and key.use_count >= key.max_uses:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="activation key has reached its max uses"
        )

    now = datetime.now(timezone.utc)
    server = db.execute(select(Server).where(Server.hostname == payload.hostname)).scalar_one_or_none()
    if server is None:
        server = Server(
            hostname=payload.hostname,
            ip_address=str(payload.ip_address),
            ssh_user=payload.ssh_user,
            environment_id=key.environment_id,
            registered_via_activation_key_id=key.id,
            last_seen_at=now,
        )
        db.add(server)
        db.flush()
    else:
        # Idempotent re-registration (e.g. a re-run bootstrap script) —
        # never touches environment_id on an existing server; environment
        # reassignment for an existing host is a deliberate, separate,
        # human-driven action, not something self-registration does.
        server.ip_address = str(payload.ip_address)
        server.ssh_user = payload.ssh_user
        server.last_seen_at = now

    if key.host_group_id is not None:
        already_member = db.execute(
            select(HostGroupServer).where(
                HostGroupServer.host_group_id == key.host_group_id,
                HostGroupServer.server_id == server.id,
            )
        ).scalar_one_or_none()
        if already_member is None:
            db.add(HostGroupServer(host_group_id=key.host_group_id, server_id=server.id))

    key.use_count += 1

    db.add(
        AuditLog(
            user_id=None,
            action=AuditAction.register_via_activation_key,
            resource_type="server",
            resource_id=str(server.id),
            detail={
                "activation_key_id": str(key.id),
                "hostname": payload.hostname,
                "tags": key.tags,
            },
        )
    )
    db.commit()
    db.refresh(server)

    return SelfRegisterResponse(server_id=server.id, environment_id=server.environment_id, hostname=server.hostname)
