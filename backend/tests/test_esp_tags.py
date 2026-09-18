"""Tests voor het omzetten van platform-tags naar het juiste verzendplatform.

Achtergrond: de templates zijn in Brevo-syntax geschreven. Zonder omzetting komt
een Klaviyo- of ActiveCampaign-mail aan met een kapotte afmeldlink.
"""

from __future__ import annotations

import pytest

from app.newsletter.esp_tags import (
    CLIPPING_BYTES,
    has_unsubscribe,
    localize_esp_tags,
)

BREVO_HTML = '<a href="{{ unsubscribe }}">Uitschrijven</a><p>{{ contact.EMAIL }}</p>'


def test_brevo_blijft_ongewijzigd() -> None:
    resultaat = localize_esp_tags(BREVO_HTML, "brevo")
    assert resultaat.html == BREVO_HTML
    assert resultaat.notes == ()


def test_klaviyo_krijgt_eigen_afmeldtag() -> None:
    resultaat = localize_esp_tags(BREVO_HTML, "klaviyo")
    assert "{% unsubscribe %}" in resultaat.html
    assert "{{ unsubscribe }}" not in resultaat.html
    assert "{{ person.email }}" in resultaat.html
    assert any("Afmeldlink omgezet" in melding for melding in resultaat.notes)


def test_activecampaign_krijgt_personalisatietag() -> None:
    resultaat = localize_esp_tags(BREVO_HTML, "activecampaign")
    assert "%UNSUBSCRIBELINK%" in resultaat.html
    assert "%EMAIL%" in resultaat.html
    assert "{{ unsubscribe }}" not in resultaat.html


def test_klaviyo_tag_in_template_werkt_ook_richting_brevo() -> None:
    """Andersom moet net zo goed: een Klaviyo-template naar een Brevo-account."""
    resultaat = localize_esp_tags('<a href="{% unsubscribe %}">weg</a>', "brevo")
    assert "{{ unsubscribe }}" in resultaat.html


def test_zonder_afmeldlink_volgt_een_waarschuwing() -> None:
    resultaat = localize_esp_tags("<p>geen link</p>", "klaviyo")
    assert any("geen afmeldlink" in melding for melding in resultaat.notes)


def test_variant_zonder_spaties_wordt_herkend() -> None:
    resultaat = localize_esp_tags('<a href="{{unsubscribe}}">weg</a>', "klaviyo")
    assert "{% unsubscribe %}" in resultaat.html


def test_te_grote_mail_wordt_gemeld() -> None:
    groot = BREVO_HTML + "<p>" + ("x" * CLIPPING_BYTES) + "</p>"
    resultaat = localize_esp_tags(groot, "brevo")
    assert any("knippen" in melding for melding in resultaat.notes)


def test_onbekend_platform_laat_html_met_rust() -> None:
    assert localize_esp_tags(BREVO_HTML, "mailchimp").html == BREVO_HTML


@pytest.mark.parametrize(
    "html,verwacht",
    [
        ('<a href="{{ unsubscribe }}">x</a>', True),
        ("{% unsubscribe %}", True),
        ("%UNSUBSCRIBELINK%", True),
        ("<p>niets</p>", False),
    ],
)
def test_has_unsubscribe(html: str, verwacht: bool) -> None:
    assert has_unsubscribe(html) is verwacht
