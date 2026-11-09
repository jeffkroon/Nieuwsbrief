"""De huidige stand van de nieuwsbrief gaat mee met het laatste gebruikersbericht."""

from __future__ import annotations

from app.newsletter.current_state import (
    EARLIER_LABEL,
    STATE_INTRO,
    replay_message,
    state_note,
    with_current_state,
)
from app.newsletter.orchestrator import CACHE_CONTROL


def _user(text: str) -> dict:
    return replay_message("user", text)


def test_gebruikersberichten_spelen_terug_als_een_tekstblok() -> None:
    assert replay_message("user", "hoi") == {
        "role": "user", "content": [{"type": "text", "text": "hoi"}]
    }
    assert replay_message("assistant", "klaar") == {"role": "assistant", "content": "klaar"}


def test_zonder_voorbeeld_alleen_de_cache_markering() -> None:
    berichten = [_user("hoi")]
    for stand in (None, {}):
        uit = with_current_state(berichten, stand)
        assert uit[-1]["content"] == [
            {"type": "text", "text": "hoi", "cache_control": CACHE_CONTROL}
        ]
    assert state_note(None) is None
    # Niet gemuteerd.
    assert berichten == [_user("hoi")]


def test_stand_komt_als_extra_blok_achter_de_gemarkeerde_tekst() -> None:
    berichten = [_user("maak een nieuwsbrief"), replay_message("assistant", "klaar"), _user("andere kop")]
    uit = with_current_state(berichten, {"header_title": "Herfstglow", "confirmed": True})
    # Eerdere berichten blijven exact gelijk (en ongemarkeerd).
    assert uit[:2] == berichten[:2]
    tekst, stand = uit[-1]["content"]
    assert tekst == {"type": "text", "text": "andere kop", "cache_control": CACHE_CONTROL}
    assert "cache_control" not in stand
    assert stand["text"].startswith(STATE_INTRO) and "HUIDIGE STAND" in stand["text"]
    assert "Herfstglow" in stand["text"]
    # Toestemming voor het concept mag nooit via de stand meeliften.
    assert "confirmed" not in stand["text"]
    # Niet gemuteerd.
    assert berichten[-1] == _user("andere kop")


def test_laatste_bericht_van_assistent_krijgt_niets() -> None:
    berichten = [replay_message("assistant", "x")]
    assert with_current_state(berichten, {"subject": "a"}) is berichten


def test_stand_is_deterministisch() -> None:
    assert state_note({"subject": "s", "intro_1": "i"}) == state_note({"intro_1": "i", "subject": "s"})


def test_eerder_gebruikt_staat_apart_gelabeld_onder_de_huidige_stand() -> None:
    stand = {
        "header_title": "Nieuw",
        "_eerder": {"header_title": ["Oud", "Ouder"], "intro_1": [], "onbekend": ["x"]},
    }
    note = state_note(stand)
    huidig, eerder = note.split(EARLIER_LABEL)
    assert "niet meer actief" in EARLIER_LABEL and "terug te zetten" in EARLIER_LABEL
    # De huidige stand bovenaan, zonder de vorige waarden.
    assert '"header_title":"Nieuw"' in huidig and "Oud" not in huidig and "_eerder" not in huidig
    assert '"header_title":["Oud","Ouder"]' in eerder
    # Lege lijsten en onbekende velden vallen weg.
    assert "intro_1" not in eerder and "onbekend" not in eerder


def test_zonder_vorige_waarden_geen_eerder_onderdeel() -> None:
    assert EARLIER_LABEL not in state_note({"subject": "s", "_eerder": {"subject": []}})
    assert EARLIER_LABEL not in state_note({"subject": "s"})
