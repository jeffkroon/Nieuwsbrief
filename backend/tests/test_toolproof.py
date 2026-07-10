"""Tests voor de tool-proof template-maker (AI stelt voor, code past toe en verifieert)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.newsletter.toolproof import apply_operations, make_toolproof, verify_toolproof

STATIC_HTML = (
    "<html><body>"
    "<p>Welkom bij Bedrijf X, dit is onze vaste intro.</p>"
    '<a href="https://bedrijfx.nl/aanbod">Bekijk aanbod</a>'
    '<div class="cards">'
    '<div><a href="https://bedrijfx.nl/p1"><img src="https://bedrijfx.nl/p1.png"/>kaart 1</a></div>'
    '<div><a href="https://bedrijfx.nl/p2"><img src="https://bedrijfx.nl/p2.png"/>kaart 2</a></div>'
    "</div>"
    "<p>Afmelden: {{ unsubscribe }}</p>"
    "</body></html>"
)

# Geldige operaties onder het nieuwe regime: pure substituties, kaartblok behouden.
OPS = [
    {"op": "replace", "find": "Welkom bij Bedrijf X, dit is onze vaste intro.",
     "from": None, "to": None, "replace": "{{INTRO_1}}", "reason": "intro vervangen"},
    {"op": "replace", "find": 'href="https://bedrijfx.nl/aanbod"',
     "from": None, "to": None, "replace": 'href="{{HOOFD_CTA_URL}}"', "reason": "hoofdknop-URL"},
    {"op": "replace", "find": ">Bekijk aanbod<",
     "from": None, "to": None, "replace": ">{{HOOFD_CTA_TEKST}}<", "reason": "hoofdknop-tekst"},
    {"op": "replace",
     "find": '<div><a href="https://bedrijfx.nl/p1"><img src="https://bedrijfx.nl/p1.png"/>kaart 1</a></div>',
     "from": None, "to": None,
     "replace": '<!-- ##KAART## --><div><a href="{{KAART_URL}}">'
                '<img src="{{KAART_IMAGE_URL}}"/>{{KAART_TITEL}}</a></div><!-- /##KAART## -->',
     "reason": "voorbeeldkaart markeren"},
    {"op": "replace_range", "find": None,
     "from": '<div><a href="https://bedrijfx.nl/p2">',
     "to": "</div><p>Afmelden:", "replace": "", "reason": "kaart-kopie verwijderen"},
]

# Het OUDE gedrag (ontwerp vervangen door ##CARDS##, vrije herschrijvingen):
# moet onder het nieuwe regime keihard geweigerd worden.
OUDE_OPS = [
    {"op": "replace", "find": "<p>Welkom bij Bedrijf X, dit is onze vaste intro.</p>",
     "from": None, "to": None, "replace": "<p style='margin:0'>{{INTRO_1}}</p>",
     "reason": "intro met herschreven markup"},
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


def test_apply_operations_valid_substitutions_and_card_dedup() -> None:
    html, applied, failed, extractie, removed = apply_operations(STATIC_HTML, OPS)
    assert failed == []
    assert len(applied) == 5
    assert "{{INTRO_1}}" in html and "{{HOOFD_CTA_URL}}" in html
    assert "<!-- ##KAART## -->" in html
    assert "kaart 2" not in html  # kopie echt verwijderd
    assert removed and "kaart 2" in removed[0]
    assert "{{ unsubscribe }}" in html
    # Originele waarden bewaard voor de round-trip.
    assert extractie.waarden["{{INTRO_1}}"] == "Welkom bij Bedrijf X, dit is onze vaste intro."
    assert extractie.waarden["{{HOOFD_CTA_URL}}"] == "https://bedrijfx.nl/aanbod"


def test_apply_operations_rejects_old_destructive_behavior() -> None:
    """Regressietest: het oude gedrag (herschrijven, ##CARDS##) wordt geweigerd."""
    html, applied, failed, _, removed = apply_operations(STATIC_HTML, OUDE_OPS)
    assert applied == [] and removed == []
    assert html == STATIC_HTML  # geen byte veranderd
    assert len(failed) == 2
    assert any("pure inhoud-vervanging" in f for f in failed)
    assert any("alleen verwijderen" in f or "##KAART##" in f for f in failed)


def test_apply_reports_non_matching_ops() -> None:
    ops = [{"op": "replace", "find": "BESTAAT NIET IN DE HTML", "from": None, "to": None,
            "replace": "{{INTRO_1}}", "reason": "kapotte vervanging"}]
    html, applied, failed, _, _ = apply_operations(STATIC_HTML, ops)
    assert html == STATIC_HTML  # niets stilletjes veranderd
    assert applied == []
    assert failed and "kapotte vervanging" in failed[0]


def test_verify_passes_for_flowing_placeholders() -> None:
    html, _, _, _, _ = apply_operations(STATIC_HTML, OPS)
    passed, failed = verify_toolproof(html)
    assert failed == []
    assert any("{{INTRO_1}}" in p for p in passed)
    assert any("kaart-blok" in p for p in passed)
    assert any("afmeldlink" in p for p in passed)


def test_make_toolproof_end_to_end() -> None:
    llm = FakeLLM({"operations": OPS, "notes": ["reviews statisch gelaten"]})
    result = make_toolproof(llm, STATIC_HTML)
    assert result.ok is True
    assert "{{HOOFD_CTA_TEKST}}" in result.html
    assert "reviews statisch gelaten" in result.notes
    assert any("byte-identiek" in p or "originele waarden" in p for p in result.checks_passed)
    assert result.warnings  # aanbevolen placeholders (logo, footer) ontbreken nog -> tips


def test_failed_verification_reverts_to_original() -> None:
    """Review-vondst: een gefaalde verificatie mag nooit gemuteerde HTML
    achterlaten die een admin per ongeluk kan opslaan. Falen = verwerpen."""
    ops = [{  # kaartblok ZONDER foto/link-tokens: sentinel-verificatie faalt
        "op": "replace",
        "find": '<div><a href="https://bedrijfx.nl/p1"><img src="https://bedrijfx.nl/p1.png"/>kaart 1</a></div>',
        "from": None, "to": None,
        "replace": '<!-- ##KAART## --><div><a href="https://bedrijfx.nl/p1">'
                   '<img src="https://bedrijfx.nl/p1.png"/>{{KAART_TITEL}}</a></div><!-- /##KAART## -->',
        "reason": "kaart zonder url/foto-tokens",
    }]
    result = make_toolproof(FakeLLM({"operations": ops, "notes": []}), STATIC_HTML)
    assert not result.ok
    assert result.html == STATIC_HTML  # omzetting verworpen, origineel onaangetast
    assert result.styles == {}
    assert any("VERWORPEN" in n for n in result.notes)


def test_strip_ws_keeps_single_space_meaningful() -> None:
    """Review-vondst: 'geen spatie' vs 'wel een spatie' tussen tags is een
    zichtbaar verschil (woorden plakken aan elkaar) en blijft dus een afwijking."""
    from app.newsletter.toolproof import _strip_ws

    assert _strip_ws("<b>Nieuw</b> <span>Product</span>") != _strip_ws(
        "<b>Nieuw</b><span>Product</span>"
    )
    assert _strip_ws("<b>a</b>\n\t <i>b</i>") == _strip_ws("<b>a</b> <i>b</i>")


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
