from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import (
    consume_refresh_token,
    create_access_token,
    get_current_user,
    hash_password,
    issue_refresh_token,
    require_role,
    verify_password,
)
from app.config import settings
from app.database import get_db
from app.limiter import limiter
from app.models import AuditAction, AuditLog, Role, User
from app.schemas import RefreshRequest, TokenPair, UIAccessToken, UserCreate, UserRead

router = APIRouter()

# Cookie name/path shared by the ui-* endpoints below. Scoped to /api/auth
# (this router's real mounted path — see app/main.py's api_router, prefix
# /api applied on top of this router's own /auth) so the browser only ever
# sends it back to the refresh/logout endpoints that need it, not on every
# request to the resource API. Must track the router's actual mount path
# exactly — a mismatch here means the browser silently never sends the
# cookie back at all, breaking silent refresh with no visible error until
# the access token expires.
UI_REFRESH_COOKIE = "refresh_token"
UI_REFRESH_COOKIE_PATH = "/api/auth"


def _set_ui_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=UI_REFRESH_COOKIE,
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=settings.refresh_token_expire_days * 86400,
        path=UI_REFRESH_COOKIE_PATH,
    )


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(
    payload: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.admin)),
):
    # Admin-only: creating a user (especially one with role=admin) must not
    # be self-service — previously this endpoint had no auth at all.
    existing = db.execute(
        select(User).where((User.username == payload.username) | (User.email == payload.email))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="username or email already registered")

    user = User(
        username=payload.username,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.flush()
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.create_user,
            resource_type="user",
            resource_id=str(user.id),
        )
    )
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenPair)
@limiter.limit("5/minute")
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.username == form_data.username)).scalar_one_or_none()
    if user is None or not verify_password(form_data.password, user.hashed_password):
        db.add(
            AuditLog(
                user_id=user.id if user is not None else None,
                action=AuditAction.login_failed,
                resource_type="user",
                resource_id=str(user.id) if user is not None else None,
                # Never log the password. Username is useful for detecting
                # credential-stuffing/enumeration attempts against real vs.
                # nonexistent accounts.
                detail={"username": form_data.username},
            )
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": user.username})
    refresh_token = issue_refresh_token(db, user)
    db.add(
        AuditLog(
            user_id=user.id,
            action=AuditAction.login,
            resource_type="user",
            resource_id=str(user.id),
        )
    )
    db.commit()
    return TokenPair(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenPair)
@limiter.limit("5/minute")
def refresh(request: Request, payload: RefreshRequest, db: Session = Depends(get_db)):
    # consume_refresh_token revokes the presented token as a side effect —
    # rotation on every use limits the replay window if a refresh token is
    # ever disclosed. A second use of the same (now-revoked) token fails.
    user = consume_refresh_token(db, payload.refresh_token)
    access_token = create_access_token(data={"sub": user.username})
    new_refresh_token = issue_refresh_token(db, user)
    db.commit()
    return TokenPair(access_token=access_token, refresh_token=new_refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: RefreshRequest, db: Session = Depends(get_db)):
    try:
        consume_refresh_token(db, payload.refresh_token)
    except HTTPException:
        # Logging out with an already-invalid/unknown token is a no-op, not
        # an error — the caller's goal (this token no longer works) is
        # already satisfied.
        db.rollback()
        return
    db.commit()


# ---------------------------------------------------------------------------
# Web UI auth — cookie-based refresh token instead of returning it in the
# response body. The access token still behaves exactly like /auth/login's:
# short-lived, held in memory by the SPA, attached as a Bearer header on
# every API call. Existing /auth/login|refresh|logout are untouched and
# remain the JSON-body flow for API/CLI-style clients.
# ---------------------------------------------------------------------------


@router.post("/ui-login", response_model=UIAccessToken)
@limiter.limit("5/minute")
def ui_login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.execute(select(User).where(User.username == form_data.username)).scalar_one_or_none()
    if user is None or not verify_password(form_data.password, user.hashed_password):
        db.add(
            AuditLog(
                user_id=user.id if user is not None else None,
                action=AuditAction.login_failed,
                resource_type="user",
                resource_id=str(user.id) if user is not None else None,
                detail={"username": form_data.username},
            )
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": user.username})
    refresh_token = issue_refresh_token(db, user)
    db.add(
        AuditLog(
            user_id=user.id,
            action=AuditAction.login,
            resource_type="user",
            resource_id=str(user.id),
        )
    )
    db.commit()
    _set_ui_refresh_cookie(response, refresh_token)
    return UIAccessToken(access_token=access_token)


@router.post("/ui-refresh", response_model=UIAccessToken)
@limiter.limit("5/minute")
def ui_refresh(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=UI_REFRESH_COOKIE),
    db: Session = Depends(get_db),
):
    if refresh_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="no refresh cookie present")
    user = consume_refresh_token(db, refresh_token)
    access_token = create_access_token(data={"sub": user.username})
    new_refresh_token = issue_refresh_token(db, user)
    db.commit()
    _set_ui_refresh_cookie(response, new_refresh_token)
    return UIAccessToken(access_token=access_token)


@router.post("/ui-logout", status_code=status.HTTP_204_NO_CONTENT)
def ui_logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=UI_REFRESH_COOKIE),
    db: Session = Depends(get_db),
):
    if refresh_token is not None:
        try:
            consume_refresh_token(db, refresh_token)
            db.commit()
        except HTTPException:
            db.rollback()
    response.delete_cookie(key=UI_REFRESH_COOKIE, path=UI_REFRESH_COOKIE_PATH)


@router.get("/me", response_model=UserRead)
def me(current_user: User = Depends(get_current_user)):
    return current_user
