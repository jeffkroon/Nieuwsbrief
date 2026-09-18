"""Compact werkgeheugen per gesprek voor de dure data-ophaal-tools.

Zonder dit riep de assistent soms dezelfde pagina twee keer aan binnen een
gesprek (elke keer een pagina-fetch + een LLM-extractie): een gebruiker die
"yes doe deze" zei kreeg soms opnieuw "N producten opgehaald van ...".

Dit is UITSLUITEND een geheugen voor het KIEZEN uit resultaten (welke
producten/wedstrijden/links/foto's er zijn). Het omzeilt nooit de garantie dat
de UITEINDELIJKE keuze bij het concept live wordt gevalideerd: die validatie
loopt via een losse weg (_validated_items/_matches/_clubs + _require_reachable
in tools.py, met een eigen validatie-cache die bij create_newsletter_draft
wordt geleegd) en raadpleegt dit geheugen niet.

Bewaard op de Conversation-rij zelf (niet proces-lokaal zoals de
validatie-cache), dus het werkt ook met meerdere workers en overleeft een
herstart van de server.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Conversation

# Ruimer dan de 10 minuten van de (proces-lokale) validatie-cache: dit geheugen
# bedient alleen de keuze-fase, niet de uiteindelijke prijs-/bereikbaarheidscheck.
MEMORY_TTL_SECONDS = 20 * 60
# Voorkomt dat een lang gesprek het geheugen (en de conversation-rij) laat vollopen.
MAX_ENTRIES = 12


def memory_key(tool: str, params: dict[str, Any]) -> str:
    """Stabiele sleutel voor deze tool-aanroep; lege/None-velden tellen niet mee."""
    relevant = {k: v for k, v in sorted(params.items()) if v not in (None, "")}
    return tool + "|" + "|".join(f"{k}={v}" for k, v in relevant.items())


def _recall(conversation: Conversation, key: str) -> dict | None:
    entry = (conversation.tool_memory or {}).get(key)
    if entry is None or time.time() - entry.get("at", 0) > MEMORY_TTL_SECONDS:
        return None
    return entry.get("result")


def _remember(session: Session, conversation: Conversation, key: str, result: dict) -> None:
    memory = dict(conversation.tool_memory or {})
    memory[key] = {"at": time.time(), "result": result}
    if len(memory) > MAX_ENTRIES:
        oudste = sorted(memory, key=lambda k: memory[k]["at"])[: len(memory) - MAX_ENTRIES]
        for k in oudste:
            del memory[k]
    conversation.tool_memory = memory
    session.commit()


def with_memory(
    session: Session,
    conversation_id: uuid.UUID | None,
    tool: str,
    params: dict[str, Any],
    maker: Callable[[], dict],
) -> dict:
    """Voer `maker()` uit, of geef een nog vers onthouden resultaat terug.

    Zonder gesprek (conversation_id is None, zoals in losse API-aanroepen of
    tests) wordt gewoon altijd `maker()` gedraaid: er is dan niets om te
    onthouden. Faalt `maker()`, dan wordt er niets weggeschreven, zodat een
    mislukte poging nooit als "geldig resultaat" blijft hangen.
    """
    if conversation_id is None:
        return maker()
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        return maker()
    key = memory_key(tool, params)
    eerder = _recall(conversation, key)
    if eerder is not None:
        return {**eerder, "from_memory": True}
    result = maker()
    _remember(session, conversation, key, result)
    return result
