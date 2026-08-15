import shlex
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import hash_opaque_token
from app.config import settings
from app.database import get_db
from app.limiter import limiter
from app.models import ActivationKey, AuditAction, AuditLog, HostGroupServer, Server
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
        select(ActivationKey).where(ActivationKey.token_hash == hash_opaque_token(payload.token))
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


@router.get("/ssh-public-key", response_class=PlainTextResponse)
def get_fleet_ssh_public_key():
    """The shared fleet SSH public key (see Server.ssh_key_path and
    docs/limitations.md) — not a secret, same trust model as GitHub's
    /user.keys. Unauthenticated so both the enrollment script (curl'd from
    a brand-new host with no credentials yet) and a human copying it by
    hand can fetch it directly, always current even across a key rotation.
    """
    key_path = f"{settings.ansible_private_key_path}.pub"
    try:
        with open(key_path) as f:
            return f.read().strip() + "\n"
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="fleet SSH public key not available on this server",
        ) from exc


@router.get("/script", response_class=PlainTextResponse)
@limiter.limit("20/minute")
def get_enrollment_script(request: Request, token: str):
    """Generates a self-contained bootstrap script for a NEW host: the
    Satellite `subscription-manager register --activationkey` /
    "Global Registration" equivalent. Run on the target host (as root, or
    via sudo), it registers the host with groundctl (POST /enrollment/register,
    same call docs/quickstart.md documents doing by hand) and installs
    groundctl's fleet SSH key into root's authorized_keys — closing the gap
    documented there ("does not SSH to it") so the host is immediately
    ready for POST /jobs/bootstrap with no separate manual key-copying step.

    No auth beyond the activation-key token itself — same posture as
    POST /enrollment/register (the token IS the credential); this endpoint
    only formats a script around that same unauthenticated call, it does
    not grant anything the token didn't already grant. The token is not
    validated here — an invalid/expired/revoked token still produces a
    script, it will simply fail with 401 when actually run, exactly as
    the raw curl command would.
    """
    api_base_url = settings.groundctl_api_base_url.rstrip("/")
    quoted_token = shlex.quote(token)

    script = f"""#!/usr/bin/env bash
# groundctl enrollment script — generated for one activation key.
# Registers this host with groundctl and installs groundctl's fleet SSH
# key so it can be bootstrapped afterward. Run as root (or via sudo).
set -euo pipefail

GROUNDCTL_API_BASE_URL={shlex.quote(api_base_url)}
GROUNDCTL_TOKEN={quoted_token}

if [[ "${{EUID}}" -ne 0 ]]; then
    echo "[groundctl-register] must be run as root (try: sudo bash)" >&2
    exit 1
fi

hostname="$(hostname -f 2>/dev/null || hostname)"
ip_address="$(hostname -I 2>/dev/null | awk '{{print $1}}')"
if [[ -z "${{ip_address}}" ]]; then
    echo "[groundctl-register] could not determine this host's IP address" >&2
    exit 1
fi

# hostname/ip_address are built into the JSON body below via printf, not a
# JSON-aware encoder — safe only because neither a DNS hostname (RFC 1123)
# nor an IPv4/IPv6 literal can contain a double quote, backslash, or a
# control character,
# the only bytes that would need escaping in a JSON string. Don't repurpose
# this pattern for a field without that same guarantee.
echo "[groundctl-register] registering ${{hostname}} (${{ip_address}}) with groundctl..."
response="$(curl -sSf -X POST "${{GROUNDCTL_API_BASE_URL}}/api/enrollment/register" \\
    -H 'Content-Type: application/json' \\
    -d "$(printf '{{"token": "%s", "hostname": "%s", "ip_address": "%s", "ssh_user": "root"}}' \\
        "${{GROUNDCTL_TOKEN}}" "${{hostname}}" "${{ip_address}}")")"
echo "[groundctl-register] registered: ${{response}}"

echo "[groundctl-register] installing groundctl's SSH key for future management..."
fleet_pubkey="$(curl -sSf "${{GROUNDCTL_API_BASE_URL}}/api/enrollment/ssh-public-key")"
install -d -m 0700 /root/.ssh
touch /root/.ssh/authorized_keys
chmod 0600 /root/.ssh/authorized_keys
if ! grep -qF "${{fleet_pubkey}}" /root/.ssh/authorized_keys; then
    echo "${{fleet_pubkey}}" >> /root/.ssh/authorized_keys
fi

echo "[groundctl-register] done — this host is now visible in groundctl."
echo "[groundctl-register] an operator can now trigger a bootstrap job to finish setup."
"""
    return PlainTextResponse(content=script, media_type="text/x-shellscript")
