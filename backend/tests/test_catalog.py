"""De hele catalogus zien, niet alleen pagina 1 (Ohcascas: 178 producten, 4 pagina's)."""

from __future__ import annotations

import json

import httpx

from app.newsletter import catalog

SHOP = "https://shop.example.nl"


def _shopify(aantal: int, *, ringen: tuple[str, ...] = ()) -> httpx.Client:
    namen = [f"Ketting {i} (Goud)" for i in range(aantal - len(ringen))] + list(ringen)
    producten = [
        {"handle": f"p{i}", "title": naam, "product_type": "",
         "variants": [{"price": "59.95", "available": True, "compare_at_price": "79.95"}],
         "images": [{"src": f"https://cdn/p{i}.jpg"}]}
        for i, naam in enumerate(namen)
    ]
    verzoeken: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        verzoeken.append(str(request.url))
        if not request.url.path.endswith("/products.json"):
            return httpx.Response(404)
        pagina = int(request.url.params.get("page", 1))
        grootte = int(request.url.params.get("limit", 30))
        stuk = producten[(pagina - 1) * grootte: pagina * grootte]
        return httpx.Response(200, json={"products": stuk})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    client.verzoeken = verzoeken  # type: ignore[attr-defined]
    return client


def test_shopify_leest_alle_paginas_van_de_collectie() -> None:
    client = _shopify(600, ringen=("Cuban Ring (Zilver)", "Cross Ring (Zilver)"))
    cat = catalog.shopify_catalog(f"{SHOP}/collections/all", client)
    assert cat is not None and cat.complete and cat.total == 600 and cat.pages_read == 3
    assert all("/collections/all/products.json" in u for u in client.verzoeken)
    p = cat.products[0]
    assert p["price"] == "€ 59,95" and p["was_price"] == "€ 79,95"
    assert p["url"] == f"{SHOP}/products/p0" and p["image_url"] == "https://cdn/p0.jpg"


def test_zoeken_vindt_zilveren_ringen_in_nl_en_en() -> None:
    producten = [
        {"name": "Cuban Ring (Zilver)"}, {"name": "Cross Ring (Goud)"},
        {"name": "Signet Ring Silver"}, {"name": "Cuban Ketting (Zilver)"},
    ]
    gevonden = [p["name"] for p in catalog.filter_products(producten, "zilveren ringen")]
    assert gevonden == ["Cuban Ring (Zilver)", "Signet Ring Silver"]
    assert catalog.filter_products(producten, None) == producten


def test_geen_shopify_geeft_none() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>")))
    assert catalog.shopify_catalog(f"{SHOP}/collectie", client) is None


def test_andere_sites_volgen_de_paginering_en_zijn_eerlijk_over_de_grens() -> None:
    eerste = '<a href="/shop?page=2">2</a><a href="/shop?page=3">3</a><a href="/shop?page=30">30</a>'
    urls = catalog.page_urls(eerste, f"{SHOP}/shop")
    assert urls[0] == f"{SHOP}/shop?page=2" and urls[-1] == f"{SHOP}/shop?page=30" and len(urls) == 29

    opgehaald: list[str] = []

    def fetch(u: str):
        opgehaald.append(u)
        return 200, u

    def extract(html: str, u: str) -> list[dict]:
        return [{"name": f"product op {u}", "url": u}]

    cat = catalog.paged_catalog(f"{SHOP}/shop", eerste, fetch, extract)
    assert cat.pages_read == catalog.MAX_HTML_PAGES
    assert cat.complete is False  # 30 pagina's, maar maximaal MAX_HTML_PAGES gelezen: nooit "alles gezien"
    assert len(opgehaald) == catalog.MAX_HTML_PAGES - 1

    klein = catalog.paged_catalog(f"{SHOP}/shop", '<a href="?page=2">2</a>', fetch, extract)
    assert klein.complete is True and klein.pages_read == 2


def test_varianten_met_gelijke_prijs_crashen_niet() -> None:
    """Gevonden op de echte Ohcascas-shop: gelijke prijzen lieten sorted() dicts vergelijken."""
    product = {"handle": "ring", "title": "Cuban Ring (Zilver)", "variants": [
        {"price": "59.95", "available": True}, {"price": "59.95", "available": False},
        {"price": "49.95", "available": False},
    ], "images": []}
    uit = catalog._shopify_product(SHOP, product)
    assert uit["price"] == "€ 59,95"  # goedkoopste BESCHIKBARE variant
    assert uit["available"] is True and uit["image_url"] is None


def _woo(aantal: int, *, rommel: bytes = b"") -> httpx.Client:
    producten = [
        {"name": f"Gateway &amp; Sensor {i}", "permalink": f"{SHOP}/en/product/p{i}/",
         "prices": {"price": "12950", "regular_price": "14950", "currency_minor_unit": 2},
         "images": [{"src": f"https://cdn/w{i}.png"}], "is_in_stock": i % 2 == 0,
         "categories": [{"name": "LoRaWAN"}]}
        for i in range(aantal)
    ]
    verzoeken: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        verzoeken.append(request)
        if not request.url.path.endswith("/wp-json/wc/store/v1/products"):
            return httpx.Response(404)
        pagina, grootte = int(request.url.params["page"]), int(request.url.params["per_page"])
        stuk = producten[(pagina - 1) * grootte: pagina * grootte]
        paginas = -(-aantal // grootte)
        return httpx.Response(200, content=rommel + json.dumps(stuk).encode(),
                              headers={"content-type": "application/json", "x-wp-totalpages": str(paginas)})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    client.verzoeken = verzoeken  # type: ignore[attr-defined]
    return client


def test_woocommerce_leest_alle_paginas_in_de_juiste_taal() -> None:
    client = _woo(250, rommel=b"BestellenBestellen")  # plugin-tekst voor de JSON (Thingsdata)
    cat = catalog.woocommerce_catalog(f"{SHOP}/en/", client)
    assert cat is not None and cat.complete and cat.total == 250 and cat.pages_read == 3
    lijst = [r for r in client.verzoeken if r.url.params["per_page"] != "1"]  # zonder de probe
    assert len(lijst) == 3 and all(r.url.params["lang"] == "en" for r in lijst)
    p = cat.products[0]
    assert p["name"] == "Gateway & Sensor 0" and p["price"] == "€ 129,50" and p["was_price"] == "€ 149,50"
    assert p["type"] == "LoRaWAN" and cat.products[1]["available"] is False


def test_geen_woocommerce_geeft_none() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html lang='nl'>")))
    assert catalog.woocommerce_catalog(f"{SHOP}/", client) is None
