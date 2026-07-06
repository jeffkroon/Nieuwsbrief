"""Integratietests voor de tool-laag (echte Postgres + fake LLM + gemockte HTTP/Brevo)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

import httpx
import pytest

from app.db.models import Newsletter
from app.newsletter.tools import ToolContext, execute_tool
from app.repositories import secrets as secrets_repo
from app.repositories import tenants as tenants_repo
from app.schemas import TenantCreate
from app.services.brevo import BrevoDraft, BrevoError

CONFIG = {
    "brand_name": "VoetbalreizenXL",
    "brand_email": "info@voetbalreizenxl.nl",
    "brand_adres": "Julianaweg 141 JK",
    "brand_postcode_stad": "1131 DH Volendam",
    "brand_telefoon": "+31 85 303 6791",
    "brand_kvk": "76484211",
    "website_url": "https://www.voetbalreizenxl.nl",
    "base_tickets_url": "https://www.voetbalreizenxl.nl/tickets/",
    "matches_url": "https://www.voetbalreizenxl.nl/tickets/premier-league/",
    "primary_color": "#FF7200",
    "logo_url": "https://cdn/logo.png",
    "header_image_url": "https://cdn/header.png",
    "dummy_image_url": "https://cdn/dummy.png",
    "facebook_url": "https://fb/x",
    "instagram_url": "https://ig/x",
    "youtube_url": "https://yt/x",
    "club_images": {},
}

MATCH_URL = "https://www.voetbalreizenxl.nl/tickets/chelsea-brighton-hove-albion/"

DRAFT_INPUT = {
    "subject": "Premier League toppers",
    "theme": "Premier League topperweek",
    "confirmed": True,
    "intro_1": "Eerste alinea.",
    "intro_2": "Tweede alinea.",
    "main_cta_text": "Bekijk alles",
    "main_cta_url": "https://x/all",
    "slot_cta_text": "Plan je trip",
    "slot_cta_url": "https://x/plan",
    "matches": [{"home": "Chelsea", "away": "Brighton & Hove Albion", "url": MATCH_URL}],
}


@dataclass
class FakeText:
    text: str
    type: str = "text"


@dataclass
class FakeResponse:
    content: list


@dataclass
class FakeMessages:
    payload: dict
    calls: list = field(default_factory=list)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse([FakeText(json.dumps(self.payload))])


class FakeLLM:
    def __init__(self, payload: dict) -> None:
        self.messages = FakeMessages(payload=payload)


class FakeBrevo:
    def __init__(self, api_key: str, *, fail: bool = False) -> None:
        self.api_key = api_key
        self.fail = fail
        self.calls: list[dict] = []

    def create_draft(self, **kwargs) -> BrevoDraft:
        if self.fail:
            raise BrevoError("Brevo down")
        self.calls.append(kwargs)
        return BrevoDraft(campaign_id=999)


def _tenant(session):
    return tenants_repo.create_tenant(
        session,
        TenantCreate(slug="voetbalreizenxl", name="VoetbalreizenXL", brevo_list_id=12, config=CONFIG),
    )


def _http(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_get_brand_config(session, cipher) -> None:
    tenant = _tenant(session)
    ctx = ToolContext(session=session, tenant_id=tenant.id, cipher=cipher)
    result = execute_tool("get_brand_config", {}, ctx)
    assert result["config"]["primary_color"] == "#FF7200"


def test_find_matches(session, cipher) -> None:
    tenant = _tenant(session)
    listing_html = '<a href="/tickets/chelsea-brighton-hove-albion/">Chelsea - Brighton</a>'
    llm = FakeLLM({"matches": [{"home": "Chelsea", "away": "Brighton & Hove Albion", "url": MATCH_URL, "price": "249,-"}]})
    ctx = ToolContext(
        session=session,
        tenant_id=tenant.id,
        cipher=cipher,
        llm=llm,
        http_client=_http(lambda r: httpx.Response(200, text=listing_html)),
    )
    result = execute_tool("find_matches", {}, ctx)
    assert result["count"] == 1
    assert result["matches"][0]["url"] == MATCH_URL
    assert result["matches"][0]["price"] == "€ 249"
    # find_matches haalde de matches_url op.
    assert llm.messages.calls[0]["messages"][0]["content"].startswith("Bron-URL:")


def test_image_filename_resolves_to_real_url(session, cipher) -> None:
    # De agent geeft een bestandsnaam mee; de backend zoekt de echte opslag-URL op.
    from app.repositories import images as images_repo
    tenant = _tenant(session)
    secrets_repo.set_tenant_secret(session, cipher, tenant.id, "brevo_api_key", "xkeysib-geheim")
    images_repo.create_image(
        session, tenant_id=tenant.id, category="banner", filename="allianz-arena.jpg",
        description="Allianz Arena", storage_path="p/a.jpg", url="https://cdn/real-allianz.jpg",
    )
    images_repo.create_image(
        session, tenant_id=tenant.id, category="club", filename="bayern.jpg",
        description="Bayern", storage_path="p/b.jpg", url="https://cdn/real-bayern.jpg",
    )
    payload = {k: v for k, v in DRAFT_INPUT.items() if k != "matches"}
    payload["header_image_url"] = "banner:allianz_arena"  # shorthand/underscore zoals het model soms doet
    payload["clubs"] = [{"name": "Bayern", "url": MATCH_URL, "image_url": "bayern.jpg", "price": "10,-"}]
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher,
        llm=FakeLLM({"price": None}),
        brevo_factory=lambda key: FakeBrevo(key),
        http_client=_http(lambda r: httpx.Response(200, text="<html>x</html>")),
    )
    execute_tool("create_newsletter_draft", payload, ctx)
    from app.db.models import Newsletter
    nl = session.query(Newsletter).filter_by(tenant_id=tenant.id).order_by(Newsletter.created_at.desc()).first()
    assert "https://cdn/real-allianz.jpg" in nl.html  # header opgelost
    assert "https://cdn/real-bayern.jpg" in nl.html   # clubfoto opgelost
    assert "banner:allianz_arena" not in nl.html      # geen kapotte shorthand


def test_list_images(session, cipher) -> None:
    from app.repositories import images as images_repo

    tenant = _tenant(session)
    images_repo.create_image(
        session, tenant_id=tenant.id, category="club", filename="arsenal.jpg",
        description="Arsenal shirt", storage_path="p/arsenal.jpg", url="https://cdn/arsenal.jpg",
    )
    ctx = ToolContext(session=session, tenant_id=tenant.id, cipher=cipher)
    result = execute_tool("list_images", {"category": "club"}, ctx)
    assert result["category"] == "club"
    assert result["images"][0]["filename"] == "arsenal.jpg"
    assert result["images"][0]["url"] == "https://cdn/arsenal.jpg"


def test_analyze_website_tone(session, cipher) -> None:
    tenant = _tenant(session)
    llm = FakeLLM({"tone_of_voice": "Informeel en sportief, je-vorm."})
    ctx = ToolContext(
        session=session,
        tenant_id=tenant.id,
        cipher=cipher,
        llm=llm,
        http_client=_http(lambda r: httpx.Response(200, text="<html>welkom bij voetbalreizen</html>")),
    )
    result = execute_tool("analyze_website_tone", {}, ctx)
    assert "sportief" in result["tone_of_voice"]
    assert result["source_url"] == CONFIG["website_url"]


def test_create_draft_happy_path(session, cipher) -> None:
    tenant = _tenant(session)
    secrets_repo.set_tenant_secret(session, cipher, tenant.id, "brevo_api_key", "xkeysib-geheim")
    created: dict = {}

    def factory(api_key: str) -> FakeBrevo:
        created["client"] = FakeBrevo(api_key)
        return created["client"]

    ctx = ToolContext(
        session=session,
        tenant_id=tenant.id,
        cipher=cipher,
        llm=FakeLLM({"price": "€ 299"}),  # live prijs-scrape per wedstrijd
        brevo_factory=factory,
        http_client=_http(lambda r: httpx.Response(200, text="<html>match page 299,-</html>")),
    )
    result = execute_tool("create_newsletter_draft", DRAFT_INPUT, ctx)

    assert result["brevo_campaign_id"] == 999
    assert result["status"] == "ready"
    # Prijs komt van de live scrape (niet uit de input).
    assert result["matches_used"][0]["price"] == "€ 299"
    assert result["matches_used"][0]["url"] == MATCH_URL
    assert created["client"].calls[0]["list_ids"] == [12]
    row = session.get(Newsletter, uuid.UUID(result["newsletter_id"]))
    assert row.status == "ready" and row.brevo_campaign_id == 999


def test_find_ticket_links(session, cipher) -> None:
    tenant = _tenant(session)
    llm = FakeLLM({"links": [{"label": "Bayern München", "url": "https://x/tickets/duitsland/bayern-munchen/"}]})
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher, llm=llm,
        http_client=_http(lambda r: httpx.Response(200, text="<html>links</html>")),
    )
    result = execute_tool("find_ticket_links", {"query": "bayern"}, ctx)
    assert result["count"] == 1
    assert result["links"][0]["url"].endswith("/bayern-munchen/")


def test_create_draft_uses_manual_price_when_site_has_none(session, cipher) -> None:
    tenant = _tenant(session)
    secrets_repo.set_tenant_secret(session, cipher, tenant.id, "brevo_api_key", "xkeysib-geheim")
    payload = {**DRAFT_INPUT, "matches": [{"home": "Bayern", "away": "Dortmund", "url": MATCH_URL, "price": "189,-"}]}
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher,
        llm=FakeLLM({"price": None}),  # site heeft geen prijs
        brevo_factory=lambda key: FakeBrevo(key),
        http_client=_http(lambda r: httpx.Response(200, text="<html>clubpagina</html>")),
    )
    result = execute_tool("create_newsletter_draft", payload, ctx)
    assert result["matches_used"][0]["price"] == "€ 189"  # handmatige prijs gebruikt


def test_create_draft_site_price_wins_over_manual(session, cipher) -> None:
    tenant = _tenant(session)
    secrets_repo.set_tenant_secret(session, cipher, tenant.id, "brevo_api_key", "xkeysib-geheim")
    payload = {**DRAFT_INPUT, "matches": [{"home": "Chelsea", "away": "Arsenal", "url": MATCH_URL, "price": "1,-"}]}
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher,
        llm=FakeLLM({"price": "€ 299"}),  # site heeft wel een prijs
        brevo_factory=lambda key: FakeBrevo(key),
        http_client=_http(lambda r: httpx.Response(200, text="<html>299,-</html>")),
    )
    result = execute_tool("create_newsletter_draft", payload, ctx)
    assert result["matches_used"][0]["price"] == "€ 299"  # echte prijs wint


def test_price_override_beats_site_price(session, cipher) -> None:
    # Gebruiker vraagt expliciet om een eigen prijs -> die wint van de site-prijs.
    tenant = _tenant(session)
    secrets_repo.set_tenant_secret(session, cipher, tenant.id, "brevo_api_key", "xkeysib-geheim")
    payload = {**DRAFT_INPUT, "matches": [{
        "home": "Chelsea", "away": "Arsenal", "url": MATCH_URL,
        "price": "249,-", "price_override": True,
    }]}
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher,
        llm=FakeLLM({"price": "€ 299"}),  # site zegt 299, maar override wint
        brevo_factory=lambda key: FakeBrevo(key),
        http_client=_http(lambda r: httpx.Response(200, text="<html>299,-</html>")),
    )
    result = execute_tool("create_newsletter_draft", payload, ctx)
    assert result["matches_used"][0]["price"] == "€ 249"  # eigen prijs, genormaliseerd


def test_price_override_still_validates_url(session, cipher) -> None:
    # Ook met een eigen prijs moet de link gewoon bestaan (garantie blijft).
    tenant = _tenant(session)
    secrets_repo.set_tenant_secret(session, cipher, tenant.id, "brevo_api_key", "xkeysib-geheim")
    payload = {**DRAFT_INPUT, "matches": [{
        "home": "Chelsea", "away": "Arsenal", "url": MATCH_URL,
        "price": "249,-", "price_override": True,
    }]}
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher,
        llm=FakeLLM({"price": None}),
        brevo_factory=lambda key: FakeBrevo(key),
        http_client=_http(lambda r: httpx.Response(404, text="weg")),
    )
    with pytest.raises(ValueError, match="onbereikbaar"):
        execute_tool("create_newsletter_draft", payload, ctx)


def test_create_draft_with_clubs(session, cipher) -> None:
    tenant = _tenant(session)
    secrets_repo.set_tenant_secret(session, cipher, tenant.id, "brevo_api_key", "xkeysib-geheim")
    payload = {k: v for k, v in DRAFT_INPUT.items() if k != "matches"}
    payload["clubs"] = [{"name": "Bayern München", "url": MATCH_URL, "price": "349,-"}]
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher,
        llm=FakeLLM({"price": None}),  # geen prijs op clubpagina -> handmatig
        brevo_factory=lambda key: FakeBrevo(key),
        http_client=_http(lambda r: httpx.Response(200, text="<html>clubpagina</html>")),
    )
    result = execute_tool("create_newsletter_draft", payload, ctx)
    assert result["matches_used"] == []
    assert result["clubs_used"][0]["name"] == "Bayern München"
    assert result["clubs_used"][0]["price"] == "€ 349"


def test_create_draft_uses_chosen_template(session, cipher) -> None:
    # Een in de chat gekozen template (ctx.template_id) wint van de standaard.
    from app.repositories import templates as templates_repo

    tenant = _tenant(session)
    secrets_repo.set_tenant_secret(session, cipher, tenant.id, "brevo_api_key", "xkeysib-geheim")
    # Standaard-template + een tweede, gekozen template met herkenbare inhoud.
    templates_repo.create_template(session, tenant_id=tenant.id, name="Standaard",
                                   html="<html>STANDAARD {{INTRO_1}} <!-- ##BANNERS## --></html>")
    chosen = templates_repo.create_template(
        session, tenant_id=tenant.id, name="Speciaal",
        html="<html>SPECIAAL {{INTRO_1}} {{STYLE_BUTTON_BG}} <!-- ##BANNERS## --></html>",
        styles={"button_bg": "#abcdef"})

    captured: dict = {}

    def factory(key):
        client = FakeBrevo(key)
        captured["client"] = client
        return client

    payload = {k: v for k, v in DRAFT_INPUT.items() if k != "matches"}
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher,
        brevo_factory=factory, template_id=chosen.id,
    )
    execute_tool("create_newsletter_draft", payload, ctx)
    html = captured["client"].calls[0]["html"]
    assert "SPECIAAL" in html and "STANDAARD" not in html  # gekozen layout gebruikt
    assert "#abcdef" in html  # met de stijl van die template


def test_club_image_falls_back_to_club_name(session, cipher) -> None:
    # Agent vergeet image_url: de backend vindt de foto alsnog via de clubnaam.
    from app.repositories import images as images_repo

    tenant = _tenant(session)
    images_repo.create_image(
        session, tenant_id=tenant.id, category="club", filename="inter-milan-dumfries.png",
        description="Inter", storage_path="p/i.png", url="https://cdn/real-inter.png",
    )
    payload = {k: v for k, v in DRAFT_INPUT.items() if k != "matches"}
    payload["clubs"] = [{"name": "Inter Milan", "url": MATCH_URL}]  # GEEN image_url meegegeven
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher, llm=FakeLLM({"price": None}),
        http_client=_http(lambda r: httpx.Response(200, text="<html>x</html>")),
        preview_holder=[],
    )
    execute_tool("preview_newsletter", payload, ctx)
    assert "https://cdn/real-inter.png" in ctx.preview_holder[0]  # foto via clubnaam gevonden


def test_preview_with_generic_items(session, cipher) -> None:
    # Generieke items (cases/blogs): URL gevalideerd, knoptekst en titel in de HTML.
    tenant = _tenant(session)
    payload = {k: v for k, v in DRAFT_INPUT.items() if k != "matches"}
    payload["items"] = [{
        "title": "Case Coolblue", "subtitle": "SEO en SEA",
        "url": "https://www.voetbalreizenxl.nl/cases/coolblue/",
        "button_text": "Lees de case",
    }]
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher,
        http_client=_http(lambda r: httpx.Response(200, text="<html>case</html>")),
        preview_holder=[],
    )
    result = execute_tool("preview_newsletter", payload, ctx)
    assert result["items_used"][0]["title"] == "Case Coolblue"
    html = ctx.preview_holder[0]
    assert "CASE COOLBLUE" in html and "Lees de case" in html
    assert "op aanvraag" not in html  # geen prijs meegegeven -> geen prijsregel


def test_items_with_unreachable_url_rejected(session, cipher) -> None:
    tenant = _tenant(session)
    payload = {k: v for k, v in DRAFT_INPUT.items() if k != "matches"}
    payload["items"] = [{"title": "Kapot", "url": "https://x.nl/404"}]
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher,
        http_client=_http(lambda r: httpx.Response(404, text="nee")),
        preview_holder=[],
    )
    with pytest.raises(ValueError, match="onbereikbaar"):
        execute_tool("preview_newsletter", payload, ctx)


def test_create_draft_via_klaviyo_when_esp_configured(session, cipher) -> None:
    # tenant.config esp=klaviyo -> Klaviyo-adapter, string-ref opgeslagen, Brevo onaangeraakt.
    from types import SimpleNamespace

    cfg = {**CONFIG, "esp": "klaviyo", "klaviyo_list_id": "LIST9"}
    tenant = tenants_repo.create_tenant(
        session, TenantCreate(slug="sieraden", name="Sieraden", config=cfg)
    )
    secrets_repo.set_tenant_secret(session, cipher, tenant.id, "klaviyo_api_key", "pk_geheim")
    captured: dict = {}

    class FakeKlaviyo:
        def __init__(self, key: str) -> None:
            captured["key"] = key

        def create_draft(self, **kw):
            captured["kw"] = kw
            return SimpleNamespace(campaign_id="CAMP9", message_id="MSG9")

    payload = {k: v for k, v in DRAFT_INPUT.items() if k != "matches"}
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher,
        klaviyo_factory=FakeKlaviyo,
        brevo_factory=lambda k: pytest.fail("Brevo mag niet worden aangeroepen"),
    )
    result = execute_tool("create_newsletter_draft", payload, ctx)
    assert captured["key"] == "pk_geheim"
    assert captured["kw"]["list_ids"] == ["LIST9"]
    assert result["esp"] == "klaviyo" and result["campaign_id"] == "CAMP9"
    assert "Klaviyo" in result["message"]
    nl = session.get(Newsletter, uuid.UUID(result["newsletter_id"]))
    assert nl.esp_campaign_ref == "CAMP9"
    assert nl.brevo_campaign_id is None


def test_klaviyo_missing_key_gives_clear_error(session, cipher) -> None:
    cfg = {**CONFIG, "esp": "klaviyo", "klaviyo_list_id": "L1"}
    tenant = tenants_repo.create_tenant(
        session, TenantCreate(slug="sieraden2", name="Sieraden2", config=cfg)
    )
    ctx = ToolContext(session=session, tenant_id=tenant.id, cipher=cipher)
    payload = {k: v for k, v in DRAFT_INPUT.items() if k != "matches"}
    with pytest.raises(ValueError, match="Klaviyo API-key"):
        execute_tool("create_newsletter_draft", payload, ctx)


def test_preview_with_sections_composes_layout(session, cipher) -> None:
    # Opzet-composer end-to-end: shell-template + secties in volgorde, hero-foto uit
    # de bibliotheek, knop-URL gecheckt, blokken (item) binnen de secties.
    from app.repositories import images as images_repo
    from app.repositories import templates as templates_repo

    tenant = _tenant(session)
    templates_repo.create_template(
        session, tenant_id=tenant.id, name="Shell",
        html="<html>SHELL-KOP<!-- ##SECTIES## -->SHELL-FOOTER {{ unsubscribe }}</html>",
    )
    images_repo.create_image(
        session, tenant_id=tenant.id, category="banner", filename="campagne-hero.png",
        description="Hero", storage_path="p/h.png", url="https://cdn/echte-hero.png",
    )
    payload = {k: v for k, v in DRAFT_INPUT.items() if k != "matches"}
    payload["items"] = [{"title": "Ankh Ring", "url": MATCH_URL, "button_text": "SHOP NU"}]
    payload["sections"] = [
        {"kind": "hero", "image_url": "campagne-hero.png", "url": MATCH_URL},
        {"kind": "text", "text": "SECTIE-INTRO"},
        {"kind": "blocks"},
        {"kind": "button", "text": "SHOP ALLES", "url": MATCH_URL},
    ]
    page = '<html><meta property="og:image" content="https://cdn/og.png">ok</html>'
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher,
        http_client=_http(lambda r: httpx.Response(200, text=page)),
        preview_holder=[],
    )
    execute_tool("preview_newsletter", payload, ctx)
    out = ctx.preview_holder[0]
    hero = out.index("https://cdn/echte-hero.png")  # bibliotheek-foto opgelost
    text = out.index("SECTIE-INTRO")
    block = out.index("ANKH RING")
    button = out.index("SHOP ALLES")
    assert out.index("SHELL-KOP") < hero < text < block < button < out.index("SHELL-FOOTER")
    assert "SHOP NU" in out  # item-knop binnen het blok


def test_sections_button_url_must_be_reachable(session, cipher) -> None:
    tenant = _tenant(session)
    payload = {k: v for k, v in DRAFT_INPUT.items() if k != "matches"}
    payload["sections"] = [{"kind": "button", "text": "SHOP", "url": "https://x.nl/404"}]
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher,
        http_client=_http(lambda r: httpx.Response(404, text="weg")),
        preview_holder=[],
    )
    with pytest.raises(ValueError, match="onbereikbaar"):
        execute_tool("preview_newsletter", payload, ctx)


def test_sections_hero_requires_findable_image(session, cipher) -> None:
    tenant = _tenant(session)
    payload = {k: v for k, v in DRAFT_INPUT.items() if k != "matches"}
    payload["sections"] = [{"kind": "hero", "image_url": "bestaat-niet.png"}]
    ctx = ToolContext(session=session, tenant_id=tenant.id, cipher=cipher, preview_holder=[])
    with pytest.raises(ValueError, match="hero-sectie"):
        execute_tool("preview_newsletter", payload, ctx)


def test_sections_unknown_kind_rejected(session, cipher) -> None:
    tenant = _tenant(session)
    payload = {k: v for k, v in DRAFT_INPUT.items() if k != "matches"}
    payload["sections"] = [{"kind": "carousel"}]
    ctx = ToolContext(session=session, tenant_id=tenant.id, cipher=cipher, preview_holder=[])
    with pytest.raises(ValueError, match="onbekende sectie-soort"):
        execute_tool("preview_newsletter", payload, ctx)


def test_find_products_tool(session, cipher) -> None:
    tenant = _tenant(session)
    payload = {"products": [{"name": "Ankh Ring", "url": "https://shop.nl/p/ankh",
                             "price": "€ 59,95", "image_url": "https://cdn.shop.nl/a.png"}]}
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher, llm=FakeLLM(payload),
        http_client=_http(lambda r: httpx.Response(200, text="<html>shop</html>")),
    )
    result = execute_tool("find_products", {"url": "https://shop.nl/collections/ringen"}, ctx)
    assert result["count"] == 1
    assert result["products"][0]["name"] == "Ankh Ring"


def test_find_products_unreachable_page(session, cipher) -> None:
    tenant = _tenant(session)
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher, llm=FakeLLM({"products": []}),
        http_client=_http(lambda r: httpx.Response(500, text="stuk")),
    )
    with pytest.raises(ValueError, match="status 500"):
        execute_tool("find_products", {"url": "https://shop.nl/x"}, ctx)


def test_item_price_rescraped_site_wins(session, cipher) -> None:
    # Item met prijs (bv. uit find_products) zonder override: live her-scrape wint.
    tenant = _tenant(session)
    payload = {k: v for k, v in DRAFT_INPUT.items() if k != "matches"}
    payload["items"] = [{"title": "Ankh Ring", "url": MATCH_URL, "price": "1,-"}]
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher,
        llm=FakeLLM({"price": "€ 59,95"}),  # site zegt 59,95
        http_client=_http(lambda r: httpx.Response(200, text="<html>59,95</html>")),
        preview_holder=[],
    )
    result = execute_tool("preview_newsletter", payload, ctx)
    assert result["items_used"][0]["price"] == "€ 59,95"


def test_item_price_override_wins(session, cipher) -> None:
    tenant = _tenant(session)
    payload = {k: v for k, v in DRAFT_INPUT.items() if k != "matches"}
    payload["items"] = [{"title": "Ankh Ring", "url": MATCH_URL,
                         "price": "49,95", "price_override": True}]
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher,
        llm=FakeLLM({"price": "€ 59,95"}),
        http_client=_http(lambda r: httpx.Response(200, text="<html>59,95</html>")),
        preview_holder=[],
    )
    result = execute_tool("preview_newsletter", payload, ctx)
    assert result["items_used"][0]["price"] == "€ 49,95"  # eigen prijs, genormaliseerd


def test_item_image_falls_back_to_og_image(session, cipher) -> None:
    # Geen image_url meegegeven en niets in de bibliotheek: og:image van de pagina.
    tenant = _tenant(session)
    payload = {k: v for k, v in DRAFT_INPUT.items() if k != "matches"}
    payload["items"] = [{"title": "Ankh Ring", "url": MATCH_URL}]
    page = '<html><meta property="og:image" content="https://cdn.shop.nl/ankh-og.png"><body>x</body></html>'
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher,
        http_client=_http(lambda r: httpx.Response(200, text=page)),
        preview_holder=[],
    )
    execute_tool("preview_newsletter", payload, ctx)
    assert "https://cdn.shop.nl/ankh-og.png" in ctx.preview_holder[0]


def test_preview_newsletter_returns_html_without_brevo(session, cipher) -> None:
    # Preview rendert de HTML, vult preview_holder, en maakt GEEN Brevo-concept aan.
    tenant = _tenant(session)
    payload = {k: v for k, v in DRAFT_INPUT.items() if k != "matches"}
    payload["header_title"] = "TOPVOETBAL"
    holder: list[str] = []
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher,
        brevo_factory=lambda key: FakeBrevo(key), preview_holder=holder,
    )
    result = execute_tool("preview_newsletter", payload, ctx)
    assert result["status"] == "preview"
    assert "newsletter_id" not in result  # niets opgeslagen
    assert len(holder) == 1
    assert "TOPVOETBAL" in holder[0]  # de kop staat in de gerenderde HTML


def test_preview_does_not_require_confirmation(session, cipher) -> None:
    # Anders dan create_newsletter_draft heeft preview geen 'confirmed' nodig.
    tenant = _tenant(session)
    payload = {k: v for k, v in DRAFT_INPUT.items() if k not in ("matches", "confirmed")}
    ctx = ToolContext(session=session, tenant_id=tenant.id, cipher=cipher)
    result = execute_tool("preview_newsletter", payload, ctx)
    assert result["status"] == "preview"


def test_create_draft_general_no_matches(session, cipher) -> None:
    # Algemene nieuwsbrief zonder wedstrijden: geen fout, gewoon een concept.
    tenant = _tenant(session)
    secrets_repo.set_tenant_secret(session, cipher, tenant.id, "brevo_api_key", "xkeysib-geheim")
    payload = {k: v for k, v in DRAFT_INPUT.items() if k != "matches"}
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher,
        brevo_factory=lambda key: FakeBrevo(key),
    )
    result = execute_tool("create_newsletter_draft", payload, ctx)
    assert result["status"] == "ready"
    assert result["matches_used"] == []


def test_create_draft_rejects_nonexistent_match(session, cipher) -> None:
    tenant = _tenant(session)
    secrets_repo.set_tenant_secret(session, cipher, tenant.id, "brevo_api_key", "xkeysib-geheim")
    ctx = ToolContext(
        session=session,
        tenant_id=tenant.id,
        cipher=cipher,
        llm=FakeLLM({"price": "€ 299"}),
        http_client=_http(lambda r: httpx.Response(404, text="not found")),
    )
    with pytest.raises(ValueError, match="bestaat niet"):
        execute_tool("create_newsletter_draft", DRAFT_INPUT, ctx)


def test_create_draft_requires_confirmation(session, cipher) -> None:
    tenant = _tenant(session)
    secrets_repo.set_tenant_secret(session, cipher, tenant.id, "brevo_api_key", "xkeysib-geheim")
    payload = {k: v for k, v in DRAFT_INPUT.items() if k != "confirmed"}  # geen toestemming
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher,
        llm=FakeLLM({"price": "€ 299"}),
        brevo_factory=lambda key: FakeBrevo(key),
        http_client=_http(lambda r: httpx.Response(200, text="<html>x</html>")),
    )
    with pytest.raises(ValueError, match="toestemming"):
        execute_tool("create_newsletter_draft", payload, ctx)


def test_create_draft_without_brevo_key_raises(session, cipher) -> None:
    tenant = _tenant(session)
    ctx = ToolContext(
        session=session,
        tenant_id=tenant.id,
        cipher=cipher,
        llm=FakeLLM({"price": "€ 299"}),
        http_client=_http(lambda r: httpx.Response(200, text="<html>x</html>")),
    )
    with pytest.raises(ValueError, match="Brevo API-key"):
        execute_tool("create_newsletter_draft", DRAFT_INPUT, ctx)


def test_create_draft_brevo_failure_records_failed(session, cipher) -> None:
    tenant = _tenant(session)
    secrets_repo.set_tenant_secret(session, cipher, tenant.id, "brevo_api_key", "xkeysib-geheim")
    ctx = ToolContext(
        session=session,
        tenant_id=tenant.id,
        cipher=cipher,
        llm=FakeLLM({"price": "€ 299"}),
        brevo_factory=lambda key: FakeBrevo(key, fail=True),
        http_client=_http(lambda r: httpx.Response(200, text="<html>x</html>")),
    )
    with pytest.raises(BrevoError):
        execute_tool("create_newsletter_draft", DRAFT_INPUT, ctx)
    rows = session.query(Newsletter).filter_by(tenant_id=tenant.id, status="failed").all()
    assert len(rows) == 1


def test_unknown_tool_raises(session, cipher) -> None:
    tenant = _tenant(session)
    ctx = ToolContext(session=session, tenant_id=tenant.id, cipher=cipher)
    with pytest.raises(ValueError, match="onbekende tool"):
        execute_tool("doesnotexist", {}, ctx)


_COLLECTIE_HTML = (
    '<html><meta property="og:image" '
    'content="http://shop.test/cdn/shop/collections/4.png?v=171&amp;width=2048"></html>'
)


def _banner_http(image_status=200, image_type="image/png"):
    def handler(r: httpx.Request) -> httpx.Response:
        if "/cdn/shop/" in r.url.path:
            return httpx.Response(image_status, headers={"content-type": image_type}, content=b"x")
        return httpx.Response(200, text=_COLLECTIE_HTML)

    return _http(handler)


def test_find_banner_returns_cropped_site_banner(session, cipher) -> None:
    tenant = _tenant(session)
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher, http_client=_banner_http()
    )
    result = execute_tool("find_banner", {"url": "https://shop.test/collections/ringen"}, ctx)
    banner = result["banner_url"]
    assert banner.startswith("https://")  # http -> https upgrade
    assert "width=1200" in banner and "height=600" in banner and "crop=center" in banner


def test_find_banner_without_og_image(session, cipher) -> None:
    tenant = _tenant(session)
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher,
        http_client=_http(lambda r: httpx.Response(200, text="<html>geen meta</html>")),
    )
    result = execute_tool("find_banner", {"url": "https://shop.test/x"}, ctx)
    assert result["banner_url"] is None
    assert "geen eigen bannerbeeld" in result["message"]


def test_find_banner_rejects_non_image(session, cipher) -> None:
    tenant = _tenant(session)
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher,
        http_client=_banner_http(image_type="text/html"),
    )
    with pytest.raises(ValueError, match="geen bereikbare afbeelding"):
        execute_tool("find_banner", {"url": "https://shop.test/collections/ringen"}, ctx)


_HOMEPAGE_HTML = (
    "<html>"
    '<a href="/collections/ringen">Ringen</a>'
    '<a href="/collections/all">Alles</a>'
    '<a href="/collections/oorbellen">Oorbellen</a>'
    '<a href="/collections/ringen?sort=prijs">Ringen gesorteerd</a>'
    '<a href="/pages/over-ons">Over ons</a>'
    "</html>"
)
_RINGEN_HTML = (
    '<html><meta property="og:image" '
    'content="https://shop.test/cdn/shop/collections/ringen.png?v=1"></html>'
)


def _candidates_http():
    def handler(r: httpx.Request) -> httpx.Response:
        if "/cdn/shop/" in r.url.path:
            return httpx.Response(200, headers={"content-type": "image/png"}, content=b"x")
        if r.url.path == "/collections/ringen":
            return httpx.Response(200, text=_RINGEN_HTML)
        if r.url.path == "/collections/oorbellen":
            return httpx.Response(200, text="<html>geen banner</html>")
        return httpx.Response(200, text=_HOMEPAGE_HTML)

    return _http(handler)


def test_find_banner_offers_collection_candidates(session, cipher) -> None:
    # De pagina zelf heeft geen banner: dan kandidaten van gelinkte collecties,
    # alleen die met een ECHTE banner (oorbellen valt af, /all wordt overgeslagen).
    tenant = _tenant(session)
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher, http_client=_candidates_http()
    )
    result = execute_tool("find_banner", {"url": "https://shop.test/"}, ctx)
    assert result["banner_url"] is None
    names = [c["name"] for c in result["candidates"]]
    assert names == ["ringen"]
    assert "width=1200" in result["candidates"][0]["banner_url"]
    assert "KIEZEN" in result["message"]


def test_find_banner_no_links_keeps_honest_message(session, cipher) -> None:
    tenant = _tenant(session)
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher,
        http_client=_http(lambda r: httpx.Response(200, text="<html>niks</html>")),
    )
    result = execute_tool("find_banner", {"url": "https://shop.test/x"}, ctx)
    assert result["banner_url"] is None and "candidates" not in result


def _preview_input(**extra) -> dict:
    return {
        "theme": "Zomer", "subject": "Zomer", "intro_1": "a", "intro_2": "b",
        "main_cta_text": "SHOP", "main_cta_url": "https://shop.test/all",
        "slot_cta_text": "SHOP", "slot_cta_url": "https://shop.test/all",
        "matches": [], **extra,
    }


def test_header_text_color_overrides_heading(session, cipher) -> None:
    tenant = _tenant(session)
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher,
        http_client=_http(lambda r: httpx.Response(200, text="<html>ok</html>")),
    )
    execute_tool("preview_newsletter", _preview_input(header_text_color="#123abc"), ctx)
    assert ctx.preview_holder, "preview hoort gerenderd te zijn"
    # De kop op de banner krijgt exact de gevraagde kleur (geen default-kleur).
    assert "#123abc" in ctx.preview_holder[-1]


def test_header_text_color_must_be_hex(session, cipher) -> None:
    tenant = _tenant(session)
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher,
        http_client=_http(lambda r: httpx.Response(200, text="<html>ok</html>")),
    )
    with pytest.raises(ValueError, match="hex-kleur"):
        execute_tool("preview_newsletter", _preview_input(header_text_color="wit"), ctx)


# ---------------------------------------------------------------------------
# style_overrides: stijl voor alleen deze nieuwsbrief (template blijft de basis)
# ---------------------------------------------------------------------------


def _make_tenant_with_template(session):
    from app.repositories import templates as templates_repo

    slug = f"stijltest-{uuid.uuid4().hex[:6]}"
    tenant = tenants_repo.create_tenant(
        session, TenantCreate(slug=slug, name=slug, config=CONFIG)
    )
    template = templates_repo.create_template(
        session,
        tenant_id=tenant.id,
        name="base template",
        html=(
            "<html><span style='color:{{STYLE_BUTTON_BG}}'></span>"
            "<i style='color:{{STYLE_CTA_BUTTON_BG}}'></i>"
            "<p>{{INTRO_1}}</p>{{ unsubscribe }}</html>"
        ),
        is_default=True,
        styles={"button_bg": "#b51a00"},
    )
    return tenant, template


def _ctx(session, cipher, tenant):
    return ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher,
        http_client=_http(lambda r: httpx.Response(200, text="<html>ok</html>")),
    )


def test_style_overrides_apply_to_render_not_template(session, cipher):
    from app.repositories import templates as templates_repo

    tenant, template = _make_tenant_with_template(session)
    ctx = _ctx(session, cipher, tenant)
    execute_tool(
        "preview_newsletter",
        _preview_input(style_overrides={"button_bg": "#000000"}),
        ctx,
    )
    assert "#000000" in ctx.preview_holder[-1]  # render gebruikt de override
    session.expire_all()
    refreshed = templates_repo.get_template(session, template.id)
    assert refreshed.styles == {"button_bg": "#b51a00"}  # template onaangetast


def test_style_overrides_pin_other_button_groups(session, cipher):
    # Productknop zwart voor deze nieuwsbrief: de onderste knop blijft #b51a00.
    tenant, _ = _make_tenant_with_template(session)
    ctx = _ctx(session, cipher, tenant)
    execute_tool(
        "preview_newsletter",
        _preview_input(style_overrides={"button_bg": "#000000"}),
        ctx,
    )
    html = ctx.preview_holder[-1]
    assert "color:#000000" in html and "color:#b51a00" in html


def test_style_overrides_reject_invalid_values(session, cipher):
    tenant, _ = _make_tenant_with_template(session)
    ctx = _ctx(session, cipher, tenant)
    with pytest.raises(ValueError, match="ongeldige stijl-overrides"):
        execute_tool(
            "preview_newsletter",
            _preview_input(style_overrides={"button_bg": "rood"}),
            ctx,
        )


def test_style_overrides_spacing_needs_tokens(session, cipher):
    tenant, _ = _make_tenant_with_template(session)  # geen spacing-tokens in html
    ctx = _ctx(session, cipher, tenant)
    with pytest.raises(ValueError, match="witruimte"):
        execute_tool(
            "preview_newsletter",
            _preview_input(style_overrides={"spacing_banner_intro": 40}),
            ctx,
        )


def test_style_overrides_inherit_within_conversation(session, cipher):
    # De override erft mee met de her-render (last_preview), dus 'maak de knop
    # zwart' blijft staan als de gebruiker daarna iets anders wijzigt.
    from app.repositories import conversations as conv_repo

    tenant, _ = _make_tenant_with_template(session)
    conversation = conv_repo.create_conversation(session, tenant_id=tenant.id, channel="web")
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher,
        conversation_id=conversation.id,
        http_client=_http(lambda r: httpx.Response(200, text="<html>ok</html>")),
    )
    execute_tool(
        "preview_newsletter",
        _preview_input(style_overrides={"button_bg": "#000000"}),
        ctx,
    )
    execute_tool("preview_newsletter", _preview_input(intro_1="nieuwe intro"), ctx)
    html = ctx.preview_holder[-1]
    assert "nieuwe intro" in html and "color:#000000" in html
