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
