"""Validatie van een (door een admin) aangeleverde template-HTML.

Hard verplicht is alleen de banner-marker: zonder die marker verdwijnen de
wedstrijd-/clubblokken zonder waarschuwing. De rest is aanbevolen en levert een
waarschuwing op, geen blokkade, zodat een admin bewust een afwijkende layout kan
maken.
"""

from __future__ import annotations

from app.newsletter.renderer import BANNER_MARKER

# Zonder deze marker komen er geen wedstrijd-/clubblokken in de mail.
REQUIRED: dict[str, str] = {
    BANNER_MARKER: "plek voor de wedstrijd-/clubblokken",
}

# Aanbevolen placeholders: ontbreken levert een waarschuwing op.
RECOMMENDED: dict[str, str] = {
    "{{ unsubscribe }}": "afmeldlink (wettelijk verplicht voor e-mail)",
    "{{ contact.EMAIL }}": "e-mailadres van de ontvanger",
    "{{HEADER_TITEL}}": "titel over de headerfoto",
    "{{HEADER_IMAGE_URL}}": "headerfoto",
    "{{INTRO_1}}": "eerste introtekst",
    "{{HOOFD_CTA_URL}}": "link van de hoofdknop",
    "{{HOOFD_CTA_TEKST}}": "tekst van de hoofdknop",
    "{{LOGO_URL}}": "logo",
    "{{BRAND_NAME}}": "bedrijfsnaam in de footer",
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
    return errors, warnings
