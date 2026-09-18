"""Tests voor het afleiden van een kleurenpalet uit de huisstijlkleur."""

from __future__ import annotations

import pytest

from app.newsletter.brand_colors import (
    MIN_CONTRAST,
    contrast_ratio,
    contrast_waarschuwingen,
    leesbare_tekstkleur,
    normalize_hex,
    palette_from_primary,
    verdonker,
)


@pytest.mark.parametrize(
    "invoer,verwacht",
    [("#FF7200", "#ff7200"), ("#abc", "#aabbcc"), (" #Fff ", "#ffffff"),
     ("ff7200", None), ("#12345", None), (None, None), ("", None)],
)
def test_normalize_hex(invoer, verwacht) -> None:
    assert normalize_hex(invoer) == verwacht


def test_palet_laat_alles_de_hoofdkleur_volgen() -> None:
    palet = palette_from_primary("#FF7200")
    for sleutel in ("button_bg", "hero_button_bg", "cta_button_bg", "accent", "block_border"):
        assert palet[sleutel] == "#ff7200"


def test_knoptekst_wordt_berekend_niet_gekozen() -> None:
    """Wit op geel leest niemand; de tekstkleur volgt het contrast."""
    op_donkerblauw = palette_from_primary("#1a3a6e")
    op_geel = palette_from_primary("#ffe600")
    assert op_donkerblauw["button_text"] == "#ffffff"
    assert op_geel["button_text"] == "#111111"
    for palet in (op_donkerblauw, op_geel):
        assert contrast_ratio(palet["button_text"], palet["button_bg"]) >= MIN_CONTRAST


def test_tweede_kleur_is_een_donkerder_tint_van_het_merk() -> None:
    palet = palette_from_primary("#ff7200")
    assert palet["price_color"] == verdonker("#ff7200")
    assert palet["price_color"] != palet["button_bg"]
    assert palet["badge_bg"] == palet["price_color"]


def test_eigen_tweede_kleur_wint() -> None:
    palet = palette_from_primary("#ff7200", "#1a3a6e")
    assert palet["price_color"] == "#1a3a6e"


def test_ongeldige_kleur_geeft_geen_palet() -> None:
    assert palette_from_primary("oranje") == {}
    assert palette_from_primary("") == {}


def test_leesbare_tekstkleur_grenzen() -> None:
    assert leesbare_tekstkleur("#000000") == "#ffffff"
    assert leesbare_tekstkleur("#ffffff") == "#111111"


def test_contrast_ratio_uitersten() -> None:
    assert round(contrast_ratio("#000000", "#ffffff"), 1) == 21.0
    assert contrast_ratio("#ff7200", "#ff7200") == 1.0


def test_waarschuwing_bij_wit_op_wit() -> None:
    meldingen = contrast_waarschuwingen({"text_color": "#ffffff", "page_bg": "#ffffff"})
    assert len(meldingen) == 1 and "lopende tekst" in meldingen[0]


def test_geen_waarschuwing_bij_een_leesbare_combinatie() -> None:
    assert contrast_waarschuwingen({"text_color": "#3b3f44", "page_bg": "#ffffff"}) == []


def test_ontbrekende_kleuren_geven_geen_valse_waarschuwing() -> None:
    assert contrast_waarschuwingen({"text_color": "#ffffff"}) == []
