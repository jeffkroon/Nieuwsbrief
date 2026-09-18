"""Tests voor hoe we ons melden bij de website van een klant.

Achtergrond: httpx meldt zich standaard als "python-httpx/0.x". Bot-filters
blokkeren dat met een 403, waardoor voetbalticketshop.nl in september 2026 ineens
onbereikbaar was terwijl de site het gewoon deed.
"""

from __future__ import annotations

import httpx

from app.newsletter import extraction
from app.newsletter.extraction import SITE_HEADERS, USER_AGENT, fetch_page


class _VangHeaders:
    """Nep-client die onthoudt met welke headers er is opgehaald."""

    def __init__(self, status: int = 200, body: str = "<html>ok</html>") -> None:
        self.gezien: list[dict] = []
        self._status = status
        self._body = body

    def get(self, url, headers=None, **kwargs):
        self.gezien.append(dict(headers or {}))
        return httpx.Response(self._status, text=self._body, request=httpx.Request("GET", url))


def test_fetch_page_meldt_zich_met_onze_eigen_naam() -> None:
    client = _VangHeaders()
    fetch_page("https://www.voetbalticketshop.nl/", client)
    assert client.gezien[0]["User-Agent"] == USER_AGENT
    assert "Dunion" in client.gezien[0]["User-Agent"]


def test_we_melden_ons_nooit_meer_als_python_httpx() -> None:
    """De standaard-user-agent van httpx is precies wat bot-filters blokkeren."""
    assert "httpx" not in USER_AGENT.lower()
    assert "python" not in USER_AGENT.lower()


def test_user_agent_is_eerlijk_en_naspeurbaar() -> None:
    """Geen Chrome nadoen: de site-eigenaar moet kunnen zien wie er langskomt."""
    assert "Mozilla" not in USER_AGENT
    assert "dunion.nl" in USER_AGENT


def test_accept_headers_gaan_mee() -> None:
    """Filters kijken ook naar Accept-headers; een browser stuurt die altijd mee."""
    client = _VangHeaders()
    fetch_page("https://example.com/", client)
    assert "text/html" in client.gezien[0]["Accept"]
    assert client.gezien[0]["Accept-Language"].startswith("nl")


def test_banner_controle_gebruikt_dezelfde_headers() -> None:
    """Een bannerfoto van een beschermde site moet net zo goed bereikbaar zijn."""
    from app.newsletter.tools import ToolContext, _require_image

    class _Afbeelding(_VangHeaders):
        def get(self, url, headers=None, **kwargs):
            self.gezien.append(dict(headers or {}))
            return httpx.Response(
                200, headers={"content-type": "image/jpeg"}, request=httpx.Request("GET", url)
            )

    client = _Afbeelding()
    _require_image(ToolContext(session=None, tenant_id=None, cipher=None, http_client=client),
                   "https://cdn.example.com/foto.jpg")
    assert client.gezien[0]["User-Agent"] == USER_AGENT


def test_site_headers_zijn_compleet() -> None:
    assert set(SITE_HEADERS) == {"User-Agent", "Accept", "Accept-Language"}
    assert extraction.SITE_HEADERS is SITE_HEADERS
