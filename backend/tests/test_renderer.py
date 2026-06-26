"""Unit-tests voor de nieuwsbrief-renderer (puur, geen I/O)."""

from __future__ import annotations

import pytest

from app.newsletter.models import PRICE_ON_REQUEST, Match, NewsletterContent
from app.newsletter.renderer import (
    BANNER_MARKER,
    club_image_url,
    render_banner,
    render_newsletter,
)

BRAND = {
    "brand_name": "VoetbalreizenXL",
    "brand_email": "info@voetbalreizenxl.nl",
    "brand_adres": "Julianaweg 141 JK",
    "brand_postcode_stad": "1131 DH Volendam",
    "brand_telefoon": "+31 85 303 6791",
    "brand_kvk": "76484211",
    "website_url": "https://www.voetbalreizenxl.nl",
    "base_tickets_url": "https://www.voetbalreizenxl.nl/tickets/",
    "primary_color": "#FF7200",
    "logo_url": "https://cdn/logo.png",
    "header_image_url": "https://cdn/header.png",
    "dummy_image_url": "https://cdn/dummy.png",
    "facebook_url": "https://fb.com/x",
    "instagram_url": "https://ig.com/x",
    "youtube_url": "https://yt.com/x",
    "club_images": {"chelsea": "https://cdn/chelsea.png", "tottenham": ""},
}

TEMPLATE = (
    "<title>{{EMAIL_TITEL}}</title>"
    "<h1>{{HEADER_TITEL}}</h1><span>{{HEADER_SUBTITEL}}</span>{{HEADER_CTA}}"
    "<a href='{{WEBSITE_URL}}'>{{BRAND_NAME}}</a>"
    "<p>{{INTRO_1}}</p><p>{{INTRO_2}}</p>"
    "<a href='{{HOOFD_CTA_URL}}'>{{HOOFD_CTA_TEKST}}</a>"
    f"{BANNER_MARKER}"
    "<a href='{{SLOT_CTA_URL}}'>{{SLOT_CTA_TEKST}}</a>"
    "footer {{BRAND_KVK}} {{ contact.EMAIL }} {{ unsubscribe }}"
)


def _content(matches: tuple[Match, ...]) -> NewsletterContent:
    return NewsletterContent(
        theme="Kerst in Londen",
        subject="Kerst in Londen",
        intro_1="Eerste alinea.",
        intro_2="Tweede alinea.",
        main_cta_text="Bekijk alles",
        main_cta_url="https://x/all",
        slot_cta_text="Plan je trip",
        slot_cta_url="https://x/plan",
        matches=matches,
    )


def test_club_image_lookup_and_fallback() -> None:
    assert club_image_url("Chelsea", BRAND) == "https://cdn/chelsea.png"
    # Lege waarde valt terug op dummy.
    assert club_image_url("Tottenham", BRAND) == "https://cdn/dummy.png"
    # Onbekende club valt terug op dummy.
    assert club_image_url("Ajax", BRAND) == "https://cdn/dummy.png"


def test_render_banner_contains_match_data() -> None:
    banner = render_banner(Match(home="Chelsea", away="Arsenal", url="https://www.voetbalreizenxl.nl/tickets/chelsea-arsenal/", price="299,-"), BRAND)
    assert "CHELSEA" in banner
    assert "ARSENAL" in banner
    assert "299,-" in banner
    assert "https://www.voetbalreizenxl.nl/tickets/chelsea-arsenal/" in banner
    assert "#FF7200" in banner  # primary color uit brand


def test_render_newsletter_fills_placeholders() -> None:
    content = _content((Match(home="Chelsea", away="Arsenal", url="https://www.voetbalreizenxl.nl/tickets/chelsea-arsenal/", price="299,-"),))
    html = render_newsletter(TEMPLATE, BRAND, content)
    assert "Kerst in Londen | VoetbalreizenXL" in html
    assert "Eerste alinea." in html and "Tweede alinea." in html
    assert "Bekijk alles" in html
    assert BANNER_MARKER not in html  # marker is vervangen
    assert "CHELSEA" in html
    # Geen onvervulde eigen placeholders meer.
    assert "{{BRAND_NAME}}" not in html and "{{INTRO_1}}" not in html


def test_render_newsletter_keeps_brevo_runtime_placeholders() -> None:
    content = _content((Match(home="Chelsea", away="Arsenal", url="https://www.voetbalreizenxl.nl/tickets/chelsea-arsenal/"),))
    html = render_newsletter(TEMPLATE, BRAND, content)
    # Brevo vult deze zelf in bij verzending; mogen niet vervangen worden.
    assert "{{ contact.EMAIL }}" in html
    assert "{{ unsubscribe }}" in html


def test_render_multiple_banners() -> None:
    matches = (
        Match(home="Chelsea", away="Arsenal", url="https://site/a/"),
        Match(home="Tottenham", away="Everton", url="https://site/b/"),
    )
    html = render_newsletter(TEMPLATE, BRAND, _content(matches))
    assert html.count("Bestel tickets") == 2


def test_default_price_is_on_request() -> None:
    html = render_newsletter(TEMPLATE, BRAND, _content((Match(home="Chelsea", away="Arsenal", url="https://site/a/"),)))
    assert PRICE_ON_REQUEST in html


def test_missing_brand_field_raises() -> None:
    broken = {k: v for k, v in BRAND.items() if k != "logo_url"}
    with pytest.raises(ValueError, match="logo_url"):
        render_newsletter(TEMPLATE, broken, _content((Match(home="A", away="B", url="https://site/a/"),)))


def test_no_matches_renders_general_newsletter() -> None:
    # Zonder wedstrijden: geen fout, geen banners, wel header/intro/knoppen.
    html = render_newsletter(TEMPLATE, BRAND, _content(()))
    assert "Bestel tickets" not in html  # geen wedstrijdblokken
    assert BANNER_MARKER not in html
    assert "Bekijk alle wedstrijden" in html  # header-knop blijft
    assert "Eerste alinea." in html


def test_header_title_falls_back_to_theme() -> None:
    # Geen header_title meegegeven -> valt terug op het thema.
    html = render_newsletter(TEMPLATE, BRAND, _content((Match(home="A", away="B", url="https://site/a/"),)))
    assert "<h1>Kerst in Londen</h1>" in html


def test_header_title_and_subtitle_used() -> None:
    content = NewsletterContent(
        theme="Kerst in Londen", subject="x", intro_1="a", intro_2="b",
        main_cta_text="c", main_cta_url="u", slot_cta_text="d", slot_cta_url="u",
        matches=(Match(home="A", away="B", url="https://site/a/"),),
        header_title="PREMIER LEAGUE TOPPERS", header_subtitle="Beleef het live",
    )
    html = render_newsletter(TEMPLATE, BRAND, content)
    assert "<h1>PREMIER LEAGUE TOPPERS</h1>" in html
    assert "Beleef het live" in html


def test_club_banner_renders() -> None:
    from app.newsletter.models import Club
    from app.newsletter.renderer import render_club_banner

    banner = render_club_banner(Club(name="Bayern München", url="https://x/tickets/duitsland/bayern-munchen/", price="€ 349"), BRAND)
    assert "BAYERN MÜNCHEN" in banner
    assert "Bekijk tickets" in banner
    assert "https://x/tickets/duitsland/bayern-munchen/" in banner
    assert "€ 349" in banner


def test_newsletter_with_clubs() -> None:
    from app.newsletter.models import Club
    content = NewsletterContent(
        theme="t", subject="s", intro_1="a", intro_2="b",
        main_cta_text="c", main_cta_url="u", slot_cta_text="d", slot_cta_url="u",
        matches=(), clubs=(Club(name="Ajax", url="https://x/ajax/"),),
    )
    html = render_newsletter(TEMPLATE, BRAND, content)
    assert "AJAX" in html and "Bekijk tickets" in html


def test_hero_cta_default() -> None:
    html = render_newsletter(TEMPLATE, BRAND, _content((Match(home="A", away="B", url="https://site/a/"),)))
    assert "Bekijk alle wedstrijden" in html
    # Default-URL valt terug op base_tickets_url uit de brand.
    assert "https://www.voetbalreizenxl.nl/tickets/" in html


def test_hero_cta_custom_text_and_url() -> None:
    content = NewsletterContent(
        theme="t", subject="s", intro_1="a", intro_2="b",
        main_cta_text="c", main_cta_url="u", slot_cta_text="d", slot_cta_url="u",
        matches=(Match(home="A", away="B", url="https://site/a/"),),
        header_cta_text="Pak je tickets", header_cta_url="https://site/overzicht/",
    )
    html = render_newsletter(TEMPLATE, BRAND, content)
    assert "Pak je tickets" in html
    assert 'href="https://site/overzicht/"' in html


def test_price_has_no_double_euro() -> None:
    # De prijs bevat al een euroteken; de banner mag er geen tweede toevoegen.
    m = Match(home="Chelsea", away="Arsenal", url="https://site/a/", price="€ 249")
    banner = render_banner(m, BRAND)
    assert "€ 249" in banner
    assert "€ €" not in banner and "&euro;" not in banner


def test_price_on_request_no_va_amount_prefix() -> None:
    banner = render_banner(Match(home="A", away="B", url="https://site/a/"), BRAND)
    assert "op aanvraag" in banner
    assert "&euro;" not in banner
