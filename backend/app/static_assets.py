"""Frontend-bestanden serveren zonder verouderde cache na een deploy.

Probleem: de browser hield app.css van een vorige versie vast (heuristische cache
op Last-Modified), terwijl index.html al nieuw was. Nieuwe elementen zonder hun
opmaak: iconen over het hele scherm, zichtbare verborgen velden.

Oplossing, twee lagen:
- index.html verwijst naar /static/...?v=<hash van alle frontend-bestanden>; na
  elke wijziging is dat een nieuwe URL, dus nooit een oude kopie.
- index.html en /static krijgen Cache-Control: no-cache: de browser mag bewaren,
  maar vraagt eerst of het nog klopt (ETag, meestal een goedkope 304).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

REVALIDATE = "no-cache"
_STATIC_REF = re.compile(r'((?:src|href)="/static/[^"?#]+)"')


def asset_version(static_dir: Path) -> str:
    """Korte hash over naam en inhoud van alle frontend-bestanden."""
    digest = hashlib.sha256()
    for path in sorted(p for p in static_dir.rglob("*") if p.is_file()):
        digest.update(path.relative_to(static_dir).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def versioned_html(html: str, version: str) -> str:
    """Zet ?v=<versie> achter elke /static/-verwijzing in src/href."""
    return _STATIC_REF.sub(lambda m: f'{m.group(1)}?v={version}"', html)


class RevalidatingStaticFiles(StaticFiles):
    """StaticFiles die de browser altijd laat hercontroleren (ETag -> 304)."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = REVALIDATE
        return response
