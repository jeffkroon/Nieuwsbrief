"""Repository voor nieuwsbrief-templates per tenant.

Eén template per tenant kan de standaard zijn. Het zetten van een standaard (of
het aanmaken van de eerste template) maakt de overige automatisch niet-standaard,
zodat er nooit twee standaarden tegelijk zijn.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import Template
from app.newsletter.styles import sanitize_styles


def list_templates(session: Session, tenant_id: uuid.UUID) -> list[Template]:
    query = (
        select(Template)
        .where(Template.tenant_id == tenant_id)
        .order_by(Template.is_default.desc(), Template.created_at)
    )
    return list(session.scalars(query))


def get_template(session: Session, template_id: uuid.UUID) -> Template | None:
    return session.get(Template, template_id)


def get_default_template(session: Session, tenant_id: uuid.UUID) -> Template | None:
    """De standaard-template, of anders de oudste die er is (of None)."""
    query = (
        select(Template)
        .where(Template.tenant_id == tenant_id)
        .order_by(Template.is_default.desc(), Template.created_at)
        .limit(1)
    )
    return session.scalars(query).first()


def _clear_default(session: Session, tenant_id: uuid.UUID) -> None:
    session.execute(
        update(Template)
        .where(Template.tenant_id == tenant_id, Template.is_default.is_(True))
        .values(is_default=False)
    )


def create_template(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    name: str,
    html: str,
    styles: dict | None = None,
    is_default: bool = False,
) -> Template:
    # De allereerste template van een tenant wordt sowieso de standaard.
    has_any = session.scalars(
        select(Template.id).where(Template.tenant_id == tenant_id).limit(1)
    ).first()
    make_default = is_default or has_any is None
    if make_default:
        _clear_default(session, tenant_id)
    template = Template(
        tenant_id=tenant_id,
        name=name,
        html=html,
        styles=sanitize_styles(styles),
        is_default=make_default,
    )
    session.add(template)
    session.commit()
    session.refresh(template)
    return template


def update_template(
    session: Session,
    template_id: uuid.UUID,
    *,
    name: str | None = None,
    html: str | None = None,
    styles: dict | None = None,
) -> Template | None:
    template = session.get(Template, template_id)
    if template is None:
        return None
    if name is not None:
        template.name = name
    if html is not None:
        template.html = html
    if styles is not None:
        template.styles = sanitize_styles(styles)
    session.commit()
    session.refresh(template)
    return template


def update_styles(session: Session, template_id: uuid.UUID, styles: dict) -> Template | None:
    """Alleen de kleuren/lettertype bijwerken (wat een bedrijf mag aanpassen)."""
    return update_template(session, template_id, styles=styles)


def set_default(session: Session, tenant_id: uuid.UUID, template_id: uuid.UUID) -> Template | None:
    template = session.get(Template, template_id)
    if template is None or template.tenant_id != tenant_id:
        return None
    _clear_default(session, tenant_id)
    template.is_default = True
    session.commit()
    session.refresh(template)
    return template


def delete_template(session: Session, template_id: uuid.UUID) -> bool:
    template = session.get(Template, template_id)
    if template is None:
        return False
    tenant_id = template.tenant_id
    was_default = template.is_default
    session.delete(template)
    session.flush()
    # Als de standaard weg is, promoveer de oudst overgebleven template.
    if was_default:
        nxt = session.scalars(
            select(Template)
            .where(Template.tenant_id == tenant_id)
            .order_by(Template.created_at)
            .limit(1)
        ).first()
        if nxt is not None:
            nxt.is_default = True
    session.commit()
    return True
