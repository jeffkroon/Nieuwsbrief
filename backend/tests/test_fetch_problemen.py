"""Tests voor de uitleg bij een mislukte pagina-ophaal.

Aanleiding: bij een 403 meldde de assistent "de website is momenteel niet
bereikbaar" en stelde voor het later opnieuw te proberen. Dat klopt niet: de site
werkt, hij weigert onze server, en herhalen helpt dus nooit.
"""

from __future__ import annotations

import pytest

from app.newsletter.extraction import fetch_probleem


def test_403_zegt_dat_we_geblokkeerd_worden_en_dat_herhalen_niet_helpt() -> None:
    melding = fetch_probleem("https://www.voetbalreizenxl.nl/tickets/", 403)
    assert "weigert onze server" in melding
    assert "Opnieuw proberen helpt niet" in melding
    assert "IP-adres" in melding
    assert "niet bereikbaar" not in melding


def test_429_zegt_juist_wel_dat_wachten_helpt() -> None:
    melding = fetch_probleem("https://example.com/", 429)
    assert "te veel verzoeken" in melding and "paar minuten" in melding


def test_404_wijst_op_de_link_zelf() -> None:
    assert "bestaat niet" in fetch_probleem("https://example.com/weg", 404)


def test_geen_antwoord_vraagt_of_het_domein_nog_bestaat() -> None:
    melding = fetch_probleem("https://voetbaltrips.nl/", None)
    assert "domein" in melding


@pytest.mark.parametrize("status", [500, 502, 503])
def test_serverfouten_mogen_wel_opnieuw(status: int) -> None:
    assert "storing" in fetch_probleem("https://example.com/", status)


def test_onbekende_status_blijft_feitelijk() -> None:
    assert "status 418" in fetch_probleem("https://example.com/", 418)


def test_elke_melding_noemt_de_url() -> None:
    for status in (403, 404, 429, 500, None, 418):
        assert "https://example.com/x" in fetch_probleem("https://example.com/x", status)
