"""De web-chat frontend wordt door FastAPI geserveerd op /."""

from __future__ import annotations


def test_index_served(client) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Nieuwsbrief-assistent" in resp.text
