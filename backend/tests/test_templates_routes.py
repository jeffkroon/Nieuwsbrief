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
        f"/tenants/{t.id}/templates", json={"name": "Card", "html": "<html>{{INTRO_1}} geen marker</html>"}
    )
    assert resp.status_code == 201


def test_create_rejects_corrupt_template(client, session) -> None:
    # Kopieer-verminking laat een losse `}}` achter; dat mag niet opgeslagen worden.
    t = _tenant(session)
    corrupt = '<html>{{INTRO_1}} <p style="color:styleBG}}">x</p></html>'
    resp = client.post(
        f"/tenants/{t.id}/templates", json={"name": "Corrupt", "html": corrupt}
    )
    assert resp.status_code == 400
    assert "ongeldig" in resp.json()["detail"].lower()


def test_health_green_for_valid_default(client, session) -> None:
    t = _brand_tenant(session)
    client.post(f"/tenants/{t.id}/templates", json={"name": "Basis", "html": MARKER_HTML})
    body = client.get(f"/tenants/{t.id}/templates/health").json()
    assert body["ok"] is True
    assert body["heeft_eigen_template"] is True
    assert body["is_standaard"] is True
    assert body["ontbrekende_brand_velden"] == []


def test_health_red_without_template(client, session) -> None:
    t = _tenant(session)
    body = client.get(f"/tenants/{t.id}/templates/health").json()
    assert body["ok"] is False
    assert body["heeft_eigen_template"] is False


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


# --- Upload, versies en capabilities ---------------------------------------
class _FakeStorage:
    """Slaat niets echt op; geeft een voorspelbare publieke URL terug."""

    def __init__(self) -> None:
        self.uploaded: list[str] = []

    def ensure_bucket(self) -> None:
        pass

    def upload(self, path: str, content: bytes, content_type: str):
        from app.services.storage import StoredImage

        self.uploaded.append(path)
        return StoredImage(storage_path=path, url=f"https://cdn.fake/{path}")

    def delete(self, path: str) -> None:
        pass


@pytest.fixture
def fake_storage():
    from app.deps import get_storage

    storage = _FakeStorage()
    app.dependency_overrides[get_storage] = lambda: storage
    yield storage
    app.dependency_overrides.pop(get_storage, None)


def _zip_export() -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archief:
        archief.writestr("export/index.html", '<html><img src="images/logo.png"></html>')
        archief.writestr("export/images/logo.png", b"png-bytes")
    return buffer.getvalue()


def test_upload_los_html_bestand(client, session, fake_storage) -> None:
    t = _tenant(session)
    resp = client.post(
        f"/tenants/{t.id}/templates/upload",
        files={"file": ("basis.html", MARKER_HTML, "text/html")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["html"] == MARKER_HTML
    assert body["images"] == []
    assert body["capabilities"]  # altijd een uitspraak over wat de template kan


def test_upload_zip_slaat_afbeeldingen_op_en_zet_verwijzingen_om(
    client, session, fake_storage
) -> None:
    t = _tenant(session)
    resp = client.post(
        f"/tenants/{t.id}/templates/upload",
        files={"file": ("export.zip", _zip_export(), "application/zip")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["images"] == ["export/images/logo.png"]
    assert "https://cdn.fake/" in body["html"]
    assert 'src="images/logo.png"' not in body["html"]
    assert fake_storage.uploaded and str(t.id) in fake_storage.uploaded[0]


def test_upload_onbruikbaar_bestand_geeft_nette_fout(client, session, fake_storage) -> None:
    t = _tenant(session)
    resp = client.post(
        f"/tenants/{t.id}/templates/upload",
        files={"file": ("template.docx", b"geen html of zip", "application/msword")},
    )
    assert resp.status_code == 400
    assert "Alleen een .html-bestand" in resp.json()["detail"]


def test_upload_mag_niet_door_een_bedrijfsgebruiker(client, session, as_company, fake_storage) -> None:
    t = _tenant(session)
    resp = client.post(
        f"/tenants/{t.id}/templates/upload",
        files={"file": ("basis.html", MARKER_HTML, "text/html")},
    )
    assert resp.status_code == 403


def test_versies_worden_bewaard_en_teruggezet(client, session) -> None:
    t = _tenant(session)
    eerste = "<html>versie een<!-- ##BANNERS## --></html>"
    tweede = "<html>versie twee<!-- ##BANNERS## --></html>"
    created = client.post(
        f"/tenants/{t.id}/templates", json={"name": "Basis", "html": eerste, "source": "upload"}
    ).json()

    versies = client.get(f"/tenants/{t.id}/templates/{created['id']}/versions").json()
    assert [v["source"] for v in versies] == ["upload"]

    client.put(
        f"/tenants/{t.id}/templates/{created['id']}",
        json={"html": tweede, "source": "handmatig"},
    )
    versies = client.get(f"/tenants/{t.id}/templates/{created['id']}/versions").json()
    assert [v["source"] for v in versies] == ["handmatig", "upload"]  # nieuwste eerst

    oudste = versies[-1]
    hersteld = client.post(
        f"/tenants/{t.id}/templates/{created['id']}/versions/{oudste['id']}/restore"
    )
    assert hersteld.status_code == 200
    assert hersteld.json()["html"] == eerste
    # Het terugzetten is zelf ook een versie, zodat niets verloren gaat.
    bronnen = [v["source"] for v in client.get(
        f"/tenants/{t.id}/templates/{created['id']}/versions"
    ).json()]
    assert bronnen[0] == "terugzetten"


def test_stijlwijziging_maakt_geen_nieuwe_versie(client, session) -> None:
    """Alleen layout-wijzigingen horen in de geschiedenis; kleuren vervuilen de lijst."""
    t = _tenant(session)
    created = client.post(
        f"/tenants/{t.id}/templates", json={"name": "Basis", "html": MARKER_HTML}
    ).json()
    client.patch(
        f"/tenants/{t.id}/templates/{created['id']}/styles",
        json={"styles": {"button_bg": "#112233"}},
    )
    versies = client.get(f"/tenants/{t.id}/templates/{created['id']}/versions").json()
    assert len(versies) == 1


def test_versie_van_andere_template_kan_niet_worden_teruggezet(client, session) -> None:
    t = _tenant(session)
    een = client.post(f"/tenants/{t.id}/templates", json={"name": "Een", "html": MARKER_HTML}).json()
    twee = client.post(f"/tenants/{t.id}/templates", json={"name": "Twee", "html": MARKER_HTML}).json()
    versie_van_een = client.get(f"/tenants/{t.id}/templates/{een['id']}/versions").json()[0]
    resp = client.post(
        f"/tenants/{t.id}/templates/{twee['id']}/versions/{versie_van_een['id']}/restore"
    )
    assert resp.status_code == 404


def test_capabilities_van_losse_html(client, session) -> None:
    t = _tenant(session)
    resp = client.post(
        f"/tenants/{t.id}/templates/capabilities",
        json={"html": "<p>{{INTRO_1}} {{VAK_QUOTE}}</p>"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert any("intro" in regel for regel in body["summary"])
    assert body["details"]["custom_slots"] == ["QUOTE"]


def test_capabilities_zonder_invoer_geeft_nette_fout(client, session) -> None:
    t = _tenant(session)
    assert client.post(f"/tenants/{t.id}/templates/capabilities", json={}).status_code == 400


def test_preview_met_eerdere_nieuwsbrief_als_inhoud(client, session) -> None:
    from app.repositories import newsletters as newsletters_repo

    t = _brand_tenant(session)
    nieuwsbrief = newsletters_repo.create_newsletter(
        session,
        tenant_id=t.id,
        subject="Kerstaanbieding",
        html="<html>oud</html>",
        theme="Kerst",
        input={"intro_1": "Dit is de echte introtekst.", "matches": []},
    )
    resp = client.post(
        f"/tenants/{t.id}/templates/preview",
        json={"html": "<html>{{INTRO_1}}<!-- ##BANNERS## --></html>", "newsletter_id": str(nieuwsbrief.id)},
    )
    assert resp.status_code == 200
    assert "Dit is de echte introtekst." in resp.text


def test_preview_met_nieuwsbrief_van_ander_bedrijf_faalt(client, session) -> None:
    from app.repositories import newsletters as newsletters_repo

    eigen = _brand_tenant(session)
    ander = _tenant(session)
    vreemd = newsletters_repo.create_newsletter(
        session, tenant_id=ander.id, subject="x", html="<html></html>", input={}
    )
    resp = client.post(
        f"/tenants/{eigen.id}/templates/preview",
        json={"html": MARKER_HTML, "newsletter_id": str(vreemd.id)},
    )
    assert resp.status_code == 404


def test_kleurvoorstel_uit_de_huisstijlkleur(client, session) -> None:
    t = _brand_tenant(session)  # primary_color #FF7200
    body = client.get(f"/tenants/{t.id}/templates/style-suggestion").json()
    assert body["primary_color"] == "#FF7200"
    assert body["styles"]["button_bg"] == "#ff7200"
    assert body["styles"]["button_text"] == "#111111"  # berekend op leesbaarheid


def test_kleurvoorstel_met_een_eigen_hoofdkleur(client, session) -> None:
    t = _brand_tenant(session)
    body = client.get(
        f"/tenants/{t.id}/templates/style-suggestion", params={"primary": "#1a3a6e"}
    ).json()
    assert body["styles"]["button_bg"] == "#1a3a6e"
    assert body["styles"]["button_text"] == "#ffffff"


def test_kleurvoorstel_zonder_huisstijlkleur_legt_uit_wat_er_moet_gebeuren(
    client, session
) -> None:
    t = _tenant(session)  # geen primary_color in de config
    body = client.get(f"/tenants/{t.id}/templates/style-suggestion").json()
    assert body["styles"] == {}
    assert "Bedrijven-tab" in body["note"]


def test_leesbaarheidscontrole_meldt_maar_blokkeert_niet(client, session) -> None:
    t = _tenant(session)
    resp = client.post(
        f"/tenants/{t.id}/templates/style-check",
        json={"styles": {"text_color": "#ffffff", "page_bg": "#ffffff"}},
    )
    assert resp.status_code == 200
    assert len(resp.json()["warnings"]) == 1
