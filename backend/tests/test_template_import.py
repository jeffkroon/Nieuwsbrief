"""Tests voor het inlezen van een geuploade template (.html of .zip-export)."""

from __future__ import annotations

import io
import zipfile

import pytest

from app.newsletter.template_import import (
    MAX_ENTRIES,
    ImportedImage,
    TemplateImportError,
    import_upload,
    rewrite_references,
)

HTML = """<html><body>
  <img src="images/logo.png" alt="logo">
  <td background="./images/achtergrond.jpg">
    <div style="background:url('images/held.png') no-repeat;">tekst</div>
  </td>
  <img src="https://cdn.example.com/extern.png" alt="extern">
</body></html>"""


def _zip(bestanden: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archief:
        for naam, inhoud in bestanden.items():
            archief.writestr(naam, inhoud)
    return buffer.getvalue()


def _opslag(opgeslagen: list[str]):
    def _store(naam: str, inhoud: bytes, content_type: str) -> str:
        opgeslagen.append(naam)
        return f"https://opslag.example.com/{naam}"

    return _store


def test_los_html_bestand() -> None:
    resultaat = import_upload("basis.html", b"<html>hallo</html>")
    assert resultaat.html == "<html>hallo</html>"
    assert resultaat.images == ()


def test_zip_slaat_afbeeldingen_op_en_herschrijft_verwijzingen() -> None:
    opgeslagen: list[str] = []
    raw = _zip(
        {
            "export/index.html": HTML.encode(),
            "export/images/logo.png": b"png",
            "export/images/achtergrond.jpg": b"jpg",
            "export/images/held.png": b"png",
        }
    )
    resultaat = import_upload("export.zip", raw, store=_opslag(opgeslagen))

    assert sorted(opgeslagen) == ["achtergrond.jpg", "held.png", "logo.png"]
    assert 'src="https://opslag.example.com/logo.png"' in resultaat.html
    assert 'background="https://opslag.example.com/achtergrond.jpg"' in resultaat.html
    assert "url('https://opslag.example.com/held.png')" in resultaat.html
    # Externe URL's blijven ongemoeid.
    assert "https://cdn.example.com/extern.png" in resultaat.html


def test_ontbrekende_afbeelding_wordt_gemeld_maar_blijft_staan() -> None:
    raw = _zip({"index.html": '<img src="images/weg.png">'.encode(), "images/er.png": b"x"})
    resultaat = import_upload("export.zip", raw, store=_opslag([]))
    assert 'src="images/weg.png"' in resultaat.html
    assert any("weg.png" in melding for melding in resultaat.notes)


def test_dubbele_bestandsnaam_matcht_alleen_op_volledig_pad() -> None:
    """Twee keer 'foto.png' in verschillende mappen: alleen het hele pad is eenduidig."""
    raw = _zip(
        {
            "index.html": '<img src="a/foto.png"><img src="b/foto.png">'.encode(),
            "a/foto.png": b"x",
            "b/foto.png": b"y",
        }
    )
    resultaat = import_upload("export.zip", raw, store=_opslag([]))
    assert resultaat.html.count("opslag.example.com") == 2
    assert "a/foto.png" not in resultaat.html


def test_zip_zonder_html_faalt() -> None:
    with pytest.raises(TemplateImportError, match="Geen .html-bestand"):
        import_upload("export.zip", _zip({"images/a.png": b"x"}), store=_opslag([]))


def test_zip_slip_wordt_geweigerd() -> None:
    raw = _zip({"../boze.html": b"<html></html>"})
    with pytest.raises(TemplateImportError, match="Onveilig pad"):
        import_upload("export.zip", raw, store=_opslag([]))


def test_te_veel_bestanden_wordt_geweigerd() -> None:
    bestanden = {"index.html": b"<html></html>"}
    bestanden.update({f"images/{i}.png": b"x" for i in range(MAX_ENTRIES + 1)})
    with pytest.raises(TemplateImportError, match="Te veel bestanden"):
        import_upload("export.zip", _zip(bestanden), store=_opslag([]))


def test_leeg_bestand_wordt_geweigerd() -> None:
    with pytest.raises(TemplateImportError, match="leeg"):
        import_upload("basis.html", b"")


def test_onbekend_bestandstype_wordt_geweigerd() -> None:
    with pytest.raises(TemplateImportError, match="Alleen een .html-bestand"):
        import_upload("template.docx", b"pk-achtig maar geen zip")


def test_ondiepste_html_wint() -> None:
    raw = _zip(
        {
            "diep/map/anders.html": b"<html>diep</html>",
            "index.html": b"<html>ondiep</html>",
        }
    )
    assert import_upload("x.zip", raw, store=_opslag([])).html == "<html>ondiep</html>"


def test_cp1252_bestand_leest_zonder_fout() -> None:
    resultaat = import_upload("oud.html", "<p>caf\xe9</p>".encode("cp1252"))
    assert "caf" in resultaat.html


def test_rewrite_zonder_afbeeldingen_laat_html_ongemoeid() -> None:
    html, notes = rewrite_references(HTML, ())
    assert html == HTML and notes == ()


def test_rewrite_negeert_data_uris() -> None:
    html = '<img src="data:image/png;base64,AAAA">'
    resultaat, notes = rewrite_references(html, (ImportedImage(path="a.png", url="https://x/a.png"),))
    assert resultaat == html
    assert notes == ()


def test_zipbom_wordt_gestopt_tijdens_het_uitpakken() -> None:
    """Een ZIP kan liegen over de uitgepakte grootte; de header is geen garantie.

    Dit bestand geeft in de header een kleine grootte op maar levert bij het
    uitpakken veel meer. De import moet dat tijdens het lezen merken, niet nadat
    het geheugen al vol is gelopen.
    """
    import io
    import zipfile

    from app.newsletter.template_import import MAX_IMAGE_BYTES

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archief:
        archief.writestr("index.html", '<img src="groot.png">')
        # Goed samendrukbaar, en fors groter dan de grens per afbeelding.
        archief.writestr("groot.png", b"\0" * (MAX_IMAGE_BYTES + 1024))
    raw = buffer.getvalue()

    # De header liegen: doe alsof het bestand maar een paar bytes is.
    with zipfile.ZipFile(io.BytesIO(raw)) as controle:
        assert controle.getinfo("groot.png").compress_size < 100_000  # echt samengedrukt

    resultaat = import_upload("bom.zip", raw, store=_opslag([]))
    # Het te grote bestand is overgeslagen met een melding; de import zelf leeft nog.
    assert resultaat.images == ()
    assert any("groot.png" in melding for melding in resultaat.notes)


def test_grote_afbeelding_wordt_overgeslagen_maar_de_rest_komt_door() -> None:
    import io
    import zipfile

    from app.newsletter.template_import import MAX_IMAGE_BYTES

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archief:
        archief.writestr("index.html", '<img src="klein.png"><img src="groot.png">')
        archief.writestr("klein.png", b"x" * 100)
        archief.writestr("groot.png", b"\0" * (MAX_IMAGE_BYTES + 1024))
    resultaat = import_upload("export.zip", buffer.getvalue(), store=_opslag([]))
    assert [i.path for i in resultaat.images] == ["klein.png"]
    assert "opslag.example.com/klein.png" in resultaat.html
