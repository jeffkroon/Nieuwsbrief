"""Validatie van een (door een admin) aangeleverde template-HTML.

Een admin mag elke layout opslaan: niets blokkeert. Ontbrekende placeholders
leveren alleen een waarschuwing op, zodat een afwijkende layout (bv. een algemene
nieuwsbrief of een kaart-/review-layout zonder wedstrijdblokken) gewoon kan.
"""

from __future__ import annotations

from app.newsletter.card_block import CARD_TPL_END, CARD_TPL_START
from app.newsletter.renderer import BANNER_MARKER, CARD_MARKER, SECTIONS_MARKER

# Niets is hard verplicht; een admin bepaalt zelf de layout.
REQUIRED: dict[str, str] = {}

# Afmeldlink: Brevo gebruikt {{ unsubscribe }}, Klaviyo {% unsubscribe %}; een van
# beide volstaat (apart gecheckt in validate_template_html).
UNSUBSCRIBE_TAGS = ("{{ unsubscribe }}", "{% unsubscribe %}")

# Aanbevolen placeholders: ontbreken levert een waarschuwing op, geen blokkade.
RECOMMENDED: dict[str, str] = {
    "{{ contact.EMAIL }}": "e-mailadres van de ontvanger",
    "{{HEADER_TITEL}}": "titel over de headerfoto",
    "{{HEADER_IMAGE_URL}}": "headerfoto",
    "{{INTRO_1}}": "eerste introtekst",
    "{{HOOFD_CTA_URL}}": "link van de hoofdknop",
    "{{HOOFD_CTA_TEKST}}": "tekst van de hoofdknop",
    "{{LOGO_URL}}": "logo",
    "{{BRAND_NAME}}": "bedrijfsnaam in de footer",
    # Stijl-placeholders: zonder deze doet de kleuren-/lettertype-builder niets op die plekken.
    "{{STYLE_FONT}}": "lettertype uit de stijl-builder (anders is het lettertype niet instelbaar)",
    "{{STYLE_TEXT_COLOR}}": "tekstkleur uit de stijl-builder (anders is de tekstkleur niet instelbaar)",
}

# Knopkleur: één van de drie knop-tokens volstaat (kaart-knoppen worden in code
# gerenderd en gebruiken button_bg zonder token).
_BUTTON_TOKENS = ("{{STYLE_BUTTON_BG}}", "{{STYLE_CTA_BUTTON_BG}}", "{{STYLE_HERO_BUTTON_BG}}")


def validate_template_html(html: str) -> tuple[list[str], list[str]]:
    """Geef (errors, warnings) terug. Lege errors-lijst = mag opgeslagen worden."""
    text = html or ""
    errors = [
        f"verplicht ontbreekt: {marker} ({desc})"
        for marker, desc in REQUIRED.items()
        if marker not in text
    ]
    warnings = [
        f"aanbevolen ontbreekt: {marker} ({desc})"
        for marker, desc in RECOMMENDED.items()
        if marker not in text
    ]
    if not any(tok in text for tok in _BUTTON_TOKENS):
        warnings.append(
            "aanbevolen ontbreekt: een knopkleur-token ({{STYLE_BUTTON_BG}}, "
            "{{STYLE_CTA_BUTTON_BG}} of {{STYLE_HERO_BUTTON_BG}}); anders zijn de "
            "knopkleuren niet instelbaar"
        )
    # Banner met titel maar zonder knop: de bannerknop kan dan nooit renderen.
    if "{{HEADER_TITEL}}" in text and "{{HEADER_CTA}}" not in text:
        warnings.append(
            "aanbevolen ontbreekt: {{HEADER_CTA}} (de knop op de banner); zonder dit "
            "token heeft de banner nooit een knop"
        )
    # Afmeldlink: een van beide ESP-tags volstaat (wettelijk verplicht voor e-mail).
    if not any(tag in text for tag in UNSUBSCRIBE_TAGS):
        warnings.append(
            "aanbevolen ontbreekt: een afmeldlink, {{ unsubscribe }} (Brevo) of "
            "{% unsubscribe %} (Klaviyo)"
        )
    # Een blok-, kaart- of secties-marker is nodig om wedstrijden/clubs/producten te tonen.
    has_block_marker = any(
        m in text for m in (BANNER_MARKER, CARD_MARKER, SECTIONS_MARKER, CARD_TPL_START)
    )
    if not has_block_marker:
        warnings.append(
            f"geen blok-marker: zonder {BANNER_MARKER}, {CARD_MARKER}, {SECTIONS_MARKER} "
            f"of een eigen kaart-blok ({CARD_TPL_START}...{CARD_TPL_END}) komen er geen "
            "inhoudsblokken in de mail (prima voor een puur algemene nieuwsbrief)"
        )
    # Een kaart-blok zonder sluit-marker kan niet gerenderd worden.
    if CARD_TPL_START in text and CARD_TPL_END not in text:
        errors.append(f"kaart-blok niet afgesloten: {CARD_TPL_START} zonder {CARD_TPL_END}")
    return errors, warnings
