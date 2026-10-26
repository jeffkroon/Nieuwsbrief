"""Escapen in de gerenderde mail: tekst van het model en gescrapete namen komen
nooit rauw in de HTML, links alleen met een veilig schema.

De tool-proof-paden renderen met escape=False: daar vullen we terug met de
ORIGINELE HTML-fragmenten en moet de render byte-identiek blijven.
"""

from __future__ import annotations

from app.newsletter.card_block import CARD_TPL_END, CARD_TPL_START
from app.newsletter.custom_fields import fill_custom_fields
from app.newsletter.html_safety import escape_text, safe_href, safe_src
from app.newsletter.models import Club, Item, Match, NewsletterContent, Section
from app.newsletter.renderer import (
    BANNER_MARKER,
    CARD_MARKER,
    SECTIONS_MARKER,
    render_newsletter,
)
from app.newsletter.toolproof import make_toolproof

from tests.test_toolproof import FakeLLM

BRAND = {
    "brand_name": "Tom & Jerry",
    "brand_email": "info@tj.test",
    "brand_adres": "Straat <1>",
    "brand_postcode_stad": "1000 AA Stad",
    "website_url": "https://tj.test",
    "primary_color": "#123456",
    "logo_url": "https://tj.test/logo.png",
    "dummy_image_url": "https://tj.test/d.png",
    "facebook_url": "javascript:alert(1)",
}

XSS = '<img src=x onerror="alert(1)">'


def _content(**overrides) -> NewsletterContent:
    base = dict(
        theme="Kaas & Wijn",
        subject='Kaas & "Wijn" <nu>',
        intro_1="<script>alert(1)</script> Tom & Jerry",
        intro_2='Zeg "hallo" tegen o\'Neill',
        main_cta_text="Shop & spaar",
        main_cta_url="https://tj.test/?a=1&b=2",
        slot_cta_text="Meer",
        slot_cta_url="javascript:alert(1)",
        matches=(),
    )
    return NewsletterContent(**{**base, **overrides})


TEMPLATE = (
    "<title>{{EMAIL_TITEL}}</title>"
    "<h1>{{HEADER_TITEL}}</h1>"
    '<img src="{{HEADER_IMAGE_URL}}" alt="{{HEADER_TITEL}}">'
    "<p>{{INTRO_1}}</p><p>{{INTRO_2}}</p>"
    '<a href="{{HOOFD_CTA_URL}}">{{HOOFD_CTA_TEKST}}</a>'
    '<a href="{{SLOT_CTA_URL}}">{{SLOT_CTA_TEKST}}</a>'
    '<a href="{{FACEBOOK_URL}}">fb</a>'
    "<footer>{{BRAND_NAME}} {{BRAND_ADRES}} | {{FOOTER_CONTACT}}</footer>"
    "{{ unsubscribe }}"
)


# --- de bouwstenen ---------------------------------------------------------


def test_escape_text_escapet_amp_lt_gt_quot_maar_niet_apostrof() -> None:
    assert escape_text('<a href="x">Tom & Jerry\'s</a>') == (
        "&lt;a href=&quot;x&quot;&gt;Tom &amp; Jerry's&lt;/a&gt;"
    )
    assert escape_text(None) == ""


def test_safe_href_laat_alleen_veilige_schemas_door() -> None:
    assert safe_href("https://x.test/?a=1&b=2") == "https://x.test/?a=1&amp;b=2"
    assert safe_href("http://x.test") == "http://x.test"
    assert safe_href("mailto:info@x.test") == "mailto:info@x.test"
    assert safe_href("tel:+31600000000") == "tel:+31600000000"
    assert safe_href("javascript:alert(1)") == "#"
    assert safe_href("  JavaScript:alert(1)") == "#"
    assert safe_href("data:text/html,<b>") == "#"
    assert safe_href('https://x.test/"onmouseover="x') == "https://x.test/&quot;onmouseover=&quot;x"
    assert safe_href("") == ""


def test_safe_src_laat_alleen_http_s_door() -> None:
    assert safe_src("https://x.test/a.png") == "https://x.test/a.png"
    assert safe_src("javascript:alert(1)") == ""
    assert safe_src("mailto:x@y.z") == ""
    assert safe_src(None) == ""


# --- vaste placeholders ----------------------------------------------------


def test_vaste_placeholders_worden_geescapet() -> None:
    html = render_newsletter(
        TEMPLATE, BRAND, _content(header_title=XSS, header_image_url="javascript:x")
    )
    assert "<script>" not in html and "onerror=\"alert" not in html
    assert "<p>&lt;script&gt;alert(1)&lt;/script&gt; Tom &amp; Jerry</p>" in html
    assert "<p>Zeg &quot;hallo&quot; tegen o'Neill</p>" in html  # ' blijft staan
    assert "<title>Kaas &amp; Wijn | Tom &amp; Jerry</title>" in html
    assert '<h1>&lt;img src=x onerror=&quot;alert(1)&quot;&gt;</h1>' in html
    assert 'alt="&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"' in html
    assert '<img src=""' in html  # onveilige foto-URL valt weg
    assert '<a href="https://tj.test/?a=1&amp;b=2">Shop &amp; spaar</a>' in html
    assert '<a href="#">Meer</a>' in html  # javascript: in de slotknop
    assert '<a href="#">fb</a>' in html  # javascript: in een brand-URL
    assert "Tom &amp; Jerry Straat &lt;1&gt; | Straat &lt;1&gt;<br>" in html


def test_escape_false_vult_ruw_in_voor_toolproof() -> None:
    html = render_newsletter(TEMPLATE, BRAND, _content(), escape=False)
    assert "<p><script>alert(1)</script> Tom & Jerry</p>" in html
    assert '<a href="javascript:alert(1)">Meer</a>' in html


# --- gegenereerde blokken ----------------------------------------------------


def _blokken() -> dict:
    return dict(
        matches=(Match(home="Tom & Jerry", away=XSS, url="javascript:x", price="€ <9>",
                       label="<b>"),),
        clubs=(Club(name="A&B", url="https://c.test/?x=1&y=2", price="€ 1",
                    stadium="<Stadion>", city="Stad & Co", image_url="javascript:x"),),
        items=(Item(title="Ring <3", url="https://i.test", subtitle='"Sub"',
                    price="€ 5 & 6", button_text="Koop & <nu>"),),
    )


def test_banners_escapen_tekst_en_links() -> None:
    html = render_newsletter(f"<html>{BANNER_MARKER}</html>", BRAND, _content(**_blokken()))
    assert XSS not in html and "<Stadion>" not in html
    assert "TOM &amp; JERRY" in html
    assert "&lt;IMG SRC=X ONERROR=&quot;ALERT(1)&quot;&gt;" in html
    assert 'href="#"' in html  # javascript:-link van de wedstrijd
    assert 'href="https://c.test/?x=1&amp;y=2"' in html
    assert "&lt;Stadion&gt; · Stad &amp; Co" in html
    assert ">Koop &amp; &lt;nu&gt;</a>" in html
    assert "€ 5 &amp; 6" in html and "€ &lt;9&gt;" in html
    # Een onveilige foto-URL wordt leeg, nooit rauw doorgegeven.
    assert 'src="javascript:' not in html


def test_kaarten_escapen_tekst_en_links() -> None:
    html = render_newsletter(f"<html>{CARD_MARKER}</html>", BRAND, _content(**_blokken()))
    assert XSS not in html
    assert "vs &lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html
    assert "&lt;Stadion&gt; &bull; Stad &amp; Co" in html  # &bull; blijft een entity
    assert ">&lt;B&gt;</span>" in html  # label
    assert 'alt="Ring &lt;3"' in html
    assert ">&quot;Sub&quot;</p>" in html
    assert 'href="#"' in html and 'src="javascript:' not in html


def test_secties_escapen_tekst_en_links() -> None:
    content = _content(sections=(
        Section(kind="hero", image_url="javascript:x", url="javascript:y"),
        Section(kind="text", text="<script>x</script> & meer"),
        Section(kind="button", text="Klik <hier>", url="https://s.test/?a&b"),
    ))
    html = render_newsletter(f"<html>{SECTIONS_MARKER}</html>", BRAND, content)
    assert "<script>" not in html
    assert "&lt;script&gt;x&lt;/script&gt; &amp; meer" in html
    assert ">Klik &lt;hier&gt;</a>" in html
    assert 'href="https://s.test/?a&amp;b"' in html
    assert 'src="javascript:' not in html and 'href="javascript:' not in html


def test_template_kaart_blok_escapet() -> None:
    kaart = (
        f'{CARD_TPL_START}<a href="{{{{KAART_URL}}}}"><img src="{{{{KAART_IMAGE_URL}}}}"></a>'
        f"<b>{{{{KAART_TITEL}}}}</b><i>{{{{KAART_LABEL}}}}</i>{CARD_TPL_END}"
    )
    item = Item(title="Tom & <Jerry>", url="javascript:x", image_url="javascript:y",
                label='"Nieuw"')
    html = render_newsletter(f"<html>{kaart}</html>", BRAND, _content(items=(item,)))
    assert "<b>Tom &amp; &lt;Jerry&gt;</b>" in html
    assert "<i>&quot;Nieuw&quot;</i>" in html
    assert '<a href="#"><img src=""></a>' in html

    ruw = render_newsletter(f"<html>{kaart}</html>", BRAND, _content(items=(item,)), escape=False)
    assert "<b>Tom & <Jerry></b>" in ruw


def test_invulvakken_escapen() -> None:
    html = "<p>{{VAK_TITEL}}</p>"
    assert fill_custom_fields(html, {"TITEL": "A & <b>"}) == "<p>A &amp; &lt;b&gt;</p>"
    assert fill_custom_fields(html, {"TITEL": "A & <b>"}, escape=False) == "<p>A & <b></p>"
    gerenderd = render_newsletter(
        "<html>{{VAK_TITEL}}</html>", BRAND, _content(custom_fields=(("TITEL", XSS),))
    )
    assert XSS not in gerenderd and "&lt;img" in gerenderd


# --- tool-proof blijft byte-identiek met speciale tekens -----------------------

SPECIAAL_HTML = """<html><head><title>Kaas &amp; Wijn | Tom &amp; Jerry</title></head>
<body>
<h1>Tom &amp; Jerry&#39;s deals</h1>
<p>Welkom &lt;3 bij &quot;ons&quot;.</p>
<a href="https://tj.test/?a=1&amp;b=2">Shop &amp; spaar</a>
<p>{{ unsubscribe }}</p>
</body></html>"""

SPECIAAL_OPS = [
    {"op": "replace", "find": "<title>Kaas &amp; Wijn | Tom &amp; Jerry</title>",
     "from": None, "to": None, "replace": "<title>{{EMAIL_TITEL}}</title>", "reason": "titel"},
    {"op": "replace", "find": "<h1>Tom &amp; Jerry&#39;s deals</h1>",
     "from": None, "to": None, "replace": "<h1>{{HEADER_TITEL}}</h1>", "reason": "kop"},
    {"op": "replace", "find": "<p>Welkom &lt;3 bij &quot;ons&quot;.</p>",
     "from": None, "to": None, "replace": "<p>{{INTRO_1}}</p>", "reason": "intro"},
    {"op": "replace", "find": 'href="https://tj.test/?a=1&amp;b=2"',
     "from": None, "to": None, "replace": 'href="{{HOOFD_CTA_URL}}"', "reason": "knop-URL"},
    {"op": "replace", "find": ">Shop &amp; spaar<",
     "from": None, "to": None, "replace": ">{{HOOFD_CTA_TEKST}}<", "reason": "knoptekst"},
]


def test_toolproof_roundtrip_blijft_byte_identiek_met_speciale_tekens() -> None:
    result = make_toolproof(FakeLLM({"operations": SPECIAAL_OPS, "notes": []}), SPECIAAL_HTML)
    assert result.failed == []
    assert result.ok, result.checks_failed
    assert any("byte-identiek" in p for p in result.checks_passed), result.checks_passed


def test_safe_href_vult_https_aan_voor_kale_www_link() -> None:
    # Een website of social die zonder schema is opgeslagen ("www.x.nl") werd '#';
    # aanvullen met https:// houdt de link werkend in plaats van hem te breken.
    assert safe_href("www.voorbeeld.nl/actie") == "https://www.voorbeeld.nl/actie"
    assert safe_href("  WWW.voorbeeld.nl") == "https://WWW.voorbeeld.nl"
    assert safe_href("javascript:alert(1)") == "#"
