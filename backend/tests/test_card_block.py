"""Tests voor het template-eigen kaart-blok (##KAART## / ##KAART_RIJ##)."""

from __future__ import annotations

from app.newsletter.models import Item, Match, NewsletterContent
from app.newsletter.renderer import render_newsletter
from app.newsletter.toolproof import verify_toolproof

BRAND = {
    "brand_name": "Ohcascas",
    "brand_email": "info@ohcascas.nl",
    "website_url": "https://shop.test",
    "primary_color": "#000000",
    "logo_url": "https://cdn.test/logo.png",
    "dummy_image_url": "https://cdn.test/dummy.png",
}

CARD = (
    "<!-- ##KAART## -->"
    '<div class="cel" style="width:50%"><a href="{{KAART_URL}}">'
    '<img src="{{KAART_IMAGE_URL}}" alt="{{KAART_TITEL}}"></a>'
    "<b>{{KAART_TITEL}}</b><i>{{KAART_SUBTITEL}}</i><s>{{KAART_PRIJS}}</s>"
    '<a href="{{KAART_URL}}">{{KAART_KNOP_TEKST}}</a></div>'
    "<!-- /##KAART## -->"
)

WITH_ROWS = (
    "<html><body><p>{{INTRO_1}}</p>"
    f'<!-- ##KAART_RIJ## --><div class="rij">{CARD}</div><!-- /##KAART_RIJ## -->'
    "{% unsubscribe %}</body></html>"
)

WITHOUT_ROWS = f"<html><body>{CARD}{{% unsubscribe %}}</body></html>"


def _item(n: int) -> Item:
    return Item(
        title=f"Ring {n}",
        url=f"https://shop.test/ring-{n}",
        subtitle=f"Sub {n}",
        price=f"€ {n}9,95",
        image_url=f"https://cdn.test/ring-{n}.png",
        button_text="SHOP NU",
    )


def _content(items: tuple[Item, ...] = (), matches: tuple[Match, ...] = ()) -> NewsletterContent:
    return NewsletterContent(
        theme="Zomer",
        subject="Zomer",
        intro_1="Intro een.",
        intro_2="Intro twee.",
        main_cta_text="SHOP",
        main_cta_url="https://shop.test/collectie",
        slot_cta_text="SHOP",
        slot_cta_url="https://shop.test/collectie",
        items=items,
        matches=matches,
    )


def test_cards_repeat_client_markup_two_per_row() -> None:
    html = render_newsletter(WITH_ROWS, BRAND, _content(items=(_item(1), _item(2), _item(3))))
    # Het ontwerp van de klant blijft staan en wordt per item herhaald.
    assert html.count('class="cel"') == 3
    # Drie kaarten = twee rijen (2 + 1).
    assert html.count('class="rij"') == 2
    for n in (1, 2, 3):
        assert f"Ring {n}" in html
        assert f"https://shop.test/ring-{n}" in html
        assert f"https://cdn.test/ring-{n}.png" in html
        assert f"€ {n}9,95" in html
    assert "SHOP NU" in html
    # Markers en placeholders zijn opgeruimd; Klaviyo-tag blijft.
    assert "##KAART##" not in html and "{{KAART_" not in html
    assert "{% unsubscribe %}" in html


def test_cards_without_row_wrapper_repeat_in_place() -> None:
    html = render_newsletter(WITHOUT_ROWS, BRAND, _content(items=(_item(1), _item(2))))
    assert html.count('class="cel"') == 2
    assert "##KAART##" not in html


def test_matches_flow_through_card_block() -> None:
    match = Match(
        home="Ajax", away="PSV", price="€ 249",
        url="https://shop.test/ajax", image_url="https://cdn.test/ajax.png",
    )
    html = render_newsletter(WITH_ROWS, BRAND, _content(matches=(match,)))
    assert "Ajax" in html and "vs PSV" in html and "Bestel tickets" in html


def test_empty_content_removes_card_region() -> None:
    html = render_newsletter(WITH_ROWS, BRAND, _content())
    assert 'class="cel"' not in html and 'class="rij"' not in html
    assert "##KAART" not in html
    assert "Intro een." in html  # rest van de template intact


def test_item_without_price_or_image_falls_back() -> None:
    item = Item(title="Ketting", url="https://shop.test/k", button_text="SHOP NU")
    html = render_newsletter(WITH_ROWS, BRAND, _content(items=(item,)))
    assert "Ketting" in html
    assert "https://cdn.test/dummy.png" in html  # dummy-fallback voor de foto
    assert "{{KAART_PRIJS}}" not in html  # lege prijs netjes gestript


def test_verify_toolproof_accepts_card_block() -> None:
    passed, failed = verify_toolproof(WITH_ROWS)
    assert not failed
    assert any("kaart-blok" in p for p in passed)


def test_verify_toolproof_flags_static_card() -> None:
    static = WITH_ROWS.replace("{{KAART_TITEL}}", "Hardcoded Ring")
    _, failed = verify_toolproof(static)
    assert any("kaart-blok" in f for f in failed)


def test_verify_toolproof_flags_unclosed_card_block() -> None:
    broken = WITH_ROWS.replace("<!-- /##KAART## -->", "")
    _, failed = verify_toolproof(broken)
    assert any("niet afgesloten" in f for f in failed)
