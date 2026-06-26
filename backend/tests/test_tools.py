"""Integratietests voor de tool-laag (echte Postgres + gemockte Brevo)."""

from __future__ import annotations

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
    "primary_color": "#FF7200",
    "logo_url": "https://cdn/logo.png",
    "header_image_url": "https://cdn/header.png",
    "dummy_image_url": "https://cdn/dummy.png",
    "facebook_url": "https://fb/x",
    "instagram_url": "https://ig/x",
    "youtube_url": "https://yt/x",
    "club_images": {},
}

DRAFT_INPUT = {
    "subject": "Kerst in Londen",
    "theme": "Kerst in Londen",
    "intro_1": "Eerste alinea.",
    "intro_2": "Tweede alinea.",
    "main_cta_text": "Bekijk alles",
    "main_cta_url": "https://x/all",
    "slot_cta_text": "Plan je trip",
    "slot_cta_url": "https://x/plan",
    "matches": [{"home": "Chelsea", "away": "Arsenal", "slug": "chelsea-arsenal", "price": "299,-"}],
}


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


def test_get_brand_config(session, cipher) -> None:
    tenant = _tenant(session)
    ctx = ToolContext(session=session, tenant_id=tenant.id, cipher=cipher)
    result = execute_tool("get_brand_config", {}, ctx)
    assert result["config"]["primary_color"] == "#FF7200"


def test_fetch_match_price_tool(session, cipher) -> None:
    tenant = _tenant(session)
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text="vanaf € 189"))
    ctx = ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher, http_client=httpx.Client(transport=transport)
    )
    result = execute_tool("fetch_match_price", {"url": "https://x/m"}, ctx)
    assert result["price"] == "€ 189"


def test_create_newsletter_draft_happy_path(session, cipher) -> None:
    tenant = _tenant(session)
    secrets_repo.set_tenant_secret(session, cipher, tenant.id, "brevo_api_key", "xkeysib-geheim")
    created: dict = {}

    def factory(api_key: str) -> FakeBrevo:
        created["client"] = FakeBrevo(api_key)
        return created["client"]

    ctx = ToolContext(session=session, tenant_id=tenant.id, cipher=cipher, brevo_factory=factory)
    result = execute_tool("create_newsletter_draft", DRAFT_INPUT, ctx)

    assert result["brevo_campaign_id"] == 999
    assert result["status"] == "ready"
    # Brevo kreeg de juiste key en een lijst-id mee.
    assert created["client"].api_key == "xkeysib-geheim"
    assert created["client"].calls[0]["list_ids"] == [12]
    # Newsletter-rij opgeslagen als ready.
    row = session.get(Newsletter, __import__("uuid").UUID(result["newsletter_id"]))
    assert row is not None and row.status == "ready" and row.brevo_campaign_id == 999


def test_create_draft_without_brevo_key_raises(session, cipher) -> None:
    tenant = _tenant(session)
    ctx = ToolContext(session=session, tenant_id=tenant.id, cipher=cipher)
    with pytest.raises(ValueError, match="Brevo API-key"):
        execute_tool("create_newsletter_draft", DRAFT_INPUT, ctx)


def test_create_draft_brevo_failure_records_failed(session, cipher) -> None:
    tenant = _tenant(session)
    secrets_repo.set_tenant_secret(session, cipher, tenant.id, "brevo_api_key", "xkeysib-geheim")
    ctx = ToolContext(
        session=session,
        tenant_id=tenant.id,
        cipher=cipher,
        brevo_factory=lambda key: FakeBrevo(key, fail=True),
    )
    with pytest.raises(BrevoError):
        execute_tool("create_newsletter_draft", DRAFT_INPUT, ctx)
    # Mislukte poging is vastgelegd als 'failed'.
    rows = session.query(Newsletter).filter_by(tenant_id=tenant.id, status="failed").all()
    assert len(rows) == 1


def test_unknown_tool_raises(session, cipher) -> None:
    tenant = _tenant(session)
    ctx = ToolContext(session=session, tenant_id=tenant.id, cipher=cipher)
    with pytest.raises(ValueError, match="onbekende tool"):
        execute_tool("doesnotexist", {}, ctx)
