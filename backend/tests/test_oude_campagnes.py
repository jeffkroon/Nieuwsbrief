"""Feiten uit eerder verstuurde campagnes in het verzendplatform (alleen-lezen).

Aanleiding (Runderkamp, 26 nov): de mail van Frank had prijs, voorwaarden en een
review; de chat kende die feiten niet en liet die blokken leeg. De campagnes staan
wel in ActiveCampaign. De tool leest ze, met de datum erbij: een feit uit een oude
campagne is niet per se nog actueel.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import httpx
import pytest

from app.newsletter.tools import ToolContext, execute_tool
from app.repositories import secrets as secrets_repo
from app.repositories import tenants as tenants_repo
from app.schemas import TenantCreate
from app.services.activecampaign import ActiveCampaignClient, ActiveCampaignError

API_URL = "https://account.api-us1.com"
HTML_KERST = (
    "<html><body><h1>Ons kerstbuffet</h1><p>voor € 39,50 per persoon</p>"
    "<p>Te bestellen vanaf 30 personen.</p><script>x()</script></body></html>"
)


@dataclass
class _Http:
    """Beantwoordt v3-GET's op pad; legt alle verzoeken vast."""

    routes: dict
    calls: list = field(default_factory=list)

    def request(self, method, url, *, params=None, json=None, headers=None):
        self.calls.append((method, url, params))
        path = url.split("/api/3/", 1)[1]
        if method != "GET" or path not in self.routes:
            return httpx.Response(404, json={})
        return httpx.Response(200, json=self.routes[path])


def _routes() -> dict:
    return {
        "campaigns": {
            "campaigns": [
                {"id": "220", "name": "Weekaanbieding", "status": "5", "sdate": "2026-11-25T09:00:00-06:00"},
                {"id": "219", "name": "Kerst (Kopieer)", "status": "0", "sdate": None},
                {"id": "215", "name": "Kerstbuffet 2026", "status": "5", "sdate": "2026-11-12T10:00:00-06:00"},
            ]
        },
        "campaigns/220/campaignMessages": {"campaignMessages": [{"messageid": "300"}]},
        "campaigns/215/campaignMessages": {"campaignMessages": [{"messageid": "291"}]},
        "messages/300": {"message": {"subject": "Week 48", "html": "<p>Rollade € 12,95</p>"}},
        "messages/291": {"message": {"subject": "Het kerstbuffet", "html": HTML_KERST}},
    }


def test_client_leest_alleen_verstuurde_campagnes_met_tekst() -> None:
    http = _Http(_routes())
    campagnes = ActiveCampaignClient(API_URL, "key", client=http).get_past_campaigns(limit=5)

    assert [c.campaign_id for c in campagnes] == ["220", "215"]  # concept 219 overgeslagen
    kerst = campagnes[1]
    assert kerst.subject == "Het kerstbuffet"
    assert kerst.sent_at.startswith("2026-11-12")
    assert "€ 39,50 per persoon" in kerst.text and "vanaf 30 personen" in kerst.text
    assert "<" not in kerst.text and "x()" not in kerst.text  # kale tekst, geen script
    assert all(method == "GET" for method, _, _ in http.calls)  # alleen lezen


def test_client_respecteert_limiet() -> None:
    campagnes = ActiveCampaignClient(API_URL, "key", client=_Http(_routes())).get_past_campaigns(limit=1)
    assert [c.campaign_id for c in campagnes] == ["220"]


def test_client_slaat_campagne_zonder_bericht_over() -> None:
    routes = _routes()
    routes["campaigns/220/campaignMessages"] = {"campaignMessages": []}
    campagnes = ActiveCampaignClient(API_URL, "key", client=_Http(routes)).get_past_campaigns(limit=5)
    assert [c.campaign_id for c in campagnes] == ["215"]


# --- tool ---------------------------------------------------------------------
def _tenant(session, cipher, esp: str):
    slug = f"oud-{uuid.uuid4().hex[:6]}"
    config = {"esp": esp, "activecampaign_api_url": API_URL, "activecampaign_list_id": "12"}
    tenant = tenants_repo.create_tenant(session, TenantCreate(slug=slug, name=slug, config=config))
    kind = {"activecampaign": "activecampaign_api_key", "klaviyo": "klaviyo_api_key"}.get(
        esp, "brevo_api_key"
    )
    secrets_repo.set_tenant_secret(session, cipher, tenant.id, kind, "key")
    return tenant


def _ctx(session, cipher, tenant, http) -> ToolContext:
    return ToolContext(
        session=session,
        tenant_id=tenant.id,
        cipher=cipher,
        activecampaign_factory=lambda url, key: ActiveCampaignClient(url, key, client=http),
    )


def test_tool_geeft_campagnes_met_datum_en_waarschuwing(session, cipher) -> None:
    tenant = _tenant(session, cipher, "activecampaign")
    result = execute_tool("get_esp_campaigns", {}, _ctx(session, cipher, tenant, _Http(_routes())))

    assert result["count"] == 2
    kerst = result["campagnes"][1]
    assert kerst["datum"] == "12-11-2026"
    assert kerst["onderwerp"] == "Het kerstbuffet"
    assert "39,50" in kerst["tekst"]
    assert "datum" in result["let_op"] and "find_products" in result["let_op"]


def test_tool_limiet_wordt_begrensd(session, cipher) -> None:
    tenant = _tenant(session, cipher, "activecampaign")
    http = _Http(_routes())
    execute_tool("get_esp_campaigns", {"limit": 99}, _ctx(session, cipher, tenant, http))
    lijst = next(params for _, url, params in http.calls if url.endswith("/campaigns"))
    assert int(lijst["limit"]) <= 20  # MAX 5 campagnes, met wat ruimte voor concepten


def test_tool_meldt_platform_zonder_ondersteuning(session, cipher) -> None:
    tenant = _tenant(session, cipher, "klaviyo")
    ctx = ToolContext(session=session, tenant_id=tenant.id, cipher=cipher)
    result = execute_tool("get_esp_campaigns", {}, ctx)
    assert result["count"] == 0
    assert "Klaviyo" in result["message"]


def test_tool_geeft_nette_fout_bij_platformfout(session, cipher) -> None:
    tenant = _tenant(session, cipher, "activecampaign")

    class _Kapot:
        def request(self, *a, **k):
            raise httpx.ConnectError("weg")

    with pytest.raises((ValueError, ActiveCampaignError)) as exc:
        execute_tool("get_esp_campaigns", {}, _ctx(session, cipher, tenant, _Kapot()))
    assert "ActiveCampaign" in str(exc.value)
