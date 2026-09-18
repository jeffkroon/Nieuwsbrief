"""Controles op de gerenderde nieuwsbrief, vlak voor het voorbeeld en het concept.

Klassieke fouten die pas bij de ontvanger opvallen: een afbeelding zonder
alt-tekst (bij geblokkeerde plaatjes ziet de lezer niets), een onderwerpregel die
in de inbox wordt afgekapt, een ontbrekende afmeldlink, of een mail die zo groot
is dat Gmail hem inkort.

Alles in code en zonder AI: dit zijn feiten over de HTML, geen oordeel. De harde
punten blokkeren het concept, de rest is advies dat de assistent kan doorgeven.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.newsletter.esp_tags import CLIPPING_BYTES, has_unsubscribe

# Inbox-afkap: Gmail toont ~50 tekens op mobiel, Outlook iets meer.
MAX_SUBJECT_CHARS = 60
MAX_PREHEADER_CHARS = 110

_IMG = re.compile(r"(?is)<img\b[^>]*>")
_ALT = re.compile(r"(?is)\balt\s*=\s*([\"'])(.*?)\1")
_HREF = re.compile(r"(?is)\bhref\s*=\s*([\"'])(.*?)\1")
_SCRIPT = re.compile(r"(?is)<script\b")


@dataclass(frozen=True)
class MailCheck:
    """Een bevinding; `blocking` bepaalt of het concept geweigerd wordt."""

    code: str
    message: str
    blocking: bool = False


def check_newsletter(
    html: str, *, subject: str = "", preheader: str | None = None
) -> list[MailCheck]:
    """Alle bevindingen, blokkerend eerst; lege lijst = niets aan de hand."""
    bevindingen: list[MailCheck] = []
    html = html or ""

    if not has_unsubscribe(html):
        # Nadrukkelijk een waarschuwing en geen blokkade: template_validation.py
        # behandelt een ontbrekende afmeldlink al als "aanbevolen ontbreekt", en die
        # bestaande keuze mag hier niet stilletjes worden omgedraaid. Klaviyo weigert
        # zelf wel hard, want dat platform maakt er geen campagne van.
        bevindingen.append(
            MailCheck(
                code="geen-afmeldlink",
                message=(
                    "Er staat geen afmeldlink in de nieuwsbrief. Klaviyo weigert de "
                    "campagne zonder, en Brevo en ActiveCampaign verplichten hem ook; "
                    "voeg hem toe aan de template."
                ),
            )
        )

    if _SCRIPT.search(html):
        bevindingen.append(
            MailCheck(
                code="script",
                message="Er staat een <script> in de mail; e-mailclients blokkeren dat.",
                blocking=True,
            )
        )

    gevaarlijk = [
        href for _, href in _HREF.findall(html)
        if href.strip().lower().startswith("javascript:")
    ]
    if gevaarlijk:
        bevindingen.append(
            MailCheck(
                code="javascript-link",
                message="Er staat een javascript:-link in de mail; die werkt nergens.",
                blocking=True,
            )
        )

    zonder_alt = [tag for tag in _IMG.findall(html) if not _heeft_alt(tag)]
    if zonder_alt:
        bevindingen.append(
            MailCheck(
                code="alt-ontbreekt",
                message=(
                    f"{len(zonder_alt)} afbeelding(en) hebben geen alt-tekst. Veel "
                    "mailprogramma's blokkeren foto's; dan ziet de lezer daar niets."
                ),
            )
        )

    if subject and len(subject) > MAX_SUBJECT_CHARS:
        bevindingen.append(
            MailCheck(
                code="onderwerp-lang",
                message=(
                    f"De onderwerpregel is {len(subject)} tekens; boven "
                    f"{MAX_SUBJECT_CHARS} kapt de inbox hem af."
                ),
            )
        )

    if preheader and len(preheader) > MAX_PREHEADER_CHARS:
        bevindingen.append(
            MailCheck(
                code="preheader-lang",
                message=(
                    f"De preheader is {len(preheader)} tekens; boven "
                    f"{MAX_PREHEADER_CHARS} wordt hij afgekapt."
                ),
            )
        )

    grootte = len(html.encode("utf-8"))
    if grootte > CLIPPING_BYTES:
        bevindingen.append(
            MailCheck(
                code="te-groot",
                message=(
                    f"De mail is {grootte // 1024} KB; boven "
                    f"{CLIPPING_BYTES // 1024} KB knippen Gmail en Klaviyo hem af."
                ),
            )
        )

    return sorted(bevindingen, key=lambda b: not b.blocking)


def blocking_messages(bevindingen: list[MailCheck]) -> list[str]:
    return [b.message for b in bevindingen if b.blocking]


def advisory_messages(bevindingen: list[MailCheck]) -> list[str]:
    return [b.message for b in bevindingen if not b.blocking]


def _heeft_alt(tag: str) -> bool:
    """Een leeg alt="" telt mee: dat is de bewuste markering voor sierafbeeldingen."""
    return _ALT.search(tag) is not None
