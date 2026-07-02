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
