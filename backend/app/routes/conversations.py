"""Routes voor chat-gesprekken die de nieuwsbrief-agent aansturen."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import uuid

import anthropic
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.deps import (
    SessionInfo,
    current_session_info,
    get_anthropic_client,
    get_cipher,
    get_session,
)
from app.ratelimit import SlidingWindowRateLimiter, client_ip
from app.repositories import conversations as repo
from app.repositories import tenants as tenants_repo
from app.schemas import (
    ConversationDetail,
    ConversationMessage,
    ConversationReply,
    ConversationStart,
    ConversationSummary,
    MessageSend,
)
from app.newsletter.orchestrator import TurnCancelled
from app.services.conversation import TurnReply, run_conversation_turn
from app.services.crypto import SecretCipher

router = APIRouter(prefix="/conversations", tags=["conversations"])

# Max 10 chat-beurten per minuut per IP (een beurt is duur: meerdere LLM-calls + Brevo).
_chat_limiter = SlidingWindowRateLimiter(max_hits=10, window_seconds=60)


def chat_rate_limit(request: Request) -> None:
    if not _chat_limiter.allow(client_ip(request)):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Te veel berichten in korte tijd. Wacht even en probeer opnieuw.",
        )


def foutmelding(exc: Exception) -> str:
    """Bekende fouten vertalen naar iets waar een gebruiker mee verder kan.

    Gedeeld door de gewone en de streamende route, zodat beide dezelfde taal
    spreken; de een maakt er een HTTP-fout van, de ander een stream-event.
    """
    if isinstance(exc, anthropic.APIStatusError):
        text = str(getattr(exc, "message", "") or exc)
        if exc.status_code == 401:
            return ("De Anthropic API-key is ongeldig of ingetrokken. Zet een nieuwe key "
                    "in de omgevingsvariabele ANTHROPIC_API_KEY (Anthropic Console -> API keys).")
        if "credit balance" in text.lower():
            return ("De Anthropic-API heeft geen tegoed meer. Vul credits aan in de "
                    "Anthropic Console (Plans & Billing) en probeer opnieuw.")
        if exc.status_code == 429:
            return "De AI-dienst is even overbelast (rate limit). Probeer het zo opnieuw."
        return f"De AI-dienst gaf een fout: {text}"
    if isinstance(exc, anthropic.APIConnectionError):
        return "Kan de AI-dienst niet bereiken. Probeer het zo opnieuw."
    if isinstance(exc, RuntimeError):
        # Bv. de iteratielimiet van de agent-loop: geen kale 500 naar de gebruiker.
        return ("De assistent had te veel stappen nodig voor deze beurt en is gestopt. "
                "Stel de vraag iets kleiner of probeer het opnieuw.")
    return "Er ging iets mis bij het opstellen van de nieuwsbrief. Probeer het opnieuw."


def _run_turn(*, session, client, cipher, conversation, user_text, template_id=None) -> TurnReply:
    """Draai een gespreksbeurt en vertaal bekende fouten naar nette meldingen."""
    try:
        return run_conversation_turn(
            session=session, client=client, cipher=cipher, conversation=conversation,
            user_text=user_text, template_id=template_id,
        )
    except (anthropic.APIStatusError, anthropic.APIConnectionError, RuntimeError) as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail=foutmelding(exc)
        ) from exc




def _require_conversation_access(info: SessionInfo, tenant_id) -> None:
    """Klant-sessies mogen alleen gesprekken van hun eigen bedrijf voeren."""
    if info.role == "admin" or info.tenant_id is None or info.tenant_id == tenant_id:
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Geen toegang tot dit bedrijf.")


@router.post("", response_model=ConversationReply, status_code=status.HTTP_201_CREATED)
def start_conversation(
    body: ConversationStart,
    session: Session = Depends(get_session),
    cipher: SecretCipher = Depends(get_cipher),
    client=Depends(get_anthropic_client),
    _: None = Depends(chat_rate_limit),
    info: SessionInfo = Depends(current_session_info),
) -> ConversationReply:
    _require_conversation_access(info, body.tenant_id)
    if tenants_repo.get_tenant(session, body.tenant_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="tenant niet gevonden")
    conversation = repo.create_conversation(
        session, tenant_id=body.tenant_id, channel=body.channel
    )
    turn = _run_turn(
        session=session, client=client, cipher=cipher, conversation=conversation,
        user_text=body.message, template_id=body.template_id,
    )
    return ConversationReply(
        conversation_id=conversation.id, reply=turn.reply, stop_reason=turn.stop_reason,
        preview_html=turn.preview_html,
    )


@router.post("/{conversation_id}/messages", response_model=ConversationReply)
def continue_conversation(
    conversation_id: uuid.UUID,
    body: MessageSend,
    session: Session = Depends(get_session),
    cipher: SecretCipher = Depends(get_cipher),
    client=Depends(get_anthropic_client),
    _: None = Depends(chat_rate_limit),
    info: SessionInfo = Depends(current_session_info),
) -> ConversationReply:
    conversation = repo.get_conversation(session, conversation_id)
    if conversation is not None:
        _require_conversation_access(info, conversation.tenant_id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="gesprek niet gevonden")
    turn = _run_turn(
        session=session, client=client, cipher=cipher, conversation=conversation,
        user_text=body.message, template_id=body.template_id,
    )
    return ConversationReply(
        conversation_id=conversation.id, reply=turn.reply, stop_reason=turn.stop_reason,
        preview_html=turn.preview_html,
    )


# --- Gesprekken teruglezen -------------------------------------------------
@router.get("", response_model=list[ConversationSummary])
def list_conversations(
    tenant_id: uuid.UUID,
    session: Session = Depends(get_session),
    info: SessionInfo = Depends(current_session_info),
) -> list[ConversationSummary]:
    """Recente gesprekken van dit bedrijf, laatst gebruikt eerst."""
    _require_conversation_access(info, tenant_id)
    gesprekken = repo.list_conversations(session, tenant_id)
    titels = repo.first_user_messages(session, [g.id for g in gesprekken])
    return [
        ConversationSummary(
            id=g.id,
            title=_titel(titels.get(g.id)),
            channel=g.channel,
            status=g.status,
            template_id=g.template_id,
            created_at=g.created_at,
            updated_at=g.updated_at,
        )
        for g in gesprekken
    ]


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: uuid.UUID,
    session: Session = Depends(get_session),
    info: SessionInfo = Depends(current_session_info),
) -> ConversationDetail:
    """Een gesprek hervatten: alle berichten plus het laatst getoonde voorbeeld."""
    conversation = repo.get_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="gesprek niet gevonden")
    _require_conversation_access(info, conversation.tenant_id)
    berichten = [
        ConversationMessage(role=m.role, content=m.content, created_at=m.created_at)
        for m in repo.list_messages(session, conversation_id)
        if m.role in ("user", "assistant") and m.content
    ]
    return ConversationDetail(
        id=conversation.id,
        tenant_id=conversation.tenant_id,
        template_id=conversation.template_id,
        messages=berichten,
        preview_html=_hervat_preview(session, conversation),
    )


def _titel(eerste_bericht: str | None, grens: int = 70) -> str:
    tekst = " ".join((eerste_bericht or "").split()) or "Nieuw gesprek"
    return tekst if len(tekst) <= grens else tekst[: grens - 1] + "..."


def _hervat_preview(session: Session, conversation) -> str | None:
    """Het laatste voorbeeld opnieuw renderen uit de bewaarde invoer.

    Zonder netwerk en zonder validatie: dit toont wat de gebruiker al had gezien.
    Een nieuw voorbeeld of concept loopt altijd weer via de tools, met alle checks.
    """
    if not conversation.last_preview:
        return None
    from app.newsletter.preview_content import content_from_draft_input
    from app.newsletter.renderer import render_newsletter
    from app.newsletter.templates import load_template
    from app.newsletter.tools import DEFAULT_TEMPLATE
    from app.repositories import templates as templates_repo

    tenant = tenants_repo.get_tenant(session, conversation.tenant_id)
    if tenant is None:
        return None
    template = None
    if conversation.template_id is not None:
        template = templates_repo.get_template(session, conversation.template_id)
    template = template or templates_repo.get_default_template(session, conversation.tenant_id)
    html = template.html if template is not None else load_template(
        (tenant.config or {}).get("template") or DEFAULT_TEMPLATE
    )
    brand = {**(tenant.config or {}), "styles": (template.styles if template else {}) or {}}
    try:
        return render_newsletter(html, brand, content_from_draft_input(conversation.last_preview))
    except (ValueError, KeyError):
        # Een oud voorbeeld dat niet meer past op de huidige template: geen preview,
        # maar het gesprek moet gewoon te hervatten zijn.
        return None


# --- Streamende beurt ------------------------------------------------------
@router.post("/stream")
async def stream_turn(
    body: ConversationStart,
    request: Request,
    session: Session = Depends(get_session),
    cipher: SecretCipher = Depends(get_cipher),
    client=Depends(get_anthropic_client),
    _: None = Depends(chat_rate_limit),
    info: SessionInfo = Depends(current_session_info),
) -> StreamingResponse:
    """Zelfde beurt als POST /conversations, maar met tussenstanden onderweg.

    Een beurt duurt soms een minuut (pagina's ophalen, prijzen controleren). De
    stap-events laten zien waar de assistent mee bezig is; verbreekt de gebruiker
    de verbinding, dan stopt de beurt bij de eerstvolgende stap in plaats van nog
    dure rondes te draaien.
    """
    conversation = _kies_gesprek(session, body, info)
    afbreken = threading.Event()
    events: queue.Queue = queue.Queue()

    def _werk() -> None:
        try:
            turn = run_conversation_turn(
                session=session,
                client=client,
                cipher=cipher,
                conversation=conversation,
                user_text=body.message,
                template_id=body.template_id,
                on_step=lambda tekst: events.put({"type": "step", "text": tekst}),
                should_stop=afbreken.is_set,
            )
            events.put(
                {
                    "type": "done",
                    "conversation_id": str(conversation.id),
                    "reply": turn.reply,
                    "stop_reason": turn.stop_reason,
                    "preview_html": turn.preview_html,
                }
            )
        except TurnCancelled:
            events.put({"type": "cancelled"})
        except Exception as exc:  # noqa: BLE001 - alles wordt een nette melding
            events.put({"type": "error", "detail": foutmelding(exc)})
        finally:
            events.put(None)

    worker = threading.Thread(target=_werk, daemon=True, name="chat-beurt")
    worker.start()

    async def _stroom():
        lus = asyncio.get_running_loop()
        # Het gesprek-id meteen sturen: de frontend kan het bewaren, ook als de
        # beurt daarna misgaat of wordt afgebroken.
        yield _sse({"type": "start", "conversation_id": str(conversation.id)})
        try:
            while True:
                item = await lus.run_in_executor(None, events.get)
                if item is None:
                    break
                yield _sse(item)
        finally:
            afbreken.set()

    return StreamingResponse(
        _stroom(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _kies_gesprek(session: Session, body: ConversationStart, info: SessionInfo):
    """Bestaand gesprek hervatten of een nieuw gesprek beginnen."""
    if body.conversation_id is not None:
        conversation = repo.get_conversation(session, body.conversation_id)
        if conversation is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="gesprek niet gevonden")
        _require_conversation_access(info, conversation.tenant_id)
        return conversation
    _require_conversation_access(info, body.tenant_id)
    if tenants_repo.get_tenant(session, body.tenant_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="tenant niet gevonden")
    return repo.create_conversation(session, tenant_id=body.tenant_id, channel=body.channel)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


