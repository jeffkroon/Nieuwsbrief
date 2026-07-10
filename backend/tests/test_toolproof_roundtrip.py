"""De ultieme garantie-test: na toolproof moet renderen met de originele waarden
het origineel byte-voor-byte reproduceren. Verandert er ook maar iets aan het
ontwerp, dan faalt dit."""

from __future__ import annotations

from app.newsletter.models import Item, NewsletterContent
from app.newsletter.renderer import render_newsletter
from app.newsletter.toolproof import make_toolproof

from tests.test_toolproof import FakeLLM

# Realistische statische template: heroknop met 3 kleurlagen, paddings, footer.
PURE_HTML = """<html><head><title>Zomeractie | Bedrijf X</title></head>
<body style="background:#f4f0ea;">
<img src="https://bedrijfx.nl/hero.png" alt="hero"/>
<h1 style="color:#1c1c2b;">De zomer begint hier</h1>
<table><tr><td bgcolor="#D62828" style="background:#D62828;">
<a href="https://bedrijfx.nl/zomer" style="background:#D62828;color:#ffffff;">Shop de actie</a>
</td></tr></table>
<td style="padding-top:64px;"><p style="color:#2a2a2a;">Welkom bij onze zomereditie.</p></td>
<p>Nog een alinea met vaste tekst.</p>
<div class="footer">Hoofdstraat 1, 1234 AB Amsterdam | info@bedrijfx.nl | KVK 87654321</div>
<p>{{ unsubscribe }}</p>
</body></html>"""

PURE_OPS = [
    {"op": "replace", "find": "<title>Zomeractie | Bedrijf X</title>",
     "from": None, "to": None, "replace": "<title>{{EMAIL_TITEL}}</title>", "reason": "titel"},
    {"op": "replace", "find": 'background:#f4f0ea;',
     "from": None, "to": None, "replace": "background:{{STYLE_PAGE_BG}};", "reason": "pagina-achtergrond"},
    {"op": "replace", "find": 'src="https://bedrijfx.nl/hero.png"',
     "from": None, "to": None, "replace": 'src="{{HEADER_IMAGE_URL}}"', "reason": "herofoto"},
    {"op": "replace", "find": '<h1 style="color:#1c1c2b;">De zomer begint hier</h1>',
     "from": None, "to": None,
     "replace": '<h1 style="color:{{STYLE_HEADING_COLOR}};">{{HEADER_TITEL}}</h1>', "reason": "kop"},
    # Heroknop: markup behouden, drie lagen zelfde token, tekst en href tokeniseren.
    {"op": "replace",
     "find": '<td bgcolor="#D62828" style="background:#D62828;">\n'
             '<a href="https://bedrijfx.nl/zomer" style="background:#D62828;color:#ffffff;">Shop de actie</a>',
     "from": None, "to": None,
     "replace": '<td bgcolor="{{STYLE_HERO_BUTTON_BG}}" style="background:{{STYLE_HERO_BUTTON_BG}};">\n'
                '<a href="{{HOOFD_CTA_URL}}" style="background:{{STYLE_HERO_BUTTON_BG}};'
                'color:{{STYLE_HERO_BUTTON_TEXT}};">{{HEADER_CTA_TEKST}}</a>',
     "reason": "heroknop"},
    {"op": "replace", "find": 'padding-top:64px;',
     "from": None, "to": None,
     "replace": "padding-top:{{STYLE_SPACING_BANNER_INTRO}}px;", "reason": "witruimte"},
    {"op": "replace", "find": '<p style="color:#2a2a2a;">Welkom bij onze zomereditie.</p>',
     "from": None, "to": None,
     "replace": '<p style="color:{{STYLE_TEXT_COLOR}};">{{INTRO_1}}</p>', "reason": "intro"},
    {"op": "replace", "find": "<p>Nog een alinea met vaste tekst.</p>",
     "from": None, "to": None,
     "replace": "<!-- ##SECTIE## --><p>{{VAK_EXTRA_ALINEA}}</p><!-- /##SECTIE## -->",
     "reason": "vrije alinea"},
    {"op": "replace",
     "find": "Hoofdstraat 1, 1234 AB Amsterdam | info@bedrijfx.nl | KVK 87654321",
     "from": None, "to": None,
     "replace": "{{BRAND_ADRES}}, {{BRAND_POSTCODE_STAD}} | {{BRAND_EMAIL}} | KVK {{BRAND_KVK}}",
     "reason": "footer-contact"},
]


def test_pure_template_roundtrip_byte_identical() -> None:
    result = make_toolproof(FakeLLM({"operations": PURE_OPS, "notes": []}), PURE_HTML)
    assert result.failed == []
    assert result.ok, result.checks_failed
    # De interne eindcheck claimt byte-identiteit...
    assert any("byte-identiek" in p for p in result.checks_passed)
    # ...en dat verifiëren we hier ONAFHANKELIJK: render met de originele waarden.
    assert result.styles == {
        "page_bg": "#f4f0ea",
        "heading_color": "#1c1c2b",
        "hero_button_bg": "#D62828",
        "hero_button_text": "#ffffff",
        "spacing_banner_intro": 64,
        "text_color": "#2a2a2a",
    }
    brand = {
        "brand_name": "Bedrijf X",
        "brand_email": "info@bedrijfx.nl",
        "brand_adres": "Hoofdstraat 1",
        "brand_postcode_stad": "1234 AB Amsterdam",
        "brand_kvk": "87654321",
        "website_url": "https://bedrijfx.nl",
        "logo_url": "https://bedrijfx.nl/logo.png",
        "dummy_image_url": "https://bedrijfx.nl/d.png",
        "primary_color": "#FF7200",
        "styles": result.styles,
    }
    content = NewsletterContent(
        theme="Zomeractie", subject="x",
        intro_1="Welkom bij onze zomereditie.", intro_2="",
        main_cta_text="", main_cta_url="https://bedrijfx.nl/zomer",
        slot_cta_text="", slot_cta_url="", matches=(),
        header_title="De zomer begint hier",
        header_cta_text="Shop de actie",
        header_image_url="https://bedrijfx.nl/hero.png",
        custom_fields=(("EXTRA_ALINEA", "Nog een alinea met vaste tekst."),),
    )
    assert render_newsletter(result.html, brand, content) == PURE_HTML


def test_sabotage_op_is_rejected_and_html_untouched() -> None:
    sabotage = [{
        "op": "replace",
        "find": '<h1 style="color:#1c1c2b;">De zomer begint hier</h1>',
        "from": None, "to": None,
        # Stiekem de markup 'moderniseren' naast de placeholder: moet geweigerd.
        "replace": '<h1 class="hero-title" style="color:#1c1c2b;">{{HEADER_TITEL}}</h1>',
        "reason": "kop",
    }]
    result = make_toolproof(FakeLLM({"operations": sabotage, "notes": []}), PURE_HTML)
    assert not result.ok
    assert result.html == PURE_HTML  # geen byte veranderd
    assert any("pure inhoud-vervanging" in f for f in result.failed)


CARD_HTML = (
    "<html><body><p>Intro hier.</p><table><tr>"
    '<td class="k"><a href="https://x.nl/p1"><img src="https://x.nl/p1.png"/></a>'
    '<h3>Product 1</h3><span>€ 10</span></td>'
    '<td class="k"><a href="https://x.nl/p2"><img src="https://x.nl/p2.png"/></a>'
    '<h3>Product 2</h3><span>€ 20</span></td>'
    "</tr></table><p>{% unsubscribe %}</p></body></html>"
)

CARD_OPS = [
    {"op": "replace", "find": "<p>Intro hier.</p>",
     "from": None, "to": None, "replace": "<p>{{INTRO_1}}</p>", "reason": "intro"},
    {"op": "replace",
     "find": '<td class="k"><a href="https://x.nl/p1"><img src="https://x.nl/p1.png"/></a>'
             '<h3>Product 1</h3><span>€ 10</span></td>',
     "from": None, "to": None,
     "replace": '<!-- ##KAART## --><td class="k"><a href="{{KAART_URL}}">'
                '<img src="{{KAART_IMAGE_URL}}"/></a><h3>{{KAART_TITEL}}</h3>'
                '<span>{{KAART_PRIJS}}</span></td><!-- /##KAART## -->',
     "reason": "voorbeeldkaart"},
    {"op": "replace_range", "find": None,
     "from": '<td class="k"><a href="https://x.nl/p2">',
     "to": "</tr>", "replace": "", "reason": "kaart-kopie weg"},
]


def test_card_template_roundtrip_minus_removed_copies() -> None:
    result = make_toolproof(FakeLLM({"operations": CARD_OPS, "notes": []}), CARD_HTML)
    assert result.failed == []
    assert result.ok, result.checks_failed
    assert any("minus de verwijderde kaart-kopieën" in p for p in result.checks_passed)

    # Onafhankelijke render met 1 product = het origineel zonder de tweede kaart.
    brand = {"brand_name": "X", "brand_email": "i@x.nl", "website_url": "https://x.nl",
             "logo_url": "https://x.nl/l.png", "dummy_image_url": "https://x.nl/d.png",
             "primary_color": "#FF7200", "styles": result.styles}
    content = NewsletterContent(
        theme="T", subject="s", intro_1="Intro hier.", intro_2="",
        main_cta_text="", main_cta_url="", slot_cta_text="", slot_cta_url="",
        matches=(), items=(Item(title="Product 1", url="https://x.nl/p1",
                                price="€ 10", image_url="https://x.nl/p1.png"),),
    )
    verwacht = CARD_HTML.replace(
        '<td class="k"><a href="https://x.nl/p2"><img src="https://x.nl/p2.png"/></a>'
        '<h3>Product 2</h3><span>€ 20</span></td>', "")
    assert render_newsletter(result.html, brand, content) == verwacht
