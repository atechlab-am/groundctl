import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.auth import require_role
from app.database import get_db
from app.models import AuditAction, AuditLog, Branding, Role, User
from app.schemas import BrandingColorsUpdate, BrandingRead

router = APIRouter()

# Single shared row — every read/write targets this exact id, enforced by
# never inserting a second row (get-or-create below always returns the
# same one once it exists). Fixed rather than "whatever the first row
# happens to be" so it's reproducible across a restore/reseed.
_BRANDING_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# Small, fixed allowlist — SVG deliberately excluded despite being a
# reasonable logo format: an SVG can embed <script>/event-handler
# attributes and this app doesn't sanitize uploaded content, so allowing
# it would let an admin (a real but non-zero trust level below "can run
# arbitrary code on the server") store a stored-XSS payload served back
# to every user via <img>. Raster formats have no equivalent script
# surface.
_ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp", "image/x-icon", "image/vnd.microsoft.icon"}
_MAX_UPLOAD_BYTES = 2 * 1024 * 1024


def _get_or_create_branding(db: Session) -> Branding:
    branding = db.get(Branding, _BRANDING_ID)
    if branding is None:
        branding = Branding(id=_BRANDING_ID)
        db.add(branding)
        db.flush()
    return branding


async def _read_validated_upload(file: UploadFile) -> tuple[bytes, str]:
    if file.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unsupported image type {file.content_type!r} — allowed: {sorted(_ALLOWED_CONTENT_TYPES)}",
        )
    data = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"image exceeds {_MAX_UPLOAD_BYTES} byte limit",
        )
    if not data:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="empty file")
    return data, file.content_type


@router.get("", response_model=BrandingRead)
def get_branding(db: Session = Depends(get_db)):
    # Unauthenticated, like GET /branding/logo and /favicon below — the
    # login screen (and the browser tab, before any session exists) needs
    # to apply the right colors/logo/favicon too. Colors and
    # has_logo/has_favicon flags aren't sensitive; same reasoning as the
    # image bytes themselves already being public.
    branding = db.get(Branding, _BRANDING_ID)
    if branding is None:
        # No admin has configured anything yet — respond with the
        # all-defaults shape rather than 404ing, since "branding not
        # customized" is the normal/expected state for a fresh install,
        # not an error condition.
        return BrandingRead(primary_color=None, accent_color=None, has_logo=False, has_favicon=False, updated_at=None)
    return BrandingRead(
        primary_color=branding.primary_color,
        accent_color=branding.accent_color,
        has_logo=branding.logo_data is not None,
        has_favicon=branding.favicon_data is not None,
        updated_at=branding.updated_at,
    )


@router.put("/colors", response_model=BrandingRead)
def update_branding_colors(
    payload: BrandingColorsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.admin)),
):
    branding = _get_or_create_branding(db)
    fields = payload.model_dump(exclude_unset=True)
    if "primary_color" in fields:
        branding.primary_color = fields["primary_color"]
    if "accent_color" in fields:
        branding.accent_color = fields["accent_color"]

    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.update_branding,
            resource_type="branding",
            resource_id=str(branding.id),
            detail=fields,
        )
    )
    db.commit()
    db.refresh(branding)
    return BrandingRead(
        primary_color=branding.primary_color,
        accent_color=branding.accent_color,
        has_logo=branding.logo_data is not None,
        has_favicon=branding.favicon_data is not None,
        updated_at=branding.updated_at,
    )


@router.post("/logo", response_model=BrandingRead)
async def upload_logo(
    file: UploadFile,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.admin)),
):
    data, content_type = await _read_validated_upload(file)
    branding = _get_or_create_branding(db)
    branding.logo_data = data
    branding.logo_content_type = content_type

    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.update_branding,
            resource_type="branding",
            resource_id=str(branding.id),
            detail={"field": "logo", "content_type": content_type, "bytes": len(data)},
        )
    )
    db.commit()
    db.refresh(branding)
    return BrandingRead(
        primary_color=branding.primary_color,
        accent_color=branding.accent_color,
        has_logo=True,
        has_favicon=branding.favicon_data is not None,
        updated_at=branding.updated_at,
    )


@router.post("/favicon", response_model=BrandingRead)
async def upload_favicon(
    file: UploadFile,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.admin)),
):
    data, content_type = await _read_validated_upload(file)
    branding = _get_or_create_branding(db)
    branding.favicon_data = data
    branding.favicon_content_type = content_type

    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.update_branding,
            resource_type="branding",
            resource_id=str(branding.id),
            detail={"field": "favicon", "content_type": content_type, "bytes": len(data)},
        )
    )
    db.commit()
    db.refresh(branding)
    return BrandingRead(
        primary_color=branding.primary_color,
        accent_color=branding.accent_color,
        has_logo=branding.logo_data is not None,
        has_favicon=True,
        updated_at=branding.updated_at,
    )


# -- unauthenticated image serving ------------------------------------------
# A <link rel="icon">/<img> tag has no mechanism to attach an Authorization
# header — gating these behind auth would make branding invisible exactly
# where it matters most (the browser tab, the pre-login screen). A
# logo/favicon isn't sensitive; same reasoning as GET
# /api/enrollment/ssh-public-key ("a public key isn't a secret").


@router.get("/logo", include_in_schema=True)
def get_logo(db: Session = Depends(get_db)):
    branding = db.get(Branding, _BRANDING_ID)
    if branding is None or branding.logo_data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no logo configured")
    return Response(content=branding.logo_data, media_type=branding.logo_content_type)


@router.get("/favicon", include_in_schema=True)
def get_favicon(db: Session = Depends(get_db)):
    branding = db.get(Branding, _BRANDING_ID)
    if branding is None or branding.favicon_data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no favicon configured")
    return Response(content=branding.favicon_data, media_type=branding.favicon_content_type)
