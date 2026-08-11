import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_role
from app.database import get_db
from app.instance_settings import get_effective_settings
from app.models import ActivationKey, AuditAction, AuditLog, HostGroup, LifecycleEnvironment, Role, User
from app.schemas import ActivationKeyCreate, ActivationKeyCreateResponse, ActivationKeyRead

router = APIRouter()


def _hash_token(token: str) -> str:
    # SHA-256, not bcrypt: the token is a secrets.token_urlsafe(32)
    # high-entropy random value, not a low-entropy human password — the
    # threat model here is disclosure, not brute-force, so a fast hash
    # for lookup-by-hash is correct (same posture as an API-key pattern).
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("", response_model=ActivationKeyCreateResponse, status_code=status.HTTP_201_CREATED)
def create_activation_key(
    payload: ActivationKeyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    environment = db.get(LifecycleEnvironment, payload.environment_id)
    if environment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="environment not found")

    if payload.host_group_id is not None and db.get(HostGroup, payload.host_group_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="host group not found")

    expires_at = payload.expires_at
    if expires_at is None:
        expires_at = datetime.now(timezone.utc) + timedelta(
            hours=get_effective_settings(db).activation_key_default_ttl_hours
        )

    token = secrets.token_urlsafe(32)
    key = ActivationKey(
        name=payload.name,
        token_hash=_hash_token(token),
        environment_id=payload.environment_id,
        host_group_id=payload.host_group_id,
        tags=payload.tags,
        expires_at=expires_at,
        max_uses=payload.max_uses,
        created_by_user_id=current_user.id,
    )
    db.add(key)
    db.flush()
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.create_activation_key,
            resource_type="activation_key",
            resource_id=str(key.id),
            # Never the token or its hash — only non-secret metadata.
            detail={"environment_id": str(key.environment_id), "host_group_id": str(key.host_group_id)
                    if key.host_group_id else None},
        )
    )
    db.commit()
    db.refresh(key)

    return ActivationKeyCreateResponse(
        id=key.id,
        name=key.name,
        token=token,
        environment_id=key.environment_id,
        host_group_id=key.host_group_id,
        tags=key.tags,
        expires_at=key.expires_at,
        max_uses=key.max_uses,
    )


@router.get("", response_model=list[ActivationKeyRead])
def list_activation_keys(
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    query = select(ActivationKey).order_by(ActivationKey.created_at.desc()).limit(limit).offset(offset)
    return list(db.execute(query).scalars())


@router.get("/{activation_key_id}", response_model=ActivationKeyRead)
def get_activation_key(
    activation_key_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    key = db.get(ActivationKey, activation_key_id)
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="activation key not found")
    return key


@router.post("/{activation_key_id}/revoke", response_model=ActivationKeyRead)
def revoke_activation_key(
    activation_key_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    key = db.get(ActivationKey, activation_key_id)
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="activation key not found")

    key.revoked = True
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.revoke_activation_key,
            resource_type="activation_key",
            resource_id=str(key.id),
        )
    )
    db.commit()
    db.refresh(key)
    return key
