"""De huidige stand van de nieuwsbrief meegeven aan de volgende chat-beurt.

Per beurt spelen we alleen de TEKST van eerdere berichten terug naar Claude, niet
de tool-aanroepen. Zonder dit wist de assistent bij "maak de teksten minder
stijf" dus niet welke intro's, producten en banner er in het voorbeeld stonden:
hij begon opnieuw met ophalen en vroeg weer naar banners.

De stand (conversation.last_preview, dezelfde velden als preview_newsletter)
gaat mee als extra tekstblok bij het LAATSTE gebruikersbericht. Niet in de
system-prompt (die blijft gecachet) en niet opgeslagen in de berichten (dan zou
elke beurt een verouderde kopie in de geschiedenis achterlaten).
"""

from __future__ import annotations

import json

STATE_INTRO = (
    "[Systeem, niet door de gebruiker getypt] HUIDIGE STAND van de nieuwsbrief in dit "
    "gesprek (de velden van het laatste voorbeeld). Dit is wat de gebruiker nu rechts "
    "ziet. Vraagt de gebruiker om een aanpassing, verander dan ALLEEN wat gevraagd is en "
    "roep preview_newsletter aan met alleen de gewijzigde velden: al het andere "
    "(producten, banner, knoppen, stijl) neemt het systeem automatisch over. Haal niets "
    "opnieuw op dat hier al staat (geen find_*, list_images of find_banner) en begin niet "
    "opnieuw aan onderdelen waar de gebruiker niet naar vroeg."
)


def state_note(last_preview: dict | None) -> str | None:
    """Tekstblok met de huidige stand, of None als er nog geen voorbeeld is."""
    if not last_preview:
        return None
    stand = {k: v for k, v in last_preview.items() if k != "confirmed"}
    return f"{STATE_INTRO}\n\n{json.dumps(stand, ensure_ascii=False, indent=1)}"


def with_current_state(messages: list[dict], last_preview: dict | None) -> list[dict]:
    """Nieuwe lijst waarin het laatste gebruikersbericht de huidige stand meekrijgt.

    Muteert niets. Zonder voorbeeld, of als het laatste bericht niet van de
    gebruiker is, komt de lijst ongewijzigd terug.
    """
    note = state_note(last_preview)
    if note is None or not messages or messages[-1].get("role") != "user":
        return messages
    last = messages[-1]
    content = last["content"]
    blocks = (
        [{"type": "text", "text": content}] if isinstance(content, str) else list(content)
    )
    return [*messages[:-1], {**last, "content": [*blocks, {"type": "text", "text": note}]}]
