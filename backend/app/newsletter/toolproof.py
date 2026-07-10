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
from app.newsletter.toolproof_ops import (
    Extractie,
    extract_styles,
    verify_range_op,
    verify_replace_op,
)

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
- {{HEADER_TITEL}} kop in de header/hero; {{HEADER_SUBTITEL}} ondertitel; \
{{HEADER_IMAGE_URL}} de hero-/headerfoto-URL
- Knop in de hero: BEHOUD de eigen knop-markup volledig; vervang alleen de \
knoptekst door {{HEADER_CTA_TEKST}}, de href door {{HOOFD_CTA_URL}} en de \
kleuren door {{STYLE_HERO_BUTTON_BG}} + {{STYLE_HERO_BUTTON_TEXT}}
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

BEDRIJFSGEGEVENS (per bedrijf ingevuld):
- {{BRAND_NAME}}, {{WEBSITE_URL}}, {{LOGO_URL}}, {{FACEBOOK_URL}}, {{INSTAGRAM_URL}}, \
{{YOUTUBE_URL}}
- Footer-contactgegevens: BEHOUD de eigen footer-markup en vervang alleen de \
concrete waarden door de losse velden {{BRAND_ADRES}}, {{BRAND_POSTCODE_STAD}}, \
{{BRAND_EMAIL}}, {{BRAND_TELEFOON}} en {{BRAND_KVK}}. Twijfel je, laat het blok \
dan statisch staan en meld het in notes.

STIJL (kleuren/lettertype uit de stijl-builder):
- {{STYLE_FONT}}, {{STYLE_TEXT_COLOR}}, {{STYLE_HEADING_COLOR}}, {{STYLE_LINK_COLOR}}, \
{{STYLE_PAGE_BG}}, {{STYLE_ACCENT}}, {{STYLE_FOOTER_BG}}, {{STYLE_FOOTER_TEXT}}
- KNOPPEN hebben drie aparte kleurgroepen; kies per knop het juiste token-paar: \
kaart-/productknoppen (bv. "SHOP NU" per product) -> {{STYLE_BUTTON_BG}} + \
{{STYLE_BUTTON_TEXT}}; de grote knop onderaan/midden (bv. "bekijk de collectie") -> \
{{STYLE_CTA_BUTTON_BG}} + {{STYLE_CTA_BUTTON_TEXT}}; de knop op de bannerfoto -> \
{{STYLE_HERO_BUTTON_BG}} + {{STYLE_HERO_BUTTON_TEXT}} (markup behouden, zie boven). \
LET OP: een knop bestaat vaak uit MEERDERE \
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
- HARDE CODE-CHECK: "replace" moet LETTERLIJK gelijk zijn aan "find" waarin alleen \
concrete waarden door placeholders zijn vervangen (en eventueel markers zijn \
ingevoegd). Elke andere afwijking, hoe klein ook, wordt door de code geweigerd.
- Zet NOOIT twee placeholders direct tegen elkaar; er moet vaste tekst tussen staan.
- Gebruik hetzelfde stijl-token nooit voor twee VERSCHILLENDE originele waarden \
(bv. twee knoppen met andere kleuren): kies dan per knop de juiste knopgroep of \
laat er één staan.
- "replace_range" mag ALLEEN overtollige kaart-kopieën verwijderen ("replace" leeg); \
elk ander gebruik wordt geweigerd.
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
    "{{HEADER_CTA_TEKST}}": "TP-HEROKNOP",
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
    # Basis-stijl met de ORIGINELE waarden uit de template (kleuren, witruimtes,
    # lettertype), zodat de getokeniseerde template er exact zo uit blijft zien.
    styles: dict = field(default_factory=dict)
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


def apply_operations(
    html: str, operations: list[dict]
) -> tuple[str, list[str], list[str], Extractie, list[str]]:
    """Pas operaties toe MET de harde substitutie-verificatie.

    Een operatie die het ontwerp zou kunnen veranderen wordt geweigerd (failed)
    en NIET toegepast. Twee fasen: eerst alle replace-ops (daarbij komt het
    bewaarde ##KAART##-blok in de HTML te staan), daarna de replace_range-ops
    (die alleen kaart-kopieën mogen wissen en het kaartblok nodig hebben voor
    de structuurvergelijking). Geeft ook de Extractie (originele waarden per
    placeholder) en de verwijderde fragmenten terug.
    """
    applied: list[str] = []
    failed: list[str] = []
    extractie = Extractie()
    removed: list[str] = []

    for op in operations:
        if op.get("op") == "replace_range":
            continue
        reason = op.get("reason") or op.get("replace", "")[:60]
        find = op.get("find") or ""
        if not find or find not in html:
            failed.append(f"tekst niet letterlijk gevonden: {reason}")
            continue
        verdict = verify_replace_op(find, op.get("replace") or "")
        if not verdict.ok:
            failed.append(f"{reason}: {verdict.reason}")
            continue
        conflict = extractie.bind(verdict.bindings)
        if conflict:
            failed.append(f"{reason}: {conflict}")
            continue
        html = html.replace(find, op["replace"], 1)
        applied.append(reason)

    for op in operations:
        if op.get("op") != "replace_range":
            continue
        reason = op.get("reason") or "sectie verwijderen"
        start_marker, end_marker = op.get("from") or "", op.get("to") or ""
        start = html.find(start_marker) if start_marker else -1
        end = html.find(end_marker, start + len(start_marker)) if start != -1 and end_marker else -1
        if start == -1 or end == -1:
            failed.append(f"sectie niet gevonden: {reason}")
            continue
        fragment = html[start:end]
        verdict = verify_range_op(html, fragment, op.get("replace") or "")
        if not verdict.ok:
            failed.append(f"{reason}: {verdict.reason}")
            continue
        html = html[:start] + html[end:]
        removed.append(fragment)
        applied.append(reason)
    return html, applied, failed, extractie, removed


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


_ONS_TOKEN = re.compile(r"\{\{[A-Z][A-Z0-9_]*\}\}")

# Token -> brand-veld voor de round-trip (de renderer vult deze uit brand).
_BRAND_TOKEN_FIELDS = {
    "{{BRAND_NAME}}": "brand_name",
    "{{BRAND_EMAIL}}": "brand_email",
    "{{BRAND_ADRES}}": "brand_adres",
    "{{BRAND_POSTCODE_STAD}}": "brand_postcode_stad",
    "{{BRAND_TELEFOON}}": "brand_telefoon",
    "{{BRAND_KVK}}": "brand_kvk",
    "{{WEBSITE_URL}}": "website_url",
    "{{LOGO_URL}}": "logo_url",
    "{{FACEBOOK_URL}}": "facebook_url",
    "{{INSTAGRAM_URL}}": "instagram_url",
    "{{YOUTUBE_URL}}": "youtube_url",
}

_TITLE_RE = re.compile(r"(?is)<title>.*?</title>")


def _strip_ws(html: str) -> str:
    """Normaliseer witruimte-RUNS tussen tags naar één spatie. Bewust niet naar
    leeg: 'geen spatie' versus 'wel een spatie' is een zichtbaar verschil
    (woorden plakken aan elkaar) en moet een afwijking blijven."""
    return re.sub(r">\s+<", "> <", html)


def roundtrip_check(
    raw_html: str, result_html: str, styles: dict, extractie: Extractie,
    removed: list[str],
) -> tuple[list[str], list[str], list[str]]:
    """De eindcheck: terugvullen met de originele waarden moet het origineel geven.

    Rendert het toolproof-resultaat met de geëxtraheerde originele waarden
    (stijl + inhoud) en vergelijkt met het origineel (minus de geverifieerde
    kaart-kopieën). Geeft (passed, failed, notes) terug.
    """
    passed: list[str] = []
    failed: list[str] = []
    notes: list[str] = []

    if _ONS_TOKEN.search(raw_html):
        notes.append(
            "de input bevatte al {{...}}-placeholders; de render-vergelijking met "
            "het origineel is dan niet mogelijk. De per-operatie-garantie geldt wel."
        )
        return passed, failed, notes

    b = extractie.waarden.get
    brand = {veld: b(token) for token, veld in _BRAND_TOKEN_FIELDS.items() if b(token) is not None}
    brand.setdefault("brand_name", "TP-MERK")
    brand.setdefault("brand_email", "tp@merk-email.test")
    brand.setdefault("website_url", "https://tp-website.test")
    brand.setdefault("logo_url", "https://tp-logo.test/logo.png")
    brand.setdefault("dummy_image_url", "https://tp-dummy.test/d.png")
    brand.setdefault("primary_color", "#FF7200")
    brand["styles"] = styles

    strip_title = False
    theme = "TP-THEMA"
    titel_origineel = b("{{EMAIL_TITEL}}")
    if titel_origineel is not None:
        staart = f" | {brand['brand_name']}"
        if titel_origineel.endswith(staart):
            theme = titel_origineel[: -len(staart)]
        else:
            strip_title = True
            notes.append(
                "de <title> wordt bij renderen 'thema | merknaam'; voor de titel "
                "geldt alleen de per-operatie-garantie"
            )

    custom_fields = tuple(
        (token[len("{{VAK_"):-2], waarde)
        for token, waarde in extractie.waarden.items()
        if token.startswith("{{VAK_")
    )
    items: tuple[Item, ...] = ()
    if has_card_block(result_html):
        items = (Item(
            title=b("{{KAART_TITEL}}") or "TP-BLOK",
            url=b("{{KAART_URL}}") or "https://tp-item.test",
            subtitle=b("{{KAART_SUBTITEL}}"),
            price=b("{{KAART_PRIJS}}"),
            image_url=b("{{KAART_IMAGE_URL}}"),
            label=b("{{KAART_LABEL}}"),
            button_text=b("{{KAART_KNOP_TEKST}}") or "Lees meer",
        ),)

    content = NewsletterContent(
        theme=theme,
        subject="",
        intro_1=b("{{INTRO_1}}") or "",
        intro_2=b("{{INTRO_2}}") or "",
        main_cta_text=b("{{HOOFD_CTA_TEKST}}") or "",
        main_cta_url=b("{{HOOFD_CTA_URL}}") or "",
        slot_cta_text=b("{{SLOT_CTA_TEKST}}") or "",
        slot_cta_url=b("{{SLOT_CTA_URL}}") or "",
        matches=(),
        items=items,
        header_title=b("{{HEADER_TITEL}}"),
        header_subtitle=b("{{HEADER_SUBTITEL}}"),
        header_cta_text=b("{{HEADER_CTA_TEKST}}"),
        header_image_url=b("{{HEADER_IMAGE_URL}}"),
        custom_fields=custom_fields,
    )

    referentie = raw_html
    for fragment in removed:
        referentie = referentie.replace(fragment, "", 1)
    try:
        rendered = render_newsletter(result_html, brand, content)
    except ValueError as exc:
        return passed, [f"round-trip-render mislukt: {exc}"], notes

    if strip_title:
        rendered = _TITLE_RE.sub("<title></title>", rendered, count=1)
        referentie = _TITLE_RE.sub("<title></title>", referentie, count=1)

    minus = " (minus de verwijderde kaart-kopieën)" if removed else ""
    if rendered == referentie:
        passed.append(f"render met de originele waarden is byte-identiek aan het origineel{minus}")
    elif _strip_ws(rendered) == _strip_ws(referentie):
        passed.append(f"render met de originele waarden is identiek aan het origineel{minus}, op witruimte na")
    else:
        genorm_r, genorm_o = _strip_ws(rendered), _strip_ws(referentie)
        idx = next(
            (i for i, (a, z) in enumerate(zip(genorm_r, genorm_o)) if a != z),
            min(len(genorm_r), len(genorm_o)),
        )
        ctx_van, ctx_tot = max(0, idx - 60), idx + 60
        failed.append(
            "render met de originele waarden wijkt af van het origineel rond: "
            f"...{genorm_o[ctx_van:ctx_tot]!r} (origineel) versus "
            f"{genorm_r[ctx_van:ctx_tot]!r} (render)"
        )
    return passed, failed, notes


def make_toolproof(llm, raw_html: str) -> ToolproofResult:
    """Volledige pipeline: voor-analyse -> voorstellen -> geverifieerd toepassen ->
    stijl-extractie -> valideren -> sentinel-verificatie -> round-trip-eindcheck."""
    input_notes = analyze_input(raw_html)
    proposal = propose_replacements(llm, raw_html)
    html, applied, failed, extractie, removed = apply_operations(
        raw_html, proposal.get("operations", [])
    )
    styles, style_notes = extract_styles(extractie)
    _, warnings = validate_template_html(html)
    checks_passed, checks_failed = verify_toolproof(html)
    rt_passed, rt_failed, rt_notes = roundtrip_check(
        raw_html, html, styles, extractie, removed
    )
    alle_failed = checks_failed + rt_failed
    extra_notes: list[str] = []
    if alle_failed:
        # Garantie in code: een omzetting die de verificatie niet haalt wordt
        # in zijn geheel verworpen. De admin krijgt het ONAANGETASTE origineel
        # terug plus het rapport; er valt dus nooit een kapot resultaat op te slaan.
        html = raw_html
        styles = {}
        extra_notes.append(
            "De omzetting is VERWORPEN omdat de verificatie faalde; de template "
            "is onaangetast. Zie de verificatieregels hierboven voor de reden."
        )
    return ToolproofResult(
        html=html,
        styles=styles,
        applied=applied,
        failed=failed,
        checks_passed=checks_passed + rt_passed,
        checks_failed=alle_failed,
        warnings=warnings,
        notes=input_notes + style_notes + rt_notes + extra_notes
        + [n for n in proposal.get("notes", []) if isinstance(n, str)],
    )
