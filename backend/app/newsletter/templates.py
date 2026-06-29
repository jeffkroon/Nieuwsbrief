"""Laden van HTML-templates die met de backend zijn meegeleverd."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

HTML_DIR = Path(__file__).resolve().parent / "html"


@lru_cache
def load_template(name: str) -> str:
    """Lees een template uit app/newsletter/html. Faalt duidelijk als die ontbreekt."""
    path = HTML_DIR / f"{name}.html"
    if not path.is_file():
        available = ", ".join(sorted(p.stem for p in HTML_DIR.glob("*.html"))) or "(geen)"
        raise FileNotFoundError(
            f"Template '{name}' niet gevonden in {HTML_DIR}. Beschikbaar: {available}"
        )
    return path.read_text(encoding="utf-8")
