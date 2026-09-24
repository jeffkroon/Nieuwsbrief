"""Banner-kandidaten nakijken voordat de assistent ze voorlegt.

Twee gaten uit de praktijk (Ohcascas, zilveren nieuwsbrief):
- Een "liggende foto" bleek een zwart posterframe van een productvideo. Formaat
  meten zegt niets over wat erop staat; een bijna egaal beeld valt nu af.
- De assistent koos een foto met gouden kettingen voor een nieuwsbrief over
  zilver: hij zag alleen bestandsnamen als "Ontwerp_zonder_titel_89.jpg". Elke
  kandidaat krijgt nu een korte beschrijving van wat er echt op staat (Haiku met
  beeldherkenning, een kleine versie van de foto, fracties van een cent).

Beide zijn best effort: mislukt een check, dan blijft de kandidaat staan zonder
beschrijving. Liever een foto zonder tekst dan helemaal geen keuze.
"""

from __future__ import annotations

import io
import re

import httpx

from app.newsletter.extraction import SITE_HEADERS, is_croppable
from app.newsletter.image_describe import describe_image

# Standaardafwijking van de grijswaarden: daaronder is het beeld (bijna) egaal.
BLANK_STDDEV = 8.0
PREVIEW_WIDTH = 64  # voor de egaal-check volstaat een postzegel
DESCRIBE_WIDTH = 512  # genoeg om goud van zilver te onderscheiden, klein genoeg om goedkoop te zijn
MAX_DOWNLOAD = 4 * 1024 * 1024


def _variant(url: str, width: int) -> str | None:
    """Kleinere versie via de CDN; None als de CDN dat niet kan."""
    if not is_croppable(url):
        return None
    if re.search(r"[?&]width=\d+", url):
        return re.sub(r"([?&])width=\d+", rf"\g<1>width={width}", url)
    return f"{url}{'&' if '?' in url else '?'}width={width}"


def _download(url: str, client: httpx.Client | None) -> tuple[bytes, str] | None:
    try:
        if client is not None:
            resp = client.get(url, headers=SITE_HEADERS)
        else:
            with httpx.Client(timeout=15.0, follow_redirects=True) as c:
                resp = c.get(url, headers=SITE_HEADERS)
    except httpx.HTTPError:
        return None
    soort = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    if resp.status_code != 200 or not soort.startswith("image/") or len(resp.content) > MAX_DOWNLOAD:
        return None
    return resp.content, soort


def looks_blank(url: str, client: httpx.Client | None = None) -> bool:
    """True als de foto (bijna) egaal is, zoals een zwart videoframe. Bij twijfel False."""
    klein = _variant(url, PREVIEW_WIDTH)
    if klein is None:
        return False  # geen goedkope versie; niet de hele foto downloaden voor deze check
    data = _download(klein, client)
    if data is None:
        return False
    try:
        from PIL import Image, ImageStat

        with Image.open(io.BytesIO(data[0])) as beeld:
            grijs = beeld.convert("L")
            return ImageStat.Stat(grijs).stddev[0] < BLANK_STDDEV
    except Exception:  # noqa: BLE001 - onleesbaar: niet afkeuren op een check die faalde
        return False


def describe(llm, url: str, client: httpx.Client | None = None) -> str | None:
    """Korte beschrijving van wat er op de foto staat, of None."""
    if llm is None:
        return None
    data = _download(_variant(url, DESCRIBE_WIDTH) or url, client)
    if data is None:
        return None
    uitkomst = describe_image(llm, data[0], data[1], filename=url.rsplit("/", 1)[-1].split("?")[0])
    return uitkomst.as_text() if uitkomst else None
