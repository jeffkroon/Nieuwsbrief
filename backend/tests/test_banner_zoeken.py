"""Banner zoeken op een webshop: geen zwarte videoframes, wel bijgesneden productfoto's,
en een beschrijving per foto zodat de assistent op thema kan kiezen (Ohcascas-casus)."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import httpx
from PIL import Image, ImageDraw

from app.newsletter import banner_check
from app.newsletter.extraction import is_croppable, normalize_banner_url
from app.newsletter.page_images import banner_candidates, find_page_images

SHOP = "https://shop.example.nl"
CDN = f"{SHOP}/cdn/shop/files"


def _jpeg(breedte: int, hoogte: int, *, egaal: bool = False) -> bytes:
    beeld = Image.new("RGB", (breedte, hoogte), (17, 17, 17))
    if not egaal:
        teken = ImageDraw.Draw(beeld)
        for x in range(0, breedte, 8):
            teken.line([(x, 0), (x, hoogte)], fill=(230, 230, 230) if x % 16 else (40, 40, 40), width=3)
    buffer = io.BytesIO()
    beeld.save(buffer, format="JPEG")
    return buffer.getvalue()


def _shop_client(beelden: dict[str, tuple[int, int, bool]]) -> httpx.Client:
    """Nep-CDN: bestandsnaam -> (breedte, hoogte, egaal). ?width= verkleint naar die breedte."""

    def handler(request: httpx.Request) -> httpx.Response:
        naam = request.url.path.rsplit("/", 1)[-1]
        if naam not in beelden:
            return httpx.Response(404)
        breedte, hoogte, egaal = beelden[naam]
        gevraagd = request.url.params.get("width")
        if gevraagd:
            schaal = int(gevraagd) / breedte
            breedte, hoogte = int(gevraagd), max(1, int(hoogte * schaal))
        data = _jpeg(breedte, hoogte, egaal=egaal)
        return httpx.Response(200, content=data, headers={"content-type": "image/jpeg"})

    return httpx.Client(transport=httpx.MockTransport(handler))


PAGINA = f"""<html><body>
<img srcset="{CDN}/preview_images/abc.thumbnail.0000000000.jpg 3200w" alt="">
<img srcset="{CDN}/ketting-zilver.png?v=1&width=3375 3375w" alt="Cuban Ketting (Zilver)">
<img src="https://elders.nl/vierkant.jpg" alt="Niet van de shop">
</body></html>"""


def test_videoframe_is_ruis() -> None:
    urls = [k.url for k in find_page_images(PAGINA, SHOP + "/products/x")]
    assert not any("preview_images" in u for u in urls)


def test_vierkante_shopfoto_wordt_liggende_uitsnede_en_andere_hosts_niet() -> None:
    client = _shop_client({
        "ketting-zilver.png": (3375, 3375, False),
        "vierkant.jpg": (2000, 2000, False),
    })
    banners = banner_candidates(PAGINA, SHOP + "/products/x", client=client)
    assert len(banners) == 1
    b = banners[0]
    assert b.cropped and (b.width, b.height) == (1200, 600)
    assert "crop=center" in b.url and "height=600" in b.url
    assert not is_croppable("https://elders.nl/vierkant.jpg")
    assert is_croppable("https://cdn.shopify.com/s/files/1/0/files/a.png")
    assert "crop=center" in normalize_banner_url("https://cdn.shopify.com/s/files/1/0/files/a.png")


def test_egaal_zwart_beeld_wordt_herkend() -> None:
    client = _shop_client({"zwart.jpg": (1600, 900, True), "foto.jpg": (1600, 900, False)})
    assert banner_check.looks_blank(f"{CDN}/zwart.jpg", client) is True
    assert banner_check.looks_blank(f"{CDN}/foto.jpg", client) is False
    # Geen goedkope kleine versie mogelijk: niet afkeuren.
    assert banner_check.looks_blank("https://elders.nl/foto.jpg", client) is False


class _FakeVisie:
    def __init__(self, beschrijving: str) -> None:
        self.calls: list = []
        antwoord = json.dumps({"description": beschrijving, "subject": None})
        self.messages = SimpleNamespace(create=self._create)
        self._antwoord = SimpleNamespace(content=[SimpleNamespace(type="text", text=antwoord)])

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self._antwoord


def test_beschrijving_gebruikt_een_kleine_versie_van_de_foto() -> None:
    client = _shop_client({"ketting.png": (3375, 3375, False)})
    llm = _FakeVisie("Zilveren schakelketting om de hals van een man")
    tekst = banner_check.describe(llm, f"{CDN}/ketting.png?v=1&width=1200&height=600&crop=center", client)
    assert tekst == "Zilveren schakelketting om de hals van een man"
    beeld = llm.calls[0]["messages"][0]["content"][0]
    assert beeld["type"] == "image" and beeld["source"]["media_type"] == "image/jpeg"
    assert banner_check.describe(None, f"{CDN}/ketting.png", client) is None


def test_find_page_images_geeft_beschrijving_en_bovenkant_variant(session, cipher) -> None:
    from app.newsletter.tools import ToolContext, execute_tool
    from app.repositories import tenants as tenants_repo
    from app.schemas import TenantCreate

    tenant = tenants_repo.create_tenant(
        session, TenantCreate(slug="shop-banner", name="Shop", config={"website_url": SHOP})
    )
    beelden = {"ketting-zilver.png": (3375, 3375, False)}
    cdn = _shop_client(beelden)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/products/x":
            return httpx.Response(200, text=PAGINA, headers={"content-type": "text/html"})
        return cdn._transport.handle_request(request)

    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher,
        llm=_FakeVisie("Zilveren ketting op zwart shirt"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = execute_tool("find_page_images", {"url": f"{SHOP}/products/x"}, ctx)
    assert result["count"] == 1
    foto = result["images"][0]
    assert foto["beschrijving"] == "Zilveren ketting op zwart shirt"
    assert "bijgesneden" in foto and "crop=top" in foto["banner_url_bovenkant"]
    assert "zilver is geen goud" in result["message"]
