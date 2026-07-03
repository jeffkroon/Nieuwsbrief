"""Validatie van een (door een admin) aangeleverde template-HTML.

Een admin mag elke layout opslaan: niets blokkeert. Ontbrekende placeholders
leveren alleen een waarschuwing op, zodat een afwijkende layout (bv. een algemene
nieuwsbrief of een kaart-/review-layout zonder wedstrijdblokken) gewoon kan.
"""

from __future__ import annotations

from app.newsletter.renderer import BANNER_MARKER, CARD_MARKER

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
    "{{STYLE_BUTTON_BG}}": "knopkleur uit de stijl-builder (anders is de knopkleur niet instelbaar)",
}


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
    # Afmeldlink: een van beide ESP-tags volstaat (wettelijk verplicht voor e-mail).
    if not any(tag in text for tag in UNSUBSCRIBE_TAGS):
        warnings.append(
            "aanbevolen ontbreekt: een afmeldlink, {{ unsubscribe }} (Brevo) of "
            "{% unsubscribe %} (Klaviyo)"
        )
    # Een blok-marker (banners OF kaarten) is nodig om wedstrijden/clubs te tonen.
    if BANNER_MARKER not in text and CARD_MARKER not in text:
        warnings.append(
            f"geen blok-marker: zonder {BANNER_MARKER} of {CARD_MARKER} komen er geen "
            "wedstrijd-/clubblokken in de mail (prima voor een puur algemene nieuwsbrief)"
        )
    return errors, warnings
