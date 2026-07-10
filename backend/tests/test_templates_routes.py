"""API-tests voor de template-routes incl. de rolverdeling (admin vs bedrijf)."""

from __future__ import annotations

import pytest

from app.deps import current_role
from app.main import app
from app.repositories import tenants as tenants_repo
from app.schemas import TenantCreate

MARKER_HTML = "<html><!-- ##BANNERS## --></html>"


def _tenant(session):
    return tenants_repo.create_tenant(session, TenantCreate(slug="ftg", name="FTG"))


def _brand_tenant(session):
    """Tenant met volledige brand-config zodat de preview kan renderen."""
    cfg = {
        "brand_name": "VoetbalreizenXL",
        "brand_email": "info@voetbalreizenxl.nl",
        "brand_adres": "Julianaweg 141",
        "brand_postcode_stad": "1131 DH Volendam",
        "brand_telefoon": "+31 85 303 6791",
        "brand_kvk": "76484211",
        "website_url": "https://www.voetbalreizenxl.nl",
        "primary_color": "#FF7200",
        "logo_url": "https://example.com/logo.png",
        "dummy_image_url": "https://example.com/dummy.png",
        "facebook_url": "https://facebook.com/x",
        "instagram_url": "https://instagram.com/x",
        "youtube_url": "https://youtube.com/x",
    }
    return tenants_repo.create_tenant(
        session, TenantCreate(slug="vrxl", name="VRXL", config=cfg)
    )


@pytest.fixture
def as_company():
    """Forceer de bedrijfsrol (geen admin)."""
    app.dependency_overrides[current_role] = lambda: "company"
    yield
    app.dependency_overrides.pop(current_role, None)


def test_create_and_list(client, session) -> None:
    t = _tenant(session)
    resp = client.post(
        f"/tenants/{t.id}/templates", json={"name": "Basis", "html": MARKER_HTML}
    )
    assert resp.status_code == 201
    assert resp.json()["is_default"] is True
    listed = client.get(f"/tenants/{t.id}/templates").json()
    assert [x["name"] for x in listed] == ["Basis"]


def test_create_without_marker_is_allowed(client, session) -> None:
    # Een afwijkende layout zonder wedstrijdblokken (bv. kaart-/review-layout) mag.
    t = _tenant(session)
    resp = client.post(
        f"/tenants/{t.id}/templates", json={"name": "Card", "html": "<html>geen marker</html>"}
    )
    assert resp.status_code == 201


def test_validate_endpoint(client, session) -> None:
    t = _tenant(session)
    resp = client.post(
        f"/tenants/{t.id}/templates/validate", json={"html": MARKER_HTML}
    )
    body = resp.json()
    assert body["ok"] is True
    assert body["warnings"]  # mist aanbevolen placeholders


def test_company_cannot_create_layout(client, session, as_company) -> None:
    t = _tenant(session)
    resp = client.post(
        f"/tenants/{t.id}/templates", json={"name": "X", "html": MARKER_HTML}
    )
    assert resp.status_code == 403


def test_company_can_update_styles(client, session, as_company) -> None:
    # Layout door admin laten aanmaken (geen rol-override actief in deze stap):
    app.dependency_overrides.pop(current_role, None)
    t = _tenant(session)
    tpl = client.post(
        f"/tenants/{t.id}/templates", json={"name": "Basis", "html": MARKER_HTML}
    ).json()
    # Nu als bedrijf de stijl aanpassen -> mag.
    app.dependency_overrides[current_role] = lambda: "company"
    resp = client.patch(
        f"/tenants/{t.id}/templates/{tpl['id']}/styles",
        json={"styles": {"button_bg": "#00ff00"}},
    )
    assert resp.status_code == 200
    assert resp.json()["styles"] == {"button_bg": "#00ff00"}


def test_set_default(client, session) -> None:
    t = _tenant(session)
    a = client.post(f"/tenants/{t.id}/templates", json={"name": "A", "html": MARKER_HTML}).json()
    b = client.post(f"/tenants/{t.id}/templates", json={"name": "B", "html": MARKER_HTML}).json()
    client.post(f"/tenants/{t.id}/templates/{b['id']}/default")
    by_name = {x["name"]: x["is_default"] for x in client.get(f"/tenants/{t.id}/templates").json()}
    assert by_name == {"A": False, "B": True}


def test_preview_applies_custom_color(client, session) -> None:
    t = _brand_tenant(session)
    resp = client.post(
        f"/tenants/{t.id}/templates/preview",
        json={"styles": {"button_bg": "#abcdef"}},
    )
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "#abcdef" in resp.text  # de gekozen knopkleur zit in de gerenderde HTML


def test_duplicate_name_gives_clean_conflict(client, session) -> None:
    t = _tenant(session)
    client.post(f"/tenants/{t.id}/templates", json={"name": "Basis", "html": MARKER_HTML})
    resp = client.post(f"/tenants/{t.id}/templates", json={"name": "Basis", "html": MARKER_HTML})
    assert resp.status_code == 409
    assert "Basis" in resp.json()["detail"]


def test_delete(client, session) -> None:
    t = _tenant(session)
    tpl = client.post(f"/tenants/{t.id}/templates", json={"name": "A", "html": MARKER_HTML}).json()
    assert client.delete(f"/tenants/{t.id}/templates/{tpl['id']}").status_code == 204
    assert client.get(f"/tenants/{t.id}/templates").json() == []


def test_toolproof_endpoint_transforms_and_reports(client, session) -> None:
    from app.deps import get_anthropic_client
    from app.main import app
    from tests.test_toolproof import OPS, STATIC_HTML, FakeLLM

    t = _tenant(session)
    app.dependency_overrides[get_anthropic_client] = lambda: FakeLLM(
        {"operations": OPS, "notes": []}
    )
    try:
        resp = client.post(f"/tenants/{t.id}/templates/toolproof", json={"html": STATIC_HTML})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "{{INTRO_1}}" in body["html"]
        assert "<!-- ##KAART## -->" in body["html"]
        assert "##CARDS##" not in body["html"]  # standaard-ontwerp-route bestaat niet meer
        assert body["checks_failed"] == []
        assert isinstance(body["styles"], dict)  # basis-stijl gaat mee naar de frontend
    finally:
        app.dependency_overrides.pop(get_anthropic_client, None)


def test_toolproof_is_admin_only(client, session) -> None:
    from app.deps import current_role
    from app.main import app

    t = _tenant(session)
    app.dependency_overrides[current_role] = lambda: "company"
    try:
        resp = client.post(f"/tenants/{t.id}/templates/toolproof", json={"html": "<html></html>"})
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(current_role, None)
