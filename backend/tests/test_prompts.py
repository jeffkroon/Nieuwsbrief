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


def test_brevo_copy_rules_present() -> None:
    prompt = build_system_prompt()
    # Onderwerpregel-regels
    assert "maximaal 50 tekens" in prompt
    assert "eerste 40 tekens" in prompt
    # Preheader-regels
    assert "85 en 100 tekens" in prompt
    assert "preview_text" in prompt
