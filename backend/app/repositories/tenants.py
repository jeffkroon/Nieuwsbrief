"""Repository voor tenants. Encapsuleert alle data-toegang achter functies."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Tenant
from app.schemas import TenantCreate, TenantUpdate


def create_tenant(session: Session, data: TenantCreate) -> Tenant:
    tenant = Tenant(
        slug=data.slug,
        name=data.name,
        status=data.status,
        brevo_list_id=data.brevo_list_id,
        config=data.config,
        settings=data.settings,
    )
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    return tenant


def get_tenant(session: Session, tenant_id: uuid.UUID) -> Tenant | None:
    return session.get(Tenant, tenant_id)


def get_tenant_by_slug(session: Session, slug: str) -> Tenant | None:
    return session.scalar(select(Tenant).where(Tenant.slug == slug))


def list_tenants(session: Session) -> list[Tenant]:
    return list(session.scalars(select(Tenant).order_by(Tenant.slug)))


def update_tenant(session: Session, tenant_id: uuid.UUID, data: TenantUpdate) -> Tenant | None:
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        return None
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(tenant, field, value)
    session.commit()
    session.refresh(tenant)
    return tenant


def delete_tenant(session: Session, tenant_id: uuid.UUID) -> bool:
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        return False
    session.delete(tenant)
    session.commit()
    return True
