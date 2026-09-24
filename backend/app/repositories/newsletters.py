"""Repository voor gegenereerde nieuwsbrieven."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
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
    esp: str | None = None,
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
        esp=esp,
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


# Statussen van nieuwsbrieven die echt als concept (of verstuurd) bestaan in het
# verzendplatform; 'failed' en half gemaakte horen niet in het geheugen.
EXISTING_STATUSES = ("ready", "approved", "sent")


def find_open_draft(
    session: Session, *, tenant_id: uuid.UUID, conversation_id: uuid.UUID | None
) -> Newsletter | None:
    """Het laatst aangemaakte concept uit dit gesprek dat nog bij te werken is."""
    if conversation_id is None:
        return None
    query = (
        select(Newsletter)
        .where(
            Newsletter.tenant_id == tenant_id,
            Newsletter.conversation_id == conversation_id,
            Newsletter.status == "ready",
            (Newsletter.brevo_campaign_id.is_not(None)) | (Newsletter.esp_campaign_ref.is_not(None)),
        )
        .order_by(Newsletter.created_at.desc())
        .limit(1)
    )
    return session.scalars(query).first()


def update_newsletter(session: Session, newsletter: Newsletter, **fields) -> Newsletter:
    """Velden van een bestaande nieuwsbrief bijwerken (en updated_at zetten)."""
    for name, value in fields.items():
        setattr(newsletter, name, value)
    newsletter.updated_at = func.now()
    session.commit()
    session.refresh(newsletter)
    return newsletter


def list_recent(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    limit: int = 5,
    exclude_conversation: uuid.UUID | None = None,
) -> list[Newsletter]:
    """Laatste echte nieuwsbrieven van een bedrijf (concept of verstuurd), nieuwste eerst."""
    query = select(Newsletter).where(
        Newsletter.tenant_id == tenant_id, Newsletter.status.in_(EXISTING_STATUSES)
    )
    if exclude_conversation is not None:
        query = query.where(
            (Newsletter.conversation_id.is_(None))
            | (Newsletter.conversation_id != exclude_conversation)
        )
    return list(session.scalars(query.order_by(Newsletter.created_at.desc()).limit(limit)))
