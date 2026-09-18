"""CSS inline zetten vlak voor het concept, met een vangnet.

Outlook (en Gmail bij een `<style>`-blok in sommige situaties) negeert CSS uit een
stylesheet. Exports uit Stripo en ActiveCampaign leunen daar wel op, waardoor een
knop die bij ons oranje is, bij de ontvanger grijs aankomt.

`css_inline` schrijft die regels als `style="..."` op de elementen zelf. Het
`<style>`-blok blijft staan (`keep_style_tags`), want daar zitten de media queries
die de mail op een telefoon leesbaar houden; die kunnen niet inline.

Het vangnet: gaat er bij het inlinen ook maar iets verloren dat de mail kapot
maakt (een platform-tag, een Outlook-conditional, of een flink stuk van de
inhoud), dan gebruiken we gewoon de originele HTML. Liever een knop die niet in
elke client kleurt dan een mail die stuk is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Wat er onder geen beding mag sneuvelen bij het inlinen.
_TE_BEWAKEN = (
    "{{ unsubscribe }}",
    "{{unsubscribe}}",
    "{% unsubscribe %}",
    "%UNSUBSCRIBELINK%",
    "{{ contact.EMAIL }}",
    "{{ person.email }}",
    "%EMAIL%",
)
_MSO = re.compile(r"(?i)<!--\[if\s+[^\]]*\]>")
# Onder deze verhouding is er zoveel weg dat we het resultaat niet vertrouwen.
_MIN_VERHOUDING = 0.8


@dataclass(frozen=True)
class InlineResult:
    html: str
    applied: bool
    note: str | None = None


def inline_css(html: str) -> InlineResult:
    """Zet CSS inline; bij twijfel onveranderd terug."""
    if not html or "<style" not in html.lower():
        return InlineResult(html=html or "", applied=False)

    try:
        import css_inline
    except ImportError:  # pragma: no cover - alleen als de dependency ontbreekt
        return InlineResult(html=html, applied=False, note="css_inline is niet beschikbaar")

    try:
        resultaat = css_inline.inline(html, keep_style_tags=True)
    except Exception as exc:  # noqa: BLE001 - kapotte CSS mag de mail niet blokkeren
        return InlineResult(html=html, applied=False, note=f"CSS inline zetten mislukte: {exc}")

    ontbreekt = _wat_ontbreekt(html, resultaat)
    if ontbreekt:
        return InlineResult(
            html=html,
            applied=False,
            note=f"CSS niet inline gezet: {ontbreekt} ging verloren, originele HTML gebruikt.",
        )
    return InlineResult(html=resultaat, applied=True)


def _wat_ontbreekt(origineel: str, resultaat: str) -> str | None:
    """Welke onmisbare eigenschap is het resultaat kwijtgeraakt?"""
    for tag in _TE_BEWAKEN:
        if origineel.count(tag) and resultaat.count(tag) < origineel.count(tag):
            return f"de tag {tag}"
    if len(_MSO.findall(origineel)) > len(_MSO.findall(resultaat)):
        return "een Outlook-conditional"
    if len(resultaat) < len(origineel) * _MIN_VERHOUDING:
        return "een groot deel van de inhoud"
    return None
