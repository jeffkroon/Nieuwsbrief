"""De VOLLEDIGE productcatalogus van een klantensite, niet alleen pagina 1.

Aanleiding (Ohcascas): /collections/all heeft 178 producten over 4 pagina's, de
tool las alleen pagina 1 (45 producten) en de assistent meldde daarna stellig dat
er "maar één soort zilveren ring" was, terwijl er vijf waren.

Twee routes, allebei eerlijk over wat ze gezien hebben (`total`, `complete`):
1. Shopify: de openbare productlijst (/collections/<handle>/products.json of
   /products.json), alle pagina's. Exact: titel, prijs, foto en URL komen zo van
   de shop zelf, zonder LLM en dus ook zonder kosten of afkap-risico.
2. WooCommerce: de openbare Store API (/wp-json/wc/store/v1/products), alle
   pagina's, per taal (WPML: ?lang=en). Ook exact en zonder LLM.
3. Andere sites: de paginering van de overzichtspagina volgen (?page=2, ...) en
   per pagina de LLM-extractie draaien, tot een vaste grens.
Een zoekterm (`query`, bv. "zilveren ringen") filtert daarna in code.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from app.newsletter.extraction import SITE_HEADERS, normalize_price

SHOPIFY_PAGE_SIZE = 250
MAX_SHOPIFY_PAGES = 8  # 2.000 producten; ruim genoeg voor een nieuwsbrief-keuze
MAX_HTML_PAGES = 15  # per pagina een Haiku-extractie (~1-2 cent): begrensd houden
WOO_PAGE_SIZE = 100
MAX_WOO_PAGES = 30  # 3.000 producten
MAX_RETURNED = 40  # zonder zoekterm: maximaal zoveel naar de assistent (~3k tokens); met query gericht

# Nederlands/Engels door elkaar in productnamen ("Ring Silver", "Ketting (Zilver)").
_SYNONIEMEN = {"zilver": ("silver",), "silver": ("zilver",), "goud": ("gold",), "gold": ("goud",)}


@dataclass(frozen=True)
class Catalog:
    products: tuple[dict, ...]
    total: int
    complete: bool
    source: str  # "shopify", "woocommerce" of "pagina's"
    pages_read: int


# ---------------------------------------------------------------- Shopify
def _origin(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _shopify_endpoint(url: str) -> str:
    m = re.search(r"/collections/([^/?#]+)", urlsplit(url).path)
    base = _origin(url)
    return f"{base}/collections/{m.group(1)}/products.json" if m else f"{base}/products.json"


def _get_json(client: httpx.Client | None, url: str, params: dict) -> dict | None:
    try:
        if client is not None:
            resp = client.get(url, params=params, headers=SITE_HEADERS)
        else:
            with httpx.Client(timeout=20.0, follow_redirects=True) as c:
                resp = c.get(url, params=params, headers=SITE_HEADERS)
    except httpx.HTTPError:
        return None
    if resp.status_code != 200 or "json" not in resp.headers.get("content-type", ""):
        return None
    try:
        body = resp.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) and isinstance(body.get("products"), list) else None


def _shopify_product(origin: str, p: dict) -> dict | None:
    handle = p.get("handle")
    title = (p.get("title") or "").strip()
    if not handle or not title:
        return None
    variants = [v for v in p.get("variants") or [] if isinstance(v, dict)]
    beschikbaar = [v for v in variants if v.get("available", True)]
    kandidaten = beschikbaar or variants
    # Sorteren op alleen de prijs: bij gelijke prijzen mag Python geen dicts vergelijken.
    prijzen = sorted(
        ((float(v["price"]), v) for v in kandidaten if _is_getal(v.get("price"))),
        key=lambda paar: paar[0],
    )
    product = {
        "name": title,
        "url": f"{origin}/products/{handle}",
        "price": _euro(prijzen[0][0]) if prijzen else None,
        "image_url": next((i.get("src") for i in p.get("images") or [] if i.get("src")), None),
        "available": bool(beschikbaar),
    }
    if prijzen:
        was = prijzen[0][1].get("compare_at_price")
        if _is_getal(was) and float(was) > prijzen[0][0]:
            product["was_price"] = _euro(float(was))
    if p.get("product_type"):
        product["type"] = p["product_type"]
    return product


def _euro(bedrag: float) -> str:
    """59.95 -> '€ 59,95'; 60.0 -> '€ 60,00' (zelfde notatie als gescrapete prijzen)."""
    return normalize_price(f"{bedrag:.2f}".replace(".", ","))


def _is_getal(waarde) -> bool:
    try:
        float(waarde)
        return True
    except (TypeError, ValueError):
        return False


def shopify_catalog(url: str, client: httpx.Client | None = None) -> Catalog | None:
    """Alle producten via de Shopify-productlijst; None als dit geen Shopify-shop is."""
    endpoint = _shopify_endpoint(url)
    origin = _origin(url)
    producten: list[dict] = []
    for pagina in range(1, MAX_SHOPIFY_PAGES + 1):
        body = _get_json(client, endpoint, {"limit": SHOPIFY_PAGE_SIZE, "page": pagina})
        if body is None:
            return None if pagina == 1 else Catalog(tuple(producten), len(producten), False, "shopify", pagina - 1)
        rij = [
            q for q in (_shopify_product(origin, p) for p in body["products"] if isinstance(p, dict)) if q
        ]
        producten.extend(rij)
        if len(body["products"]) < SHOPIFY_PAGE_SIZE:
            return Catalog(tuple(producten), len(producten), True, "shopify", pagina)
    return Catalog(tuple(producten), len(producten), False, "shopify", MAX_SHOPIFY_PAGES)


# ---------------------------------------------------------------- WooCommerce
_TAAL_PREFIX = re.compile(r"^/([a-z]{2})(?:/|$)")
_HTML_LANG = re.compile(r"""<html[^>]*\blang=["']([a-z]{2})""", re.I)


def _woo_lang(url: str, client: httpx.Client | None) -> str | None:
    """Taal van de shop-URL: /en/... -> en; anders het lang-attribuut van de pagina."""
    m = _TAAL_PREFIX.match(urlsplit(url).path)
    if m:
        return m.group(1)
    try:
        resp = client.get(url, headers=SITE_HEADERS) if client else httpx.get(url, headers=SITE_HEADERS, timeout=20, follow_redirects=True)
    except httpx.HTTPError:
        return None
    m = _HTML_LANG.search(resp.text[:5000])
    return m.group(1).lower() if m else None


def _woo_page(client: httpx.Client | None, endpoint: str, params: dict) -> tuple[list, int | None] | None:
    try:
        if client is not None:
            resp = client.get(endpoint, params=params, headers=SITE_HEADERS)
        else:
            with httpx.Client(timeout=30.0, follow_redirects=True) as c:
                resp = c.get(endpoint, params=params, headers=SITE_HEADERS)
    except httpx.HTTPError:
        return None
    if resp.status_code != 200 or "json" not in resp.headers.get("content-type", ""):
        return None
    # Sommige plugins zetten tekst vóór de JSON; begin bij het eerste '['.
    start = resp.content.find(b"[")
    if start < 0:
        return None
    try:
        rijen = json.loads(resp.content[start:])
    except ValueError:
        return None
    if not isinstance(rijen, list):
        return None
    totaal = resp.headers.get("x-wp-totalpages")
    return rijen, int(totaal) if totaal and totaal.isdigit() else None


def _woo_product(p: dict) -> dict | None:
    naam = html_lib.unescape((p.get("name") or "").strip())
    link = p.get("permalink")
    if not naam or not link:
        return None
    prijzen = p.get("prices") or {}
    decimalen = int(prijzen.get("currency_minor_unit") or 2)

    def bedrag(waarde):
        return _euro(int(waarde) / (10 ** decimalen)) if str(waarde or "").isdigit() else None

    product = {
        "name": naam,
        "url": link,
        "price": bedrag(prijzen.get("price")),
        "image_url": next((i.get("src") for i in p.get("images") or [] if i.get("src")), None),
        "available": bool(p.get("is_in_stock", True)),
    }
    was = bedrag(prijzen.get("regular_price"))
    if was and prijzen.get("regular_price") != prijzen.get("price"):
        product["was_price"] = was
    categorieen = [html_lib.unescape(c.get("name", "")) for c in p.get("categories") or [] if c.get("name")]
    if categorieen:
        product["type"] = ", ".join(categorieen)
    return product


def woocommerce_catalog(url: str, client: httpx.Client | None = None) -> Catalog | None:
    """Alle producten via de WooCommerce Store API; None als die er niet is."""
    endpoint = f"{_origin(url)}/wp-json/wc/store/v1/products"
    # Eerst goedkoop kijken of de API er is; pas dan de taal bepalen (kan een
    # pagina-ophaalactie kosten) en de hele lijst lezen.
    if _woo_page(client, endpoint, {"per_page": 1, "page": 1}) is None:
        return None
    taal = _woo_lang(url, client)
    basis = {"per_page": WOO_PAGE_SIZE, **({"lang": taal} if taal else {})}
    producten: list[dict] = []
    for pagina in range(1, MAX_WOO_PAGES + 1):
        uitkomst = _woo_page(client, endpoint, {**basis, "page": pagina})
        if uitkomst is None:
            return None if pagina == 1 else Catalog(tuple(producten), len(producten), False, "woocommerce", pagina - 1)
        rijen, totaal_paginas = uitkomst
        producten.extend(q for q in (_woo_product(r) for r in rijen if isinstance(r, dict)) if q)
        laatste = totaal_paginas is not None and pagina >= totaal_paginas
        if laatste or len(rijen) < WOO_PAGE_SIZE:
            return Catalog(tuple(producten), len(producten), True, "woocommerce", pagina)
    return Catalog(tuple(producten), len(producten), False, "woocommerce", MAX_WOO_PAGES)


# ---------------------------------------------------------------- andere sites
def page_urls(html: str, url: str) -> list[str]:
    """Alle vervolgpagina's van een overzicht (?page=N), in volgorde, zonder de huidige."""
    nummers = {
        int(m.group(1))
        for m in re.finditer(r"""href=["'][^"']*[?&]page=(\d+)""", html_lib.unescape(html))
    }
    basis = url.split("#")[0]
    zonder = re.sub(r"([?&])page=\d+&?", r"\1", basis).rstrip("?&")
    teken = "&" if "?" in zonder else "?"
    # "1 2 3 ... 12": ook de niet getoonde tussenpagina's bestaan.
    hoogste = max(nummers, default=1)
    return [f"{zonder}{teken}page={n}" for n in range(2, hoogste + 1)]


def paged_catalog(
    url: str,
    first_html: str,
    fetch: Callable[[str], tuple[int | None, str]],
    extract: Callable[[str, str], list[dict]],
) -> Catalog:
    """Overzichtspagina plus vervolgpagina's (tot MAX_HTML_PAGES); extract(html, url)."""
    alle_vervolg = page_urls(first_html, url)
    te_lezen = alle_vervolg[: MAX_HTML_PAGES - 1]
    gezien: dict[str, dict] = {}
    gelezen = 0
    for pagina_url, html in [(url, first_html), *((u, None) for u in te_lezen)]:
        if html is None:
            status, html = fetch(pagina_url)
            if status != 200:
                break
        gelezen += 1
        for product in extract(html, pagina_url):
            sleutel = urljoin(pagina_url, product.get("url") or "") or product.get("name", "")
            gezien.setdefault(sleutel, product)
    compleet = gelezen == 1 + len(alle_vervolg)
    return Catalog(tuple(gezien.values()), len(gezien), compleet, "pagina's", gelezen)


# ---------------------------------------------------------------- zoeken
def _stam(woord: str) -> str:
    for achtervoegsel in ("en", "s", "e"):
        if woord.endswith(achtervoegsel) and len(woord) > len(achtervoegsel) + 3:
            return woord[: -len(achtervoegsel)]
    return woord


def _woorden(tekst: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9à-ÿ]+", tekst.lower()) if len(w) > 1]


def matches(product: dict, query: str) -> bool:
    """Alle zoekwoorden (gestemd, NL/EN-synoniemen) komen voor in naam of type."""
    hooiberg = " ".join(str(product.get(k) or "") for k in ("name", "type")).lower()
    for woord in _woorden(query):
        stam = _stam(woord)
        opties = (stam, *_SYNONIEMEN.get(stam, ()))
        if not any(optie in hooiberg for optie in opties):
            return False
    return True


def filter_products(products: tuple[dict, ...] | list[dict], query: str | None) -> list[dict]:
    if not query or not query.strip():
        return list(products)
    return [p for p in products if matches(p, query)]
