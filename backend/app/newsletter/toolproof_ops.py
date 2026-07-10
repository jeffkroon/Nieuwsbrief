"""Verificatie van toolproof-operaties: het ontwerp mag NOOIT veranderen.

Het contract dat deze module in code afdwingt: een 'replace'-operatie is alleen
geldig als `replace` letterlijk gelijk is aan `find` waarin uitsluitend concrete
waarden door bekende placeholders zijn vervangen (plus eventueel pure marker-
inserties). Elke byte van `find` die niet in een placeholder-gat valt moet dus
onaangeraakt terugkomen. Daaruit volgt wiskundig dat terugvullen met de originele
waarden het origineel reproduceert: de AI kan per constructie geen markup
herschrijven, alleen inhoud tokeniseren.

De originele waarden uit de gaten worden verzameld (Extractie) zodat de
stijl-tokens hun ORIGINELE kleur/witruimte als basis-stijl meekrijgen; zonder
die extractie zou een getokeniseerde template op systeem-defaults terugvallen
en er ineens anders uitzien.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.newsletter.card_block import (
    CARD_ROW_END,
    CARD_ROW_START,
    CARD_TPL_END,
    CARD_TPL_START,
    has_card_block,
)
from app.newsletter.custom_fields import SECTION_END, SECTION_START
from app.newsletter.styles import (
    EMAIL_SAFE_FONTS,
    FONT_KEY,
    TEMPLATE_TOKENS,
    is_valid_hex_color,
)

# Backtracking-guards: een op die hier overheen gaat is sowieso te grof.
MAX_TOKENS_PER_OP = 20
MAX_FIND_CHARS = 20_000

# Gat-patronen per stijl-tokensoort (restrictief: een kleur-token mag alleen
# een kleur vervangen, een spacing-token alleen een getal).
_GAP_COLOR = r"#[0-9a-fA-F]{3,8}"
_GAP_SPACING = r"[0-9]{1,3}"
_GAP_FONT = r'[^;{}<>"]+'
# Content-gaten mogen GEEN tags bevatten: als {{INTRO_1}} een <table> zou
# opslokken, reproduceert de round-trip het origineel nog wel (zelfde waarde
# terug), maar verdwijnt die tabel bij elke toekomstige render met andere
# tekst. Tag-grenzen zijn dus een harde grens voor het gat.
_GAP_FREE = r"[^<>]*?"

# Vaste content-placeholders die de renderer kent (vrij gat).
_CONTENT_TOKENS = (
    "{{EMAIL_TITEL}}",
    "{{HEADER_TITEL}}",
    "{{HEADER_SUBTITEL}}",
    "{{HEADER_CTA_TEKST}}",
    "{{HEADER_IMAGE_URL}}",
    "{{INTRO_1}}",
    "{{INTRO_2}}",
    "{{HOOFD_CTA_URL}}",
    "{{HOOFD_CTA_TEKST}}",
    "{{SLOT_CTA_URL}}",
    "{{SLOT_CTA_TEKST}}",
    "{{BRAND_NAME}}",
    "{{BRAND_ADRES}}",
    "{{BRAND_POSTCODE_STAD}}",
    "{{BRAND_EMAIL}}",
    "{{BRAND_TELEFOON}}",
    "{{BRAND_KVK}}",
    "{{WEBSITE_URL}}",
    "{{LOGO_URL}}",
    "{{FACEBOOK_URL}}",
    "{{INSTAGRAM_URL}}",
    "{{YOUTUBE_URL}}",
    "{{KAART_TITEL}}",
    "{{KAART_SUBTITEL}}",
    "{{KAART_PRIJS}}",
    "{{KAART_URL}}",
    "{{KAART_IMAGE_URL}}",
    "{{KAART_KNOP_TEKST}}",
    "{{KAART_LABEL}}",
)

_MARKERS = (
    SECTION_START,
    SECTION_END,
    CARD_TPL_START,
    CARD_TPL_END,
    CARD_ROW_START,
    CARD_ROW_END,
)

# Deze routes vervangen ontwerp door door ons gegenereerde markup; bij toolproof
# ten strengste verboden (het ontwerp moet van de klant blijven).
FORBIDDEN_TOKENS = (
    "<!-- ##CARDS## -->",
    "<!-- ##BANNERS## -->",
    "<!-- ##SECTIES## -->",
    "{{HEADER_CTA}}",
    "{{FOOTER_CONTACT}}",
)

_VAK_PATTERN = re.compile(r"\{\{VAK_[A-Z0-9_]+\}\}")
# Alleen ONZE token-stijl ({{HOOFDLETTERS_MET_UNDERSCORES}}); ESP-tags zoals
# {{ unsubscribe }} of {{ contact.EMAIL }} hebben spaties/kleine letters en
# blijven gewoon toegestaan als vaste tekst.
_ANY_PLACEHOLDER = re.compile(r"\{\{[A-Z][A-Z0-9_]*\}\}")


def _style_gap(token: str) -> str:
    if "SPACING" in token:
        return _GAP_SPACING
    if token == "{{STYLE_FONT}}":
        return _GAP_FONT
    return _GAP_COLOR


def _gap_for(token: str) -> str | None:
    """Gat-patroon voor een token; None = marker (pure insertie, geen gat)."""
    if token in _MARKERS:
        return None
    if token in TEMPLATE_TOKENS:
        return _style_gap(token)
    return _GAP_FREE


def _known_tokens() -> list[str]:
    """Alle toegestane tokens, langste eerst (voor eenduidige segmentatie)."""
    tokens = list(_CONTENT_TOKENS) + list(TEMPLATE_TOKENS) + list(_MARKERS)
    return sorted(tokens, key=len, reverse=True)


_SEGMENT_RE = re.compile(
    "(" + "|".join(re.escape(t) for t in _known_tokens()) + "|" + _VAK_PATTERN.pattern + ")"
)


@dataclass(frozen=True)
class OpVerdict:
    ok: bool
    reason: str = ""
    bindings: tuple[tuple[str, str], ...] = ()  # (token, originele waarde)


def _reject(reason: str) -> OpVerdict:
    return OpVerdict(ok=False, reason=reason)


def verify_replace_op(find: str, replace: str) -> OpVerdict:
    """Is `replace` een pure inhoud-vervanging van `find`? Zo ja: geef de bindings.

    Elke afwijzing komt met een reden die de AI (via failed) en de admin (via
    het rapport) kunnen begrijpen.
    """
    if len(find) > MAX_FIND_CHARS:
        return _reject("operatie te groot; splits hem op in kleinere vervangingen")
    for verboden in FORBIDDEN_TOKENS:
        if verboden in replace:
            return _reject(
                f"{verboden} is bij toolproof niet toegestaan: het vervangt het "
                "ontwerp van de klant door gegenereerde opmaak"
            )

    segments = _SEGMENT_RE.split(replace)
    tokens = [seg for i, seg in enumerate(segments) if i % 2 == 1]
    literals = [seg for i, seg in enumerate(segments) if i % 2 == 0]

    # Onbekende {{...}}-tokens in de literal-delen zijn niet toegestaan.
    for literal in literals:
        onbekend = _ANY_PLACEHOLDER.search(literal)
        if onbekend:
            return _reject(
                f"onbekende placeholder {onbekend.group(0)} is niet toegestaan; "
                "gebruik alleen de gedocumenteerde placeholders of {{VAK_*}}-vakken"
            )
    if not tokens:
        return _reject(
            "replace bevat geen enkele bekende placeholder; toolproof mag alleen "
            "inhoud door placeholders vervangen, niets herschrijven"
        )
    if len(tokens) > MAX_TOKENS_PER_OP:
        return _reject("te veel placeholders in één operatie; splits hem op")

    # Twee gat-dragende tokens direct tegen elkaar: gaten zijn dan niet eenduidig.
    for i in range(len(tokens) - 1):
        if literals[i + 1] == "" and _gap_for(tokens[i]) and _gap_for(tokens[i + 1]):
            return _reject(
                f"{tokens[i]} en {tokens[i + 1]} staan direct tegen elkaar; zet er "
                "vaste tekst tussen of splits de operatie op"
            )

    # Regex: literals letterlijk, per gat-token een capture-groep.
    pattern_parts: list[str] = [re.escape(literals[0])]
    gap_tokens: list[str] = []
    for token, literal in zip(tokens, literals[1:]):
        gap = _gap_for(token)
        if gap is None:
            pass  # marker: pure insertie, niets uit find consumeren
        else:
            pattern_parts.append(f"({gap})")
            gap_tokens.append(token)
        pattern_parts.append(re.escape(literal))
    match = re.fullmatch("".join(pattern_parts), find, re.DOTALL)
    if match is None:
        return _reject(
            "replace is geen pure inhoud-vervanging van find: alleen concrete "
            "waarden mogen door placeholders vervangen worden, de markup zelf "
            "moet byte-voor-byte gelijk blijven"
        )

    # Zelfde token twee keer binnen deze op: de waarden moeten gelijk zijn.
    bindings: dict[str, str] = {}
    for token, waarde in zip(gap_tokens, match.groups()):
        if token in bindings and bindings[token] != waarde:
            return _reject(
                f"{token} zou binnen één operatie twee verschillende waarden "
                f"vervangen ({bindings[token]!r} en {waarde!r}); splits de operatie op"
            )
        bindings[token] = waarde
    return OpVerdict(ok=True, bindings=tuple(bindings.items()))


@dataclass
class Extractie:
    """Verzamelt per token de originele waarde, met conflictdetectie over alle ops."""

    waarden: dict[str, str] = field(default_factory=dict)

    def bind(self, bindings: tuple[tuple[str, str], ...]) -> str | None:
        """Neem bindings over; geef een foutreden terug bij een conflict (en
        neem dan niets van deze operatie over)."""
        for token, waarde in bindings:
            bestaand = self.waarden.get(token)
            if bestaand is not None and bestaand != waarde:
                return (
                    f"{token} zou zowel {bestaand!r} als {waarde!r} vervangen; "
                    "kies per element een eigen token (bv. aparte knopgroepen) of "
                    "laat één van beide staan"
                )
        for token, waarde in bindings:
            self.waarden[token] = waarde
        return None


def extract_styles(extractie: Extractie) -> tuple[dict, list[str]]:
    """Stijl-tokens -> styles-dict met de ORIGINELE waarden (de basis-stijl).

    Geeft (styles, notes) terug. Ongeldige waarden horen hier niet meer voor te
    komen (de gat-patronen zijn restrictief), maar worden voor de zekerheid
    overgeslagen met een note.
    """
    styles: dict = {}
    notes: list[str] = []
    for token, sleutel in TEMPLATE_TOKENS.items():
        waarde = extractie.waarden.get(token)
        if waarde is None:
            continue
        if "SPACING" in token:
            styles[sleutel] = int(waarde)
        elif token == "{{STYLE_FONT}}":
            font_key = _font_key(waarde)
            if font_key is None:
                notes.append(
                    f"lettertype {waarde!r} staat niet in de mail-veilige lijst; "
                    "de font-family is letterlijk blijven staan"
                )
                continue
            styles[FONT_KEY] = font_key  # opslag-sleutel is 'font_family', niet 'font
        else:
            if not is_valid_hex_color(waarde):
                notes.append(f"kleur {waarde!r} voor {token} overgeslagen (geen hex)")
                continue
            styles[sleutel] = waarde
    if styles:
        beschrijving = ", ".join(f"{k} {v}" for k, v in sorted(styles.items()))
        notes.append(f"Basisstijl overgenomen uit het origineel: {beschrijving}")
    return styles, notes


def _font_key(stack: str) -> str | None:
    """Reverse-map een font-family-stack naar een sleutel uit EMAIL_SAFE_FONTS."""
    normalized = re.sub(r"""["'\s]""", "", stack).lower()
    for key, known in EMAIL_SAFE_FONTS.items():
        if re.sub(r"""["'\s]""", "", known).lower() == normalized:
            return key
    return None


# -- replace_range: alleen kaart-kopieën verwijderen ---------------------------


_DATA_ATTRS = ("href", "src", "alt", "title")


def _tag_skeleton(fragment: str) -> tuple[str, ...]:
    """Structuur-handtekening van een HTML-fragment: per tag de naam plus de
    attributen. Attribuutwaarden tellen mee (een <td class="disclaimer"> is
    GEEN kopie van <td class="kaart">), behalve de data-attributen href/src/
    alt/title: die verschillen legitiem tussen kaart-kopieën en worden
    gemaskeerd. Tekstinhoud telt niet mee (productnamen verschillen)."""
    skeleton: list[str] = []
    for m in re.finditer(r"<\s*(/?)\s*([a-zA-Z0-9]+)([^>]*)>", fragment):
        sluit, naam, attrs = m.group(1), m.group(2).lower(), m.group(3)
        if sluit:
            skeleton.append(f"/{naam}")
            continue
        parts = []
        for am in re.finditer(r"""([a-zA-Z-]+)\s*=\s*("[^"]*"|'[^']*')""", attrs):
            attr = am.group(1).lower()
            waarde = "*" if attr in _DATA_ATTRS else am.group(2)
            parts.append(f"{attr}={waarde}")
        skeleton.append(naam + "|" + ",".join(sorted(parts)))
    return tuple(skeleton)


def _kept_card_skeletons(html: str) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]] | None:
    """(kaart-skelet, rij-prefix-skelet, rij-suffix-skelet) van het bewaarde blok."""
    card_start = html.find(CARD_TPL_START)
    card_end = html.find(CARD_TPL_END, card_start)
    if card_start == -1 or card_end == -1:
        return None
    card = html[card_start + len(CARD_TPL_START):card_end]
    row_start = html.find(CARD_ROW_START)
    row_end = html.find(CARD_ROW_END, row_start)
    prefix: str = ""
    suffix: str = ""
    if row_start != -1 and row_end != -1 and row_start < card_start and card_end <= row_end:
        prefix = html[row_start + len(CARD_ROW_START):card_start]
        suffix = html[card_end + len(CARD_TPL_END):row_end]
    return _tag_skeleton(card), _tag_skeleton(prefix), _tag_skeleton(suffix)


def verify_range_op(html: str, removed: str, replace: str) -> OpVerdict:
    """replace_range mag alleen overtollige kopieën van de voorbeeldkaart wissen.

    `html` is de template NA de replace-ops (het bewaarde ##KAART##-blok staat
    er dan al in); `removed` is de tekst die de range zou verwijderen.
    """
    if (replace or "").strip():
        return _reject(
            "replace_range mag alleen verwijderen (overtollige kaart-kopieën); "
            "vervangen door nieuwe opmaak is bij toolproof niet toegestaan"
        )
    if _SEGMENT_RE.search(removed) or _ANY_PLACEHOLDER.search(removed):
        return _reject(
            "de te verwijderen sectie bevat al placeholders of markers; die mag "
            "je niet verwijderen"
        )
    if not has_card_block(html):
        return _reject(
            "verwijderen kan alleen als er een bewaard <!-- ##KAART## -->-blok is; "
            "markeer eerst één voorbeeldkaart"
        )
    skeletons = _kept_card_skeletons(html)
    if skeletons is None:
        return _reject("het bewaarde kaartblok is niet compleet (eindmarker ontbreekt)")
    card, row_prefix, row_suffix = skeletons

    rest = list(_tag_skeleton(removed))
    if not rest:
        if not removed.strip():
            return OpVerdict(ok=True)  # alleen witruimte: onschadelijk
        return _reject(
            "de te verwijderen sectie bevat tekst zonder kaart-markup; dat is "
            "geen kaart-kopie en mag niet verwijderd worden"
        )
    guard = 0
    while rest and guard < 50:
        guard += 1
        if card and tuple(rest[:len(card)]) == card:
            del rest[:len(card)]
            continue
        row_unit = list(row_prefix) + list(card) + list(row_suffix)
        if row_unit and tuple(rest[:len(row_unit)]) == tuple(row_unit):
            del rest[:len(row_unit)]
            continue
        if row_prefix and tuple(rest[:len(row_prefix)]) == row_prefix:
            del rest[:len(row_prefix)]
            continue
        if row_suffix and tuple(rest[:len(row_suffix)]) == row_suffix:
            del rest[:len(row_suffix)]
            continue
        break
    if rest:
        return _reject(
            "de te verwijderen sectie is niet herkend als kopie van de "
            "voorbeeldkaart (structuur wijkt af); verwijder de kopieën handmatig "
            "of markeer een passender voorbeeldkaart"
        )
    return OpVerdict(ok=True)
