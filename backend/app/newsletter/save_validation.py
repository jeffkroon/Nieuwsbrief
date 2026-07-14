"""Opslag-garantie voor templates: een template mag de database alleen in als hij
een sentinel-render foutloos doorstaat.

Waar `validate_template_html` bewust laks is (een admin mag bijna elke layout
opslaan), is dit de harde poort bij het daadwerkelijk opslaan. Doel: de
kopieer-verminking (afgekapte of losse `{{`/`}}`) en half-getokeniseerde templates
tegenhouden, zonder geldige templates ten onrechte te weigeren. Garantie in code,
niet in een prompt: hergebruikt de bestaande `validate_template_html` en
`verify_toolproof` (sentinel-render) i.p.v. eigen regels te verzinnen.
"""

from __future__ import annotations

import re

from app.newsletter.template_validation import validate_template_html
from app.newsletter.toolproof import (
    _SENTINEL_BRAND,
    _SENTINEL_CONTENT,
    verify_toolproof,
)
from app.newsletter.renderer import render_newsletter

# Een goedgevormd token: {{...}} zonder haakjes ertussen. `[^{}]*` zorgt dat we
# niet per ongeluk over een afgekapt token of CSS-haakjes heen matchen.
_WELLFORMED_TOKEN = re.compile(r"\{\{[^{}]*?\}\}")
# <style>-blokken bevatten geneste CSS-haakjes (media queries eindigen op `}}`);
# die tellen we niet mee voor de token-integriteit.
_STYLE_BLOCK = re.compile(r"<style\b[^>]*>.*?</style>", re.DOTALL | re.IGNORECASE)


def _brace_integrity_errors(html: str) -> list[str]:
    """Meld verminkte/afgekapte tokens: losse `{{` of `}}` die geen net token vormen."""
    scrubbed = _STYLE_BLOCK.sub("", html or "")
    open_count = scrubbed.count("{{")
    close_count = scrubbed.count("}}")
    wellformed = _WELLFORMED_TOKEN.findall(scrubbed)
    if open_count != close_count or open_count != len(wellformed):
        return [
            "de template bevat een losse of afgekapte `{{`/`}}`; waarschijnlijk is er "
            "iets misgegaan bij het kopiëren (er ontbreekt een stukje). Plak de "
            "template opnieuw of maak hem opnieuw tool-proof en sla dan pas op."
        ]
    return []


def validate_template_for_save(
    html: str, styles: dict | None = None
) -> tuple[list[str], list[str]]:
    """Geef (errors, warnings) terug. Lege errors-lijst = mag opgeslagen worden.

    Bouwt op `validate_template_html` (bestaande harde errors + waarschuwingen) en
    voegt de harde opslag-poort toe: brace-integriteit, een sentinel-render die
    niet mag crashen, en de tool-proof sentinel-verificatie (`verify_toolproof`).
    """
    errors, warnings = validate_template_html(html)

    errors.extend(_brace_integrity_errors(html))

    # De sentinel-render mag niet crashen (kapotte structuur/placeholder).
    try:
        render_newsletter(html or "", _SENTINEL_BRAND, _SENTINEL_CONTENT)
    except Exception as exc:  # noqa: BLE001 - alle renderfouten zijn opslag-blokkerend
        errors.append(
            "de template kon niet worden gerenderd met testinhoud "
            f"({type(exc).__name__}); hij bevat waarschijnlijk kapotte HTML of een "
            "onbekende placeholder."
        )
        return errors, warnings

    # Tool-proof sentinel-verificatie: elke aanwezige placeholder/marker moet
    # daadwerkelijk doorstromen en de blok-structuur moet kloppen.
    _, tp_failed = verify_toolproof(html or "")
    errors.extend(tp_failed)

    return errors, warnings
