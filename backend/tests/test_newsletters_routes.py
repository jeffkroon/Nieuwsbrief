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
