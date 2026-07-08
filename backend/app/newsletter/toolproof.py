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
import re
from dataclasses import dataclass, field, replace

from app.newsletter.card_block import CARD_TPL_START, has_card_block
from app.newsletter.custom_fields import (
    SECTION_END,
    SECTION_START,
    find_custom_slots,
)
from app.newsletter.models import Item, NewsletterContent, Section
from app.newsletter.renderer import (
    BANNER_MARKER,
    CARD_MARKER,
    SECTIONS_MARKER,
    render_newsletter,
)
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
- EIGEN KAART-ONTWERP BEHOUDEN (voorkeur!): heeft de template een eigen ontwerp voor \
herhaalde product-/inhouds-kaarten (bv. een grid met foto, naam, prijs en knop per \
product), GOOI DAT ONTWERP DAN NIET WEG. Behoud precies EEN voorbeeldkaart, zet er \
<!-- ##KAART## --> voor en <!-- /##KAART## --> na, en vervang binnen die kaart de \
concrete waarden door {{KAART_TITEL}}, {{KAART_SUBTITEL}}, {{KAART_PRIJS}}, \
{{KAART_URL}} (zowel de link op de foto als op de knop), {{KAART_IMAGE_URL}} en \
{{KAART_KNOP_TEKST}}. Staan de kaarten per rij in een wrapper (bv. 2 naast elkaar), \
behoud dan EEN rij-wrapper en zet er <!-- ##KAART_RIJ## --> voor en \
<!-- /##KAART_RIJ## --> na (met de voorbeeldkaart erbinnen). Verwijder alle overige \
kaarten en rijen met replace_range. De code herhaalt de voorbeeldkaart per product, \
twee per rij.
- EIGEN TEKSTSECTIES BEHOUDEN met invulvakken (voorkeur voor al het redactionele!): \
heeft de template eigen inhoudssecties die NIET op de vaste placeholders passen \
(artikelen, kolommen, interviews, Q&A, aankondigingen), GOOI ZE NIET WEG en bouw ze \
NIET om. Vervang alleen de concrete teksten door vrije invulvakken: {{VAK_<NAAM>}} \
(hoofdletters, beschrijvend, bv. {{VAK_ARTIKEL_TITEL}}, {{VAK_QA_VRAAG_1}}). Zet \
<!-- ##SECTIE## --> vóór en <!-- /##SECTIE## --> ná elke afzonderlijke sectie: een \
sectie waarvan geen enkel vak inhoud krijgt wordt dan automatisch uit de mail \
weggelaten. Nooit nesten; elk blok eerst sluiten. Ook onbekende placeholders die al \
in de input staan (bv. {{artikel_titel}}) zet je zo om naar {{VAK_*}}-vakken of, als \
er een duidelijke match is, naar onze vaste placeholders.
- <!-- ##CARDS## --> of <!-- ##BANNERS## -->: vervangt de HELE sectie door \
inhoudsblokken in ONS standaard-ontwerp. LAATSTE REDMIDDEL: alleen als de template \
GEEN eigen kaart-ontwerp heeft EN de sectie ook niet als {{VAK_*}}-tekstsectie te \
behouden is. Kies ##CARDS## bij een grid van kaarten naast elkaar, ##BANNERS## bij \
brede blokken onder elkaar. Gebruik hiervoor replace_range over de complete sectie.
- <!-- ##SECTIES## -->: alleen voor "schil"-templates waar de HELE variabele \
middenzone (hero + teksten + blokken + knoppen samen) per nieuwsbrief opnieuw wordt \
samengesteld in de chat. Vervang dan die complete middenzone door deze ene marker en \
laat head en footer staan. LAATSTE REDMIDDEL: alleen als losse placeholders én \
{{VAK_*}}-vakken allebei niet passen.

BEDRIJFSGEGEVENS (per bedrijf ingevuld):
- {{BRAND_NAME}}, {{WEBSITE_URL}}, {{LOGO_URL}}, {{FACEBOOK_URL}}, {{INSTAGRAM_URL}}, \
{{YOUTUBE_URL}}
- {{FOOTER_CONTACT}}: HEEL het blok met adres/e-mail/telefoon/KVK in de footer \
vervangen door deze ene placeholder (regels die het bedrijf niet heeft worden \
automatisch weggelaten). Gebruik deze boven losse velden; losse velden \
({{BRAND_ADRES}}, {{BRAND_POSTCODE_STAD}}, {{BRAND_EMAIL}}, {{BRAND_TELEFOON}}, \
{{BRAND_KVK}}) bestaan ook maar laten lege labels achter als iets ontbreekt.

STIJL (kleuren/lettertype uit de stijl-builder):
- {{STYLE_FONT}}, {{STYLE_TEXT_COLOR}}, {{STYLE_HEADING_COLOR}}, {{STYLE_LINK_COLOR}}, \
{{STYLE_PAGE_BG}}, {{STYLE_ACCENT}}, {{STYLE_FOOTER_BG}}, {{STYLE_FOOTER_TEXT}}
- KNOPPEN hebben drie aparte kleurgroepen; kies per knop het juiste token-paar: \
kaart-/productknoppen (bv. "SHOP NU" per product) -> {{STYLE_BUTTON_BG}} + \
{{STYLE_BUTTON_TEXT}}; de grote knop onderaan/midden (bv. "bekijk de collectie") -> \
{{STYLE_CTA_BUTTON_BG}} + {{STYLE_CTA_BUTTON_TEXT}}; de knop op de bannerfoto wordt \
{{HEADER_CTA}} (hele knop vervangen). LET OP: een knop bestaat vaak uit MEERDERE \
lagen (bgcolor op de td, background in de td-style, én background/color in de \
<a>-tag); vervang de kleur in ALLE lagen van dezelfde knop door hetzelfde token, \
anders blijft de zichtbare laag een andere kleur houden.
- WITRUIMTE: vervang de verticale paddings tussen de hoofd-zones door deze tokens \
(alleen het getal, "px" laten staan): banner/hero -> introtekst = \
{{STYLE_SPACING_BANNER_INTRO}}, introtekst -> producten/blokken = \
{{STYLE_SPACING_INTRO_PRODUCTS}}, producten -> tekst eronder = \
{{STYLE_SPACING_PRODUCTS_TEXT}}, die tekst -> onderste knop = \
{{STYLE_SPACING_TEXT_BUTTON}}. Voorbeeld: "padding-top:80px" wordt \
"padding-top:{{STYLE_SPACING_BANNER_INTRO}}px". Alleen toepassen op de zones die \
duidelijk herkenbaar zijn; twijfel je, laat de padding staan en meld het in notes.

REGELS:
- JOUW ENIGE TAAK is concrete inhoud vervangen door placeholders. Het ONTWERP van de \
template (layout, secties, structuur, CSS) verander je NOOIT; je verwijdert geen \
secties behalve overtollige kopieën van de voorbeeldkaart/-rij.
- Geef ALLEEN operaties terug, nooit de hele HTML.
- "find", "from" en "to" moeten LETTERLIJK en byte-exact uit de input komen (kopieer \
precies, inclusief spaties, aanhalingstekens en hoofdletters) en lang genoeg zijn om \
uniek te zijn. Kort ze NOOIT af met "..." of iets dergelijks.
- Gebruik "replace" voor korte stukken. Gebruik "replace_range" voor grote secties: \
alles vanaf "from" tot aan (exclusief) "to" wordt vervangen door "replace".
- Vervang knopkleuren per knopgroep (zie STIJL hierboven: kaartknoppen, grote \
CTA-knop, bannerknop) en in ALLE lagen van dezelfde knop. Gewone tekstkleur wordt \
{{STYLE_TEXT_COLOR}}, linkkleuren {{STYLE_LINK_COLOR}}, de pagina-achtergrond \
{{STYLE_PAGE_BG}}, de footer {{STYLE_FOOTER_BG}} en {{STYLE_FOOTER_TEXT}}, en \
font-family van lopende tekst {{STYLE_FONT}}.
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
    items=(
        Item(
            title="TP-BLOK",
            url="https://tp-item.test",
            button_text="TP-ITEMKNOP",
            subtitle="TP-SUBBLOK",
            price="TP-PRIJS",
            image_url="https://tp-itemfoto.test/i.png",
        ),
    ),
    header_title="TP-KOP",
    header_subtitle="TP-SUBKOP",
    header_cta_text="TP-HEROKNOP",
    header_image_url="https://tp-hero.test/h.png",
    sections=(
        Section(kind="text", text="TP-SECTIE-TEKST"),
        Section(kind="blocks"),
        Section(kind="button", text="TP-SECTIEKNOP", url="https://tp-sectieknop.test"),
    ),
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
    "{{FOOTER_CONTACT}}": "TP-ADRES 1",
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
    if html.count(SECTION_START) != html.count(SECTION_END):
        return [], [
            "##SECTIE##-markers zijn niet in balans "
            f"({html.count(SECTION_START)}x start, {html.count(SECTION_END)}x einde)"
        ]
    slots = find_custom_slots(html)
    content = _SENTINEL_CONTENT
    if slots:
        content = replace(
            _SENTINEL_CONTENT,
            custom_fields=tuple((naam, f"TP-VAK-{naam}") for naam in slots),
        )
    try:
        rendered = render_newsletter(html, _SENTINEL_BRAND, content)
    except ValueError as exc:
        return [], [f"render mislukt: {exc}"]

    for naam in slots:
        if f"TP-VAK-{naam}" in rendered:
            passed.append(f"invulvak {naam} stroomt door")
        else:
            failed.append(f"invulvak {naam} staat in de template maar komt niet in de render")
    if slots:
        # Zonder inhoud moeten de vak-secties geruisloos wegvallen.
        try:
            kaal = render_newsletter(html, _SENTINEL_BRAND, _SENTINEL_CONTENT)
        except ValueError as exc:
            return passed, failed + [f"render zonder invulvakken mislukt: {exc}"]
        if SECTION_START in kaal or "{{VAK_" in kaal:
            failed.append("lege invulvak-secties vallen niet netjes weg")
        else:
            passed.append("lege invulvak-secties vallen netjes weg")

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

    if CARD_TPL_START in html:
        if not has_card_block(html):
            failed.append("kaart-blok niet afgesloten (<!-- /##KAART## --> ontbreekt)")
        else:
            # Het eigen kaart-ontwerp moet de item-data echt tonen: titel, link en foto.
            checks = {
                "titel": "TP-BLOK",
                "link": "https://tp-item.test",
                "foto": "https://tp-itemfoto.test/i.png",
            }
            missing = [naam for naam, sentinel in checks.items() if sentinel not in rendered]
            if missing:
                failed.append(
                    f"kaart-blok aanwezig maar {', '.join(missing)} komt niet in de render "
                    "(placeholder {{KAART_...}} vergeten?)"
                )
            else:
                passed.append("kaart-blok herhaalt het eigen ontwerp met de item-data")

    if SECTIONS_MARKER in html:
        if "TP-SECTIE-TEKST" in rendered and "TP-BLOK" in rendered:
            passed.append("secties-marker rendert de opzet-secties")
        else:
            failed.append("secties-marker aanwezig maar de secties renderen niet")

    for tag in ("{{ unsubscribe }}", "{% unsubscribe %}"):
        if tag in html:
            if tag in rendered:
                passed.append(f"afmeldlink ({tag}) blijft behouden")
            else:
                failed.append(f"afmeldlink ({tag}) verdwijnt bij het renderen")

    return passed, failed


_UNSAFE_CSS = re.compile(
    r"display\s*:\s*(?:grid|flex)|:root\b|var\(--|aspect-ratio\s*:|position\s*:\s*absolute",
    re.IGNORECASE,
)
_FOREIGN_PLACEHOLDER = re.compile(r"\{\{\s*([a-z][a-z0-9_.]*)\s*\}\}")
_ESP_TAG_PREFIXES = ("contact.", "unsubscribe", "organization.", "current_year", "mirror")


def analyze_input(raw_html: str) -> list[str]:
    """Eerlijke voor-checks op de aangeleverde HTML; uitkomsten gaan mee in notes."""
    notes: list[str] = []
    vreemd = sorted({
        naam for naam in _FOREIGN_PLACEHOLDER.findall(raw_html or "")
        if not naam.startswith(_ESP_TAG_PREFIXES)
    })
    if vreemd:
        kop = ", ".join(vreemd[:8]) + ("..." if len(vreemd) > 8 else "")
        notes.append(
            f"De input bevat eigen placeholders ({kop}); die kent het systeem niet. "
            "Ze zijn waar mogelijk omgezet naar onze placeholders of {{VAK_*}}-invulvakken; "
            "controleer het resultaat."
        )
    if _UNSAFE_CSS.search(raw_html or ""):
        notes.append(
            "Let op: de layout leunt op CSS die veel e-mailclients niet ondersteunen "
            "(grid/flexbox/CSS-variabelen/absolute positionering). Toolproof vervangt "
            "inhoud, geen layout; voor betrouwbare weergave in Outlook/Gmail is een "
            "tabel-gebaseerde opbouw nodig."
        )
    return notes


def make_toolproof(llm, raw_html: str) -> ToolproofResult:
    """Volledige pipeline: voor-analyse -> voorstellen -> toepassen -> valideren -> verificatie."""
    input_notes = analyze_input(raw_html)
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
        notes=input_notes + [n for n in proposal.get("notes", []) if isinstance(n, str)],
    )
