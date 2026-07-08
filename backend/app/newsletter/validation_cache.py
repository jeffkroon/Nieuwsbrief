"""Korte-termijn cache voor live validaties (prijzen, bereikbaarheid, og-foto's).

De garanties blijven: elk blok wordt live gevalideerd. Maar een re-render binnen
hetzelfde kwartier ("maak de knop zwart") hoeft niet ALLE ongewijzigde blokken
opnieuw te fetchen en door Haiku te halen; dat was per re-render een pagina-fetch
plus ~10k tokens extractie per blok. Verloopt een waarde, dan wordt er gewoon
opnieuw gevalideerd; bij een process-herstart is de cache leeg en geldt hetzelfde.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable
from threading import Lock

DEFAULT_TTL_SECONDS = 600  # 10 minuten: ruim binnen een preview->akkoord-cyclus
DEFAULT_MAX_ENTRIES = 500


class ValidationCache:
    """Kleine TTL-cache, thread-safe, met vaste maximale omvang (LRU-achtig)."""

    def __init__(
        self,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._now = time_fn
        self._data: OrderedDict[tuple, tuple[float, object]] = OrderedDict()
        self._lock = Lock()

    def get(self, key: tuple) -> tuple[bool, object]:
        """(gevonden, waarde); verlopen waarden tellen als niet gevonden."""
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return (False, None)
            expires, value = entry
            if self._now() >= expires:
                del self._data[key]
                return (False, None)
            self._data.move_to_end(key)
            return (True, value)

    def set(self, key: tuple, value: object) -> None:
        with self._lock:
            self._data[key] = (self._now() + self._ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
