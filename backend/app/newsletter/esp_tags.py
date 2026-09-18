"""Platform-tags in de gerenderde nieuwsbrief omzetten naar het juiste verzendplatform.

Elk platform heeft zijn eigen syntax voor de afmeldlink en het e-mailadres van de
ontvanger. Onze templates zijn in Brevo-syntax geschreven ({{ unsubscribe }}), dus
gingen die tags als letterlijke tekst mee naar Klaviyo en ActiveCampaign: een
kapotte afmeldlink bij de ontvanger, terwijl beide platforms een werkende
afmeldlink verplicht stellen.

Vandaar deze vertaling, vlak voor het aanmaken van het concept. Twee redenen om
het hier te doen en niet in de template:
- een bedrijf kan van platform wisselen zonder dat elke template opnieuw moet;
- de tool-proof-garantie (byte-gelijke round-trip van de TEMPLATE) blijft
  onaangeroerd: dit raakt alleen de gerenderde uitvoer van een losse nieuwsbrief.

Bronnen (gecontroleerd 18 september 2026): Brevo gebruikt {{ unsubscribe }},
Klaviyo {% unsubscribe %} en ActiveCampaign de personalisatie-tag
%UNSUBSCRIBELINK%; alle drie verplichten een afmeldlink in elke campagne.
"""

from __future__ import annotations

from dataclasses import dataclass

BREVO = "brevo"
KLAVIYO = "klaviyo"
ACTIVECAMPAIGN = "activecampaign"

# Per doelplatform: de tag die daar werkt, en alle schrijfwijzen die we herkennen
# als "dit is de afmeldlink" (inclusief de varianten van de andere platforms).
_UNSUBSCRIBE_TARGET = {
    BREVO: "{{ unsubscribe }}",
    KLAVIYO: "{% unsubscribe %}",
    ACTIVECAMPAIGN: "%UNSUBSCRIBELINK%",
}
_UNSUBSCRIBE_SOURCES = (
    "{{ unsubscribe }}",
    "{{unsubscribe}}",
    "{% unsubscribe %}",
    "{%unsubscribe%}",
    "%UNSUBSCRIBELINK%",
)

# Het e-mailadres van de ontvanger; zelfde verhaal, minder vaak gebruikt.
_EMAIL_TARGET = {
    BREVO: "{{ contact.EMAIL }}",
    KLAVIYO: "{{ person.email }}",
    ACTIVECAMPAIGN: "%EMAIL%",
}
_EMAIL_SOURCES = (
    "{{ contact.EMAIL }}",
    "{{contact.EMAIL}}",
    "{{ person.email }}",
    "{{person.email}}",
    "%EMAIL%",
)

# Boven deze grens knippen Gmail en Klaviyo de mail af ("Bericht is ingekort").
CLIPPING_BYTES = 102_400


@dataclass(frozen=True)
class LocalizedHtml:
    html: str
    notes: tuple[str, ...] = ()


def localize_esp_tags(html: str, esp: str) -> LocalizedHtml:
    """Zet de afmeldlink en e-mailtag om naar de syntax van `esp`.

    Onbekend platform of lege HTML: ongewijzigd terug. De melding vertelt wat er
    is aangepast, zodat het in het gespreksantwoord zichtbaar kan worden gemaakt.
    """
    if not html or esp not in _UNSUBSCRIBE_TARGET:
        return LocalizedHtml(html=html or "")

    resultaat = html
    notes: list[str] = []

    resultaat, vervangen = _swap(resultaat, _UNSUBSCRIBE_SOURCES, _UNSUBSCRIBE_TARGET[esp])
    if vervangen:
        notes.append(
            f"Afmeldlink omgezet naar de {esp}-tag {_UNSUBSCRIBE_TARGET[esp]} "
            f"({vervangen}x)."
        )
    elif _UNSUBSCRIBE_TARGET[esp] not in resultaat:
        notes.append(
            "Let op: in deze nieuwsbrief staat geen afmeldlink. Alle platforms "
            "verplichten die; voeg hem toe aan de template."
        )

    resultaat, vervangen = _swap(resultaat, _EMAIL_SOURCES, _EMAIL_TARGET[esp])
    if vervangen:
        notes.append(f"E-mailtag omgezet naar {_EMAIL_TARGET[esp]} ({vervangen}x).")

    grootte = len(resultaat.encode("utf-8"))
    if grootte > CLIPPING_BYTES:
        notes.append(
            f"De mail is {grootte // 1024} KB; boven {CLIPPING_BYTES // 1024} KB knippen "
            "Gmail en Klaviyo hem af ('Bericht is ingekort'). Overweeg minder blokken."
        )

    return LocalizedHtml(html=resultaat, notes=tuple(notes))


def _swap(html: str, sources: tuple[str, ...], target: str) -> tuple[str, int]:
    """Vervang elke bekende schrijfwijze door de doel-tag; telt de vervangingen."""
    aantal = 0
    for source in sources:
        if source == target:
            continue
        treffers = html.count(source)
        if treffers:
            html = html.replace(source, target)
            aantal += treffers
    return html, aantal


def has_unsubscribe(html: str) -> bool:
    """Staat er een afmeldlink in, in welke platform-syntax dan ook?"""
    return any(source in (html or "") for source in _UNSUBSCRIBE_SOURCES)
