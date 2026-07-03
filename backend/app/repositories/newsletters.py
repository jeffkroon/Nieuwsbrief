"""Repository voor gegenereerde nieuwsbrieven."""

from __future__ import annotations

import uuid

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
