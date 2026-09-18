"""De web-chat frontend wordt door FastAPI geserveerd op /."""

from __future__ import annotations


def test_index_served(client) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Nieuwsbrief-assistent" in resp.text


def _index(client) -> str:
    return client.get("/").text


def test_chat_gebruikt_de_streamende_route(client) -> None:
    """Zonder stream ziet de gebruiker een minuut lang alleen 'Aan het werk'."""
    html = _index(client)
    assert "/conversations/stream" in html
    assert "text/event-stream" not in html  # de browser leest de stroom zelf uit


def test_chat_heeft_stopknop_en_gespreksgeschiedenis(client) -> None:
    html = _index(client)
    for element in ('id="stop"', 'id="chatHistory"', 'id="newChat"', 'id="quickStarts"'):
        assert element in html


def test_templatebeheer_heeft_upload_bewerken_en_versies(client) -> None:
    html = _index(client)
    for element in ('id="tmplDrop"', 'id="tmplFile"', 'id="tmplCancelEdit"', 'id="toolproofDiff"'):
        assert element in html
    assert "/versions" in html


def test_geen_externe_bronnen_in_de_frontend(client) -> None:
    """Alles moet lokaal werken: geen CDN-afhankelijkheid in een klantomgeving."""
    html = _index(client)
    for bron in ("cdnjs.cloudflare.com", "cdn.jsdelivr.net", "unpkg.com", "code.jquery.com"):
        assert bron not in html
