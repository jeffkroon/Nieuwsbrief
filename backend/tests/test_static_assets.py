"""Na een deploy mag de browser nooit een oude css/js bij nieuwe HTML gebruiken."""

from __future__ import annotations

from pathlib import Path

from app.static_assets import asset_version, versioned_html


def test_versie_verandert_als_een_bestand_verandert(tmp_path: Path) -> None:
    (tmp_path / "app.css").write_text("a{}")
    eerst = asset_version(tmp_path)
    (tmp_path / "app.css").write_text("a{color:red}")
    assert asset_version(tmp_path) != eerst


def test_alle_static_verwijzingen_krijgen_een_versie() -> None:
    html = '<link href="/static/app.css"><script src="/static/chat.js"></script><a href="/x">'
    uit = versioned_html(html, "abc123")
    assert 'href="/static/app.css?v=abc123"' in uit
    assert 'src="/static/chat.js?v=abc123"' in uit
    assert 'href="/x"' in uit


def test_index_en_static_laten_de_browser_hercontroleren(client) -> None:
    index = client.get("/")
    assert index.headers["cache-control"] == "no-cache"
    assert "/static/app.css?v=" in index.text and "/static/picker.js?v=" in index.text
    css = client.get("/static/app.css")
    assert css.status_code == 200 and css.headers["cache-control"] == "no-cache"


def test_iconen_hebben_vaste_afmetingen_zonder_css() -> None:
    """Zonder CSS werden inline-SVG's schermvullend; width/height voorkomt dat."""
    static = Path(__file__).resolve().parents[1] / "app" / "static"
    for naam in ("index.html", "picker.js", "chat.js"):
        tekst = (static / naam).read_text()
        assert '<svg viewBox="0 0 24 24"' not in tekst, naam
