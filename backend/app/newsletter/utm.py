"""UTM-parameters op de links in de nieuwsbrief.

Zonder UTM's ziet de klant in Google Analytics alleen "direct verkeer" en is het
resultaat van een nieuwsbrief niet te meten. Met UTM's is per campagne te zien
wat hij opleverde.

Twee keuzes die het veilig houden:
- alleen links naar de eigen website van het bedrijf krijgen parameters; een link
  naar Facebook of een afmeldlink van het verzendplatform blijft ongemoeid;
- het staat per bedrijf uit tot het wordt ingesteld (`config["utm"]`), zodat een
  bestaande klant nooit ineens andere links in zijn mail krijgt.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Platform-tags in een URL, bv. %UNSUBSCRIBELINK% van ActiveCampaign. Niet te
# verwarren met gewone procent-codering (%20): die heeft geen sluitend procent
# na een rij hoofdletters.
_PLATFORM_TAG = re.compile(r"%[A-Z][A-Z_]{2,}%")

_HREF = re.compile(r"""(?is)(\bhref\s*=\s*)(["'])(.*?)\2""")
_TOEGESTANE_SLEUTELS = ("source", "medium", "campaign", "content", "term")


def utm_params(config: dict, *, campaign: str = "") -> dict[str, str]:
    """De in te stellen UTM-waarden van dit bedrijf; leeg = uit.

    `campaign` (het thema van deze nieuwsbrief) vult `utm_campaign` als daar in de
    configuratie niets vasts voor is gezet.
    """
    ruw = (config or {}).get("utm")
    if not isinstance(ruw, dict) or not ruw:
        return {}
    params = {
        f"utm_{sleutel}": str(ruw[sleutel]).strip()
        for sleutel in _TOEGESTANE_SLEUTELS
        if ruw.get(sleutel)
    }
    if "utm_campaign" not in params and campaign:
        params["utm_campaign"] = _slug(campaign)
    return params


def add_utm(html: str, params: dict[str, str], *, website_url: str) -> str:
    """Zet de UTM-parameters op links naar de eigen site; laat de rest met rust."""
    if not html or not params or not website_url:
        return html or ""
    eigen_host = _host(website_url)
    if not eigen_host:
        return html

    def _vervang(match: re.Match) -> str:
        url = match.group(3)
        nieuwe = _met_utm(url, params, eigen_host)
        if nieuwe is None:
            return match.group(0)
        return f"{match.group(1)}{match.group(2)}{nieuwe}{match.group(2)}"

    return _HREF.sub(_vervang, html)


def _met_utm(url: str, params: dict[str, str], eigen_host: str) -> str | None:
    """De URL met parameters, of None als deze link met rust gelaten moet worden."""
    schoon = (url or "").strip()
    if not schoon.lower().startswith(("http://", "https://")):
        return None  # mailto, tel, anker, of een tag van het verzendplatform
    if "{{" in schoon or "{%" in schoon or _PLATFORM_TAG.search(schoon):
        return None  # bevat een platform-tag; niet aankomen
    deel = urlsplit(schoon)
    if _kale_host(deel.netloc) != eigen_host:
        return None  # externe link (social, partner): geen eigen UTM's op plakken
    bestaand = dict(parse_qsl(deel.query, keep_blank_values=True))
    if any(sleutel.startswith("utm_") for sleutel in bestaand):
        return None  # al voorzien van tracking; niet overschrijven
    query = urlencode({**bestaand, **params})
    return urlunsplit((deel.scheme, deel.netloc, deel.path, query, deel.fragment))


def _host(url: str) -> str:
    return _kale_host(urlsplit(url if "//" in url else f"https://{url}").netloc)


def _kale_host(netloc: str) -> str:
    """Host zonder www en zonder poort, zodat www-varianten samenvallen."""
    host = (netloc or "").split("@")[-1].split(":")[0].lower()
    return host[4:] if host.startswith("www.") else host


def _slug(tekst: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (tekst or "").lower()).strip("-")[:60]
