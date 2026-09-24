"""De web-chat frontend wordt door FastAPI geserveerd op /."""

from __future__ import annotations


def test_index_served(client) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Nieuwsbrief-assistent" in resp.text


def _index(client) -> str:
    return client.get("/").text


def _frontend(client) -> str:
    """De hele frontend: de pagina plus alle losse bestanden die hij inlaadt."""
    import re

    html = client.get("/").text
    delen = [html]
    for pad in re.findall(r'(?:src|href)="(/static/[^"]+)"', html):
        resp = client.get(pad)
        assert resp.status_code == 200, f"{pad} wordt niet geserveerd"
        delen.append(resp.text)
    return "\n".join(delen)


def test_chat_gebruikt_de_streamende_route(client) -> None:
    """Zonder stream ziet de gebruiker een minuut lang alleen 'Aan het werk'."""
    html = _frontend(client)
    assert "/conversations/stream" in html
    assert "text/event-stream" not in html  # de browser leest de stroom zelf uit


def test_chat_heeft_stopknop_en_gespreksgeschiedenis(client) -> None:
    html = _frontend(client)
    for element in ('id="stop"', 'id="convList"', 'id="newChat"', 'id="quickStarts"'):
        assert element in html
    # Gesprekken staan in de sidebar (zoals ChatGPT) en zijn te verwijderen.
    assert html.index('id="convList"') < html.index('id="app"')
    assert 'method: "DELETE"' in html


def test_templatebeheer_heeft_upload_bewerken_en_versies(client) -> None:
    html = _frontend(client)
    for element in ('id="tmplDrop"', 'id="tmplFile"', 'id="tmplCancelEdit"', 'id="toolproofDiff"'):
        assert element in html
    assert "/versions" in html


def test_geen_externe_bronnen_in_de_frontend(client) -> None:
    """Alles moet lokaal werken: geen CDN-afhankelijkheid in een klantomgeving."""
    html = _index(client)
    for bron in ("cdnjs.cloudflare.com", "cdn.jsdelivr.net", "unpkg.com", "code.jquery.com"):
        assert bron not in html


def test_nieuwsbrieven_tab_bestaat(client) -> None:
    html = _frontend(client)
    for element in ('id="navNewsletters"', 'id="newslettersView"', 'id="nlList"'):
        assert element in html
    assert "/newsletters" in html


def test_stijlscherm_heeft_hoofdkleur_en_inklapbare_rest(client) -> None:
    """21 losse kleurkiezers is een bedieningspaneel, geen klantproduct."""
    html = _index(client)
    assert 'id="stPrimary"' in html
    assert 'id="stFromBrand"' in html
    assert "Alle kleuren apart instellen" in html
    assert 'id="stWarnings"' in html


def test_voorbeeld_staat_naast_de_kleuren(client) -> None:
    html = _frontend(client)
    assert "style-split" in html and "preview-col" in html


def test_frontend_is_opgesplitst_in_leesbare_bestanden(client) -> None:
    """Eén bestand van tweeduizend regels werd onwerkbaar; de eigen norm is 800."""
    import re

    html = client.get("/").text
    bestanden = re.findall(r'(?:src|href)="(/static/[^"]+)"', html)
    assert len(bestanden) >= 6, "de frontend hoort in losse onderdelen te staan"
    assert len(html.splitlines()) < 800, "index.html is weer te groot geworden"
    for pad in bestanden:
        resp = client.get(pad)
        assert resp.status_code == 200
        assert len(resp.text.splitlines()) < 800, f"{pad} is te groot geworden"


def test_geen_blokkerende_browser_dialogen(client) -> None:
    """confirm() blokkeert de pagina en ziet er in elke browser anders uit."""
    html = _frontend(client)
    assert "confirm(`" not in html and "confirm('" not in html
    assert "function bevestig(" in html


def test_scripts_zoeken_alleen_elementen_op_die_bestaan(client) -> None:
    """Vangt de klassieke fout na het opsplitsen: een script dat een element
    opzoekt dat niet (meer) in de pagina staat, waardoor alles stilvalt."""
    import re

    html = client.get("/").text
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    for pad in re.findall(r'src="(/static/[^"]+\.js)"', html):
        js = client.get(pad).text
        gevraagd = set(re.findall(r'getElementById\("([^"]+)"\)', js))
        ontbreekt = sorted(gevraagd - ids)
        assert not ontbreekt, f"{pad} zoekt niet-bestaande elementen: {ontbreekt}"


def test_stijlvoorbeeld_toont_de_mail_op_ware_breedte(client) -> None:
    """In een smalle kolom slaat de mobiele media query van de mail zelf aan en
    puilt de tekst uit de hero-cel door de tekst eronder. Daarom een vaste
    breedte die als geheel wordt geschaald, net als het chat-voorbeeld."""
    html = _frontend(client)
    assert "preview-scaler" in html
    assert "VOORBEELD_BREEDTE = 620" in html
    assert "transform-origin: top left" in html


def test_klant_en_template_kiezer_zijn_modern_maar_houden_de_select(client) -> None:
    """De <select>s blijven de bron van waarheid; picker.js tekent er een kiezer overheen."""
    html = _frontend(client)
    assert 'id="tenant"' in html and 'id="chatTemplate"' in html
    assert "/static/picker.js" in html
    assert html.index("/static/picker.js") < html.index("/static/chat.js")


def test_antwoorden_van_de_assistent_krijgen_veilige_opmaak() -> None:
    """Markdown (vet, lijstjes) wordt als DOM gebouwd, nooit via innerHTML."""
    from pathlib import Path

    chat = (Path(__file__).resolve().parents[1] / "app" / "static" / "chat.js").read_text()
    start = chat.index("function inlineMd")
    einde = chat.index("async function sendMessage")
    renderer = chat[start:einde]
    assert "renderMarkdown" in renderer and "innerHTML" not in renderer
    assert "https?:" in renderer  # alleen http(s)-links, geen javascript:
