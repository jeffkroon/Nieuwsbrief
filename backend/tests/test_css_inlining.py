"""Tests voor het inline zetten van CSS, inclusief het vangnet."""

from __future__ import annotations

from app.newsletter import css_inlining
from app.newsletter.css_inlining import inline_css

MET_STYLE = """<html><head><style>.knop{background:#FF7200;color:#fff}
@media (max-width:600px){.knop{display:block}}</style></head>
<body>
<!--[if mso]><table width="600"><tr><td><![endif]-->
<a class="knop" href="https://x.nl">Klik</a>
<a href="{{ unsubscribe }}">Uitschrijven</a>
<!--[if mso]></td></tr></table><![endif]-->
</body></html>"""


def test_stijl_wordt_inline_gezet() -> None:
    resultaat = inline_css(MET_STYLE)
    assert resultaat.applied is True
    assert "#FF7200" in resultaat.html
    assert 'style="' in resultaat.html


def test_media_queries_blijven_staan() -> None:
    """Media queries kunnen niet inline; zonder het style-blok is de mail op
    mobiel stuk."""
    assert "@media" in inline_css(MET_STYLE).html


def test_outlook_conditionals_en_platformtags_overleven() -> None:
    resultaat = inline_css(MET_STYLE).html
    assert "[if mso]" in resultaat
    assert "{{ unsubscribe }}" in resultaat


def test_html_zonder_style_blijft_ongemoeid() -> None:
    html = "<html><body><p>hallo</p></body></html>"
    resultaat = inline_css(html)
    assert resultaat.html == html and resultaat.applied is False


def test_vangnet_valt_terug_op_het_origineel(monkeypatch) -> None:
    """Sloopt de inliner een platform-tag, dan gaat de originele HTML de deur uit."""

    class _Sloper:
        @staticmethod
        def inline(html, **kwargs):
            return html.replace("{{ unsubscribe }}", "")

    monkeypatch.setitem(__import__("sys").modules, "css_inline", _Sloper)
    resultaat = inline_css(MET_STYLE)
    assert resultaat.applied is False
    assert resultaat.html == MET_STYLE
    assert "{{ unsubscribe }}" in resultaat.note


def test_vangnet_bij_een_kapotte_inliner(monkeypatch) -> None:
    class _Stuk:
        @staticmethod
        def inline(html, **kwargs):
            raise RuntimeError("parser omgevallen")

    monkeypatch.setitem(__import__("sys").modules, "css_inline", _Stuk)
    resultaat = inline_css(MET_STYLE)
    assert resultaat.applied is False and resultaat.html == MET_STYLE
    assert "mislukte" in resultaat.note


def test_vangnet_bij_groot_inhoudsverlies(monkeypatch) -> None:
    class _Knipper:
        @staticmethod
        def inline(html, **kwargs):
            return html[: len(html) // 2]

    monkeypatch.setitem(__import__("sys").modules, "css_inline", _Knipper)
    resultaat = inline_css(MET_STYLE)
    assert resultaat.applied is False and resultaat.html == MET_STYLE
