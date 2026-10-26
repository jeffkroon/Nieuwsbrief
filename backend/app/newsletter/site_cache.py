"""Proces-lokale caches voor dure site-data: de productcatalogus en fotobeschrijvingen.

De catalogus (tot een paar duizend producten) stond eerst per gesprek in
conversations.tool_memory (jsonb). Dat maakte de gespreksrij groot en elk nieuw
gesprek van hetzelfde bedrijf haalde de hele catalogus opnieuw op. Nu staat hij
hier, per (tenant_id, url), gedeeld door alle gesprekken van dat bedrijf.

Fotobeschrijvingen (één Haiku-call per foto) worden per foto-URL onthouden, zodat
find_banner/find_page_images dezelfde foto niet steeds opnieuw laten beschrijven.

Dit is alleen een geheugen voor het KIEZEN; de garanties (live validatie van de
uiteindelijke keuze bij het concept) lopen via een losse weg en raadplegen deze
caches niet.

AANNAME: er draait één instance (zie .do/app.yaml, instance_count: 1). Bij meer
instances of workers heeft elk proces zijn eigen kopie; dat is niet fout (hooguit
een extra fetch), maar dan is een gedeelde opslag zuiniger.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from app.newsletter.validation_cache import ValidationCache

CATALOG_TTL_SECONDS = 20 * 60  # zelfde venster als het werkgeheugen per gesprek
# Een catalogus kan groot zijn; een handvol per proces is ruim genoeg.
CATALOG_MAX_ENTRIES = 50
DESCRIPTION_TTL_SECONDS = 24 * 60 * 60  # wat er op een foto staat verandert zelden
DESCRIPTION_MAX_ENTRIES = 2000

catalog_cache = ValidationCache(ttl_seconds=CATALOG_TTL_SECONDS, max_entries=CATALOG_MAX_ENTRIES)
description_cache = ValidationCache(
    ttl_seconds=DESCRIPTION_TTL_SECONDS, max_entries=DESCRIPTION_MAX_ENTRIES
)


def cached_catalog(tenant_id: uuid.UUID, url: str, maker: Callable[[], dict]) -> dict:
    """De catalogus van deze URL voor dit bedrijf, uit de cache of vers via `maker()`.

    Uit de cache komt het resultaat met "from_memory": True terug. Faalt `maker()`,
    dan wordt er niets bewaard: een mislukte poging blijft nooit hangen.
    """
    sleutel = (tenant_id, url)
    gevonden, waarde = catalog_cache.get(sleutel)
    if gevonden:
        return {**waarde, "from_memory": True}
    result = maker()
    catalog_cache.set(sleutel, result)
    return result


def cached_description(url: str, maker: Callable[[], str | None]) -> str | None:
    """Beschrijving van de foto op `url`; alleen een gelukte beschrijving wordt bewaard.

    None (geen LLM, foto niet te downloaden) wordt niet onthouden, zodat een
    tijdelijke storing niet 24 uur lang "geen beschrijving" oplevert.
    """
    gevonden, waarde = description_cache.get((url,))
    if gevonden:
        return waarde
    beschrijving = maker()
    if beschrijving:
        description_cache.set((url,), beschrijving)
    return beschrijving


def clear() -> None:
    """Beide caches leeg (voor tests)."""
    catalog_cache.clear()
    description_cache.clear()
