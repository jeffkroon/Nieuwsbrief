"""De server haalt klantsites op, maar nooit interne adressen (SSRF).

Wie een URL kan invullen (website van een bedrijf, banner-URL, productpagina),
mag de server niet naar 127.0.0.1, het cloud-metadata-adres of het interne
netwerk sturen. De guard kijkt bij elk verzoek, ook na elke redirect.
"""

from __future__ import annotations

import socket
import uuid

import httpx
import pytest

from app.newsletter import safe_http
from app.newsletter.safe_http import OnveiligAdres, controleer_url, site_client

PUBLIEK = "93.184.216.34"


@pytest.fixture
def dns(monkeypatch):
    """Nep-DNS: host -> IP, zodat de test niet van het echte netwerk afhangt."""
    tabel: dict[str, str] = {}

    def fake_getaddrinfo(host, port, *args, **kwargs):
        ip = tabel.get(host, host)
        familie = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(familie, socket.SOCK_STREAM, 6, "", (ip, port or 0))]

    monkeypatch.setattr(safe_http.socket, "getaddrinfo", fake_getaddrinfo)
    return tabel


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/admin",
        "http://192.168.1.1/",
        "http://[::1]/",
        "http://0.0.0.0/",
        "http://[::ffff:127.0.0.1]/",
    ],
)
def test_interne_adressen_worden_geweigerd(dns, url) -> None:
    with pytest.raises(OnveiligAdres):
        controleer_url(httpx.URL(url))


def test_localhost_wordt_geweigerd(dns) -> None:
    dns["localhost"] = "127.0.0.1"
    with pytest.raises(OnveiligAdres):
        controleer_url(httpx.URL("http://localhost:8000/"))


def test_ander_schema_wordt_geweigerd(dns) -> None:
    with pytest.raises(OnveiligAdres, match="ftp"):
        controleer_url(httpx.URL("ftp://example.com/bestand"))


def test_onbekende_host_wordt_geweigerd(monkeypatch) -> None:
    def kapot(*args, **kwargs):
        raise socket.gaierror("bestaat niet")

    monkeypatch.setattr(safe_http.socket, "getaddrinfo", kapot)
    with pytest.raises(OnveiligAdres):
        controleer_url(httpx.URL("https://bestaat-niet.invalid/"))


def test_publiek_adres_is_toegestaan(dns) -> None:
    dns["example.com"] = PUBLIEK
    controleer_url(httpx.URL("https://example.com/pagina"))  # gooit niets


def test_weigering_is_een_httpx_fout() -> None:
    """Bestaande `except httpx.HTTPError`-paden vangen de weigering netjes op."""
    assert issubclass(OnveiligAdres, httpx.HTTPError)


def _client_met(handler) -> httpx.Client:
    """site_client, maar met een nep-transport in plaats van het echte netwerk."""
    return site_client(timeout=5.0, transport=httpx.MockTransport(handler))


def test_site_client_haalt_publieke_pagina_op(dns) -> None:
    dns["example.com"] = PUBLIEK
    client = _client_met(lambda r: httpx.Response(200, text="ok"))
    assert client.get("https://example.com/").text == "ok"
    assert client.follow_redirects is True


def test_site_client_weigert_intern_adres_zonder_verzoek(dns) -> None:
    gezien: list[str] = []

    def handler(request):
        gezien.append(str(request.url))
        return httpx.Response(200)

    client = _client_met(handler)
    with pytest.raises(OnveiligAdres):
        client.get("http://127.0.0.1/")
    assert gezien == []  # het verzoek is nooit verstuurd


def test_redirect_naar_intern_adres_wordt_geweigerd(dns) -> None:
    dns["example.com"] = PUBLIEK
    gezien: list[str] = []

    def handler(request):
        gezien.append(str(request.url))
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/"})
        return httpx.Response(200, text="geheim")

    client = _client_met(handler)
    with pytest.raises(OnveiligAdres):
        client.get("https://example.com/")
    assert gezien == ["https://example.com/"]  # de metadata-server is nooit bereikt


@pytest.fixture
def guard_spion(monkeypatch):
    """Vervang de guard door een spion die elk verzoek weigert en onthoudt."""
    gezien: list[str] = []

    def spion(request):
        gezien.append(str(request.url))
        raise OnveiligAdres("geweigerd in test", request=request)

    monkeypatch.setattr(safe_http, "_guard", spion)
    return gezien


def _haal_op_zonder_client(soort: str):
    """Roep elke plek aan die zelf een client maakt als er geen is meegegeven."""
    from app.newsletter import banner_check, catalog, extraction, page_images

    url = "https://klant.example/"
    aanroepen = {
        "fetch_page": lambda: extraction.fetch_page(url),
        "get_json": lambda: catalog._get_json(None, url, {}),
        "woo_page": lambda: catalog._woo_page(None, url, {}),
        "woo_lang": lambda: catalog._woo_lang(url, None),
        "measure_image": lambda: page_images.measure_image(url),
        "download": lambda: banner_check._download(url, None),
    }
    return aanroepen[soort]()


@pytest.mark.parametrize(
    ("soort", "verwacht"),
    [
        ("fetch_page", (None, "")),
        ("get_json", None),
        ("woo_page", None),
        ("woo_lang", None),
        ("measure_image", None),
        ("download", None),
    ],
)
def test_klantsite_ophalen_gaat_altijd_door_de_guard(guard_spion, soort, verwacht) -> None:
    assert _haal_op_zonder_client(soort) == verwacht
    assert guard_spion == ["https://klant.example/"]


def test_banner_controle_gaat_door_de_guard(guard_spion) -> None:
    from app.newsletter.site_tools import _require_image
    from app.newsletter.tool_context import ToolContext

    ctx = ToolContext(session=None, tenant_id=uuid.uuid4(), cipher=None)
    with pytest.raises(ValueError, match="onbereikbaar"):
        _require_image(ctx, "https://klant.example/banner.jpg")
    assert guard_spion == ["https://klant.example/banner.jpg"]
