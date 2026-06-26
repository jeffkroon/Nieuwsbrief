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
    banner = render_banner(Match(home="Chelsea", away="Arsenal", slug="chelsea-arsenal", price="299,-"), BRAND)
    assert "CHELSEA" in banner
    assert "ARSENAL" in banner
    assert "299,-" in banner
    assert "https://www.voetbalreizenxl.nl/tickets/chelsea-arsenal/" in banner
    assert "#FF7200" in banner  # primary color uit brand


def test_render_newsletter_fills_placeholders() -> None:
    content = _content((Match(home="Chelsea", away="Arsenal", slug="chelsea-arsenal", price="299,-"),))
    html = render_newsletter(TEMPLATE, BRAND, content)
    assert "Kerst in Londen | VoetbalreizenXL" in html
    assert "Eerste alinea." in html and "Tweede alinea." in html
    assert "Bekijk alles" in html
    assert BANNER_MARKER not in html  # marker is vervangen
    assert "CHELSEA" in html
    # Geen onvervulde eigen placeholders meer.
    assert "{{BRAND_NAME}}" not in html and "{{INTRO_1}}" not in html


def test_render_newsletter_keeps_brevo_runtime_placeholders() -> None:
    content = _content((Match(home="Chelsea", away="Arsenal", slug="chelsea-arsenal"),))
    html = render_newsletter(TEMPLATE, BRAND, content)
    # Brevo vult deze zelf in bij verzending; mogen niet vervangen worden.
    assert "{{ contact.EMAIL }}" in html
    assert "{{ unsubscribe }}" in html


def test_render_multiple_banners() -> None:
    matches = (
        Match(home="Chelsea", away="Arsenal", slug="a"),
        Match(home="Tottenham", away="Everton", slug="b"),
    )
    html = render_newsletter(TEMPLATE, BRAND, _content(matches))
    assert html.count("Bestel tickets") == 2


def test_default_price_is_on_request() -> None:
    html = render_newsletter(TEMPLATE, BRAND, _content((Match(home="Chelsea", away="Arsenal", slug="a"),)))
    assert PRICE_ON_REQUEST in html


def test_missing_brand_field_raises() -> None:
    broken = {k: v for k, v in BRAND.items() if k != "logo_url"}
    with pytest.raises(ValueError, match="logo_url"):
        render_newsletter(TEMPLATE, broken, _content((Match(home="A", away="B", slug="a"),)))


def test_no_matches_raises() -> None:
    with pytest.raises(ValueError, match="wedstrijd"):
        render_newsletter(TEMPLATE, BRAND, _content(()))
