"""Foto's in eigen invulvakken: bibliotheek-bestandsnaam wordt de echte URL.

Aanleiding (Runderkamp, 26 nov): de assistent vulde {{VAK_HERO_TITEL_AFBEELDING}}
met de bestandsnaam 'titel-runderkamps-kerstbuffet.png' in plaats van de URL. De
bannerfoto werd al omgezet via de bibliotheek, een invulvak niet: kapotte foto in
de mail. Garantie in code: een vak dat in een src-attribuut staat krijgt een echte
URL uit de bibliotheek, of de preview weigert met uitleg.
"""

from __future__ import annotations

import uuid

import pytest

from app.newsletter.block_validation import resolved_custom_images
from app.newsletter.custom_fields import image_slots
from app.newsletter.tools import ToolContext
from app.repositories import images as images_repo
from app.repositories import tenants as tenants_repo
from app.schemas import TenantCreate

TEMPLATE = (
    '<img src="{{VAK_TITEL_FOTO}}" alt="{{VAK_KOP}}">'
    "<h1>{{VAK_KOP}}</h1>"
    "<img src='{{VAK_LOS_FOTO}}'>"
)
LIB_URL = "https://cdn.example/runderkamp/titels/abc-titel.png"


def test_image_slots_vindt_alleen_vakken_in_src() -> None:
    assert image_slots(TEMPLATE) == {"TITEL_FOTO", "LOS_FOTO"}


@pytest.fixture
def ctx(session, cipher):
    slug = f"foto-{uuid.uuid4().hex[:6]}"
    tenant = tenants_repo.create_tenant(session, TenantCreate(slug=slug, name=slug))
    images_repo.create_image(
        session, tenant_id=tenant.id, category="titels", filename="titel.png",
        description="Titelafbeelding", storage_path="x/titel.png", url=LIB_URL,
    )
    return ToolContext(session=session, tenant_id=tenant.id, cipher=cipher)


def test_bestandsnaam_uit_bibliotheek_wordt_url(ctx) -> None:
    fields = {"TITEL_FOTO": "titel.png", "KOP": "titel.png"}
    out = resolved_custom_images(ctx, fields, TEMPLATE)
    assert out["TITEL_FOTO"] == LIB_URL
    assert out["KOP"] == "titel.png"  # tekstvak blijft tekst, ook als het op een naam lijkt


def test_categorie_prefix_werkt_ook(ctx) -> None:
    out = resolved_custom_images(ctx, {"TITEL_FOTO": "titels:titel.png"}, TEMPLATE)
    assert out["TITEL_FOTO"] == LIB_URL


def test_volledige_url_en_leeg_blijven_staan(ctx) -> None:
    fields = {"TITEL_FOTO": "https://elders.example/x.jpg", "LOS_FOTO": ""}
    assert resolved_custom_images(ctx, fields, TEMPLATE) == fields


def test_onbekende_naam_in_fotovak_wordt_geweigerd(ctx) -> None:
    with pytest.raises(ValueError) as exc:
        resolved_custom_images(ctx, {"TITEL_FOTO": "bestaat-niet.png"}, TEMPLATE)
    melding = str(exc.value)
    assert "VAK_TITEL_FOTO" in melding and "list_images" in melding


def test_vage_omschrijving_wordt_niet_gegokt(ctx) -> None:
    # resolve_image matcht ook op omschrijving; voor invulvakken alleen exact.
    with pytest.raises(ValueError):
        resolved_custom_images(ctx, {"TITEL_FOTO": "Titelafbeelding"}, TEMPLATE)
