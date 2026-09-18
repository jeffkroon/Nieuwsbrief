"""Een volledig kleurenpalet afleiden uit de huisstijlkleur van een bedrijf.

Het stijlscherm had 21 losse kleurkiezers. Een klant denkt niet in "kaartrand" of
"badge-kleur"; die denkt: maak het onze huisstijl. Uit één merkkleur is de rest
prima af te leiden, met leesbare knopteksten en een rustiger tweede kleur voor
prijzen en labels.

Waarom niet de website scrapen? Dat is geprobeerd en het werkt niet betrouwbaar:
sites op Bootstrap (zoals voetbalreizenxl.nl) bevatten honderden kleuren uit het
framework, en de meest voorkomende is dan Bootstrap-blauw (#0d6efd), niet de
merkkleur. Een verkeerd voorstel is erger dan geen voorstel. De huisstijlkleur
staat al bij het bedrijf, is bij het aanmaken gecontroleerd door een mens, en is
dus de betrouwbare bron.

Puur rekenwerk, geen AI en geen netwerk. Het resultaat is een VOORSTEL: de
gebruiker ziet het voorbeeld en beslist zelf of hij het opslaat.
"""

from __future__ import annotations

import re

_HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
# Onder deze verhouding is tekst op een vlak niet prettig leesbaar (WCAG AA).
MIN_CONTRAST = 4.5


def normalize_hex(waarde: str | None) -> str | None:
    """#abc en #AABBCC naar de lange kleine-letter-vorm; None als het geen kleur is."""
    treffer = _HEX.match((waarde or "").strip())
    if not treffer:
        return None
    cijfers = treffer.group(1).lower()
    if len(cijfers) == 3:
        cijfers = "".join(teken * 2 for teken in cijfers)
    return f"#{cijfers}"


def _kanalen(hexwaarde: str) -> tuple[int, int, int]:
    h = hexwaarde.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def relative_luminance(hexwaarde: str) -> float:
    """Helderheid volgens WCAG, voor het kiezen van leesbare tekst op een kleur."""

    def _lineair(waarde: int) -> float:
        v = waarde / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (_lineair(k) for k in _kanalen(hexwaarde))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(voorgrond: str, achtergrond: str) -> float:
    """Contrast tussen twee kleuren (1 = gelijk, 21 = zwart op wit)."""
    a, b = relative_luminance(voorgrond), relative_luminance(achtergrond)
    licht, donker = max(a, b), min(a, b)
    return (licht + 0.05) / (donker + 0.05)


def leesbare_tekstkleur(achtergrond: str) -> str:
    """Wit of bijna-zwart, afhankelijk van wat leesbaar is op deze achtergrond."""
    return "#ffffff" if contrast_ratio("#ffffff", achtergrond) >= MIN_CONTRAST else "#111111"


def verdonker(hexwaarde: str, factor: float = 0.45) -> str:
    """Een donkerder tint van dezelfde kleur, voor prijzen en labels."""
    r, g, b = _kanalen(hexwaarde)
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(k * (1 - factor)))) for k in (r, g, b))


def palette_from_primary(primair: str, secundair: str | None = None) -> dict[str, str]:
    """Het hele palet uit één merkkleur; lege dict als de kleur ongeldig is."""
    hoofd = normalize_hex(primair)
    if hoofd is None:
        return {}
    tweede = normalize_hex(secundair) or verdonker(hoofd)
    knoptekst = leesbare_tekstkleur(hoofd)

    return {
        # Alles wat de aandacht moet trekken volgt de hoofdkleur.
        "button_bg": hoofd,
        "hero_button_bg": hoofd,
        "cta_button_bg": hoofd,
        "accent": hoofd,
        "block_border": hoofd,
        "home_color": hoofd,
        # Knopteksten worden berekend, niet gekozen: wit op geel leest niemand.
        "button_text": knoptekst,
        "hero_button_text": knoptekst,
        "cta_button_text": knoptekst,
        # De tweede kleur is rustiger, maar hoort bij het merk.
        "price_color": tweede,
        "badge_bg": tweede,
        "away_color": tweede,
        "link_color": tweede,
    }


def contrast_waarschuwingen(styles: dict) -> list[str]:
    """Combinaties die de lezer niet kan lezen; leeg als alles in orde is.

    We controleren alt-teksten in de mail al; dit is de tegenhanger voor kleur.
    """
    paren = (
        ("button_text", "button_bg", "de productknop"),
        ("hero_button_text", "hero_button_bg", "de knop op de banner"),
        ("cta_button_text", "cta_button_bg", "de onderste knop"),
        ("footer_text", "footer_bg", "de footer"),
        ("text_color", "page_bg", "de lopende tekst"),
    )
    meldingen = []
    for voorgrond_sleutel, achtergrond_sleutel, naam in paren:
        voorgrond = normalize_hex(styles.get(voorgrond_sleutel))
        achtergrond = normalize_hex(styles.get(achtergrond_sleutel))
        if not voorgrond or not achtergrond:
            continue
        verhouding = contrast_ratio(voorgrond, achtergrond)
        if verhouding < MIN_CONTRAST:
            meldingen.append(
                f"Te weinig contrast op {naam} ({verhouding:.1f}:1, minimaal "
                f"{MIN_CONTRAST}:1). Kies een lichtere of donkerdere tekstkleur."
            )
    return meldingen
