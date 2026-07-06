"""Unit-tests voor de stijl-laag: sanitatie, defaults en placeholder-injectie."""

from __future__ import annotations

from app.newsletter.styles import (
    DEFAULT_FONT_STACK,
    EMAIL_SAFE_FONTS,
    effective_styles,
    sanitize_styles,
    style_replacements,
)

BRAND = {"primary_color": "#FF7200"}


def test_sanitize_keeps_valid_hex_and_known_font() -> None:
    clean = sanitize_styles(
        {
            "button_bg": "#123abc",
            "text_color": "#000",
            "font_family": "Georgia",
            "accent": "#FFFFFF",
        }
    )
    assert clean["button_bg"] == "#123abc"
    assert clean["text_color"] == "#000"
    assert clean["accent"] == "#FFFFFF"
    assert clean["font_family"] == "georgia"  # genormaliseerd naar lowercase


def test_sanitize_drops_injection_and_unknown() -> None:
    clean = sanitize_styles(
        {
            "button_bg": "red;} body{display:none",  # geen geldige hex -> weg
            "text_color": "javascript:alert(1)",  # weg
            "font_family": "Comic Sans'; evil",  # onbekend lettertype -> weg
            "rogue_key": "#fff",  # onbekende sleutel -> weg
        }
    )
    assert clean == {}


def test_sanitize_handles_none() -> None:
    assert sanitize_styles(None) == {}


def test_effective_styles_defaults() -> None:
    st = effective_styles(BRAND)
    assert st["button_bg"] == "#FF7200"  # valt terug op primaire merkkleur
    assert st["accent"] == "#FF7200"
    assert st["block_border"] == "#FF7200"  # merkkleur
    assert st["button_text"] == "#ffffff"
    assert st["text_color"] == "#3b3f44"
    assert st["heading_color"] == "#ffffff"
    assert st["page_bg"] == "#ffffff"
    assert st["footer_bg"] == "#6a6a6b"
    assert st["home_color"] == "#00AEEF"
    assert st["price_color"] == "#1a3a6e"
    assert st["font"] == DEFAULT_FONT_STACK


def test_effective_styles_uses_custom_values() -> None:
    brand = {**BRAND, "styles": {"button_bg": "#00ff00", "font_family": "verdana"}}
    st = effective_styles(brand)
    assert st["button_bg"] == "#00ff00"
    assert st["font"] == EMAIL_SAFE_FONTS["verdana"]
    # niet-gezette waarden vallen nog steeds terug op de merkkleur
    assert st["accent"] == "#FF7200"


def test_style_replacements_returns_all_tokens() -> None:
    repl = style_replacements(BRAND)
    for token in (
        "{{STYLE_FONT}}",
        "{{STYLE_TEXT_COLOR}}",
        "{{STYLE_HEADING_COLOR}}",
        "{{STYLE_BUTTON_BG}}",
        "{{STYLE_BUTTON_TEXT}}",
        "{{STYLE_ACCENT}}",
    ):
        assert token in repl


# ---------------------------------------------------------------------------
# Witruimte-sleutels (2026-07-06): alleen banner->intro en intro->producten
# ---------------------------------------------------------------------------


def test_sanitize_accepts_valid_spacing() -> None:
    clean = sanitize_styles({"spacing_banner_intro": 40, "spacing_intro_products": "0"})
    assert clean["spacing_banner_intro"] == 40
    assert clean["spacing_intro_products"] == 0


def test_sanitize_rejects_invalid_spacing() -> None:
    clean = sanitize_styles(
        {
            "spacing_banner_intro": -5,
            "spacing_intro_products": 999,  # boven max
            "spacing_onzin": 40,  # onbekende sleutel
        }
    )
    assert clean == {}


def test_sanitize_rejects_bool_and_css_injection_spacing() -> None:
    clean = sanitize_styles(
        {"spacing_banner_intro": True, "spacing_intro_products": "80px;position:fixed"}
    )
    assert clean == {}


def test_effective_styles_spacing_defaults_keep_render_identical() -> None:
    st = effective_styles(BRAND)
    assert st["spacing_banner_intro"] == 80
    assert st["spacing_intro_products"] == 80


def test_style_replacements_include_spacing_tokens_as_strings() -> None:
    repl = style_replacements({**BRAND, "styles": {"spacing_banner_intro": 24}})
    assert repl["{{STYLE_SPACING_BANNER_INTRO}}"] == "24"
    assert repl["{{STYLE_SPACING_INTRO_PRODUCTS}}"] == "80"


def test_button_groups_split_with_fallback() -> None:
    # Nieuw: banner-, kaart- en onderste knop apart; fallback = alles volgt button_bg.
    from app.newsletter.renderer import _render_hero_cta, _section_button, render_cards
    from app.newsletter.models import Item, Match, NewsletterContent, Section
    from app.newsletter.styles import effective_styles

    brand = {
        "primary_color": "#ff7200", "brand_name": "x", "brand_email": "x@x.nl",
        "website_url": "https://x", "logo_url": "https://c/l.png",
        "dummy_image_url": "https://c/d.png",
        "styles": {"button_bg": "#000000", "hero_button_bg": "#ffffff",
                   "cta_button_bg": "#d62828"},
    }
    content = NewsletterContent(
        theme="t", subject="s", intro_1="a", intro_2="b",
        main_cta_text="SHOP", main_cta_url="https://x/c",
        slot_cta_text="S", slot_cta_url="https://x/c", matches=(),
    )
    hero = _render_hero_cta(brand, content)
    assert "background:#ffffff" in hero  # bannerknop wit
    st = effective_styles(brand)
    knop = _section_button(Section(kind="button", text="K", url="https://x/c"), st)
    assert "background:#d62828" in knop  # onderste knop rood
    cards = render_cards((), (), brand, (Item(title="R", url="https://x/p", button_text="SHOP NU"),))
    assert "background:#000000" in cards  # productknop zwart
    # Tekstkleuren volgen button_text zolang niet apart gezet.
    assert st["hero_button_text"] == st["button_text"] == st["cta_button_text"]
