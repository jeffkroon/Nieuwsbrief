"""Tests voor de leesbare voortgangsregels tijdens een chat-beurt."""

from __future__ import annotations

from app.newsletter.orchestrator import ToolEvent
from app.newsletter.progress import describe


def test_wedstrijden_met_aantal_en_pagina() -> None:
    regel = describe(
        ToolEvent(
            name="find_matches",
            input={"url": "https://www.voetbalreizenxl.nl/tickets/serie-a/"},
            result={"count": 15, "source_url": "https://www.voetbalreizenxl.nl/tickets/serie-a/"},
        )
    )
    assert "15 wedstrijden gevonden" in regel
    assert "/tickets/serie-a/" in regel
    assert "https://" not in regel  # alleen het pad, anders wordt de regel onleesbaar


def test_concept_noemt_platform_en_aantal_blokken() -> None:
    regel = describe(
        ToolEvent(
            name="create_newsletter_draft",
            input={},
            result={"esp": "klaviyo", "matches_used": [1, 2], "clubs_used": [3], "items_used": []},
        )
    )
    assert "Klaviyo" in regel and "3 blokken" in regel
    assert "niets verstuurd" in regel.lower()


def test_fout_wordt_kort_gemeld() -> None:
    regel = describe(ToolEvent(name="find_products", input={}, error="pagina gaf status 404"))
    assert "mislukt" in regel and "404" in regel


def test_voorbeeld_meldt_lege_invulvakken() -> None:
    regel = describe(
        ToolEvent(name="preview_newsletter", input={}, result={"unfilled_fields": ["QUOTE", "TIP"]})
    )
    assert "2 invulvakken nog leeg" in regel


def test_onbekende_tool_geeft_toch_een_regel() -> None:
    assert describe(ToolEvent(name="iets_nieuws", input={}, result={})) == "Iets nieuws: klaar"


def test_lange_foutmelding_wordt_ingekort() -> None:
    regel = describe(ToolEvent(name="find_matches", input={}, error="x" * 500))
    assert len(regel) < 200 and regel.endswith("...)")


def test_uit_werkgeheugen_wordt_zichtbaar_gemeld() -> None:
    regel = describe(
        ToolEvent(
            name="find_products",
            input={"url": "https://shop.test/"},
            result={"products": ["a", "b", "c"], "source_url": "https://shop.test/", "from_memory": True},
        )
    )
    assert "3 items opgehaald" in regel
    assert "al eerder in dit gesprek opgehaald" in regel


def test_verse_aanroep_krijgt_geen_geheugen_notitie() -> None:
    regel = describe(
        ToolEvent(
            name="find_products",
            input={"url": "https://shop.test/"},
            result={"count": 3, "source_url": "https://shop.test/"},
        )
    )
    assert "al eerder" not in regel
