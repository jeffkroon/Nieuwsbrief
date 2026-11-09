"""Eerder gebruikte teksten per veld, zodat de assistent iets kan terugzetten.

"Zet de vorige kop terug" of "die eerste intro was beter" lukt alleen als de
vorige waarde nog ergens staat. Oude standen in de chatgeschiedenis laten staan
is verwarrend (welke is actief?); daarom houden we per tekstveld alleen de
laatste paar VORIGE waarden bij, in de stand zelf onder een gereserveerde sleutel.

Die sleutel erft nooit mee naar een render (zie _NOT_INHERITED in
newsletter_build) en komt dus ook niet in Newsletter.input terecht.
"""

from __future__ import annotations

# Gereserveerde sleutel in conversation.last_preview.
EARLIER_KEY = "_eerder"

# Velden waarvan we vorige waarden bewaren: losse teksten en de bannerfoto.
TRACKED_FIELDS = (
    "subject",
    "preview_text",
    "header_title",
    "header_subtitle",
    "header_cta_text",
    "intro_1",
    "intro_2",
    "main_cta_text",
    "slot_cta_text",
    "header_image_url",
)

MAX_EARLIER = 3


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def earlier_of(stand: dict | None) -> dict[str, list[str]]:
    """De opgeslagen vorige waarden, gecontroleerd; lege lijsten vallen weg.

    De stand komt uit de database: alleen bekende velden met tekstwaarden tellen.
    """
    raw = (stand or {}).get(EARLIER_KEY)
    if not isinstance(raw, dict):
        return {}
    cleaned = {
        field: [v for v in values if _text(v)][:MAX_EARLIER]
        for field, values in raw.items()
        if field in TRACKED_FIELDS and isinstance(values, list)
    }
    return {field: values for field, values in cleaned.items() if values}


def _field_history(old: str | None, new: str | None, history: list[str]) -> list[str]:
    """Vorige waarden van één veld na deze render: nieuwste eerst, zonder dubbele.

    Alleen een echte wijziging schuift de oude waarde erbij. De actieve waarde
    staat er nooit in, ook niet als de gebruiker een oude waarde terugzet.
    """
    added = [old] if old is not None and old != new else []
    unique: list[str] = []
    for value in [*added, *history]:
        if value != new and value not in unique:
            unique.append(value)
    return unique[:MAX_EARLIER]


def updated_earlier(previous: dict | None, merged: dict) -> dict[str, list[str]]:
    """Nieuwe vorige-waarden na een geslaagde render (puur, muteert niets).

    `previous` is de stand van vóór de render (met eventueel `_eerder`),
    `merged` de nieuwe invoer zonder `_eerder`.
    """
    history = earlier_of(previous)
    result = {
        field: _field_history(
            _text((previous or {}).get(field)), _text(merged.get(field)), history.get(field, [])
        )
        for field in TRACKED_FIELDS
    }
    return {field: values for field, values in result.items() if values}
