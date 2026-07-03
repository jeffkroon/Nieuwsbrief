"""Automatisch invullen van een nieuw bedrijf op basis van naam + website.

Deterministisch waar het kan (socials, logo, themakleur, og:image via regex),
een goedkope LLM-extractie (Haiku) voor de contactgegevens uit de homepage en
contactpagina. Het resultaat is een VOORSTEL: de admin controleert en slaat op;
er wordt niets automatisch aangemaakt en niets verzonnen (ontbrekend = leeg +
melding in notes).
"""

from __future__ import annotations

import html as html_lib
import json
import re
from urllib.parse import urljoin, urlparse

import httpx

from app.newsletter import extraction

_SOCIAL_PATTERNS = {
    "facebook_url": re.compile(r'https?://(?:www\.)?facebook\.com/[^\s"\'<>)]+', re.I),
    "instagram_url": re.compile(r'https?://(?:www\.)?instagram\.com/[^\s"\'<>)]+', re.I),
    "youtube_url": re.compile(r'https?://(?:www\.)?youtube\.com/[^\s"\'<>)]+', re.I),
}
_HEX = re.compile(r"^#[0-9a-fA-F]{3,8}$")

_DETAILS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "email": {"type": ["string", "null"]},
        "phone": {"type": ["string", "null"]},
        "address": {"type": ["string", "null"]},
        "postcode_city": {"type": ["string", "null"]},
        "kvk": {"type": ["string", "null"]},
        "content_types": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "button_text": {"type": "string"},
                    "source_url": {"type": ["string", "null"]},
                    "has_price": {"type": "boolean"},
                },
                "required": ["name", "button_text", "source_url", "has_price"],
            },
        },
    },
    "required": ["email", "phone", "address", "postcode_city", "kvk", "content_types"],
}

_DETAILS_SYSTEM = (
    "Je krijgt de tekstinhoud van de website van een bedrijf (homepage en eventueel "
    "de contactpagina). Haal de bedrijfsgegevens eruit die ECHT in de tekst staan: "
    "e-mailadres, telefoonnummer, straat + huisnummer (address), postcode + plaats "
    "(postcode_city) en KVK-nummer. Staat iets er niet, geef null; verzin niets. "
    "Stel daarnaast maximaal 3 nieuwsbrief-soorten voor die bij dit bedrijf passen "
    "(bv. 'Producten' voor een webshop, 'Cases' voor een bureau, 'Acties'): per soort "
    "een korte naam, een passende knoptekst (bv. 'SHOP NU' of 'Lees meer'), de "
    "bijbehorende pagina-URL exact zoals in de tekst (of null), en of er prijzen bij "
    "horen. Gebruik alleen URL's die letterlijk in de tekst staan."
)


def _first_social(html: str, pattern: re.Pattern) -> str | None:
    m = pattern.search(html)
    if not m:
        return None
    return html_lib.unescape(m.group(0)).rstrip('\\/"')


def _find_theme_color(html: str) -> str | None:
    m = re.search(
        r'(?is)<meta[^>]+name=["\']theme-color["\'][^>]+content=["\']([^"\']+)["\']', html
    ) or re.search(
        r'(?is)<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']theme-color["\']', html
    )
    if m and _HEX.match(m.group(1).strip()):
        return m.group(1).strip()
    return None


def _find_logo(html: str, base_url: str) -> str | None:
    """Eerste <img> die op een logo lijkt (src/class/alt/id bevat 'logo')."""
    for tag in re.findall(r"(?is)<img[^>]+>", html):
        if "logo" not in tag.lower():
            continue
        m = re.search(r'src=["\']([^"\']+)["\']', tag)
        if m:
            return urljoin(base_url, html_lib.unescape(m.group(1)))
    return None


def _find_contact_url(html: str, base_url: str) -> str | None:
    host = urlparse(base_url).netloc
    for m in re.finditer(r'(?i)href=["\']([^"\']*contact[^"\']*)["\']', html):
        url = urljoin(base_url, html_lib.unescape(m.group(1)))
        if urlparse(url).netloc == host:
            return url
    return None


def _extract_details(llm, text: str, website_url: str) -> dict:
    response = llm.messages.create(
        model=extraction.EXTRACT_MODEL,
        max_tokens=1500,
        system=_DETAILS_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": _DETAILS_SCHEMA}},
        messages=[{"role": "user", "content": f"Website: {website_url}\n\n{text}"}],
    )
    raw = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"email": None, "phone": None, "address": None, "postcode_city": None,
                "kvk": None, "content_types": []}


def prefill_company(
    llm, *, name: str, website_url: str, http_client: httpx.Client | None = None
) -> dict:
    """Bouw een config-voorstel voor een nieuw bedrijf vanaf de website.

    Geeft {"config": {...}, "content_types": [...], "notes": [...]} terug.
    Ontbrekende gegevens blijven leeg en worden in notes gemeld (niets verzinnen).
    """
    status, home_html = extraction.fetch_page(website_url, http_client)
    if status != 200:
        raise ValueError(f"Website onbereikbaar: {website_url} (status {status})")

    text = extraction.html_to_text(home_html, website_url)
    contact_url = _find_contact_url(home_html, website_url)
    if contact_url:
        c_status, contact_html = extraction.fetch_page(contact_url, http_client)
        if c_status == 200:
            text += "\n\nCONTACTPAGINA:\n" + extraction.html_to_text(
                contact_html, contact_url, max_chars=15_000
            )

    details = _extract_details(llm, text, website_url)
    og_image = extraction.extract_og_image(home_html)
    logo = _find_logo(home_html, website_url)
    theme_color = _find_theme_color(home_html)
    socials = {key: _first_social(home_html, pat) for key, pat in _SOCIAL_PATTERNS.items()}

    config = {
        "brand_name": name,
        "website_url": website_url,
        "brand_email": details.get("email") or "",
        "brand_telefoon": details.get("phone") or "",
        "brand_adres": details.get("address") or "",
        "brand_postcode_stad": details.get("postcode_city") or "",
        "brand_kvk": details.get("kvk") or "",
        "primary_color": theme_color or "#FF7200",
        "logo_url": logo or og_image or "",
        "dummy_image_url": og_image or logo or "",
        "header_image_url": og_image or "",
        "facebook_url": socials["facebook_url"] or "",
        "instagram_url": socials["instagram_url"] or "",
        "youtube_url": socials["youtube_url"] or "",
    }

    labels = {
        "brand_email": "e-mailadres", "brand_telefoon": "telefoonnummer",
        "brand_adres": "adres", "brand_postcode_stad": "postcode + plaats",
        "brand_kvk": "KVK-nummer", "logo_url": "logo", "dummy_image_url": "fallback-foto",
    }
    notes = [
        f"{label} niet gevonden op de site, vul handmatig in"
        for key, label in labels.items()
        if not config.get(key)
    ]
    if not theme_color:
        notes.append("geen themakleur gevonden, standaardkleur ingevuld")
    for key in ("facebook_url", "instagram_url", "youtube_url"):
        if not config[key]:
            notes.append(f"{key.split('_')[0]} niet gevonden (valt bij opslaan terug op de website)")

    content_types = [
        ct for ct in details.get("content_types", [])
        if isinstance(ct, dict) and ct.get("name")
    ][:3]
    return {"config": config, "content_types": content_types, "notes": notes}
