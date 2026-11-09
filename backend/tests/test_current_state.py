"""De stand van de nieuwsbrief gaat mee met het gebruikersbericht waar hij bij hoorde."""

from __future__ import annotations

from app.newsletter.current_state import (
    STATE_INTRO,
    UNCHANGED_NOTE,
    note_for_turn,
    state_metadata,
    state_note,
    stored_note,
    with_state_note,
)


def test_zonder_voorbeeld_geen_notitie() -> None:
    assert state_note(None) is None
    assert state_note({}) is None
    assert note_for_turn(None, []) is None
    assert state_metadata(None) == {}


def test_notitie_is_deterministisch_en_zonder_toestemming() -> None:
    a = state_note({"subject": "s", "header_title": "Herfstglow", "confirmed": True})
    b = state_note({"header_title": "Herfstglow", "subject": "s"})
    # Zelfde stand, andere sleutelvolgorde: byte-identiek (anders breekt de cache).
    assert a == b
    assert a.startswith(STATE_INTRO)
    assert "Herfstglow" in a
    # Toestemming voor het concept mag nooit via de stand meeliften.
    assert "confirmed" not in a


def test_intro_zegt_dat_de_laatste_stand_leidend_is() -> None:
    assert "LAATSTE" in STATE_INTRO and "leidend" in STATE_INTRO


def test_notitie_komt_als_extra_blok_bij_een_gebruikersbericht() -> None:
    bericht = {"role": "user", "content": "andere kop"}
    uit = with_state_note(bericht, "STAND x")
    assert uit["content"] == [
        {"type": "text", "text": "andere kop"},
        {"type": "text", "text": "STAND x"},
    ]
    # Niet gemuteerd.
    assert bericht == {"role": "user", "content": "andere kop"}


def test_zonder_notitie_of_bij_assistent_blijft_het_bericht_gelijk() -> None:
    bericht = {"role": "user", "content": "hoi"}
    assert with_state_note(bericht, None) is bericht
    assistent = {"role": "assistant", "content": "x"}
    assert with_state_note(assistent, "STAND x") is assistent


def test_bestaande_blokken_blijven_staan() -> None:
    bericht = {"role": "user", "content": [{"type": "text", "text": "a"}]}
    uit = with_state_note(bericht, "STAND x")
    assert uit["content"][0] == {"type": "text", "text": "a"}
    assert len(uit["content"]) == 2
    assert len(bericht["content"]) == 1


def test_opgeslagen_notitie_teruglezen() -> None:
    assert stored_note(state_metadata("STAND x")) == "STAND x"
    # Oude berichten zonder (of met vreemde) metadata breken niets.
    assert stored_note({}) is None
    assert stored_note(None) is None
    assert stored_note({"state_note": 42}) is None


def test_ongewijzigde_stand_wordt_niet_nog_eens_volledig_meegestuurd() -> None:
    stand = {"subject": "s"}
    volledig = state_note(stand)
    assert note_for_turn(stand, [None]) == volledig
    assert note_for_turn(stand, [volledig, None]) == UNCHANGED_NOTE
    # Ook na een eerdere 'ongewijzigd' telt de laatste VOLLEDIGE notitie.
    assert note_for_turn(stand, [volledig, UNCHANGED_NOTE]) == UNCHANGED_NOTE
    # Gewijzigd: weer volledig.
    assert note_for_turn({"subject": "t"}, [volledig]) == state_note({"subject": "t"})
