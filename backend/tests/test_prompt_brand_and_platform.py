"""Systeemprompt: kloppende stijl-regel, bedrijfsblok en platform-neutrale tools."""

import json

from app.newsletter.prompts import build_system_prompt
from app.newsletter.tool_schemas import TOOL_DEFINITIONS

_BRAND = {
    "brand_name": "VoetbalreizenXL",
    "website_url": "https://www.voetbalreizenxl.nl",
    "matches_url": "https://www.voetbalreizenxl.nl/wedstrijden",
    "claude_prompt": "Spreek de lezer aan met je en noem altijd de stadionsfeer.",
    "brevo_api_key": "geheim-123",
    "tone_of_voice": "Sportief en enthousiast.",
    "primary_color": "#ff0000",
}


def test_stijlregel_niet_tegenstrijdig():
    prompt = build_system_prompt()
    assert "Dit geldt voor ALLEEN deze nieuwsbrief" in prompt
    assert "Dit geldt voor ALLE nieuwsbrieven van deze template" not in prompt


def test_bedrijfsblok_met_brand():
    prompt = build_system_prompt(brand=_BRAND)
    assert "=== BEDRIJF ===" in prompt
    for waarde in ("VoetbalreizenXL", _BRAND["website_url"], _BRAND["matches_url"],
                   _BRAND["claude_prompt"]):
        assert waarde in prompt


def test_bedrijfsblok_zonder_secrets_en_tone():
    prompt = build_system_prompt(brand=_BRAND)
    blok = prompt.split("=== BEDRIJF ===", 1)[1]
    assert "geheim-123" not in prompt
    assert "Sportief en enthousiast." not in blok
    assert "#ff0000" not in blok


def test_bedrijfsblok_ontbreekt_zonder_brand():
    assert "=== BEDRIJF ===" not in build_system_prompt()
    assert "=== BEDRIJF ===" not in build_system_prompt(brand={})
    assert "=== BEDRIJF ===" not in build_system_prompt(brand={"brand_name": "  "})


def test_bedrijfsblok_alleen_gevulde_velden():
    prompt = build_system_prompt(brand={"brand_name": "Theo Tol", "matches_url": ""})
    blok = prompt.split("=== BEDRIJF ===", 1)[1]
    assert "Theo Tol" in blok
    assert "matches_url" not in blok


def test_bedrijfsblok_stabiel_voor_cache():
    omgekeerd = dict(reversed(list(_BRAND.items())))
    assert build_system_prompt(brand=_BRAND) == build_system_prompt(brand=omgekeerd)


def test_tool_beschrijvingen_platform_neutraal():
    for tool in TOOL_DEFINITIONS:
        tekst = json.dumps(tool, ensure_ascii=False)
        tekst = tekst.replace("Brevo, Klaviyo of ActiveCampaign", "")
        assert "Brevo" not in tekst, tool["name"]


def test_get_brand_config_verwijst_naar_bedrijfsblok():
    tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "get_brand_config")
    assert "BEDRIJF" in tool["description"]
