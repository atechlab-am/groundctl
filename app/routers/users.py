import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_role
from app.database import get_db
from app.models import AuditAction, AuditLog, Role, User
from app.schemas import UserRead, UserUpdate

router = APIRouter()


def _count_active_admins(db: Session, excluding_user_id: uuid.UUID | None = None) -> int:
    query = select(func.count()).select_from(User).where(User.role == Role.admin, User.active.is_(True))
    if excluding_user_id is not None:
        query = query.where(User.id != excluding_user_id)
    return db.execute(query).scalar_one()


@router.get("", response_model=list[UserRead])
def list_users(
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.admin)),
):
    query = select(User).order_by(User.username).limit(limit).offset(offset)
    return list(db.execute(query).scalars())


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.admin)),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    fields = payload.model_dump(exclude_unset=True)

    if "email" in fields:
        existing = db.execute(
            select(User).where(User.email == fields["email"], User.id != user_id)
        ).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email already registered")
        user.email = fields["email"]

    if "role" in fields and fields["role"] != user.role:
        # Last-admin-lockout guard: refuse to demote the only active admin
        # out of the admin role — no endpoint anywhere lets an admin grant
        # themselves the role back once nobody with admin rights exists to
        # call this same endpoint.
        if user.role == Role.admin and fields["role"] != Role.admin and _count_active_admins(db, excluding_user_id=user.id) == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="cannot demote the last active admin — promote another user to admin first",
            )
        user.role = fields["role"]

    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.update_user,
            resource_type="user",
            resource_id=str(user.id),
            detail=fields,
        )
    )
    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/deactivate", response_model=UserRead)
def deactivate_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.admin)),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    if user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="cannot deactivate your own account")

    if user.role == Role.admin and _count_active_admins(db, excluding_user_id=user.id) == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="cannot deactivate the last active admin — promote another user to admin first",
        )

    if not user.active:
        return user

    user.active = False
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.deactivate_user,
            resource_type="user",
            resource_id=str(user.id),
        )
    )
    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/reactivate", response_model=UserRead)
def reactivate_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.admin)),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    if user.active:
        return user

    user.active = True
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.reactivate_user,
            resource_type="user",
            resource_id=str(user.id),
        )
    )
    db.commit()
    db.refresh(user)
    return user
