"""De huidige stand van de nieuwsbrief meegeven aan de volgende chat-beurt.

Per beurt spelen we alleen de TEKST van eerdere berichten terug naar Claude, niet
de tool-aanroepen. Zonder dit wist de assistent bij "maak de teksten minder
stijf" dus niet welke intro's, producten en banner er in het voorbeeld stonden:
hij begon opnieuw met ophalen en vroeg weer naar banners.

De stand (conversation.last_preview, dezelfde velden als preview_newsletter)
gaat mee als extra tekstblok bij het LAATSTE gebruikersbericht. Niet in de
system-prompt (die blijft gecachet) en niet opgeslagen in de berichten: er staat
dus nooit een oude stand in de geschiedenis die met de huidige verward kan worden.
Vorige teksten (om iets terug te zetten) staan in hetzelfde blok, apart gelabeld.

Prompt-cache over beurten heen: het tekstblok van het laatste gebruikersbericht
krijgt een cache-markering, het stand-blok komt erachter. De cache loopt dan tot
en met de tekst van het bericht, zonder stand. Een beurt later komt dat bericht
terug als precies hetzelfde tekstblok (zonder stand), dus die prefix wordt uit de
cache gelezen. De markering zelf telt niet mee in de prefix: een markering die
verschuift breekt de cache niet. Daarom speelt elk gebruikersbericht altijd terug
als lijst met één tekstblok, en is alleen het laatste gemarkeerd (samen met
system en de markering van de orchestrator op het laatste blok: maximaal 3 van
de 4 toegestane markeringen).
"""

from __future__ import annotations

import json

from app.newsletter.earlier_values import EARLIER_KEY, earlier_of
from app.newsletter.orchestrator import CACHE_CONTROL

STATE_INTRO = (
    "[Systeem, niet door de gebruiker getypt] HUIDIGE STAND van de nieuwsbrief in dit "
    "gesprek (de velden van het laatste voorbeeld). Dit is wat de gebruiker nu rechts "
    "ziet. Vraagt de gebruiker om een aanpassing, verander dan ALLEEN wat gevraagd is en "
    "roep preview_newsletter aan met alleen de gewijzigde velden: al het andere "
    "(producten, banner, knoppen, stijl) neemt het systeem automatisch over. Haal niets "
    "opnieuw op dat hier al staat (geen find_*, list_images of find_banner) en begin niet "
    "opnieuw aan onderdelen waar de gebruiker niet naar vroeg."
)

EARLIER_LABEL = (
    "EERDER GEBRUIKT (niet meer actief; alleen gebruiken als de gebruiker vraagt iets "
    "terug te zetten). Per veld de vorige waarden, nieuwste eerst:"
)

# Nooit in het stand-blok: toestemming mag niet meeliften, en de vorige waarden
# krijgen hun eigen, apart gelabelde onderdeel.
_HIDDEN = frozenset({"confirmed", EARLIER_KEY})


def _dumps(value: dict) -> str:
    """Deterministisch en compact: dezelfde stand geeft altijd dezelfde bytes."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def state_note(last_preview: dict | None) -> str | None:
    """Tekstblok met de huidige stand, of None als er nog geen voorbeeld is."""
    if not last_preview:
        return None
    stand = {k: v for k, v in last_preview.items() if k not in _HIDDEN}
    note = f"{STATE_INTRO}\n\n{_dumps(stand)}"
    earlier = earlier_of(last_preview)
    return f"{note}\n\n{EARLIER_LABEL}\n{_dumps(earlier)}" if earlier else note


def replay_message(role: str, content: str) -> dict:
    """Een opgeslagen bericht in de vorm waarin het altijd wordt teruggespeeld.

    Gebruikersberichten als lijst met één tekstblok: precies de vorm die het
    bericht had toen het het laatste was (min markering en stand-blok).
    """
    if role != "user":
        return {"role": role, "content": content}
    return {"role": role, "content": [{"type": "text", "text": content}]}


def with_current_state(messages: list[dict], last_preview: dict | None) -> list[dict]:
    """Nieuwe lijst waarin het laatste gebruikersbericht markering en stand krijgt.

    Muteert niets. Het laatste tekstblok van het bericht krijgt de cache-markering;
    de stand (als er een voorbeeld is) komt er als apart blok achter. Is het
    laatste bericht niet van de gebruiker, dan komt de lijst ongewijzigd terug.
    """
    if not messages or messages[-1].get("role") != "user":
        return messages
    last = messages[-1]
    content = last["content"]
    blocks = (
        [{"type": "text", "text": content}] if isinstance(content, str) else list(content)
    )
    if not blocks:
        return messages
    marked = [*blocks[:-1], {**blocks[-1], "cache_control": CACHE_CONTROL}]
    note = state_note(last_preview)
    extra = [{"type": "text", "text": note}] if note else []
    return [*messages[:-1], {**last, "content": [*marked, *extra]}]
