"""De renderer moet met elke template-structuur overweg kunnen.

Ongevulde eigen placeholders worden gestript; Brevo-runtime tags blijven staan; een
template zonder banner-marker degradeert netjes (geen wedstrijdblokken, geen fout).
"""

from __future__ import annotations

from app.newsletter.models import Match, NewsletterContent
from app.newsletter.renderer import render_newsletter

BRAND = {
    "brand_name": "X",
    "brand_email": "a@b.nl",
    "brand_adres": "Straat 1",
    "brand_postcode_stad": "1000 AA Stad",
    "brand_telefoon": "+31",
    "brand_kvk": "123",
    "website_url": "https://x.nl",
    "primary_color": "#FF7200",
    "logo_url": "https://x/l.png",
    "dummy_image_url": "https://x/d.png",
    "facebook_url": "#",
    "instagram_url": "#",
    "youtube_url": "#",
}


def _content(matches=()):
    return NewsletterContent(
        theme="T",
        subject="S",
        intro_1="i1",
        intro_2="i2",
        main_cta_text="m",
        main_cta_url="https://x",
        slot_cta_text="s",
        slot_cta_url="https://x",
        matches=tuple(matches),
    )


def test_unknown_internal_placeholder_is_stripped() -> None:
    template = "<html>{{INTRO_1}} {{ONBEKEND_VELD}} einde</html>"
    out = render_newsletter(template, BRAND, _content())
    assert "{{ONBEKEND_VELD}}" not in out
    assert "i1" in out  # bekende placeholder wel gevuld


def test_brevo_runtime_tags_survive() -> None:
    template = "<html>{{INTRO_1}} {{ contact.EMAIL }} {{ unsubscribe }} {{ ##BANNERS## }}</html>"
    out = render_newsletter(template, BRAND, _content())
    assert "{{ contact.EMAIL }}" in out
    assert "{{ unsubscribe }}" in out


def test_klaviyo_runtime_tags_survive() -> None:
    # Klaviyo-templates gebruiken {% ... %} en {{ organization.* }}; die blijven staan.
    template = (
        "<html>{{INTRO_1}} {% unsubscribe %} {% current_year %} "
        "{{ organization.name }} {{ organization.full_address }}</html>"
    )
    out = render_newsletter(template, BRAND, _content())
    for tag in ("{% unsubscribe %}", "{% current_year %}",
                "{{ organization.name }}", "{{ organization.full_address }}"):
        assert tag in out


def test_card_marker_renders_cards() -> None:
    from app.newsletter.models import Club
    from app.newsletter.renderer import render_cards

    template = "<html>{{INTRO_1}} <!-- ##CARDS## --></html>"
    clubs = (
        Club(name="Inter Milan", url="https://x.nl/tickets/italie/inter-milan/", price="op aanvraag",
             image_url="https://cdn/inter.png", stadium="Giuseppe Meazza", city="Milaan"),
    )
    content = NewsletterContent(
        theme="T", subject="S", intro_1="i1", intro_2="i2", main_cta_text="m",
        main_cta_url="https://x", slot_cta_text="s", slot_cta_url="https://x",
        matches=(), clubs=clubs,
    )
    out = render_newsletter(template, BRAND, content)
    assert "INTER MILAN" in out
    assert "https://cdn/inter.png" in out  # echte foto, geen dummy
    assert "/tickets/italie/inter-milan/" in out  # juiste link
    assert "Giuseppe Meazza" in out and "Milaan" in out
    assert "<!-- ##CARDS## -->" not in out  # marker vervangen
    # Losse helper geeft lege string bij geen items.
    assert render_cards((), (), BRAND) == ""


def test_card_label_renders_as_badge_and_accent_colors_name() -> None:
    from app.newsletter.models import Club
    from app.newsletter.renderer import render_cards

    clubs = (
        Club(name="Juventus", url="https://x.nl/juventus", price="op aanvraag",
             image_url="https://cdn/j.png", stadium="Allianz", city="Turijn",
             label="Vroegboekkorting"),
    )
    brand = {**BRAND, "styles": {"accent": "#abcdef"}}
    out = render_cards((), clubs, brand)
    assert "VROEGBOEKKORTING" in out  # optioneel badge-label (hoofdletters)
    assert "#abcdef" in out  # accent kleurt de clubnaam


def test_all_custom_block_and_card_colors_apply() -> None:
    from app.newsletter.models import Club, Match
    from app.newsletter.renderer import render_banner, render_cards

    brand = {**BRAND, "styles": {
        "home_color": "#111111", "away_color": "#222222", "price_color": "#333333",
        "block_border": "#444444", "card_border": "#555555", "card_bg": "#666666",
        "badge_bg": "#777777", "accent": "#888888",
    }}
    banner = render_banner(Match("Ajax", "Feyenoord", "https://x", "€ 10"), brand)
    assert all(c in banner for c in ("#111111", "#222222", "#333333", "#444444"))

    cards = render_cards(
        (),
        (Club(name="PSV", url="https://x", price="€ 20", image_url="https://c/p.png",
              stadium="Philips", city="Eindhoven", label="NIEUW"),),
        brand,
    )
    assert all(c in cards for c in ("#555555", "#666666", "#333333", "#777777", "#888888"))


def test_item_banner_and_card_render_generic_content() -> None:
    from app.newsletter.models import Item
    from app.newsletter.renderer import render_cards, render_item_banner

    item = Item(title="Case Coolblue", url="https://x.nl/cases/coolblue",
                subtitle="SEO en SEA", image_url="https://cdn/case.png",
                button_text="Lees de case")
    banner = render_item_banner(item, BRAND)
    assert "CASE COOLBLUE" in banner
    assert "Lees de case" in banner
    assert "https://x.nl/cases/coolblue" in banner
    assert "op aanvraag" not in banner  # geen prijs = geen prijsregel

    cards = render_cards((), (), BRAND, (item,))
    assert "CASE COOLBLUE" in cards and "Lees de case" in cards
    assert "op aanvraag" not in cards and "v.a." not in cards


def test_item_with_price_shows_price() -> None:
    from app.newsletter.models import Item
    from app.newsletter.renderer import render_item_banner

    out = render_item_banner(
        Item(title="Menu december", url="https://x.nl/menu", price="€ 59",
             button_text="Reserveer"), BRAND,
    )
    assert "€ 59" in out and "Reserveer" in out


def test_items_render_via_markers() -> None:
    from app.newsletter.models import Item

    content = NewsletterContent(
        theme="T", subject="S", intro_1="i1", intro_2="i2", main_cta_text="m",
        main_cta_url="https://x", slot_cta_text="s", slot_cta_url="https://x",
        matches=(), items=(Item(title="Vacature developer", url="https://x.nl/jobs/dev",
                                button_text="Bekijk vacature"),),
    )
    banners = render_newsletter("<html><!-- ##BANNERS## --></html>", BRAND, content)
    cards = render_newsletter("<html><!-- ##CARDS## --></html>", BRAND, content)
    for out in (banners, cards):
        assert "VACATURE DEVELOPER" in out and "Bekijk vacature" in out


def test_template_without_banner_marker_degrades() -> None:
    # Geen marker en met wedstrijden: geen blokken, geen fout, schone output.
    template = "<html>{{INTRO_1}} geen marker hier</html>"
    out = render_newsletter(template, BRAND, _content([Match("A", "B", "https://x", "€ 9")]))
    assert "Bestel tickets" not in out  # blokken niet gerenderd
    assert "{{" not in out  # geen rauwe placeholders
