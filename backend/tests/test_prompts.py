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


def test_default_prompt_is_football() -> None:
    prompt = build_system_prompt()
    assert "WEDSTRIJDEN" in prompt
    assert "find_matches" in prompt
    assert "CLUBS" in prompt


def test_custom_content_types_replace_football() -> None:
    types = [
        {"kind": "items", "name": "Cases", "button_text": "Lees de case",
         "source_url": "https://x.nl/cases/"},
        {"kind": "items", "name": "Acties", "button_text": "Bekijk aanbieding", "has_price": True},
    ]
    prompt = build_system_prompt(content_types=types)
    assert "CASES" in prompt and "ACTIES" in prompt
    assert "Lees de case" in prompt and "Bekijk aanbieding" in prompt
    assert "https://x.nl/cases/" in prompt
    assert "find_matches" not in prompt  # geen voetbal-instructies voor dit bedrijf
    assert "ALGEMENE" in prompt  # algemeen kan altijd


def test_mixed_content_types() -> None:
    prompt = build_system_prompt(content_types=[{"kind": "matches"}, {"kind": "items", "name": "Blogs"}])
    assert "find_matches" in prompt and "BLOGS" in prompt


def test_brevo_copy_rules_present() -> None:
    prompt = build_system_prompt()
    # Onderwerpregel-regels
    assert "maximaal 50 tekens" in prompt
    assert "eerste 40 tekens" in prompt
    # Preheader-regels
    assert "85 en 100 tekens" in prompt
    assert "preview_text" in prompt


def test_opzet_step_present() -> None:
    # De opzet-composer-stap: over de opbouw praten en doorgeven via `sections`.
    prompt = build_system_prompt()
    assert "OPZET" in prompt
    assert "`sections`" in prompt
    assert "preview_newsletter" in prompt


def test_template_info_shapes_prompt() -> None:
    # Secties-template -> stap 2b doorlopen; vaste template -> 2b overslaan.
    with_sections = build_system_prompt(
        template_info={"is_fallback": False, "name": "Shell", "has_sections": True}
    )
    assert "OPZET-SECTIES" in with_sections and '"Shell"' in with_sections
    fixed = build_system_prompt(
        template_info={"is_fallback": False, "name": "Card", "has_sections": False}
    )
    assert "VASTE opzet" in fixed and "sla stap 2b" in fixed
    fallback = build_system_prompt(template_info={"is_fallback": True, "has_sections": False})
    assert "GEEN eigen template" in fallback
    # Zonder template_info geen sectie (bestaand gedrag).
    assert "ACTIEVE TEMPLATE" not in build_system_prompt()


def test_esp_label_follows_tenant() -> None:
    # Klaviyo-bedrijf: het gesprek noemt Klaviyo, niet Brevo.
    klaviyo = build_system_prompt(esp="klaviyo")
    assert "Klaviyo" in klaviyo and "Brevo" not in klaviyo
    assert "Brevo" in build_system_prompt()  # default blijft Brevo


def test_template_without_header_title_warns_agent() -> None:
    zonder = build_system_prompt(
        template_info={"is_fallback": False, "name": "Kaal", "has_sections": False,
                       "has_header_title": False}
    )
    assert "GEEN kop of ondertitel over de bannerfoto" in zonder
    met = build_system_prompt(
        template_info={"is_fallback": False, "name": "Vol", "has_sections": False,
                       "has_header_title": True}
    )
    assert "GEEN kop of ondertitel" not in met


def test_reizen_is_third_football_kind() -> None:
    # Voetbal-default heeft nu drie soorten; 'reis' wordt nooit meer stilletjes
    # als losse-ticketwedstrijd geinterpreteerd.
    p = build_system_prompt()
    assert "WEDSTRIJDEN, CLUBS, REIZEN" in p
    assert "overnachting" in p and "Bekijk deze reis" in p
    assert "VOETBALREIS" in p
    # Expliciete config met alleen reizen werkt ook.
    alleen_reizen = build_system_prompt(content_types=[{"kind": "reizen"}])
    assert "REIZEN" in alleen_reizen and "find_matches" in alleen_reizen
