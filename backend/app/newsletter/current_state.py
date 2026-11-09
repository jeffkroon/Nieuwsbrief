"""De stand van de nieuwsbrief meegeven aan de chat-beurten.

Per beurt spelen we alleen de TEKST van eerdere berichten terug naar Claude, niet
de tool-aanroepen. Zonder stand wist de assistent bij "maak de teksten minder
stijf" dus niet welke intro's, producten en banner er in het voorbeeld stonden:
hij begon opnieuw met ophalen en vroeg weer naar banners.

De stand (conversation.last_preview, dezelfde velden als preview_newsletter)
gaat mee als extra tekstblok bij het gebruikersbericht, niet in de system-prompt
(die blijft gecachet). De notitie wordt bij dat bericht opgeslagen (in
metadata) en bij elke volgende beurt precies zo teruggespeeld. Zo blijven
eerdere beurten byte-identiek en leest de volgende beurt ze uit de prompt-cache;
een notitie die alleen aan het laatste bericht hing, verdween een beurt later
en brak daarmee de cache voor de hele geschiedenis.

Oude notities beschrijven dus een eerdere stand; de intro zegt dat de stand bij
het LAATSTE bericht leidend is. Is de stand sinds de vorige volledige notitie
niet veranderd, dan gaat er alleen een korte verwijzing mee.
"""

from __future__ import annotations

import json

# Sleutel in mail.messages.metadata waaronder de meegestuurde notitie staat.
STATE_NOTE_KEY = "state_note"

STATE_INTRO = (
    "[Systeem, niet door de gebruiker getypt] STAND van de nieuwsbrief op het moment "
    "van dit bericht (de velden van het laatste voorbeeld). Bij eerdere berichten is "
    "dit een oude stand: de stand bij het LAATSTE gebruikersbericht is leidend, dat is "
    "wat de gebruiker nu rechts ziet. Vraagt de gebruiker om een aanpassing, verander "
    "dan ALLEEN wat gevraagd is en roep preview_newsletter aan met alleen de gewijzigde "
    "velden: al het andere (producten, banner, knoppen, stijl) neemt het systeem "
    "automatisch over. Haal niets opnieuw op dat hier al staat (geen find_*, "
    "list_images of find_banner) en begin niet opnieuw aan onderdelen waar de "
    "gebruiker niet naar vroeg."
)

UNCHANGED_NOTE = (
    "[Systeem, niet door de gebruiker getypt] STAND van de nieuwsbrief op het moment "
    "van dit bericht: ongewijzigd, gelijk aan de laatst volledig meegegeven stand "
    "hierboven. Die is nu leidend. Verander alleen wat de gebruiker vraagt."
)


def state_note(last_preview: dict | None) -> str | None:
    """Tekstblok met de stand, of None als er nog geen voorbeeld is.

    Deterministisch (gesorteerde sleutels, vaste scheidingstekens): dezelfde stand
    geeft altijd dezelfde bytes. Compact, want elke notitie blijft in de context.
    """
    if not last_preview:
        return None
    stand = {k: v for k, v in last_preview.items() if k != "confirmed"}
    body = json.dumps(stand, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{STATE_INTRO}\n\n{body}"


def note_for_turn(last_preview: dict | None, earlier_notes: list[str | None]) -> str | None:
    """De notitie voor het nieuwe gebruikersbericht.

    `earlier_notes` zijn de opgeslagen notities van de eerdere berichten, in
    volgorde. Is de stand gelijk aan de laatste volledige notitie, dan volstaat
    een korte verwijzing in plaats van dezelfde stand nog een keer.
    """
    note = state_note(last_preview)
    if note is None:
        return None
    previous_full = next(
        (n for n in reversed(earlier_notes) if n is not None and n != UNCHANGED_NOTE),
        None,
    )
    return UNCHANGED_NOTE if note == previous_full else note


def state_metadata(note: str | None) -> dict:
    """Metadata om bij het gebruikersbericht op te slaan (leeg zonder notitie)."""
    return {STATE_NOTE_KEY: note} if note else {}


def stored_note(metadata: dict | None) -> str | None:
    """De opgeslagen notitie van een bericht; None voor oude berichten zonder."""
    note = (metadata or {}).get(STATE_NOTE_KEY)
    return note if isinstance(note, str) and note else None


def with_state_note(message: dict, note: str | None) -> dict:
    """Nieuw bericht waarin een gebruikersbericht de notitie als extra blok krijgt.

    Muteert niets. Zonder notitie, of bij een bericht van de assistent, komt het
    bericht ongewijzigd terug.
    """
    if note is None or message.get("role") != "user":
        return message
    content = message["content"]
    blocks = (
        [{"type": "text", "text": content}] if isinstance(content, str) else list(content)
    )
    return {**message, "content": [*blocks, {"type": "text", "text": note}]}
