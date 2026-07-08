"""Template-eigen invulvakken: vrije {{VAK_*}}-placeholders per template.

Waar de vaste placeholders ({{INTRO_1}}, {{KAART_*}}, ...) uit het content-model
komen, mag een template daarnaast eigen tekstvakken declareren: {{VAK_<NAAM>}}.
De chat-agent vult die per nieuwsbrief via `custom_fields` (alleen met informatie
van de gebruiker; niets verzinnen).

Optionele secties: een blok tussen <!-- ##SECTIE## --> en <!-- /##SECTIE## -->
wordt in zijn geheel weggelaten als GEEN ENKEL invulvak erbinnen inhoud kreeg.
Zo kan een rijke template (artikel, Q&A, uitgelicht persoon) veilig secties
overslaan zonder lege koppen of losse randen achter te laten. Garantie in code,
niet in de prompt.
"""

from __future__ import annotations

import re

SLOT_PATTERN = re.compile(r"\{\{VAK_([A-Z0-9_]+)\}\}")
SECTION_START = "<!-- ##SECTIE## -->"
SECTION_END = "<!-- /##SECTIE## -->"


def find_custom_slots(html: str) -> list[str]:
    """Alle eigen invulvakken in een template, uniek en in volgorde van voorkomen."""
    seen: list[str] = []
    for name in SLOT_PATTERN.findall(html or ""):
        if name not in seen:
            seen.append(name)
    return seen


def normalize_custom_fields(raw: dict) -> dict[str, str]:
    """Sleutels naar VAK-vorm (hoofdletters, zonder 'VAK_'-prefix), waarden gestript."""
    clean: dict[str, str] = {}
    for key, value in (raw or {}).items():
        name = str(key).strip().upper()
        if name.startswith("VAK_"):
            name = name[len("VAK_"):]
        clean[name] = str(value).strip()
    return clean


def _fill(html: str, fields: dict[str, str]) -> str:
    return SLOT_PATTERN.sub(lambda m: fields.get(m.group(1), ""), html)


def fill_custom_fields(html: str, fields: dict[str, str]) -> str:
    """Vul de {{VAK_*}}-placeholders en laat lege ##SECTIE##-blokken vervallen.

    Volgorde per sectieblok: heeft geen enkel vak erbinnen inhoud, dan verdwijnt
    het hele blok (inclusief markers); anders blijft het blok staan (zonder
    markers) met de vakken ingevuld. Vakken buiten sectieblokken worden gewoon
    ingevuld; een leeg vak wordt een lege string.
    """
    fields = normalize_custom_fields(fields)
    parts: list[str] = []
    rest = html or ""
    while True:
        start = rest.find(SECTION_START)
        if start == -1:
            break
        end = rest.find(SECTION_END, start)
        if end == -1:
            break  # niet-afgesloten blok: laat staan, geen halve verwijderingen
        inner = rest[start + len(SECTION_START):end]
        parts.append(_fill(rest[:start], fields))
        slots = SLOT_PATTERN.findall(inner)
        if any(fields.get(name) for name in slots):
            parts.append(_fill(inner, fields))
        rest = rest[end + len(SECTION_END):]
    parts.append(_fill(rest, fields))
    return "".join(parts)
