"""Routes voor chat-gesprekken die de nieuwsbrief-agent aansturen."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.deps import get_anthropic_client, get_cipher, get_session
from app.repositories import conversations as repo
from app.repositories import tenants as tenants_repo
from app.schemas import ConversationReply, ConversationStart, MessageSend
from app.services.conversation import run_conversation_turn
from app.services.crypto import SecretCipher

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("", response_model=ConversationReply, status_code=status.HTTP_201_CREATED)
def start_conversation(
    body: ConversationStart,
    session: Session = Depends(get_session),
    cipher: SecretCipher = Depends(get_cipher),
    client=Depends(get_anthropic_client),
) -> ConversationReply:
    if tenants_repo.get_tenant(session, body.tenant_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="tenant niet gevonden")
    conversation = repo.create_conversation(
        session, tenant_id=body.tenant_id, channel=body.channel
    )
    turn = run_conversation_turn(
        session=session, client=client, cipher=cipher, conversation=conversation, user_text=body.message
    )
    return ConversationReply(
        conversation_id=conversation.id, reply=turn.reply, stop_reason=turn.stop_reason
    )


@router.post("/{conversation_id}/messages", response_model=ConversationReply)
def continue_conversation(
    conversation_id: uuid.UUID,
    body: MessageSend,
    session: Session = Depends(get_session),
    cipher: SecretCipher = Depends(get_cipher),
    client=Depends(get_anthropic_client),
) -> ConversationReply:
    conversation = repo.get_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="gesprek niet gevonden")
    turn = run_conversation_turn(
        session=session, client=client, cipher=cipher, conversation=conversation, user_text=body.message
    )
    return ConversationReply(
        conversation_id=conversation.id, reply=turn.reply, stop_reason=turn.stop_reason
    )
