import hashlib
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import RefreshToken, Role, User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# Hierarchical role ordering — admin can do everything operator/viewer can,
# operator can do everything viewer can. Matches how these three roles read
# semantically (viewer=read-only, operator=day-to-day ops, admin=everything)
# and avoids an admin being locked out of an endpoint gated at "operator".
ROLE_RANK: dict[Role, int] = {Role.viewer: 0, Role.operator: 1, Role.admin: 2}


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
# rotating JWT. Same hash-only-storage posture as ActivationKey
# (app/routers/activation_keys.py's _hash_token): the raw token is returned
# once and only its SHA-256 hash is ever persisted.
# ---------------------------------------------------------------------------


def _hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_refresh_token(db: Session, user: User) -> str:
    raw = secrets.token_urlsafe(32)
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=_hash_refresh_token(raw),
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
    token_hash = _hash_refresh_token(raw_token)
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
