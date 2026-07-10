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
from app.newsletter.capabilities import template_capabilities
from app.newsletter.renderer import SECTIONS_MARKER
from app.newsletter.templates import load_template
from app.newsletter.tools import DEFAULT_TEMPLATE
from app.newsletter.tools import TOOL_DEFINITIONS, ToolContext, execute_tool
from app.repositories import conversations as repo
from app.repositories import templates as templates_repo
from app.services.crypto import SecretCipher
from app.services.llm_usage import TrackingLLM
from app.services.tone import ensure_tone

# Alleen deze rollen worden teruggespeeld naar Claude als geschiedenis.
_REPLAYABLE_ROLES = {"user", "assistant"}


def _template_info(
    session: Session, tenant_id: uuid.UUID, template_id: uuid.UUID | None
) -> dict:
    """Feiten over de actieve template voor de prompt (naam, secties, fallback).

    Zelfde keuzevolgorde als de renderer: gekozen template > standaard van het
    bedrijf > ingebouwde fallback.
    """
    template = None
    if template_id is not None:
        candidate = templates_repo.get_template(session, template_id)
        if candidate is not None and candidate.tenant_id == tenant_id:
            template = candidate
    if template is None:
        template = templates_repo.get_default_template(session, tenant_id)
    if template is None:
        # De ingebouwde fallback-layout: capaciteiten uit het echte bestand halen,
        # zodat de assistent er net zo eerlijk over is als over eigen templates.
        html = load_template(DEFAULT_TEMPLATE)
        return {
            "is_fallback": True,
            "has_sections": SECTIONS_MARKER in html,
            "has_header_title": "{{HEADER_TITEL}}" in html,
            "capabilities": template_capabilities(html),
        }
    html = template.html or ""
    return {
        "is_fallback": False,
        "name": template.name,
        "has_sections": SECTIONS_MARKER in html,
        "has_header_title": "{{HEADER_TITEL}}" in html,
        "capabilities": template_capabilities(html),
    }


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
    # Template-keuze onthouden: expliciet meegestuurd wint en wordt bewaard;
    # zonder keuze geldt de eerder gekozen template van dit gesprek.
    if template_id is not None and template_id != conversation.template_id:
        conversation.template_id = template_id
    template_id = template_id or conversation.template_id

    repo.add_message(session, conversation.id, "user", user_text)

    # Elke Claude-call van deze beurt (orchestrator én Haiku-extracties) wordt
    # geregistreerd in mail.llm_usage: meten wat een gesprek werkelijk kost.
    client = TrackingLLM(
        client, session, purpose="chat",
        tenant_id=conversation.tenant_id, conversation_id=conversation.id,
    )

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
    # De nieuwsbrief-soorten van het bedrijf bepalen het gespreksscript (stap 2).
    tenant = session.get(Tenant, conversation.tenant_id)
    tone = ensure_tone(session, tenant, client) if tenant else None
    content_types = (tenant.config or {}).get("content_types") if tenant else None
    template_info = _template_info(session, conversation.tenant_id, template_id)

    esp = (tenant.config or {}).get("esp") if tenant else None
    result = run_agent_turn(
        client,
        system=build_system_prompt(tone, content_types, template_info, esp=esp),
        messages=claude_messages,
        tools=TOOL_DEFINITIONS,
        dispatch=lambda name, tool_input: execute_tool(name, tool_input, ctx),
    )

    repo.add_message(session, conversation.id, "assistant", result.final_text)
    preview_html = ctx.preview_holder[-1] if ctx.preview_holder else None
    return TurnReply(
        reply=result.final_text, stop_reason=result.stop_reason, preview_html=preview_html
    )
