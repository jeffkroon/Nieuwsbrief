"""Borgt dat de vaste regels in de system-prompt staan."""

from __future__ import annotations

from app.newsletter.prompts import OPENING_QUESTION, build_system_prompt


def test_opening_question_present() -> None:
    assert OPENING_QUESTION == "Waar wil je dat ik de nieuwsbrief over schrijf?"
    assert OPENING_QUESTION in build_system_prompt()


def test_stays_in_scope() -> None:
    prompt = build_system_prompt().lower()
    assert "blijf binnen je taak" in prompt
    assert "wiskunde" in prompt  # voorbeeld van wat geweigerd wordt


def test_tone_of_voice_injected_when_known() -> None:
    # Zonder tone: geen tone-sectie. Met tone: verplicht ingezet.
    assert "TONE OF VOICE VAN DIT BEDRIJF" not in build_system_prompt()
    prompt = build_system_prompt("Informeel, sportief, veel uitroeptekens.")
    assert "TONE OF VOICE VAN DIT BEDRIJF (VERPLICHT)" in prompt
    assert "Informeel, sportief, veel uitroeptekens." in prompt


def test_clubs_step_asks_to_confirm_venue() -> None:
    # Kleingedrukt (stadion/stad) moet bevestigd worden, niet verzonnen.
    prompt = build_system_prompt().lower()
    assert "verzin geen stadion" in prompt


def test_brevo_copy_rules_present() -> None:
    prompt = build_system_prompt()
    # Onderwerpregel-regels
    assert "maximaal 50 tekens" in prompt
    assert "eerste 40 tekens" in prompt
    # Preheader-regels
    assert "85 en 100 tekens" in prompt
    assert "preview_text" in prompt
