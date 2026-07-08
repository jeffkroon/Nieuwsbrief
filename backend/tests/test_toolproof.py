"""Tests voor de tool-proof template-maker (AI stelt voor, code past toe en verifieert)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.newsletter.toolproof import apply_replacements, make_toolproof, verify_toolproof

STATIC_HTML = (
    "<html><body>"
    "<p>Welkom bij Bedrijf X, dit is onze vaste intro.</p>"
    '<a href="https://bedrijfx.nl/aanbod">Bekijk aanbod</a>'
    '<div class="cards"><div>kaart 1</div><div>kaart 2</div></div>'
    "<p>Afmelden: {{ unsubscribe }}</p>"
    "</body></html>"
)

OPS = [
    {"op": "replace", "find": "Welkom bij Bedrijf X, dit is onze vaste intro.",
     "from": None, "to": None, "replace": "{{INTRO_1}}", "reason": "intro vervangen"},
    {"op": "replace", "find": 'href="https://bedrijfx.nl/aanbod"',
     "from": None, "to": None, "replace": 'href="{{HOOFD_CTA_URL}}"', "reason": "hoofdknop-URL"},
    {"op": "replace", "find": ">Bekijk aanbod<",
     "from": None, "to": None, "replace": ">{{HOOFD_CTA_TEKST}}<", "reason": "hoofdknop-tekst"},
    {"op": "replace_range", "find": None, "from": '<div class="cards">',
     "to": "<p>Afmelden:", "replace": "<!-- ##CARDS## -->\n", "reason": "kaarten-sectie"},
]


@dataclass
class _FakeText:
    text: str
    type: str = "text"


@dataclass
class _FakeResp:
    content: list


@dataclass
class _FakeMessages:
    payload: dict
    calls: list = field(default_factory=list)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResp([_FakeText(json.dumps(self.payload))])


class FakeLLM:
    def __init__(self, payload: dict) -> None:
        self.messages = _FakeMessages(payload=payload)


def test_apply_replacements_exact_and_range() -> None:
    html, applied, failed = apply_replacements(STATIC_HTML, OPS)
    assert failed == []
    assert len(applied) == 4
    assert "{{INTRO_1}}" in html and "{{HOOFD_CTA_URL}}" in html
    assert "<!-- ##CARDS## -->" in html
    assert "kaart 1" not in html  # sectie echt vervangen
    assert "{{ unsubscribe }}" in html  # na de range blijft staan


def test_apply_reports_non_matching_ops() -> None:
    ops = [{"op": "replace", "find": "BESTAAT NIET IN DE HTML", "from": None, "to": None,
            "replace": "x", "reason": "kapotte vervanging"}]
    html, applied, failed = apply_replacements(STATIC_HTML, ops)
    assert html == STATIC_HTML  # niets stilletjes veranderd
    assert applied == []
    assert failed and "kapotte vervanging" in failed[0]


def test_verify_passes_for_flowing_placeholders() -> None:
    html, _, _ = apply_replacements(STATIC_HTML, OPS)
    passed, failed = verify_toolproof(html)
    assert failed == []
    assert any("{{INTRO_1}}" in p for p in passed)
    assert any("blokken-marker" in p for p in passed)
    assert any("afmeldlink" in p for p in passed)


def test_make_toolproof_end_to_end() -> None:
    llm = FakeLLM({"operations": OPS, "notes": ["reviews statisch gelaten"]})
    result = make_toolproof(llm, STATIC_HTML)
    assert result.ok is True
    assert "{{HOOFD_CTA_TEKST}}" in result.html
    assert result.notes == ["reviews statisch gelaten"]
    assert result.warnings  # aanbevolen placeholders (logo, footer) ontbreken nog -> tips


def test_make_toolproof_not_ok_when_ops_fail() -> None:
    llm = FakeLLM({"operations": [
        {"op": "replace", "find": "NIET AANWEZIG", "from": None, "to": None,
         "replace": "{{INTRO_1}}", "reason": "intro"},
    ], "notes": []})
    result = make_toolproof(llm, STATIC_HTML)
    assert result.ok is False
    assert result.failed


# -- invulvakken ({{VAK_*}}) in de toolproof-verificatie ------------------------


def test_verify_checks_custom_slots_flow() -> None:
    html = (
        "<html><body>{{INTRO_1}}{{INTRO_2}}"
        "<!-- ##SECTIE## --><div>{{VAK_ARTIKEL}}</div><!-- /##SECTIE## -->"
        "</body></html>"
    )
    passed, failed = verify_toolproof(html)
    assert failed == []
    assert any("invulvak ARTIKEL stroomt door" in p for p in passed)
    assert any("vallen netjes weg" in p for p in passed)


def test_verify_fails_on_unbalanced_section_markers() -> None:
    html = "<html><body><!-- ##SECTIE## -->{{VAK_X}}</body></html>"
    passed, failed = verify_toolproof(html)
    assert passed == []
    assert failed and "niet in balans" in failed[0]


def test_verify_fails_on_nested_sections() -> None:
    html = (
        "<html><body><!-- ##SECTIE## -->{{VAK_A}}"
        "<!-- ##SECTIE## -->{{VAK_B}}<!-- /##SECTIE## -->"
        "<!-- /##SECTIE## --></body></html>"
    )
    _, failed = verify_toolproof(html)
    assert failed and "render mislukt" in failed[0]


def test_analyze_input_flags_foreign_placeholders_and_unsafe_css() -> None:
    from app.newsletter.toolproof import analyze_input

    origineel = (
        "<style>:root { --clr: #fff; } .grid { display: grid; }</style>"
        "<p>{{bedrijfsnaam}} en {{artikel_titel}}</p>"
        "<p>{{ unsubscribe }} {{ contact.EMAIL }}</p>"
    )
    notes = analyze_input(origineel)
    assert any("eigen placeholders" in n and "bedrijfsnaam" in n for n in notes)
    assert any("e-mailclients niet ondersteunen" in n for n in notes)
    # ESP-tags zijn geen 'eigen placeholders'.
    assert not any("unsubscribe" in n for n in notes)
    assert analyze_input("<p>{{INTRO_1}}</p>") == []


def test_make_toolproof_includes_input_notes() -> None:
    llm = FakeLLM({"operations": OPS, "notes": ["ai-note"]})
    result = make_toolproof(llm, STATIC_HTML.replace("<body>", "<body style='display:grid'>"))
    assert any("e-mailclients" in n for n in result.notes)
    assert "ai-note" in result.notes
