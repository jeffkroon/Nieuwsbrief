"""Foto's vinden op een pagina van de klantensite, zonder iets te verzinnen.

De tool keek voor beeld alleen naar `og:image`. Ontbreekt die, dan stond hij met
lege handen terwijl de pagina vol echte foto's staat: hero's als CSS-achtergrond,
productfoto's in <img>, beeld in JSON-LD. Daartussen zit ook ruis die je nooit op
de kop van een klantmail wilt: partnerlogo's, vlaggetjes, certificaten,
trackingpixels.

Daarom twee stappen, allebei in code:
1. `find_page_images`: alle kandidaten uit de HTML, ontdaan van herkenbare ruis,
   gerangschikt op hoe betrouwbaar de bron is (JSON-LD en og:image voorop).
2. `measure_image`: van de beste kandidaten de echte afmetingen lezen uit de
   eerste 128 KB (Range-verzoek), zodat alleen liggend beeld van voldoende
   breedte als banner wordt voorgelegd. Een logo van 5 KB valt hier vanzelf af.

De tool legt VOOR, de mens kiest. Een stockfoto of partnerlogo automatisch op de
banner zetten is erger dan geen banner.
"""

from __future__ import annotations

import html as html_lib
import io
import json
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from app.newsletter.extraction import SITE_HEADERS, is_croppable, normalize_banner_url

# Grenzen voor bruikbaar beeld in een mail.
MIN_BANNER_WIDTH = 600
MIN_PRODUCT_WIDTH = 300
MIN_ATTR_SIZE = 120  # kleiner in width/height-attribuut = icoon of pixel
MEASURE_BYTES = 128 * 1024  # eerste deel van het bestand volstaat voor de header
MAX_MEASURE = 12  # nooit meer bestanden aanraken per pagina

# Bestandsnamen en alt-teksten die vrijwel altijd geen foto zijn.
_RUIS = re.compile(
    r"logo|icon|sprite|pixel|tracking|avatar|flag|badge|certif|favicon|loader|spinner"
    r"|arrow|placeholder|blank|spacer|emoji|payment|ideal|visa|mastercard|paypal"
    r"|partner|award|keurmerk|social|whatsapp|linkedin|facebook|instagram|youtube",
    re.I,
)
_OVERGESLAGEN_EXT = (".svg", ".ico", ".gif")
# Posterframes van productvideo's (Shopify: /preview_images/...thumbnail): vaak een
# zwart eerste frame. Liggend en groot, dus zonder dit filter de "beste" banner.
_VIDEO_POSTER = re.compile(r"/preview_images/|\.thumbnail\.", re.I)

_IMG = re.compile(r"(?is)<img\b[^>]*>")
_SOURCE = re.compile(r"(?is)<source\b[^>]*>")
_ATTR = re.compile(r"""(?is)\b([a-z:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""")
_BG = re.compile(r"""(?is)background(?:-image)?\s*:\s*[^;"'}]*?url\(\s*(["']?)([^"')]+)\1\s*\)""")
_OG = re.compile(
    r"""(?is)<meta[^>]+(?:property|name)=["']og:image(?::url)?["'][^>]*>"""
)
_JSONLD = re.compile(r"(?is)<script[^>]+application/ld\+json[^>]*>(.*?)</script>")

# Betrouwbaarheid van de bron: lager is beter.
_BRON_RANG = {"jsonld": 0, "og": 1, "background": 2, "srcset": 3, "img": 4}


@dataclass(frozen=True)
class ImageCandidate:
    url: str
    source: str
    alt: str = ""
    attr_width: int | None = None
    attr_height: int | None = None
    position: int = 0

    @property
    def filename(self) -> str:
        return urlsplit(self.url).path.rsplit("/", 1)[-1]


@dataclass(frozen=True)
class MeasuredImage:
    url: str
    width: int
    height: int
    content_type: str
    source: str
    alt: str = ""
    total_bytes: int | None = None
    cropped: bool = False  # door de CDN liggend bijgesneden uit een vierkante/staande foto

    @property
    def landscape(self) -> bool:
        return self.width > self.height

    @property
    def filename(self) -> str:
        return urlsplit(self.url).path.rsplit("/", 1)[-1]

    def label(self) -> str:
        """Korte naam voor in de keuzelijst: alt-tekst als die er is, anders de bestandsnaam."""
        naam = self.alt.strip() or re.sub(r"[-_]+", " ", self.filename.rsplit(".", 1)[0])
        return f"{naam} ({self.width}x{self.height})"


# ---------------------------------------------------------------------------
# Stap 1: kandidaten uit de HTML
# ---------------------------------------------------------------------------
def find_page_images(html: str, base_url: str) -> list[ImageCandidate]:
    """Alle plausibele foto's op de pagina, ontdubbeld en gerangschikt; nooit ruis."""
    if not html:
        return []
    gevonden: dict[str, ImageCandidate] = {}
    positie = 0

    def _voeg_toe(ruwe_url: str, bron: str, alt: str = "", w: int | None = None, h: int | None = None) -> None:
        nonlocal positie
        url = _normaliseer(ruwe_url, base_url)
        if url is None or _is_ruis(url, alt, w, h):
            return
        positie += 1
        bestaand = gevonden.get(url)
        kandidaat = ImageCandidate(url, bron, alt.strip(), w, h, positie)
        # Zelfde beeld via een betrouwbaardere bron: die wint.
        if bestaand is None or _BRON_RANG[bron] < _BRON_RANG[bestaand.source]:
            gevonden[url] = kandidaat if bestaand is None else ImageCandidate(
                url, bron, alt.strip() or bestaand.alt, w or bestaand.attr_width,
                h or bestaand.attr_height, bestaand.position,
            )

    for url in _jsonld_images(html):
        _voeg_toe(url, "jsonld")
    for tag in _OG.findall(html):
        attrs = _attrs(tag)
        _voeg_toe(attrs.get("content", ""), "og")
    for tag in _IMG.findall(html):
        attrs = _attrs(tag)
        alt = attrs.get("alt", "")
        w, h = _getal(attrs.get("width")), _getal(attrs.get("height"))
        src = attrs.get("data-src") or attrs.get("data-lazy-src") or attrs.get("src", "")
        srcset = attrs.get("data-srcset") or attrs.get("srcset")
        if srcset:
            grootste = _grootste_uit_srcset(srcset)
            if grootste:
                _voeg_toe(grootste, "srcset", alt, w, h)
                continue  # src is dan de kleinste variant van hetzelfde beeld
        if src:
            _voeg_toe(src, "img", alt, w, h)
    for tag in _SOURCE.findall(html):
        attrs = _attrs(tag)
        srcset = attrs.get("data-srcset") or attrs.get("srcset")
        if srcset:
            grootste = _grootste_uit_srcset(srcset)
            if grootste:
                _voeg_toe(grootste, "srcset")
    for _, url in _BG.findall(html):
        _voeg_toe(url, "background")

    return sorted(gevonden.values(), key=_rangorde)


def _rangorde(k: ImageCandidate) -> tuple:
    breedte = k.attr_width or 0
    return (_BRON_RANG[k.source], -breedte, k.position)


def _attrs(tag: str) -> dict[str, str]:
    return {
        naam.lower(): html_lib.unescape(a if a is not None else (b if b is not None else c or ""))
        for naam, a, b, c in _ATTR.findall(tag)
    }


def _getal(waarde: str | None) -> int | None:
    if not waarde:
        return None
    m = re.match(r"\s*(\d+)", waarde)
    return int(m.group(1)) if m else None


def _grootste_uit_srcset(srcset: str) -> str | None:
    """Uit 'a.jpg 400w, b.jpg 1200w' de breedste; zonder descriptors de laatste."""
    beste, beste_w = None, -1
    for deel in srcset.split(","):
        stukken = deel.strip().split()
        if not stukken:
            continue
        url = stukken[0]
        w = 0
        if len(stukken) > 1:
            m = re.match(r"(\d+)(w|x)", stukken[1])
            if m:
                w = int(m.group(1)) * (1000 if m.group(2) == "x" else 1)
        if w >= beste_w:
            beste, beste_w = url, w
    return beste


def _normaliseer(ruwe_url: str, base_url: str) -> str | None:
    url = html_lib.unescape((ruwe_url or "").strip()).strip("\"' ")
    if not url or url.startswith(("data:", "blob:", "javascript:", "{{", "{%")):
        return None
    absoluut = urljoin(base_url, url)
    if not absoluut.startswith(("http://", "https://")):
        return None
    return absoluut.split("#", 1)[0]


def _is_ruis(url: str, alt: str, w: int | None, h: int | None) -> bool:
    pad = urlsplit(url).path.lower()
    if pad.endswith(_OVERGESLAGEN_EXT) or _VIDEO_POSTER.search(pad):
        return True
    if (w is not None and w < MIN_ATTR_SIZE) or (h is not None and h < MIN_ATTR_SIZE):
        return True
    return bool(_RUIS.search(pad.rsplit("/", 1)[-1]) or _RUIS.search(alt or ""))


def _jsonld_images(html: str) -> list[str]:
    """Beeld uit gestructureerde data; volgt @id-verwijzingen binnen dezelfde graaf."""
    urls: list[str] = []
    for blok in _JSONLD.findall(html):
        try:
            data = json.loads(blok.strip())
        except (ValueError, TypeError):
            continue
        knopen = _knopen(data)
        op_id = {k.get("@id"): k for k in knopen if isinstance(k, dict) and k.get("@id")}
        for knoop in knopen:
            if not isinstance(knoop, dict) or knoop.get("@type") in ("Organization", "Brand"):
                continue  # daar staat het logo, geen foto
            for sleutel in ("image", "primaryImageOfPage", "thumbnailUrl", "contentUrl"):
                for url in _beeld_urls(knoop.get(sleutel), op_id):
                    if url not in urls:
                        urls.append(url)
    return urls


def _knopen(data) -> list:
    if isinstance(data, list):
        return [k for item in data for k in _knopen(item)]
    if isinstance(data, dict):
        rest = data.get("@graph")
        return [data] + (_knopen(rest) if rest else [])
    return []


def _beeld_urls(waarde, op_id: dict) -> list[str]:
    if not waarde:
        return []
    if isinstance(waarde, str):
        return [waarde]
    if isinstance(waarde, list):
        return [u for item in waarde for u in _beeld_urls(item, op_id)]
    if isinstance(waarde, dict):
        if waarde.get("@type") == "ImageObject" or "url" in waarde or "contentUrl" in waarde:
            return [u for u in (waarde.get("contentUrl"), waarde.get("url")) if isinstance(u, str)]
        verwezen = op_id.get(waarde.get("@id"))
        if verwezen is not None and verwezen is not waarde:
            return _beeld_urls(verwezen, {})
    return []


# ---------------------------------------------------------------------------
# Stap 2: echte afmetingen lezen
# ---------------------------------------------------------------------------
def measure_image(
    url: str, client: httpx.Client | None = None, *, timeout: float = 15.0,
    source: str = "img", alt: str = "",
) -> MeasuredImage | None:
    """Afmetingen uit de eerste 128 KB; None als het geen leesbare afbeelding is."""
    headers = {**SITE_HEADERS, "Range": f"bytes=0-{MEASURE_BYTES - 1}"}
    try:
        if client is not None:
            resp = client.get(url, headers=headers)
        else:
            with httpx.Client(timeout=timeout, follow_redirects=True) as c:
                resp = c.get(url, headers=headers)
    except httpx.HTTPError:
        return None
    if resp.status_code not in (200, 206):
        return None
    content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    if not content_type.startswith("image/") or content_type == "image/svg+xml":
        return None
    afmetingen = _afmetingen(resp.content[:MEASURE_BYTES])
    if afmetingen is None:
        return None
    breedte, hoogte = afmetingen
    return MeasuredImage(
        url=str(resp.url), width=breedte, height=hoogte, content_type=content_type,
        source=source, alt=alt, total_bytes=_totaal_bytes(resp),
    )


def _afmetingen(data: bytes) -> tuple[int, int] | None:
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - dependency ontbreekt alleen bij kapotte install
        return None
    try:
        with Image.open(io.BytesIO(data)) as beeld:
            return int(beeld.width), int(beeld.height)
    except Exception:  # noqa: BLE001 - afgekapt of onleesbaar bestand: gewoon overslaan
        return None


def _totaal_bytes(resp: httpx.Response) -> int | None:
    bereik = resp.headers.get("content-range", "")
    if "/" in bereik and bereik.rsplit("/", 1)[-1].isdigit():
        return int(bereik.rsplit("/", 1)[-1])
    lengte = resp.headers.get("content-length")
    return int(lengte) if lengte and lengte.isdigit() and resp.status_code == 200 else None


# ---------------------------------------------------------------------------
# Samengesteld: kandidaten voor de banner en voor een productfoto
# ---------------------------------------------------------------------------
def banner_candidates(
    html: str, base_url: str, *, client: httpx.Client | None = None,
    limit: int = 6, min_width: int = MIN_BANNER_WIDTH,
) -> list[MeasuredImage]:
    """Foto's die als banner kunnen, gemeten, om aan de gebruiker voor te leggen.

    Eerst echt liggend beeld. Daarna vierkante of staande foto's die de CDN zelf
    liggend kan bijsnijden (Shopify): op webshops is dat vaak het mooiste beeld
    (campagnefoto, product om de hals), maar het viel eerder af als "niet liggend".
    """
    liggend: list[MeasuredImage] = []
    bij_te_snijden: list[MeasuredImage] = []
    for kandidaat in find_page_images(html, base_url)[:MAX_MEASURE]:
        gemeten = measure_image(kandidaat.url, client, source=kandidaat.source, alt=kandidaat.alt)
        if gemeten is None:
            continue
        if gemeten.landscape and gemeten.width >= min_width:
            liggend.append(gemeten)
        elif is_croppable(gemeten.url) and min(gemeten.width, gemeten.height) >= min_width:
            bij_te_snijden.append(_als_banner_uitsnede(gemeten))
        if len(liggend) >= limit:
            break
    return (liggend + bij_te_snijden)[:limit]


def _als_banner_uitsnede(beeld: MeasuredImage) -> MeasuredImage:
    from app.newsletter.extraction import BANNER_HEIGHT, BANNER_WIDTH

    return MeasuredImage(
        url=normalize_banner_url(beeld.url, crop="landscape"), width=BANNER_WIDTH,
        height=BANNER_HEIGHT, content_type=beeld.content_type, source=beeld.source,
        alt=beeld.alt, total_bytes=None, cropped=True,
    )


def best_product_image(
    html: str, base_url: str, *, client: httpx.Client | None = None,
    min_width: int = MIN_PRODUCT_WIDTH,
) -> str | None:
    """De meest betrouwbare foto van een productpagina, of None; nooit een gok."""
    for kandidaat in find_page_images(html, base_url)[:MAX_MEASURE]:
        gemeten = measure_image(kandidaat.url, client, source=kandidaat.source, alt=kandidaat.alt)
        if gemeten and gemeten.width >= min_width and gemeten.height >= min_width // 2:
            return gemeten.url
    return None
