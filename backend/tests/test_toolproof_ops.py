"""Unit-tests voor de substitutie-verificatie: het ontwerp kan per constructie
niet veranderen; alleen inhoud mag door placeholders vervangen worden."""

from __future__ import annotations

from app.newsletter.toolproof_ops import (
    Extractie,
    extract_styles,
    verify_range_op,
    verify_replace_op,
)

# -- verify_replace_op: geldige substituties ----------------------------------


def test_simple_substitution_gives_binding() -> None:
    v = verify_replace_op(
        "<p>Welkom bij onze winkel!</p>", "<p>{{INTRO_1}}</p>"
    )
    assert v.ok
    assert dict(v.bindings) == {"{{INTRO_1}}": "Welkom bij onze winkel!"}


def test_token_at_start_and_end() -> None:
    v = verify_replace_op("Kop hier", "{{HEADER_TITEL}} hier")
    assert v.ok and dict(v.bindings) == {"{{HEADER_TITEL}}": "Kop"}
    v = verify_replace_op("kleur:#D62828", "kleur:{{STYLE_BUTTON_BG}}")
    assert v.ok and dict(v.bindings) == {"{{STYLE_BUTTON_BG}}": "#D62828"}


def test_multiple_tokens_one_op() -> None:
    v = verify_replace_op(
        'bgcolor="#D62828" color="#ffffff"',
        'bgcolor="{{STYLE_BUTTON_BG}}" color="{{STYLE_BUTTON_TEXT}}"',
    )
    assert v.ok
    assert dict(v.bindings) == {
        "{{STYLE_BUTTON_BG}}": "#D62828",
        "{{STYLE_BUTTON_TEXT}}": "#ffffff",
    }


def test_same_token_twice_same_value_ok() -> None:
    v = verify_replace_op(
        '<a href="https://x.nl/p">x</a><a href="https://x.nl/p">y</a>',
        '<a href="{{KAART_URL}}">x</a><a href="{{KAART_URL}}">y</a>',
    )
    assert v.ok and dict(v.bindings) == {"{{KAART_URL}}": "https://x.nl/p"}


def test_marker_is_pure_insertion() -> None:
    v = verify_replace_op(
        "<div>kaart</div>",
        "<!-- ##KAART## --><div>kaart</div><!-- /##KAART## -->",
    )
    assert v.ok and v.bindings == ()


def test_vak_token_and_sectie_marker() -> None:
    v = verify_replace_op(
        "<h2>Onze zomeractie</h2>",
        "<!-- ##SECTIE## --><h2>{{VAK_ACTIE_TITEL}}</h2><!-- /##SECTIE## -->",
    )
    assert v.ok
    assert dict(v.bindings) == {"{{VAK_ACTIE_TITEL}}": "Onze zomeractie"}


def test_spacing_token_binds_number_only() -> None:
    v = verify_replace_op(
        "padding-top:80px", "padding-top:{{STYLE_SPACING_BANNER_INTRO}}px"
    )
    assert v.ok and dict(v.bindings) == {"{{STYLE_SPACING_BANNER_INTRO}}": "80"}


# -- verify_replace_op: afwijzingen --------------------------------------------


def test_rewritten_markup_rejected() -> None:
    v = verify_replace_op(
        '<td class="oud" style="color:#000">Tekst</td>',
        '<td class="nieuw" style="color:#000">{{INTRO_1}}</td>',  # class herschreven
    )
    assert not v.ok and "pure inhoud-vervanging" in v.reason


def test_no_placeholder_at_all_rejected() -> None:
    v = verify_replace_op("<p>a</p>", "<p>b</p>")
    assert not v.ok and "geen enkele bekende placeholder" in v.reason


def test_forbidden_tokens_rejected() -> None:
    for verboden in ("<!-- ##CARDS## -->", "<!-- ##SECTIES## -->",
                     "{{HEADER_CTA}}", "{{FOOTER_CONTACT}}"):
        v = verify_replace_op("iets", f"x{verboden}y")
        assert not v.ok and "niet toegestaan" in v.reason


def test_unknown_placeholder_rejected() -> None:
    v = verify_replace_op("Tekst", "{{MIJN_EIGEN_DING}}")
    assert not v.ok and "onbekende placeholder" in v.reason


def test_esp_tags_allowed_in_literals() -> None:
    v = verify_replace_op(
        "<p>Afmelden: {{ unsubscribe }} | {{ contact.EMAIL }} | Welkom</p>",
        "<p>Afmelden: {{ unsubscribe }} | {{ contact.EMAIL }} | {{INTRO_1}}</p>",
    )
    assert v.ok and dict(v.bindings) == {"{{INTRO_1}}": "Welkom"}


def test_adjacent_gap_tokens_rejected() -> None:
    v = verify_replace_op("KopSub", "{{HEADER_TITEL}}{{HEADER_SUBTITEL}}")
    assert not v.ok and "direct tegen elkaar" in v.reason


def test_same_token_two_values_in_one_op_rejected() -> None:
    v = verify_replace_op(
        "#D62828 en #000000",
        "{{STYLE_BUTTON_BG}} en {{STYLE_BUTTON_BG}}",
    )
    assert not v.ok and "twee verschillende waarden" in v.reason


def test_color_token_cannot_swallow_markup() -> None:
    # Het kleur-gat is restrictief: er past alleen een hex-kleur in.
    v = verify_replace_op(
        'style="background:red"', 'style="background:{{STYLE_BUTTON_BG}}"'
    )
    assert not v.ok  # 'red' is geen hex


# -- Extractie: conflictdetectie over ops heen ----------------------------------


def test_extractie_conflict_across_ops() -> None:
    ex = Extractie()
    assert ex.bind((("{{STYLE_BUTTON_BG}}", "#D62828"),)) is None
    assert ex.bind((("{{STYLE_BUTTON_BG}}", "#D62828"),)) is None  # zelfde mag
    fout = ex.bind((("{{STYLE_BUTTON_BG}}", "#000000"),))
    assert fout and "eigen token" in fout
    assert ex.waarden["{{STYLE_BUTTON_BG}}"] == "#D62828"  # conflict niet overgenomen


def test_extract_styles_maps_originals() -> None:
    ex = Extractie()
    ex.bind((
        ("{{STYLE_BUTTON_BG}}", "#D62828"),
        ("{{STYLE_SPACING_BANNER_INTRO}}", "40"),
        ("{{STYLE_FONT}}", "'Trebuchet MS',Helvetica,sans-serif"),
        ("{{INTRO_1}}", "gewone tekst telt niet mee"),
    ))
    styles, notes = extract_styles(ex)
    assert styles == {
        "button_bg": "#D62828",
        "spacing_banner_intro": 40,
        "font_family": "trebuchet",
    }
    assert any("Basisstijl overgenomen" in n for n in notes)


def test_extract_styles_unknown_font_gets_note() -> None:
    ex = Extractie()
    ex.bind((("{{STYLE_FONT}}", "'Comic Sans MS',cursive"),))
    styles, notes = extract_styles(ex)
    assert "font_family" not in styles
    assert any("mail-veilige lijst" in n for n in notes)


# -- verify_range_op: alleen kaart-kopieën wissen --------------------------------

_CARD = '<td class="c"><img src="https://x/1.png"/><p>Kaart</p></td>'
_HTML_MET_KAART = (
    "<table><tr>"
    "<!-- ##KAART## -->" + _CARD + "<!-- /##KAART## -->"
    "</tr></table>"
)


def test_range_removes_duplicate_cards() -> None:
    dubbel = '<td class="d"><img src="https://x/2.png"/><p>Ander</p></td>'
    v = verify_range_op(_HTML_MET_KAART, dubbel + dubbel, "")
    assert v.ok


def test_range_with_replacement_content_rejected() -> None:
    v = verify_range_op(_HTML_MET_KAART, _CARD, "<div>nieuw ontwerp</div>")
    assert not v.ok and "alleen verwijderen" in v.reason


def test_range_with_different_structure_rejected() -> None:
    v = verify_range_op(_HTML_MET_KAART, "<section><h1>iets anders</h1></section>", "")
    assert not v.ok and "niet herkend als kopie" in v.reason


def test_range_containing_tokens_rejected() -> None:
    v = verify_range_op(_HTML_MET_KAART, '<td class="c">{{KAART_TITEL}}</td>', "")
    assert not v.ok and "al placeholders" in v.reason


def test_range_without_kept_card_block_rejected() -> None:
    v = verify_range_op("<table></table>", _CARD, "")
    assert not v.ok and "##KAART##" in v.reason
