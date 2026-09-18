"""Tests voor de controles op de gerenderde nieuwsbrief."""

from __future__ import annotations

from app.newsletter.mail_checks import (
    advisory_messages,
    blocking_messages,
    check_newsletter,
)

GOED = '<html><img src="x.png" alt="logo"><a href="{{ unsubscribe }}">weg</a></html>'


def test_goede_nieuwsbrief_heeft_geen_bevindingen() -> None:
    assert check_newsletter(GOED, subject="Kort onderwerp") == []


def test_ontbrekende_afmeldlink_waarschuwt_maar_blokkeert_niet() -> None:
    """Bewust geen blokkade: template_validation.py noemt dit al 'aanbevolen', en
    die bestaande keuze mag hier niet stilletjes worden omgedraaid. Klaviyo weigert
    zelf wel hard, want dat platform maakt er geen campagne van."""
    bevindingen = check_newsletter("<html><p>niets</p></html>")
    assert "geen-afmeldlink" in [b.code for b in bevindingen]
    assert blocking_messages(bevindingen) == []
    assert any("afmeldlink" in melding for melding in advisory_messages(bevindingen))


def test_javascript_link_blokkeert() -> None:
    html = GOED.replace('<img src="x.png" alt="logo">', '<a href="javascript:alert(1)">x</a>')
    codes = [b.code for b in check_newsletter(html)]
    assert "javascript-link" in codes


def test_script_tag_blokkeert() -> None:
    html = GOED + "<script>alert(1)</script>"
    assert "script" in [b.code for b in check_newsletter(html) if b.blocking]


def test_afbeelding_zonder_alt_is_advies_geen_blokkade() -> None:
    html = '<img src="x.png"><a href="{{ unsubscribe }}">weg</a>'
    bevindingen = check_newsletter(html)
    assert blocking_messages(bevindingen) == []
    assert any("alt-tekst" in melding for melding in advisory_messages(bevindingen))


def test_lege_alt_telt_als_bewuste_keuze() -> None:
    html = '<img src="sier.png" alt=""><a href="{{ unsubscribe }}">weg</a>'
    assert check_newsletter(html) == []


def test_te_lang_onderwerp_en_preheader_worden_gemeld() -> None:
    bevindingen = check_newsletter(GOED, subject="x" * 80, preheader="y" * 200)
    codes = [b.code for b in bevindingen]
    assert "onderwerp-lang" in codes and "preheader-lang" in codes
    assert blocking_messages(bevindingen) == []


def test_blokkerende_bevindingen_staan_vooraan() -> None:
    html = '<img src="x.png"><script>x</script>'
    bevindingen = check_newsletter(html, subject="x" * 80)
    assert bevindingen[0].blocking is True
