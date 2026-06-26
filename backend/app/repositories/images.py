"""Repository voor geüploade foto's per tenant."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Image, Tenant

BANNER_CATEGORY = "banner"


def tenant_categories(tenant: Tenant) -> list[str]:
    """Categorieën van een tenant: 'banner' altijd eerst, daarna de eigen keuzes."""
    custom = [c for c in tenant.config.get("image_categories", []) if c and c != BANNER_CATEGORY]
    return [BANNER_CATEGORY, *custom]


def create_image(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    category: str,
    filename: str,
    storage_path: str,
    url: str,
    description: str | None = None,
) -> Image:
    image = Image(
        tenant_id=tenant_id,
        category=category,
        filename=filename,
        description=description,
        storage_path=storage_path,
        url=url,
    )
    session.add(image)
    session.commit()
    session.refresh(image)
    return image


def list_images(session: Session, tenant_id: uuid.UUID, category: str | None = None) -> list[Image]:
    query = select(Image).where(Image.tenant_id == tenant_id)
    if category:
        query = query.where(Image.category == category)
    return list(session.scalars(query.order_by(Image.category, Image.filename)))


def get_image(session: Session, image_id: uuid.UUID) -> Image | None:
    return session.get(Image, image_id)


def delete_image(session: Session, image_id: uuid.UUID) -> bool:
    image = session.get(Image, image_id)
    if image is None:
        return False
    session.delete(image)
    session.commit()
    return True
