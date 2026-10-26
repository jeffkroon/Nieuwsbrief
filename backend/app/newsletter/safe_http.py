"""Klantsites ophalen zonder dat de server interne adressen bezoekt (SSRF).

Een URL komt vaak van buiten: de website van een nieuw bedrijf, een banner-URL
of een productpagina die de assistent noemt. Zonder controle kan zo'n URL de
server naar 127.0.0.1, het interne netwerk of het cloud-metadata-adres
(169.254.169.254) sturen. De guard hier weigert dat vóór elk verzoek, ook na
elke redirect: een publieke site die doorstuurt naar een intern adres komt er
dus ook niet door.

De weigering is een httpx.HTTPError, zodat de bestaande foutpaden
(`except httpx.HTTPError`) hem netjes afhandelen als "onbereikbaar".

Bekende grens: tussen onze controle en het echte verbinden lost httpx de naam
opnieuw op. Een DNS-server die precies daartussen van antwoord wisselt (DNS
rebinding) valt hier niet onder; dat vraagt een eigen transport.
"""

from __future__ import annotations

import ipaddress
import socket

import httpx

TOEGESTANE_SCHEMAS = frozenset({"http", "https"})

IpAdres = ipaddress.IPv4Address | ipaddress.IPv6Address


class OnveiligAdres(httpx.RequestError):
    """Verzoek geweigerd: geen http(s), of de host wijst naar een intern adres."""


def _is_intern(ip: IpAdres) -> bool:
    """True voor elk adres dat niet op het publieke internet hoort."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped  # ::ffff:127.0.0.1 is gewoon 127.0.0.1
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or not ip.is_global
    )


def _adressen(host: str, poort: int | None) -> tuple[IpAdres, ...]:
    """Alle IP-adressen waar de host naar wijst; leeg als hij niet bestaat."""
    try:
        antwoorden = socket.getaddrinfo(host, poort, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        return ()
    return tuple(ipaddress.ip_address(info[4][0].split("%", 1)[0]) for info in antwoorden)


def controleer_url(url: httpx.URL, request: httpx.Request | None = None) -> None:
    """Gooi OnveiligAdres als deze URL niet naar een publieke website wijst."""
    if url.scheme not in TOEGESTANE_SCHEMAS:
        raise OnveiligAdres(
            f"Adres geweigerd: alleen http en https zijn toegestaan, niet '{url.scheme}'.",
            request=request,
        )
    host = url.host
    if not host:
        raise OnveiligAdres("Adres geweigerd: er staat geen website in de URL.", request=request)
    adressen = _adressen(host, url.port)
    if not adressen:
        raise OnveiligAdres(f"Adres geweigerd: de website '{host}' bestaat niet.", request=request)
    if any(_is_intern(ip) for ip in adressen):
        raise OnveiligAdres(
            f"Adres geweigerd: '{host}' wijst naar een intern adres, niet naar een publieke website.",
            request=request,
        )


def _guard(request: httpx.Request) -> None:
    """Event-hook: httpx roept hem aan vóór elk verzoek, ook na een redirect."""
    controleer_url(request.url, request)


def site_client(
    timeout: float, *, transport: httpx.BaseTransport | None = None
) -> httpx.Client:
    """httpx.Client voor klantsites: volgt redirects, maar nooit naar interne adressen.

    `transport` is er alleen voor tests (httpx.MockTransport); de guard blijft
    dan gewoon actief.
    """
    return httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        event_hooks={"request": [_guard]},
        transport=transport,
    )
