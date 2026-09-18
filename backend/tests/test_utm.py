"""Tests voor de UTM-parameters op de links in de nieuwsbrief."""

from __future__ import annotations

from app.newsletter.utm import add_utm, utm_params

SITE = "https://www.voetbalreizenxl.nl"
PARAMS = {"utm_source": "nieuwsbrief", "utm_medium": "email", "utm_campaign": "serie-a"}


def test_staat_uit_zonder_configuratie() -> None:
    assert utm_params({}) == {}
    assert utm_params({"utm": {}}) == {}


def test_campagne_valt_terug_op_het_thema() -> None:
    params = utm_params({"utm": {"source": "nieuwsbrief"}}, campaign="Serie A in maart!")
    assert params == {"utm_source": "nieuwsbrief", "utm_campaign": "serie-a-in-maart"}


def test_eigen_links_krijgen_parameters() -> None:
    html = f'<a href="{SITE}/tickets/as-roma/">Roma</a>'
    resultaat = add_utm(html, PARAMS, website_url=SITE)
    assert "utm_source=nieuwsbrief" in resultaat and "utm_campaign=serie-a" in resultaat
    assert resultaat.startswith(f'<a href="{SITE}/tickets/as-roma/?')


def test_externe_links_blijven_ongemoeid() -> None:
    html = '<a href="https://facebook.com/voetbalreizenxl">fb</a>'
    assert add_utm(html, PARAMS, website_url=SITE) == html


def test_platform_tags_en_mailto_blijven_ongemoeid() -> None:
    html = '<a href="{{ unsubscribe }}">weg</a><a href="mailto:info@x.nl">mail</a>'
    assert add_utm(html, PARAMS, website_url=SITE) == html


def test_bestaande_query_blijft_behouden() -> None:
    html = f'<a href="{SITE}/tickets/?sort=prijs">x</a>'
    resultaat = add_utm(html, PARAMS, website_url=SITE)
    assert "sort=prijs" in resultaat and "utm_source=nieuwsbrief" in resultaat


def test_link_met_eigen_tracking_wordt_niet_overschreven() -> None:
    html = f'<a href="{SITE}/x?utm_source=partner">x</a>'
    assert add_utm(html, PARAMS, website_url=SITE) == html


def test_www_en_kaal_domein_gelden_als_dezelfde_site() -> None:
    html = '<a href="https://voetbalreizenxl.nl/tickets/">x</a>'
    assert "utm_source" in add_utm(html, PARAMS, website_url=SITE)


def test_zonder_parameters_verandert_er_niets() -> None:
    html = f'<a href="{SITE}/x">x</a>'
    assert add_utm(html, {}, website_url=SITE) == html


def test_activecampaign_tag_in_de_url_wordt_met_rust_gelaten() -> None:
    """De oude check keek alleen naar het eerste teken van de host en deed dus
    niets; een %TAG% in het pad moet wel worden herkend."""
    html = f'<a href="{SITE}/volg/%UNSUBSCRIBELINK%">weg</a>'
    assert add_utm(html, PARAMS, website_url=SITE) == html


def test_gewone_procent_codering_krijgt_gewoon_utm() -> None:
    """%20 is geen platform-tag; zo'n link hoort wel gemeten te worden."""
    html = f'<a href="{SITE}/reis%20naar%20rome">x</a>'
    assert "utm_source=nieuwsbrief" in add_utm(html, PARAMS, website_url=SITE)
