import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth import require_role
from app.database import get_db
from app.models import AuditAction, AuditLog, Product, Repository, Role, User
from app.schemas import ProductCreate, ProductRead, ProductUpdate

router = APIRouter()


def _read(db: Session, product: Product) -> ProductRead:
    repository_count = db.execute(
        select(func.count()).select_from(Repository).where(Repository.product_id == product.id)
    ).scalar_one()
    return ProductRead(
        id=product.id,
        name=product.name,
        description=product.description,
        repository_count=repository_count,
        created_at=product.created_at,
    )


def _get_product_or_404(db: Session, product_id: uuid.UUID) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="product not found")
    return product


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    existing = db.execute(select(Product).where(Product.name == payload.name)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="product name already exists")

    product = Product(name=payload.name, description=payload.description)
    db.add(product)
    db.flush()
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.create_product,
            resource_type="product",
            resource_id=product.name,
        )
    )
    db.commit()
    db.refresh(product)
    return _read(db, product)


@router.get("", response_model=list[ProductRead])
def list_products(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    products = list(db.execute(select(Product).order_by(Product.name)).scalars())
    return [_read(db, product) for product in products]


@router.get("/{product_id}", response_model=ProductRead)
def get_product(
    product_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.viewer)),
):
    product = _get_product_or_404(db, product_id)
    return _read(db, product)


@router.put("/{product_id}", response_model=ProductRead)
def update_product(
    product_id: uuid.UUID,
    payload: ProductUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    product = _get_product_or_404(db, product_id)

    if payload.name != product.name:
        existing = db.execute(select(Product).where(Product.name == payload.name)).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="product name already exists")

    product.name = payload.name
    product.description = payload.description
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.update_product,
            resource_type="product",
            resource_id=product.name,
        )
    )
    db.commit()
    db.refresh(product)
    return _read(db, product)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.operator)),
):
    """Ungroups member repositories rather than blocking — a Product is
    purely organizational (see Product's docstring in models.py), so unlike
    deleting a Repository (blocked by ContentView references) there's no
    content-lifecycle harm in deleting a Product out from under its
    repositories. They fall back to product_id=NULL (ungrouped), same state
    a never-assigned repository is already in.
    """
    product = _get_product_or_404(db, product_id)

    db.execute(update(Repository).where(Repository.product_id == product.id).values(product_id=None))
    db.add(
        AuditLog(
            user_id=current_user.id,
            action=AuditAction.delete_product,
            resource_type="product",
            resource_id=product.name,
        )
    )
    db.delete(product)
    db.commit()
