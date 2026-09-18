"""Repository voor gegenereerde nieuwsbrieven."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Newsletter


def create_newsletter(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    subject: str,
    html: str,
    theme: str | None = None,
    conversation_id: uuid.UUID | None = None,
    input: dict | None = None,
    brevo_campaign_id: int | None = None,
    esp_campaign_ref: str | None = None,
    status: str = "draft",
) -> Newsletter:
    newsletter = Newsletter(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        theme=theme,
        subject=subject,
        html=html,
        input=input or {},
        brevo_campaign_id=brevo_campaign_id,
        esp_campaign_ref=esp_campaign_ref,
        status=status,
    )
    session.add(newsletter)
    session.commit()
    session.refresh(newsletter)
    return newsletter


def get_newsletter(session: Session, newsletter_id: uuid.UUID) -> Newsletter | None:
    return session.get(Newsletter, newsletter_id)


def list_newsletters(
    session: Session, tenant_id: uuid.UUID, *, limit: int = 50
) -> list[Newsletter]:
    """Nieuwste eerst; de HTML komt mee voor de preview van een losse nieuwsbrief."""
    query = (
        select(Newsletter)
        .where(Newsletter.tenant_id == tenant_id)
        .order_by(Newsletter.created_at.desc())
        .limit(limit)
    )
    return list(session.scalars(query))
