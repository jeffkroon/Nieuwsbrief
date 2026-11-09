"""Vorige teksten per veld: alleen bij een echte wijziging, max 3, nieuwste eerst."""

from __future__ import annotations

from app.newsletter.earlier_values import EARLIER_KEY, earlier_of, updated_earlier


def _volgende(stand: dict, nieuw: dict) -> dict:
    """De stand na een render zoals _remember_preview hem opslaat."""
    invoer = {k: v for k, v in nieuw.items() if k != EARLIER_KEY}
    earlier = updated_earlier(stand, invoer)
    return {**invoer, EARLIER_KEY: earlier} if earlier else invoer


def test_eerste_render_heeft_nog_geen_vorige_waarden() -> None:
    assert updated_earlier(None, {"subject": "a"}) == {}
    assert updated_earlier({}, {"subject": "a"}) == {}


def test_groeit_alleen_bij_een_echte_wijziging() -> None:
    stand = _volgende({}, {"subject": "a", "intro_1": "x"})
    stand = _volgende(stand, {"subject": "a", "intro_1": "x"})
    assert EARLIER_KEY not in stand
    stand = _volgende(stand, {"subject": "b", "intro_1": "x"})
    assert stand[EARLIER_KEY] == {"subject": ["a"]}


def test_maximaal_drie_nieuwste_eerst() -> None:
    stand: dict = {}
    for waarde in ["a", "b", "c", "d", "e"]:
        stand = _volgende(stand, {"subject": waarde})
    assert stand[EARLIER_KEY] == {"subject": ["d", "c", "b"]}


def test_geen_duplicaten_en_de_actieve_waarde_staat_er_niet_in() -> None:
    stand: dict = {}
    for waarde in ["a", "b", "a"]:  # terugzetten naar a
        stand = _volgende(stand, {"subject": waarde})
    assert stand[EARLIER_KEY] == {"subject": ["b"]}
    stand = _volgende(stand, {"subject": "b"})
    assert stand[EARLIER_KEY] == {"subject": ["a"]}


def test_alleen_bekende_tekstvelden() -> None:
    stand = _volgende({}, {"subject": "a", "main_cta_url": "https://x", "items": [1]})
    stand = _volgende(stand, {"subject": "b", "main_cta_url": "https://y", "items": [2]})
    assert stand[EARLIER_KEY] == {"subject": ["a"]}


def test_leeg_maken_bewaart_de_oude_waarde() -> None:
    stand = _volgende({}, {"header_subtitle": "weg ermee"})
    stand = _volgende(stand, {"header_subtitle": ""})
    assert stand[EARLIER_KEY] == {"header_subtitle": ["weg ermee"]}


def test_vreemde_opslag_breekt_niets() -> None:
    assert earlier_of({EARLIER_KEY: "kapot"}) == {}
    assert earlier_of({EARLIER_KEY: {"subject": [1, None, "", "ok"]}}) == {"subject": ["ok"]}
    assert earlier_of(None) == {}
