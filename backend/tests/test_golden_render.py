"""Golden-render tests: vang visuele regressies in de ingebouwde templates.

De byte/token-tests bewijzen dat placeholders doorstromen, maar niemand kijkt naar
de gerénderde mail. Deze test rendert elke builtin met vaste voorbeeldinhoud en
vergelijkt met een opgeslagen snapshot. Wijkt de render af, dan faalt de test;
herzie bewust en regenereer met UPDATE_GOLDEN=1.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from app.newsletter.renderer import render_newsletter
from app.newsletter.templates import load_template
from app.routes.templates import _SAMPLE

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
_INTERN = re.compile(r"\{\{[A-Z0-9_]+\}\}")

# Vaste voorbeeld-brand (alle verplichte velden) zodat de render deterministisch is.
BRAND = {
    "brand_name": "Voorbeeldmerk",
    "brand_email": "info@voorbeeld.nl",
    "brand_adres": "Voorbeeldstraat 1",
    "brand_postcode_stad": "1000 AA Voorbeeldstad",
    "website_url": "https://voorbeeld.nl",
    "primary_color": "#123456",
    "logo_url": "https://voorbeeld.nl/logo.png",
    "dummy_image_url": "https://voorbeeld.nl/dummy.png",
    "facebook_url": "https://facebook.com/voorbeeld",
    "instagram_url": "https://instagram.com/voorbeeld",
    "youtube_url": "https://youtube.com/voorbeeld",
    "styles": {},
}

BUILTINS = ["neutraal-basis", "voetbalreizenxl-main"]


def _render(name: str) -> str:
    return render_newsletter(load_template(name), dict(BRAND), _SAMPLE)


@pytest.mark.parametrize("name", BUILTINS)
def test_builtin_golden_render(name: str) -> None:
    out = _render(name)

    # Geen ongesubstitueerde interne tokens en geen losse/afgekapte haakjes.
    assert not _INTERN.findall(out), _INTERN.findall(out)
    assert out.count("{{") == out.count("}}"), "losse haakjes in de render"

    path = GOLDEN_DIR / f"{name}.html"
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN_DIR.mkdir(exist_ok=True)
        path.write_text(out)
        return
    assert path.exists(), f"golden ontbreekt voor {name}; draai met UPDATE_GOLDEN=1"
    assert path.read_text() == out, (
        f"de render van {name!r} wijkt af van de golden snapshot. Controleer de "
        "wijziging visueel; klopt hij, regenereer dan met UPDATE_GOLDEN=1."
    )
