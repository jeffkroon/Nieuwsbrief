"""Tests voor de nieuwsbrieven-lijst en de link naar het verzendplatform."""

from __future__ import annotations

import pytest

from app.newsletter.esp_links import campaign_link
from app.repositories import newsletters as repo
from app.repositories import tenants as tenants_repo
from app.schemas import TenantCreate


def _tenant(session, **config):
    return tenants_repo.create_tenant(
        session, TenantCreate(slug=f"t{len(config)}{id(config) % 1000}", name="Klant", config=config)
    )


# --- links ------------------------------------------------------------------
def test_brevo_krijgt_een_echte_deeplink() -> None:
    link = campaign_link("brevo", "4512")
    assert link.url == "https://app.brevo.com/marketing-campaign/edit/4512"
    assert link.is_deeplink is True


def test_klaviyo_linkt_naar_het_overzicht_niet_naar_een_gok() -> None:
    link = campaign_link("klaviyo", "01HX")
    assert link.url == "https://www.klaviyo.com/campaigns"
    assert link.is_deeplink is False


def test_activecampaign_leidt_de_dashboard_url_af_van_de_api_url() -> None:
    link = campaign_link("activecampaign", "88", api_url="https://dunion.api-us1.com")
    assert link.url == "https://dunion.activehosted.com/app/campaigns"
    assert link.is_deeplink is False


def test_activecampaign_zonder_api_url_geeft_geen_link() -> None:
    assert campaign_link("activecampaign", "88", api_url="") is None


def test_onbekend_platform_geeft_geen_link() -> None:
    assert campaign_link("mailchimp", "1") is None


# --- routes -----------------------------------------------------------------
def test_lijst_toont_nieuwste_eerst_met_link(client, session) -> None:
    tenant = _tenant(session, esp="brevo")
    repo.create_newsletter(
        session, tenant_id=tenant.id, subject="Oud", html="<p>oud</p>", brevo_campaign_id=1
    )
    repo.create_newsletter(
        session, tenant_id=tenant.id, subject="Nieuw", html="<p>nieuw</p>", brevo_campaign_id=2
    )

    lijst = client.get(f"/tenants/{tenant.id}/newsletters").json()
    assert [n["subject"] for n in lijst] == ["Nieuw", "Oud"]
    assert lijst[0]["link_url"].endswith("/2")
    assert lijst[0]["link_is_deeplink"] is True


def test_mislukt_concept_zonder_campagne_heeft_geen_link(client, session) -> None:
    tenant = _tenant(session, esp="brevo")
    repo.create_newsletter(
        session, tenant_id=tenant.id, subject="Mislukt", html="<p>x</p>", status="failed"
    )
    regel = client.get(f"/tenants/{tenant.id}/newsletters").json()[0]
    assert regel["status"] == "failed"
    assert regel["link_url"] is None


def test_html_van_een_nieuwsbrief_is_op_te_vragen(client, session) -> None:
    tenant = _tenant(session, esp="brevo")
    nieuwsbrief = repo.create_newsletter(
        session, tenant_id=tenant.id, subject="Kerst", html="<p>hallo</p>"
    )
    resp = client.get(f"/tenants/{tenant.id}/newsletters/{nieuwsbrief.id}/html")
    assert resp.status_code == 200
    assert "<p>hallo</p>" in resp.text


def test_nieuwsbrief_van_ander_bedrijf_is_niet_op_te_vragen(client, session) -> None:
    eigen = _tenant(session, esp="brevo")
    ander = tenants_repo.create_tenant(session, TenantCreate(slug="ander-bedrijf", name="Ander"))
    vreemd = repo.create_newsletter(
        session, tenant_id=ander.id, subject="Geheim", html="<p>geheim</p>"
    )
    resp = client.get(f"/tenants/{eigen.id}/newsletters/{vreemd.id}/html")
    assert resp.status_code == 404


def test_klaviyo_nieuwsbrief_gebruikt_de_tekst_referentie(client, session) -> None:
    tenant = _tenant(session, esp="klaviyo")
    repo.create_newsletter(
        session, tenant_id=tenant.id, subject="K", html="<p>x</p>", esp_campaign_ref="01HXABC"
    )
    regel = client.get(f"/tenants/{tenant.id}/newsletters").json()[0]
    assert regel["campaign_ref"] == "01HXABC"
    assert regel["esp"] == "klaviyo"


# --- resultaten uit het verzendplatform ---------------------------------------
class _FakeResultsBrevo:
    def __init__(self, results=None, error=None) -> None:
        self.results, self.error, self.calls = results, error, 0

    def get_results(self, campaign_id):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.results


@pytest.fixture
def nep_brevo():
    from app.deps import get_esp_factories
    from app.main import app
    from app.services.esp_connection import EspFactories

    holder = {}

    def install(fake):
        holder["fake"] = fake
        app.dependency_overrides[get_esp_factories] = lambda: EspFactories(brevo=lambda key: fake)
        return fake

    yield install
    app.dependency_overrides.pop(get_esp_factories, None)


def _met_key(session, cipher, tenant):
    from app.repositories import secrets as secrets_repo

    secrets_repo.set_tenant_secret(session, cipher, tenant.id, "brevo_api_key", "k")


def test_resultaten_ophalen_bewaart_ze_en_markeert_verstuurd(client, session, cipher, nep_brevo) -> None:
    from app.services.esp import CampaignResults

    tenant = _tenant(session, esp="brevo")
    _met_key(session, cipher, tenant)
    nb = repo.create_newsletter(
        session, tenant_id=tenant.id, subject="S", html="<p/>", brevo_campaign_id=5, status="ready"
    )
    fake = nep_brevo(_FakeResultsBrevo(CampaignResults(status="sent", sent=100, open_rate=0.3)))

    antwoord = client.post(f"/tenants/{tenant.id}/newsletters/{nb.id}/results")
    assert antwoord.status_code == 200
    body = antwoord.json()
    assert body["from_cache"] is False and body["stats"]["open_rate"] == 0.3
    session.refresh(nb)
    assert nb.status == "sent" and nb.stats["sent"] == 100

    # Binnen de afkoeltijd: bewaarde cijfers, geen nieuwe vraag aan het platform.
    tweede = client.post(f"/tenants/{tenant.id}/newsletters/{nb.id}/results").json()
    assert tweede["from_cache"] is True and fake.calls == 1
    lijst = client.get(f"/tenants/{tenant.id}/newsletters").json()
    assert lijst[0]["stats"]["open_rate"] == 0.3


def test_resultaten_van_mislukt_concept_geeft_nette_fout(client, session, cipher, nep_brevo) -> None:
    tenant = _tenant(session, esp="brevo")
    nb = repo.create_newsletter(session, tenant_id=tenant.id, subject="S", html="", status="failed")
    nep_brevo(_FakeResultsBrevo())
    antwoord = client.post(f"/tenants/{tenant.id}/newsletters/{nb.id}/results")
    assert antwoord.status_code == 400
    assert "geen campagne" in antwoord.json()["detail"]


def test_resultaten_platformfout_wordt_vertaald(client, session, cipher, nep_brevo) -> None:
    from app.services.brevo import BrevoError

    tenant = _tenant(session, esp="brevo")
    _met_key(session, cipher, tenant)
    nb = repo.create_newsletter(
        session, tenant_id=tenant.id, subject="S", html="<p/>", brevo_campaign_id=5, status="ready"
    )
    nep_brevo(_FakeResultsBrevo(error=BrevoError("Brevo gaf HTTP 401: key")))
    antwoord = client.post(f"/tenants/{tenant.id}/newsletters/{nb.id}/results")
    assert antwoord.status_code == 400 and "leesrechten" in antwoord.json()["detail"]


def test_resultaten_van_ander_bedrijf_niet_op_te_vragen(client, session, cipher, nep_brevo) -> None:
    eigen = _tenant(session, esp="brevo")
    ander = _tenant(session, esp="brevo", x=1)
    nb = repo.create_newsletter(session, tenant_id=ander.id, subject="S", html="", brevo_campaign_id=5)
    nep_brevo(_FakeResultsBrevo())
    assert client.post(f"/tenants/{eigen.id}/newsletters/{nb.id}/results").status_code == 404
