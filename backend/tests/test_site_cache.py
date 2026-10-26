"""Proces-lokale caches voor de catalogus en fotobeschrijvingen (site_cache.py)."""

from __future__ import annotations

import httpx
import pytest

from app.newsletter import site_cache
from app.newsletter.tools import ToolContext, execute_tool
from app.repositories import conversations as conv_repo
from app.repositories import tenants as tenants_repo
from app.schemas import TenantCreate
from tests.test_banner_zoeken import PAGINA, SHOP, _FakeVisie, _shop_client
from tests.test_tools import CONFIG, FakeLLM, _tellende_http, _tenant

_PRODUCT = {"name": "Bal", "url": "https://x/bal", "price": "€ 20", "image_url": None}


def _ctx(session, cipher, tenant_id, http, llm, conversation_id=None) -> ToolContext:
    return ToolContext(
        session=session, tenant_id=tenant_id, cipher=cipher,
        conversation_id=conversation_id, llm=llm, http_client=http,
    )


def test_catalogus_wordt_gedeeld_door_gesprekken_van_hetzelfde_bedrijf(session, cipher) -> None:
    tenant = _tenant(session)
    een = conv_repo.create_conversation(session, tenant_id=tenant.id, channel="web")
    ander = conv_repo.create_conversation(session, tenant_id=tenant.id, channel="web")
    http, teller = _tellende_http(lambda r: httpx.Response(200, text="<html>shop</html>"))
    llm = FakeLLM({"products": [_PRODUCT]})

    eerste = execute_tool("find_products", {"url": CONFIG["website_url"]}, _ctx(session, cipher, tenant.id, http, llm, een.id))
    tweede = execute_tool("find_products", {"url": CONFIG["website_url"]}, _ctx(session, cipher, tenant.id, http, llm, ander.id))

    assert teller["n"] == 1, "een ander gesprek van hetzelfde bedrijf hergebruikt de catalogus"
    assert len(llm.messages.calls) == 1
    assert "from_memory" not in eerste
    assert tweede["from_memory"] is True
    assert tweede["products"] == eerste["products"]


def test_catalogus_staat_niet_meer_in_de_gespreksrij(session, cipher) -> None:
    tenant = _tenant(session)
    conversation = conv_repo.create_conversation(session, tenant_id=tenant.id, channel="web")
    http, _ = _tellende_http(lambda r: httpx.Response(200, text="<html>shop</html>"))
    ctx = _ctx(session, cipher, tenant.id, http, FakeLLM({"products": [_PRODUCT]}), conversation.id)
    execute_tool("find_products", {"url": CONFIG["website_url"]}, ctx)
    session.refresh(conversation)
    assert not (conversation.tool_memory or {}), "de catalogus hoort niet in conversations.tool_memory"


def test_catalogus_wordt_niet_gedeeld_tussen_bedrijven(session, cipher) -> None:
    een = _tenant(session)
    ander = tenants_repo.create_tenant(session, TenantCreate(slug="ander", name="Ander", config=CONFIG))
    http, teller = _tellende_http(lambda r: httpx.Response(200, text="<html>shop</html>"))
    llm = FakeLLM({"products": [_PRODUCT]})
    execute_tool("find_products", {"url": CONFIG["website_url"]}, _ctx(session, cipher, een.id, http, llm))
    tweede = execute_tool("find_products", {"url": CONFIG["website_url"]}, _ctx(session, cipher, ander.id, http, llm))
    assert teller["n"] == 2
    assert "from_memory" not in tweede


def test_catalogus_verloopt_na_de_ttl() -> None:
    nu = {"t": 0.0}
    cache = site_cache.ValidationCache(ttl_seconds=site_cache.CATALOG_TTL_SECONDS, time_fn=lambda: nu["t"])
    cache.set(("t", "u"), {"products": []})
    nu["t"] = site_cache.CATALOG_TTL_SECONDS + 1
    assert cache.get(("t", "u")) == (False, None)
    assert site_cache.CATALOG_TTL_SECONDS == 20 * 60


def test_mislukte_catalogus_wordt_niet_onthouden() -> None:
    def stuk() -> dict:
        raise ValueError("pagina gaf status 503")

    with pytest.raises(ValueError):
        site_cache.cached_catalog("tenant", "https://x.nl/", stuk)
    vers = site_cache.cached_catalog("tenant", "https://x.nl/", lambda: {"products": [1]})
    assert vers == {"products": [1]}


def test_geen_beschrijving_wordt_niet_onthouden() -> None:
    aanroepen = {"n": 0}

    def maker() -> str | None:
        aanroepen["n"] += 1
        return None if aanroepen["n"] == 1 else "Rode bal"

    assert site_cache.cached_description("https://x.nl/a.jpg", maker) is None
    assert site_cache.cached_description("https://x.nl/a.jpg", maker) == "Rode bal"
    assert site_cache.cached_description("https://x.nl/a.jpg", maker) == "Rode bal"
    assert aanroepen["n"] == 2


def test_fotobeschrijving_wordt_niet_opnieuw_gemaakt(session, cipher) -> None:
    """Twee gesprekken (dus geen werkgeheugen) op dezelfde pagina: één Haiku-call per foto."""
    tenant = tenants_repo.create_tenant(
        session, TenantCreate(slug="shop-cache", name="Shop", config={"website_url": SHOP})
    )
    cdn = _shop_client({"ketting-zilver.png": (3375, 3375, False)})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/products/x":
            return httpx.Response(200, text=PAGINA, headers={"content-type": "text/html"})
        return cdn._transport.handle_request(request)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    llm = _FakeVisie("Zilveren ketting op zwart shirt")
    for _ in range(2):
        conversation = conv_repo.create_conversation(session, tenant_id=tenant.id, channel="web")
        result = execute_tool(
            "find_page_images", {"url": f"{SHOP}/products/x"},
            _ctx(session, cipher, tenant.id, http, llm, conversation.id),
        )
        assert result["images"][0]["beschrijving"] == "Zilveren ketting op zwart shirt"
    assert len(llm.calls) == 1, "de tweede aanroep mag de foto niet opnieuw laten beschrijven"
