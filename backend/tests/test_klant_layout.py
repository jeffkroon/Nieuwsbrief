"""Klant-login beheert de layout van het eigen bedrijf, nooit die van een ander.

Een klant met een eigen account (sessie gebonden aan één bedrijf) mag templates
uploaden, bewerken, verwijderen en versies terugzetten, maar alleen voor dat
bedrijf. Een ongebonden niet-admin-sessie blijft geweigerd, zoals voorheen.
"""

from __future__ import annotations

import uuid

import pytest

from app.deps import SessionInfo, current_session_info
from app.main import app
from app.repositories import tenants as tenants_repo
from app.schemas import TenantCreate

HTML_EEN = "<html>een<!-- ##BANNERS## --></html>"
HTML_TWEE = "<html>twee<!-- ##BANNERS## --></html>"


def _tenant(session, prefix: str):
    slug = f"{prefix}-{uuid.uuid4().hex[:6]}"
    return tenants_repo.create_tenant(session, TenantCreate(slug=slug, name=slug))


@pytest.fixture
def als_sessie():
    def install(role: str, tenant_id=None) -> None:
        app.dependency_overrides[current_session_info] = lambda: SessionInfo(
            role=role, tenant_id=tenant_id
        )

    yield install
    app.dependency_overrides.pop(current_session_info, None)


def test_klant_beheert_layout_van_eigen_bedrijf(client, session, als_sessie) -> None:
    eigen = _tenant(session, "eigen")
    als_sessie("company", eigen.id)
    basis = f"/tenants/{eigen.id}/templates"

    assert client.get(f"{basis}/starter").status_code == 200
    assert client.post(f"{basis}/validate", json={"html": HTML_EEN}).status_code == 200
    assert client.post(f"{basis}/capabilities", json={"html": HTML_EEN}).status_code == 200
    upload = client.post(
        f"{basis}/upload", files={"file": ("basis.html", HTML_EEN, "text/html")}
    )
    assert upload.status_code == 200

    created = client.post(basis, json={"name": "Basis", "html": HTML_EEN})
    assert created.status_code == 201
    tid = created.json()["id"]
    assert client.put(f"{basis}/{tid}", json={"html": HTML_TWEE}).status_code == 200

    versies = client.get(f"{basis}/{tid}/versions")
    assert versies.status_code == 200
    oudste = versies.json()[-1]["id"]
    terug = client.post(f"{basis}/{tid}/versions/{oudste}/restore")
    assert terug.status_code == 200
    assert terug.json()["html"] == HTML_EEN

    assert client.delete(f"{basis}/{tid}").status_code == 204


def test_klant_kan_niet_bij_layout_van_ander_bedrijf(client, session, als_sessie) -> None:
    eigen = _tenant(session, "eigen")
    ander = _tenant(session, "ander")
    andere_tpl = client.post(  # als admin (standaard in tests) aangemaakt
        f"/tenants/{ander.id}/templates", json={"name": "Van ander", "html": HTML_EEN}
    ).json()

    als_sessie("company", eigen.id)
    basis = f"/tenants/{ander.id}/templates"
    pogingen = [
        client.get(f"{basis}/starter"),
        client.post(basis, json={"name": "Inbraak", "html": HTML_EEN}),
        client.put(f"{basis}/{andere_tpl['id']}", json={"html": HTML_TWEE}),
        client.delete(f"{basis}/{andere_tpl['id']}"),
        client.get(f"{basis}/{andere_tpl['id']}/versions"),
        client.post(f"{basis}/upload", files={"file": ("x.html", HTML_EEN, "text/html")}),
    ]
    assert [r.status_code for r in pogingen] == [403] * len(pogingen)


def test_ongebonden_bedrijfssessie_blijft_geweigerd(client, session, als_sessie) -> None:
    t = _tenant(session, "los")
    als_sessie("company", None)
    resp = client.post(f"/tenants/{t.id}/templates", json={"name": "X", "html": HTML_EEN})
    assert resp.status_code == 403


def test_klant_houdt_beheerrechten_van_dunion_niet(client, session, als_sessie) -> None:
    eigen = _tenant(session, "eigen")
    als_sessie("company", eigen.id)
    # Gezondheidsrapport, bedrijfsgegevens en sleutels blijven alleen voor Dunion.
    assert client.get(f"/tenants/{eigen.id}/templates/health").status_code == 403
    assert client.patch(f"/tenants/{eigen.id}", json={"name": "Nieuw"}).status_code == 403
    sleutel = {"kind": "activecampaign_api_key", "value": "x"}
    assert client.put(f"/tenants/{eigen.id}/secrets", json=sleutel).status_code == 403


@pytest.mark.parametrize(
    ("role", "gebonden", "verwacht"),
    [("admin", False, True), ("company", True, True), ("company", False, False)],
)
def test_me_meldt_of_layout_beheerd_mag_worden(
    client, als_sessie, role: str, gebonden: bool, verwacht: bool
) -> None:
    als_sessie(role, uuid.uuid4() if gebonden else None)
    assert client.get("/me").json()["can_manage_layout"] is verwacht
