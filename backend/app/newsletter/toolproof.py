"""Maakt een geplakte (statische) template tool-proof: hardcoded inhoud -> placeholders.

Werkwijze (garanties in code, niet in het model):
1. Een LLM stelt EXACTE vervangingsoperaties voor (nooit de hele HTML terug, alleen
   chirurgische find/replace-operaties, zodat het model niets kan herschrijven of
   inkorten).
2. De code past de operaties toe; operaties die niet letterlijk matchen worden als
   "mislukt" gerapporteerd in plaats van stilletjes overgeslagen.
3. De omgezette template wordt gerenderd met sentinel-content; per aanwezige
   placeholder checkt de code dat de sentinel echt in de output verschijnt. Een
   half-statische template (knop die niet meebeweegt) valt hier direct door de mand.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.newsletter.models import Item, NewsletterContent
from app.newsletter.renderer import BANNER_MARKER, CARD_MARKER, render_newsletter
from app.newsletter.template_validation import validate_template_html

TRANSFORM_MODEL = "claude-sonnet-4-6"
MAX_TEMPLATE_CHARS = 150_000
MAX_OUTPUT_TOKENS = 16000

_REPLACEMENTS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "operations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "op": {"type": "string", "enum": ["replace", "replace_range"]},
                    "find": {"type": ["string", "null"]},
                    "from": {"type": ["string", "null"]},
                    "to": {"type": ["string", "null"]},
                    "replace": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["op", "find", "from", "to", "replace", "reason"],
            },
        },
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["operations", "notes"],
}

_TRANSFORM_SYSTEM = """Je krijgt de volledige HTML van een e-mailtemplate met hardcoded inhoud \
(teksten, knoppen, logo, footer van een specifiek bedrijf). Stel EXACTE vervangingsoperaties \
voor die de hardcoded inhoud vervangen door de placeholders van ons nieuwsbrief-systeem, \
zodat de template herbruikbaar ("tool-proof") wordt.

BESCHIKBARE PLACEHOLDERS (per nieuwsbrief ingevuld):
- {{EMAIL_TITEL}}: de <title> van de mail
- {{HEADER_TITEL}} kop in de header/hero; {{HEADER_SUBTITEL}} ondertitel; {{HEADER_CTA}} \
de knop in de hero (vervang de HELE knop-tabel door deze placeholder); \
{{HEADER_IMAGE_URL}} de hero-/headerfoto-URL
- {{INTRO_1}} eerste intro-alinea; {{INTRO_2}} tweede intro-alinea (alleen de tekst \
binnen de <p>, niet de tags zelf)
- {{HOOFD_CTA_URL}} en {{HOOFD_CTA_TEKST}}: href en tekst van de belangrijkste knop
- {{SLOT_CTA_URL}} en {{SLOT_CTA_TEKST}}: href en tekst van de onderste/tweede knop
- <!-- ##CARDS## --> of <!-- ##BANNERS## -->: vervangt de HELE sectie met herhaalde \
inhoudsblokken (product-/wedstrijd-/case-kaarten). Kies ##CARDS## bij een grid van \
kaarten naast elkaar, ##BANNERS## bij brede blokken onder elkaar. Gebruik hiervoor \
replace_range over de complete sectie.

BEDRIJFSGEGEVENS (per bedrijf ingevuld):
- {{BRAND_NAME}}, {{BRAND_ADRES}}, {{BRAND_POSTCODE_STAD}}, {{BRAND_EMAIL}}, \
{{BRAND_TELEFOON}}, {{BRAND_KVK}}, {{WEBSITE_URL}}, {{LOGO_URL}}, {{FACEBOOK_URL}}, \
{{INSTAGRAM_URL}}, {{YOUTUBE_URL}}

STIJL (kleuren/lettertype uit de stijl-builder):
- {{STYLE_FONT}}, {{STYLE_TEXT_COLOR}}, {{STYLE_HEADING_COLOR}}, {{STYLE_LINK_COLOR}}, \
{{STYLE_PAGE_BG}}, {{STYLE_BUTTON_BG}}, {{STYLE_BUTTON_TEXT}}, {{STYLE_ACCENT}}, \
{{STYLE_FOOTER_BG}}, {{STYLE_FOOTER_TEXT}}

REGELS:
- Geef ALLEEN operaties terug, nooit de hele HTML.
- "find", "from" en "to" moeten LETTERLIJK en byte-exact uit de input komen (kopieer \
precies, inclusief spaties, aanhalingstekens en hoofdletters) en lang genoeg zijn om \
uniek te zijn. Kort ze NOOIT af met "..." of iets dergelijks.
- Gebruik "replace" voor korte stukken. Gebruik "replace_range" voor grote secties: \
alles vanaf "from" tot aan (exclusief) "to" wordt vervangen door "replace".
- Vervang knopkleuren door {{STYLE_BUTTON_BG}} en {{STYLE_BUTTON_TEXT}}, gewone \
tekstkleur door {{STYLE_TEXT_COLOR}}, linkkleuren door {{STYLE_LINK_COLOR}}, de \
pagina-achtergrond door {{STYLE_PAGE_BG}}, de footer door {{STYLE_FOOTER_BG}} en \
{{STYLE_FOOTER_TEXT}}, en font-family van lopende tekst door {{STYLE_FONT}}.
- Laat ESP-tags exact staan: Brevo-tags ({{ unsubscribe }}, {{ contact.EMAIL }}) en \
Klaviyo-tags ({% unsubscribe %}, {% current_year %}, {{ organization.name }}, \
{{ organization.full_address }} en vergelijkbaar). Voeg zelf geen afmeldlink toe.
- Echte klantreviews/testimonials en juridische teksten mogen statisch blijven; meld \
dat in notes.
- Meld in notes alles wat je niet kon vervangen of wat aandacht nodig heeft."""

# Sentinel-waarden: uniek per placeholder (geen prefixen van elkaar), zodat de
# doorstroom-check per veld eenduidig is.
_SENTINEL_BRAND = {
    "brand_name": "TP-MERK",
    "brand_email": "tp@merk-email.test",
    "brand_adres": "TP-ADRES 1",
    "brand_postcode_stad": "1234 TP STAD",
    "brand_telefoon": "+31 6 00 000 000",
    "brand_kvk": "TP-KVK-123",
    "website_url": "https://tp-website.test",
    "primary_color": "#FF7200",
    "logo_url": "https://tp-logo.test/logo.png",
    "dummy_image_url": "https://tp-dummy.test/d.png",
    "facebook_url": "https://tp-facebook.test",
    "instagram_url": "https://tp-instagram.test",
    "youtube_url": "https://tp-youtube.test",
}

_SENTINEL_CONTENT = NewsletterContent(
    theme="TP-THEMA",
    subject="TP-ONDERWERP",
    intro_1="TP-INTRO-EEN",
    intro_2="TP-INTRO-TWEE",
    main_cta_text="TP-HOOFDKNOP",
    main_cta_url="https://tp-hoofd.test",
    slot_cta_text="TP-SLOTKNOP",
    slot_cta_url="https://tp-slot.test",
    matches=(),
    items=(Item(title="TP-BLOK", url="https://tp-item.test", button_text="TP-ITEMKNOP"),),
    header_title="TP-KOP",
    header_subtitle="TP-SUBKOP",
    header_cta_text="TP-HEROKNOP",
    header_image_url="https://tp-hero.test/h.png",
)

# placeholder -> sentinel die in de render moet verschijnen als de placeholder bestaat.
_PLACEHOLDER_SENTINELS = {
    "{{INTRO_1}}": "TP-INTRO-EEN",
    "{{INTRO_2}}": "TP-INTRO-TWEE",
    "{{HOOFD_CTA_URL}}": "https://tp-hoofd.test",
    "{{HOOFD_CTA_TEKST}}": "TP-HOOFDKNOP",
    "{{SLOT_CTA_URL}}": "https://tp-slot.test",
    "{{SLOT_CTA_TEKST}}": "TP-SLOTKNOP",
    "{{HEADER_TITEL}}": "TP-KOP",
    "{{HEADER_SUBTITEL}}": "TP-SUBKOP",
    "{{HEADER_CTA}}": "TP-HEROKNOP",
    "{{HEADER_IMAGE_URL}}": "https://tp-hero.test/h.png",
    "{{LOGO_URL}}": "https://tp-logo.test/logo.png",
    "{{WEBSITE_URL}}": "https://tp-website.test",
    "{{BRAND_NAME}}": "TP-MERK",
    "{{BRAND_EMAIL}}": "tp@merk-email.test",
    "{{BRAND_ADRES}}": "TP-ADRES 1",
    "{{BRAND_POSTCODE_STAD}}": "1234 TP STAD",
    "{{BRAND_TELEFOON}}": "+31 6 00 000 000",
    "{{BRAND_KVK}}": "TP-KVK-123",
    "{{FACEBOOK_URL}}": "https://tp-facebook.test",
    "{{INSTAGRAM_URL}}": "https://tp-instagram.test",
    "{{YOUTUBE_URL}}": "https://tp-youtube.test",
}


@dataclass(frozen=True)
class ToolproofResult:
    html: str
    applied: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    checks_passed: list[str] = field(default_factory=list)
    checks_failed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed and not self.checks_failed


def propose_replacements(llm, raw_html: str) -> dict:
    """Vraag het LLM om exacte vervangingsoperaties (structured output)."""
    response = llm.messages.create(
        model=TRANSFORM_MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=_TRANSFORM_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": _REPLACEMENTS_SCHEMA}},
        messages=[{"role": "user", "content": f"Template-HTML:\n{raw_html}"}],
    )
    text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {"operations": [], "notes": ["LLM-antwoord kon niet worden gelezen."]}


def apply_replacements(html: str, operations: list[dict]) -> tuple[str, list[str], list[str]]:
    """Pas de operaties toe. Niet-matchende operaties worden gerapporteerd, nooit gegokt."""
    applied: list[str] = []
    failed: list[str] = []
    for op in operations:
        reason = op.get("reason") or op.get("replace", "")[:60]
        if op.get("op") == "replace_range":
            start_marker, end_marker = op.get("from") or "", op.get("to") or ""
            start = html.find(start_marker) if start_marker else -1
            end = html.find(end_marker, start + len(start_marker)) if start != -1 and end_marker else -1
            if start == -1 or end == -1:
                failed.append(f"sectie niet gevonden: {reason}")
                continue
            html = html[:start] + op["replace"] + html[end:]
            applied.append(reason)
        else:
            find = op.get("find") or ""
            if not find or find not in html:
                failed.append(f"tekst niet letterlijk gevonden: {reason}")
                continue
            html = html.replace(find, op["replace"], 1)
            applied.append(reason)
    return html, applied, failed


def verify_toolproof(html: str) -> tuple[list[str], list[str]]:
    """Render met sentinel-content en check dat elke aanwezige placeholder doorstroomt."""
    passed: list[str] = []
    failed: list[str] = []
    try:
        rendered = render_newsletter(html, _SENTINEL_BRAND, _SENTINEL_CONTENT)
    except ValueError as exc:
        return [], [f"render mislukt: {exc}"]

    for placeholder, sentinel in _PLACEHOLDER_SENTINELS.items():
        if placeholder not in html:
            continue
        if sentinel in rendered:
            passed.append(f"{placeholder} stroomt door")
        else:
            failed.append(f"{placeholder} staat in de template maar komt niet in de render")

    if BANNER_MARKER in html or CARD_MARKER in html:
        if "TP-BLOK" in rendered:
            passed.append("blokken-marker rendert de inhoudsblokken")
        else:
            failed.append("blokken-marker aanwezig maar de blokken renderen niet")

    for tag in ("{{ unsubscribe }}", "{% unsubscribe %}"):
        if tag in html:
            if tag in rendered:
                passed.append(f"afmeldlink ({tag}) blijft behouden")
            else:
                failed.append(f"afmeldlink ({tag}) verdwijnt bij het renderen")

    return passed, failed


def make_toolproof(llm, raw_html: str) -> ToolproofResult:
    """Volledige pipeline: voorstellen -> toepassen -> valideren -> sentinel-verificatie."""
    proposal = propose_replacements(llm, raw_html)
    html, applied, failed = apply_replacements(raw_html, proposal.get("operations", []))
    _, warnings = validate_template_html(html)
    checks_passed, checks_failed = verify_toolproof(html)
    return ToolproofResult(
        html=html,
        applied=applied,
        failed=failed,
        checks_passed=checks_passed,
        checks_failed=checks_failed,
        warnings=warnings,
        notes=[n for n in proposal.get("notes", []) if isinstance(n, str)],
    )
