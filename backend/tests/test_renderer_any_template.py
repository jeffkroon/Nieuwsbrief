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


def test_template_without_banner_marker_degrades() -> None:
    # Geen marker en met wedstrijden: geen blokken, geen fout, schone output.
    template = "<html>{{INTRO_1}} geen marker hier</html>"
    out = render_newsletter(template, BRAND, _content([Match("A", "B", "https://x", "€ 9")]))
    assert "Bestel tickets" not in out  # blokken niet gerenderd
    assert "{{" not in out  # geen rauwe placeholders
