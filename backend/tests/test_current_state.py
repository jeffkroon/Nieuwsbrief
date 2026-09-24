"""De huidige stand van de nieuwsbrief gaat mee met het laatste gebruikersbericht."""

from __future__ import annotations

from app.newsletter.current_state import state_note, with_current_state


def test_zonder_voorbeeld_blijft_alles_gelijk() -> None:
    berichten = [{"role": "user", "content": "hoi"}]
    assert with_current_state(berichten, None) is berichten
    assert with_current_state(berichten, {}) is berichten


def test_stand_komt_als_extra_blok_bij_het_laatste_gebruikersbericht() -> None:
    berichten = [
        {"role": "user", "content": "maak een nieuwsbrief"},
        {"role": "assistant", "content": "klaar"},
        {"role": "user", "content": "andere kop"},
    ]
    uit = with_current_state(berichten, {"header_title": "Herfstglow", "confirmed": True})
    assert uit[:2] == berichten[:2]
    blokken = uit[-1]["content"]
    assert blokken[0] == {"type": "text", "text": "andere kop"}
    assert "Herfstglow" in blokken[1]["text"]
    # Toestemming voor het concept mag nooit via de stand meeliften.
    assert "confirmed" not in blokken[1]["text"]
    # Niet gemuteerd.
    assert berichten[-1]["content"] == "andere kop"


def test_laatste_bericht_van_assistent_krijgt_niets() -> None:
    berichten = [{"role": "assistant", "content": "x"}]
    assert with_current_state(berichten, {"subject": "a"}) is berichten


def test_bestaande_blokken_blijven_staan() -> None:
    berichten = [{"role": "user", "content": [{"type": "text", "text": "a"}]}]
    uit = with_current_state(berichten, {"subject": "s"})
    assert uit[0]["content"][0] == {"type": "text", "text": "a"}
    assert len(uit[0]["content"]) == 2
    assert state_note(None) is None
