"""Import van een geuploade template: los .html-bestand of .zip-export.

Een export uit Stripo, ActiveCampaign of Brevo is vaak een ZIP met de HTML plus
een map met afbeeldingen. Die afbeeldingen staan niet op internet, dus de mail
zou bij de ontvanger met kapotte plaatjes aankomen. Daarom: afbeeldingen naar de
beeldopslag van het bedrijf en de verwijzingen in de HTML herschrijven naar de
publieke URL.

Pure verwerking met een injecteerbare opslag-functie, zodat tests geen netwerk
nodig hebben. Er wordt hier niets opgeslagen in de database: de admin krijgt de
HTML terug, bekijkt het voorbeeld en beslist zelf of hij hem bewaart.
"""

from __future__ import annotations

import io
import posixpath
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import unquote

# Grenzen: een echte export is een paar MB. Ruim genoeg, maar niet onbeperkt
# (een ZIP-bom of een map met 10.000 bestanden mag de server niet omleggen).
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 60 * 1024 * 1024
MAX_ENTRIES = 300
MAX_IMAGE_BYTES = 8 * 1024 * 1024
# Blokgrootte waarin we uitpakken; zo weten we wanneer we moeten stoppen zonder
# eerst alles in het geheugen te trekken.
_LEES_BLOK = 256 * 1024

HTML_SUFFIXES = (".html", ".htm")
IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}

# Verwijzingen die we herschrijven: src="...", background="..." en url(...) in CSS.
_ATTR_RE = re.compile(r"""(?i)\b(src|background)(\s*=\s*)(["'])(.*?)\3""")
_CSS_URL_RE = re.compile(r"""(?i)\burl\(\s*(["']?)([^"')]+)\1\s*\)""")

# Externe of ingebedde verwijzingen laten we met rust.
_EXTERNAL_PREFIXES = ("http://", "https://", "//", "data:", "cid:", "mailto:", "#", "{{")


class TemplateImportError(ValueError):
    """Onbruikbare upload; de melding is bedoeld voor de admin in de UI."""


@dataclass(frozen=True)
class ImportedImage:
    """Een meegeleverde afbeelding die is opgeslagen; `path` is het pad in de ZIP."""

    path: str
    url: str


@dataclass(frozen=True)
class ImportedTemplate:
    html: str
    images: tuple[ImportedImage, ...] = ()
    notes: tuple[str, ...] = ()


# Opslaan van een afbeelding: (bestandsnaam, inhoud, content-type) -> publieke URL.
StoreImage = Callable[[str, bytes, str], str]


def decode_html(raw: bytes) -> str:
    """Bytes naar tekst. Exports zijn UTF-8 of (oudere Outlook-tools) cp1252."""
    for encoding in ("utf-8", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise TemplateImportError(
        "Kan de tekst van dit bestand niet lezen. Sla de template op als UTF-8 en probeer opnieuw."
    )


def import_upload(filename: str, raw: bytes, *, store: StoreImage | None = None) -> ImportedTemplate:
    """Los .html-bestand of .zip-export inlezen; kiest zelf de juiste route."""
    if not raw:
        raise TemplateImportError("Het bestand is leeg.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise TemplateImportError(
            f"Bestand te groot ({len(raw) // (1024 * 1024)} MB); maximaal "
            f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )
    name = (filename or "").lower()
    if name.endswith(".zip") or zipfile.is_zipfile(io.BytesIO(raw)):
        if store is None:
            raise TemplateImportError("Beeldopslag is niet beschikbaar; upload de losse HTML.")
        return import_zip(raw, store=store)
    if name.endswith(HTML_SUFFIXES) or not name:
        return ImportedTemplate(html=decode_html(raw))
    raise TemplateImportError("Alleen een .html-bestand of een .zip-export wordt ondersteund.")


def import_zip(raw: bytes, *, store: StoreImage) -> ImportedTemplate:
    """ZIP-export uitpakken: HTML eruit, afbeeldingen opslaan, verwijzingen omzetten."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise TemplateImportError("Dit is geen geldig ZIP-bestand.") from exc

    with archive:
        entries = [item for item in archive.infolist() if not item.is_dir()]
        _check_archive_limits(entries)
        html_entry = _pick_html_entry(entries)
        html = decode_html(_lees_begrensd(archive, html_entry, MAX_UNCOMPRESSED_BYTES))
        images, notes = _store_images(archive, entries, store=store)

    html, rewrite_notes = rewrite_references(html, images)
    if not images:
        notes = (*notes, "Geen afbeeldingen in de ZIP gevonden; alleen de HTML is ingelezen.")
    return ImportedTemplate(html=html, images=images, notes=(*notes, *rewrite_notes))


def _check_archive_limits(entries: list[zipfile.ZipInfo]) -> None:
    if not entries:
        raise TemplateImportError("Het ZIP-bestand is leeg.")
    if len(entries) > MAX_ENTRIES:
        raise TemplateImportError(
            f"Te veel bestanden in de ZIP ({len(entries)}); maximaal {MAX_ENTRIES}."
        )
    # LET OP: `file_size` komt uit de ZIP-header en wordt door de maker van het
    # bestand bepaald; een zip-bom liegt daarover. Dit is dus een eerste zeef, geen
    # garantie. De echte begrenzing zit in `_lees_begrensd`, dat tijdens het
    # uitpakken telt en stopt.
    opgegeven = sum(item.file_size for item in entries)
    if opgegeven > MAX_UNCOMPRESSED_BYTES:
        raise TemplateImportError(
            f"Inhoud van de ZIP is te groot ({opgegeven // (1024 * 1024)} MB uitgepakt); maximaal "
            f"{MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} MB."
        )
    for item in entries:
        if _is_unsafe_path(item.filename):
            raise TemplateImportError(
                f"Onveilig pad in de ZIP: {item.filename!r}. Pak de export opnieuw in."
            )


def _lees_begrensd(archive: zipfile.ZipFile, item: zipfile.ZipInfo, maximum: int) -> bytes:
    """Pak een bestand uit tot hoogstens `maximum` bytes.

    De opgegeven grootte in de ZIP-header is niet te vertrouwen: een zip-bom geeft
    een klein getal op en levert bij het uitpakken gigabytes. Daarom lezen we in
    blokken en stoppen we zodra de grens wordt overschreden, in plaats van eerst
    alles in het geheugen te laten lopen.
    """
    stukken: list[bytes] = []
    gelezen = 0
    with archive.open(item) as stroom:
        while True:
            blok = stroom.read(_LEES_BLOK)
            if not blok:
                break
            gelezen += len(blok)
            if gelezen > maximum:
                raise TemplateImportError(
                    f"{posixpath.basename(item.filename)} is bij het uitpakken groter dan "
                    f"{maximum // (1024 * 1024)} MB; de ZIP klopt niet."
                )
            stukken.append(blok)
    return b"".join(stukken)


def _is_unsafe_path(name: str) -> bool:
    """Zip-slip: paden die buiten de map wijzen of absoluut zijn, weigeren we."""
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or ".." in normalized.split("/"):
        return True
    return ":" in normalized.split("/")[0] and len(normalized.split("/")[0]) == 2


def _pick_html_entry(entries: list[zipfile.ZipInfo]) -> zipfile.ZipInfo:
    """De HTML van de export: het ondiepste .html-bestand, bij gelijke diepte de eerste."""
    candidates = [
        item for item in entries
        if item.filename.lower().endswith(HTML_SUFFIXES)
        and not posixpath.basename(item.filename).startswith((".", "_"))
    ]
    if not candidates:
        raise TemplateImportError("Geen .html-bestand in de ZIP gevonden.")
    candidates.sort(key=lambda item: (item.filename.count("/"), item.filename.lower()))
    return candidates[0]


def _store_images(
    archive: zipfile.ZipFile, entries: list[zipfile.ZipInfo], *, store: StoreImage
) -> tuple[tuple[ImportedImage, ...], tuple[str, ...]]:
    stored: list[ImportedImage] = []
    notes: list[str] = []
    for item in entries:
        suffix = posixpath.splitext(item.filename)[1].lower()
        content_type = IMAGE_TYPES.get(suffix)
        if content_type is None:
            continue
        try:
            inhoud = _lees_begrensd(archive, item, MAX_IMAGE_BYTES)
        except TemplateImportError:
            notes.append(
                f"{posixpath.basename(item.filename)} is groter dan "
                f"{MAX_IMAGE_BYTES // (1024 * 1024)} MB en is overgeslagen."
            )
            continue
        url = store(posixpath.basename(item.filename), inhoud, content_type)
        stored.append(ImportedImage(path=item.filename, url=url))
    return tuple(stored), tuple(notes)


def rewrite_references(html: str, images: tuple[ImportedImage, ...]) -> tuple[str, tuple[str, ...]]:
    """Vervang lokale verwijzingen door de opgeslagen URL's.

    Zoekt op het volledige pad in de ZIP en, als die bestandsnaam maar een keer
    voorkomt, ook op de kale bestandsnaam. Een verwijzing die nergens bij past
    blijft staan en wordt gemeld, zodat de admin het ziet.
    """
    if not images:
        return html, ()
    lookup = _reference_lookup(images)
    missing: set[str] = set()

    def _swap(reference: str) -> str | None:
        key = _normalize_reference(reference)
        if not key or reference.strip().lower().startswith(_EXTERNAL_PREFIXES):
            return None
        url = lookup.get(key) or lookup.get(posixpath.basename(key))
        if url is None:
            missing.add(posixpath.basename(key))
            return None
        return url

    def _attr(match: re.Match) -> str:
        url = _swap(match.group(4))
        if url is None:
            return match.group(0)
        return f"{match.group(1)}{match.group(2)}{match.group(3)}{url}{match.group(3)}"

    def _css(match: re.Match) -> str:
        url = _swap(match.group(2))
        if url is None:
            return match.group(0)
        quote = match.group(1)
        return f"url({quote}{url}{quote})"

    result = _CSS_URL_RE.sub(_css, _ATTR_RE.sub(_attr, html))
    notes = ()
    if missing:
        namen = ", ".join(sorted(missing)[:5]) + ("..." if len(missing) > 5 else "")
        notes = (
            f"Deze verwijzingen stonden niet in de ZIP en blijven ongewijzigd: {namen}. "
            "Controleer of die afbeeldingen al online staan.",
        )
    return result, notes


def _reference_lookup(images: tuple[ImportedImage, ...]) -> dict[str, str]:
    """Pad -> URL, plus bestandsnaam -> URL voor namen die maar een keer voorkomen."""
    lookup = {_normalize_reference(image.path): image.url for image in images}
    counts: dict[str, int] = {}
    for image in images:
        base = posixpath.basename(image.path).lower()
        counts[base] = counts.get(base, 0) + 1
    for image in images:
        base = posixpath.basename(image.path).lower()
        if counts[base] == 1:
            lookup.setdefault(base, image.url)
    return lookup


def _normalize_reference(reference: str) -> str:
    """Een verwijzing herleiden tot een vergelijkbaar pad (zonder ./, query of #)."""
    value = unquote((reference or "").strip().replace("\\", "/"))
    value = value.split("?", 1)[0].split("#", 1)[0]
    while value.startswith(("./", "/")):
        value = value[2:] if value.startswith("./") else value[1:]
    return value.lower()
