"""Geheugen over eerdere nieuwsbrieven van dit bedrijf.

Zonder dit wist de assistent niet wat er vorige keer in stond: hij kon dezelfde
producten of wedstrijden opnieuw kiezen, en "zelfde opzet als vorige maand" werkte
niet. Alleen-lezen uit de eigen database; resultaten (open/klik) komen mee als die
al zijn opgehaald in de Nieuwsbrieven-tab.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from app.db.models import Newsletter
from app.newsletter.tool_context import ToolContext
from app.repositories import newsletters as newsletters_repo

DEFAULT_LIMIT = 5
MAX_LIMIT = 10
_STATUS_LABELS = {"ready": "concept", "approved": "concept", "sent": "verstuurd"}

SCHEMA = {
    "name": "get_recent_newsletters",
    "description": "De laatste nieuwsbrieven die voor dit bedrijf zijn gemaakt (uit eerdere "
    "gesprekken): datum, onderwerp, thema, kop, intro, welke producten/wedstrijden/clubs erin "
    "stonden en, als bekend, de open- en klikcijfers. Roep dit EENMAAL aan bij het begin van "
    "een nieuwe nieuwsbrief, zodat je niet dezelfde producten of invalshoek herhaalt, en als "
    "de gebruiker verwijst naar een eerdere nieuwsbrief ('zelfde opzet als vorige keer'). "
    "Links en prijzen hieruit zijn NIET actueel: haal ze opnieuw op met find_* voordat je "
    "ze gebruikt.",
    "input_schema": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": f"Aantal (standaard {DEFAULT_LIMIT}, max {MAX_LIMIT})"},
        },
    },
}


def _blocks(data: dict) -> list[str]:
    """Korte omschrijving per blok: wat stond erin, niet de volledige velden."""
    matches = [f"{m.get('home')} - {m.get('away')}" for m in data.get("matches") or []]
    clubs = [str(c.get("name")) for c in data.get("clubs") or []]
    items = [str(i.get("title")) for i in data.get("items") or []]
    return [b for b in (*matches, *clubs, *items) if b and b != "None"]


def _results(stats: dict | None) -> dict | None:
    if not stats:
        return None
    return {
        k: stats.get(k)
        for k in ("sent", "open_rate", "click_rate", "unsubscribes")
        if stats.get(k) is not None
    } or None


def _summary(newsletter: Newsletter) -> dict:
    data = newsletter.input or {}
    created = newsletter.created_at
    if created.tzinfo is None:
        datum = created.strftime("%d-%m-%Y")
    else:
        datum = created.astimezone(ZoneInfo("Europe/Amsterdam")).strftime("%d-%m-%Y")
    return {
        "datum": datum,
        "status": _STATUS_LABELS.get(newsletter.status, newsletter.status),
        "onderwerp": newsletter.subject,
        "preheader": data.get("preview_text"),
        "thema": newsletter.theme,
        "kop": data.get("header_title"),
        "intro": data.get("intro_1"),
        "blokken": _blocks(data),
        "resultaten": _results(newsletter.stats),
    }


def _tool_get_recent_newsletters(ctx: ToolContext, tool_input: dict) -> dict:
    try:
        limit = int(tool_input.get("limit") or DEFAULT_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    limit = max(1, min(limit, MAX_LIMIT))
    rows = newsletters_repo.list_recent(
        ctx.session, ctx.tenant_id, limit=limit, exclude_conversation=ctx.conversation_id
    )
    if not rows:
        return {"count": 0, "newsletters": [], "message": "Voor dit bedrijf is nog geen eerdere nieuwsbrief gemaakt."}
    return {
        "count": len(rows),
        "newsletters": [_summary(n) for n in rows],
        "message": "Nieuwste eerst. Gebruik dit om herhaling te vermijden of een eerdere opzet "
        "te volgen; kies producten en prijzen altijd opnieuw uit find_* (die zijn actueel). "
        "open_rate/click_rate zijn fracties (0.25 = 25%).",
    }


HANDLERS = {"get_recent_newsletters": _tool_get_recent_newsletters}
