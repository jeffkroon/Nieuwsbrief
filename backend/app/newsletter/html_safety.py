"""Veilig invullen van tekst en links in de gerenderde mail.

Teksten van het model en gescrapete productnamen ("Tom & Jerry", of erger
`<img onerror=...>`) mogen nooit rauw in de HTML belanden. Garantie in code:
tekst wordt geëscapet en een link of foto komt er alleen in met een veilig schema.

Bewust NIET geëscapet: de apostrof (`'`). Die is in tekst en in attributen met
dubbele quotes onschuldig, en escapen zou veel output zonder reden veranderen.

`Invuller` bundelt de drie invul-functies, zodat de renderer per aanroep kan
kiezen: VEILIG voor elke echte mail, RUW voor de tool-proof-paden, die terugvullen
met ORIGINELE HTML-fragmenten en byte-identiek moeten blijven.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

# Volgorde telt: & eerst, anders escapen we onze eigen entities nog een keer.
_ESCAPES = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ('"', "&quot;"))

LINK_SCHEMES = ("http://", "https://", "mailto:", "tel:")
IMAGE_SCHEMES = ("http://", "https://")

# Wat er op de plek van een onveilige link of foto komt.
_UNSAFE_LINK = "#"
_UNSAFE_IMAGE = ""


def escape_text(value: str | None) -> str:
    """Escape &, <, > en " (niet '): veilig in tekst én in attributen."""
    text = value or ""
    for teken, entity in _ESCAPES:
        text = text.replace(teken, entity)
    return text


def has_scheme(value: str | None, schemes: tuple[str, ...]) -> bool:
    """Begint de URL (zonder voorloop-witruimte, hoofdletterongevoelig) met een van de schema's?"""
    return (value or "").strip().lower().startswith(schemes)


def _safe_url(value: str | None, schemes: tuple[str, ...], unsafe: str) -> str:
    if not value:
        return ""
    return escape_text(value) if has_scheme(value, schemes) else unsafe


def safe_href(value: str | None) -> str:
    """Link voor een href: http(s), mailto of tel; anders '#'. Leeg blijft leeg.

    Een kale "www.x.nl" (zo opgeslagen in het bedrijfsformulier) krijgt https://
    ervoor: anders zou een werkende website-link ineens '#' worden.
    """
    kaal = (value or "").strip()
    if kaal.lower().startswith("www."):
        value = f"https://{kaal}"
    return _safe_url(value, LINK_SCHEMES, _UNSAFE_LINK)


def safe_src(value: str | None) -> str:
    """Foto-URL voor een src: alleen http(s); anders leeg."""
    return _safe_url(value, IMAGE_SCHEMES, _UNSAFE_IMAGE)


def _raw(value: str | None) -> str:
    return value or ""


@dataclass(frozen=True)
class Invuller:
    """Hoe een waarde in de template komt: als tekst, als link of als foto-URL."""

    text: Callable[[str | None], str]
    href: Callable[[str | None], str]
    src: Callable[[str | None], str]


VEILIG = Invuller(text=escape_text, href=safe_href, src=safe_src)
RUW = Invuller(text=_raw, href=_raw, src=_raw)


def invuller(escape: bool) -> Invuller:
    return VEILIG if escape else RUW
