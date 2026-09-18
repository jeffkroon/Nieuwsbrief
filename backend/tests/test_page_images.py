"""Tests voor het vinden en meten van foto's op een klantpagina."""

from __future__ import annotations

import io

import httpx
from PIL import Image

from app.newsletter.page_images import (
    MIN_BANNER_WIDTH,
    banner_candidates,
    best_product_image,
    find_page_images,
    measure_image,
)

BASE = "https://shop.example.nl/collectie/"

HTML = """<html><head>
<meta property="og:image" content="/media/hero-og.jpg">
<script type="application/ld+json">{"@graph":[
  {"@type":"Organization","logo":"/media/logo-org.png"},
  {"@type":"WebPage","primaryImageOfPage":{"@id":"#hoofdfoto"}},
  {"@type":"ImageObject","@id":"#hoofdfoto","contentUrl":"https://cdn.example.nl/hoofd.jpg"}
]}</script>
</head><body>
<img src="/assets/Bedrijf_Logo.svg" alt="Bedrijf logo" width="200">
<img src="data:image/png;base64,AAAA" alt="vlag" width="16" height="11">
<img src="/media/partner-remeha.png" alt="Remeha">
<img src="/media/pixel.gif" width="1" height="1">
<img src="/media/product-a.jpg" alt="KPN IOT M2M EU">
<img data-src="/media/lazy-b.jpg" alt="Lazy product" width="640" height="480">
<img srcset="/media/s-400.jpg 400w, /media/s-1200.jpg 1200w" src="/media/s-400.jpg" alt="Set">
<div style="background-image:url('/media/hero-bg.jpg')"></div>
<style>.hero{background:url(&quot;/media/css-bg.jpg&quot;) no-repeat}</style>
<img src="/media/product-a.jpg" alt="dubbel">
</body></html>"""


def _png(breedte: int, hoogte: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (breedte, hoogte), (255, 114, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


def _client(afmetingen: dict[str, tuple[int, int] | None]) -> httpx.Client:
    """Nep-server: per bestandsnaam een PNG van die grootte, of een 404."""

    def handler(request: httpx.Request) -> httpx.Response:
        naam = request.url.path.rsplit("/", 1)[-1]
        maat = afmetingen.get(naam)
        if maat is None:
            return httpx.Response(404)
        data = _png(*maat)
        return httpx.Response(200, content=data, headers={"content-type": "image/png",
                                                          "content-length": str(len(data))})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_ruis_valt_weg_en_echte_fotos_blijven() -> None:
    urls = [k.filename for k in find_page_images(HTML, BASE)]
    for ruis in ("Bedrijf_Logo.svg", "partner-remeha.png", "pixel.gif", "logo-org.png"):
        assert ruis not in urls
    assert "AAAA" not in " ".join(urls)  # data-URI
    for echt in ("hero-og.jpg", "hoofd.jpg", "product-a.jpg", "lazy-b.jpg", "s-1200.jpg",
                 "hero-bg.jpg", "css-bg.jpg"):
        assert echt in urls, echt


def test_betrouwbaarste_bron_staat_voorop_en_dubbelen_zijn_weg() -> None:
    kandidaten = find_page_images(HTML, BASE)
    assert kandidaten[0].source == "jsonld" and kandidaten[0].filename == "hoofd.jpg"
    assert kandidaten[1].source == "og"
    assert [k.filename for k in kandidaten].count("product-a.jpg") == 1


def test_jsonld_volgt_id_verwijzing_maar_slaat_organisatielogo_over() -> None:
    urls = [k.url for k in find_page_images(HTML, BASE)]
    assert "https://cdn.example.nl/hoofd.jpg" in urls
    assert not any("logo-org" in u for u in urls)


def test_srcset_kiest_de_breedste_variant() -> None:
    urls = [k.filename for k in find_page_images(HTML, BASE)]
    assert "s-1200.jpg" in urls and "s-400.jpg" not in urls


def test_relatieve_paden_worden_absoluut() -> None:
    assert all(k.url.startswith("https://") for k in find_page_images(HTML, BASE))


def test_lege_of_kapotte_html_geeft_niets() -> None:
    assert find_page_images("", BASE) == []
    assert find_page_images("<html><script type='application/ld+json'>{kapot</script>", BASE) == []


def test_meten_leest_echte_afmetingen() -> None:
    client = _client({"hero-bg.jpg": (1200, 600)})
    gemeten = measure_image(f"{BASE}../media/hero-bg.jpg".replace("collectie/../", ""), client)
    assert gemeten is not None
    assert (gemeten.width, gemeten.height) == (1200, 600)
    assert gemeten.landscape and gemeten.total_bytes


def test_meten_weigert_niet_afbeeldingen_en_404() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".html"):
            return httpx.Response(200, text="<html>", headers={"content-type": "text/html"})
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert measure_image("https://x.nl/pagina.html", client) is None
    assert measure_image("https://x.nl/weg.jpg", client) is None


def test_bannerkandidaten_alleen_liggend_en_breed_genoeg() -> None:
    client = _client({
        "hoofd.jpg": (MIN_BANNER_WIDTH, 300),          # liggend, breed genoeg
        "hero-og.jpg": (400, 200),                      # te smal
        "product-a.jpg": (800, 1200),                   # staand
        "hero-bg.jpg": (1600, 900),
        "css-bg.jpg": (1600, 900),
    })
    banners = banner_candidates(HTML, BASE, client=client)
    namen = [b.filename for b in banners]
    assert "hoofd.jpg" in namen and "hero-bg.jpg" in namen
    assert "hero-og.jpg" not in namen and "product-a.jpg" not in namen
    assert all(b.landscape and b.width >= MIN_BANNER_WIDTH for b in banners)


def test_bannerkandidaten_stoppen_bij_de_limiet() -> None:
    client = _client({n: (1600, 900) for n in
                      ("hoofd.jpg", "hero-og.jpg", "product-a.jpg", "lazy-b.jpg", "s-1200.jpg",
                       "hero-bg.jpg", "css-bg.jpg")})
    assert len(banner_candidates(HTML, BASE, client=client, limit=3)) == 3


def test_productfoto_kiest_betrouwbaarste_bruikbare_en_anders_niets() -> None:
    client = _client({"hoofd.jpg": (100, 100), "hero-og.jpg": (900, 900)})
    assert best_product_image(HTML, BASE, client=client).endswith("hero-og.jpg")
    assert best_product_image(HTML, BASE, client=_client({})) is None


def test_label_gebruikt_alt_of_bestandsnaam() -> None:
    client = _client({"lazy-b.jpg": (1200, 600), "hero-bg.jpg": (1200, 600)})
    labels = [b.label() for b in banner_candidates(HTML, BASE, client=client)]
    assert "Lazy product (1200x600)" in labels
    assert "hero bg (1200x600)" in labels
