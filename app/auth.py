import hashlib
import secrets
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import BeaconToken, RefreshToken, Role, Server, ServerLifecycleState, User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")
# Separate security scheme from oauth2_scheme above — a beacon token is NOT
# a JWT and carries no OAuth2 token-endpoint semantics; using a distinct
# HTTPBearer keeps the two auth systems visually distinct in the generated
# OpenAPI docs rather than implying beacons could authenticate via
# POST /auth/login.
beacon_bearer_scheme = HTTPBearer(auto_error=False)

# Hierarchical role ordering — admin can do everything operator/viewer can,
# operator can do everything viewer can. Matches how these three roles read
# semantically (viewer=read-only, operator=day-to-day ops, admin=everything)
# and avoids an admin being locked out of an endpoint gated at "operator".
ROLE_RANK: dict[Role, int] = {Role.viewer: 0, Role.operator: 1, Role.admin: 2}


def hash_opaque_token(token: str) -> str:
    """Canonical hash for every high-entropy, secrets.token_urlsafe(32)-style
    opaque credential in this app (ActivationKey, RefreshToken, BeaconToken).
    SHA-256, not bcrypt: these tokens are already high-entropy random values,
    not low-entropy human passwords — the threat model is disclosure, not
    brute-force, so a fast hash for lookup-by-hash is correct (same posture
    as an API-key pattern). Only the hash is ever persisted; the raw token
    is returned to the caller exactly once, at issuance.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.jwt_expire_minutes)
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        username = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None or not user.active:
        # Same 401 as any other invalid credential — doesn't distinguish
        # "deactivated" from "doesn't exist" to a caller, matching login's
        # existing no-enumeration posture. A deactivated user's still-live
        # access token (up to 15 min, jwt_expire_minutes) is rejected here
        # immediately rather than waiting for natural expiry; refresh is
        # already a dead end since issue_refresh_token only ever gets
        # called from a login path this same check now blocks.
        raise credentials_exception
    return user


def require_role(min_role: Role) -> Callable[[User], User]:
    # Real, hierarchical enforcement. ROLE_RANK[user.role] >= ROLE_RANK[min_role]
    # so e.g. require_role(Role.operator) admits both operator and admin users.
    def _check(user: User = Depends(get_current_user)) -> User:
        if ROLE_RANK[user.role] < ROLE_RANK[min_role]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"requires {min_role.value} role or higher",
            )
        return user

    return _check


# ---------------------------------------------------------------------------
# Refresh tokens — DB-backed and revocable (RefreshToken), not a stateless
# rotating JWT. Same hash-only-storage posture as ActivationKey/BeaconToken
# (hash_opaque_token above): the raw token is returned once and only its
# SHA-256 hash is ever persisted.
# ---------------------------------------------------------------------------


def issue_refresh_token(db: Session, user: User) -> str:
    raw = secrets.token_urlsafe(32)
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_opaque_token(raw),
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
        )
    )
    return raw


def consume_refresh_token(db: Session, raw_token: str) -> User:
    """Validate a refresh token, revoke it, and return its owning user.
    Caller is responsible for issuing a replacement (rotation) and committing.
    Raises HTTPException(401) for any invalid/expired/revoked/reused token.
    """
    invalid = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid refresh token")
    token_hash = hash_opaque_token(raw_token)
    record = db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    ).scalar_one_or_none()
    if record is None or record.revoked_at is not None:
        raise invalid
    if record.expires_at < datetime.now(timezone.utc):
        raise invalid

    user = db.get(User, record.user_id)
    if user is None:
        raise invalid

    record.revoked_at = datetime.now(timezone.utc)
    return user


# ---------------------------------------------------------------------------
# Beacon auth — a second, deliberate, non-JWT auth path for the optional
# pull-based Beacon agent (see ROADMAP.md Phase 9). A beacon holds a
# per-server BeaconToken, not a human JWT, so it can never carry a Role and
# is resolved through this dependency instead of get_current_user/
# require_role. Structural invariant, load-bearing for the whole subsystem:
# a beacon can only ever act as the ONE server its token is bound to — no
# endpoint anywhere in app/routers/beacon.py accepts a server_id parameter
# of any kind; identity always comes from the token, never the request.
# ---------------------------------------------------------------------------


def mint_beacon_token(db: Session, server: Server, name: str | None, created_by_user_id: uuid.UUID | None) -> tuple[BeaconToken, str]:
    """Mints a new BeaconToken and returns (row, raw_token) — the raw
    value is never stored, only its hash, and this is the only moment it
    exists in plaintext. Shared by servers.py's POST
    /{server_id}/beacon-token (operator-initiated) and install_beacon_task
    (server-initiated, as part of an SSH-rollout job) so token minting has
    exactly one implementation rather than two copies that could drift.
    Caller is responsible for the AuditLog row and commit — the audit
    detail differs slightly between the two call sites (one has a human
    actor, the other doesn't).
    """
    raw = secrets.token_urlsafe(32)
    beacon_token = BeaconToken(
        server_id=server.id,
        token_hash=hash_opaque_token(raw),
        name=name,
        created_by_user_id=created_by_user_id,
    )
    db.add(beacon_token)
    db.flush()
    return beacon_token, raw


def get_current_beacon_server(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(beacon_bearer_scheme),
) -> Server:
    invalid = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid beacon token")
    if credentials is None:
        raise invalid

    token_hash = hash_opaque_token(credentials.credentials)
    beacon_token = db.execute(
        select(BeaconToken).where(BeaconToken.token_hash == token_hash)
    ).scalar_one_or_none()
    if beacon_token is None:
        raise invalid
    if beacon_token.revoked:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="beacon token has been revoked")
    if beacon_token.expires_at is not None and beacon_token.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="beacon token has expired")

    server = db.get(Server, beacon_token.server_id)
    if server is None:
        raise invalid
    if server.lifecycle_state == ServerLifecycleState.decommissioned:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="server is decommissioned")

    beacon_token.last_used_at = datetime.now(timezone.utc)
    db.commit()
    return server
