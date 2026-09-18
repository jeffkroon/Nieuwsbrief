"""Repository voor gesprekken en hun berichten."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Conversation, Message


def create_conversation(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    channel: str = "web",
    external_ref: str | None = None,
) -> Conversation:
    conversation = Conversation(tenant_id=tenant_id, channel=channel, external_ref=external_ref)
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    return conversation


def get_conversation(session: Session, conversation_id: uuid.UUID) -> Conversation | None:
    return session.get(Conversation, conversation_id)


def add_message(
    session: Session,
    conversation_id: uuid.UUID,
    role: str,
    content: str,
    metadata: dict | None = None,
) -> Message:
    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        metadata_=metadata or {},
    )
    session.add(message)
    # Bijwerken zodat de gesprekkenlijst op "laatst gebruikt" kan sorteren; zonder
    # dit zakt een hervat gesprek weg tussen oudere gesprekken.
    conversation = session.get(Conversation, conversation_id)
    if conversation is not None:
        conversation.updated_at = func.now()
    session.commit()
    session.refresh(message)
    return message


def list_messages(session: Session, conversation_id: uuid.UUID) -> list[Message]:
    return list(
        session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
    )


def list_conversations(
    session: Session, tenant_id: uuid.UUID, *, limit: int = 30
) -> list[Conversation]:
    """Gesprekken van dit bedrijf, laatst gebruikt eerst."""
    query = (
        select(Conversation)
        .where(Conversation.tenant_id == tenant_id)
        .order_by(Conversation.updated_at.desc(), Conversation.created_at.desc())
        .limit(limit)
    )
    return list(session.scalars(query))


def first_user_messages(
    session: Session, conversation_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """Het eerste bericht van de gebruiker per gesprek, als titel voor de lijst.

    Eén query voor de hele lijst; anders kost een zijbalk met 30 gesprekken er 30.
    """
    if not conversation_ids:
        return {}
    eerste = (
        select(
            Message.conversation_id,
            func.min(Message.created_at).label("eerste"),
        )
        .where(Message.conversation_id.in_(conversation_ids), Message.role == "user")
        .group_by(Message.conversation_id)
        .subquery()
    )
    query = select(Message.conversation_id, Message.content).join(
        eerste,
        (Message.conversation_id == eerste.c.conversation_id)
        & (Message.created_at == eerste.c.eerste),
    )
    return {row[0]: row[1] for row in session.execute(query)}
