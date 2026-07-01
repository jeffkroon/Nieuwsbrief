"""Verbindt een gesprek met de Claude-orchestratie.

Bewaart de gebruikersbeurt, herbouwt de gespreksgeschiedenis als Claude-berichten,
draait één agent-beurt met de tools van deze tenant, en bewaart het antwoord.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import Conversation, Tenant
from app.newsletter.orchestrator import run_agent_turn
from app.newsletter.prompts import build_system_prompt
from app.newsletter.tools import TOOL_DEFINITIONS, ToolContext, execute_tool
from app.repositories import conversations as repo
from app.services.crypto import SecretCipher
from app.services.tone import ensure_tone

# Alleen deze rollen worden teruggespeeld naar Claude als geschiedenis.
_REPLAYABLE_ROLES = {"user", "assistant"}


@dataclass(frozen=True)
class TurnReply:
    reply: str
    stop_reason: str
    preview_html: str | None = None  # voorbeeld-HTML als de assistent preview_newsletter draaide


def run_conversation_turn(
    *,
    session: Session,
    client,
    cipher: SecretCipher,
    conversation: Conversation,
    user_text: str,
    template_id: uuid.UUID | None = None,
) -> TurnReply:
    repo.add_message(session, conversation.id, "user", user_text)

    history = repo.list_messages(session, conversation.id)
    claude_messages = [
        {"role": m.role, "content": m.content}
        for m in history
        if m.role in _REPLAYABLE_ROLES and m.content
    ]

    ctx = ToolContext(
        session=session,
        tenant_id=conversation.tenant_id,
        cipher=cipher,
        llm=client,
        conversation_id=conversation.id,
        template_id=template_id,
    )

    # Tone of voice van het bedrijf gegarandeerd meegeven (eenmalig geanalyseerd + gecacht),
    # zodat de assistent altijd in de huisstijl schrijft, los van of hij de tool aanroept.
    tenant = session.get(Tenant, conversation.tenant_id)
    tone = ensure_tone(session, tenant, client) if tenant else None

    result = run_agent_turn(
        client,
        system=build_system_prompt(tone),
        messages=claude_messages,
        tools=TOOL_DEFINITIONS,
        dispatch=lambda name, tool_input: execute_tool(name, tool_input, ctx),
    )

    repo.add_message(session, conversation.id, "assistant", result.final_text)
    preview_html = ctx.preview_holder[-1] if ctx.preview_holder else None
    return TurnReply(
        reply=result.final_text, stop_reason=result.stop_reason, preview_html=preview_html
    )
