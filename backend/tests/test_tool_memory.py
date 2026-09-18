"""Tests voor het compacte werkgeheugen per gesprek (tool_memory.py)."""

from __future__ import annotations

import time
import uuid

from app.newsletter.tool_memory import MEMORY_TTL_SECONDS, memory_key, with_memory
from app.repositories import conversations as conv_repo
from app.repositories import tenants as tenants_repo
from app.schemas import TenantCreate


def _tenant(session):
    slug = f"geheugen-{uuid.uuid4().hex[:8]}"
    return tenants_repo.create_tenant(session, TenantCreate(slug=slug, name="Geheugen BV"))


def _conversation(session):
    tenant = _tenant(session)
    return conv_repo.create_conversation(session, tenant_id=tenant.id, channel="web")


def test_memory_key_is_stabiel_en_negeert_lege_velden() -> None:
    assert memory_key("find_products", {"url": "https://x.nl/"}) == memory_key(
        "find_products", {"url": "https://x.nl/", "onbekend": None}
    )
    assert memory_key("find_products", {"url": "https://x.nl/"}) != memory_key(
        "find_matches", {"url": "https://x.nl/"}
    )


def test_memory_key_verschillende_params_geven_verschillende_sleutels() -> None:
    a = memory_key("find_ticket_links", {"url": "https://x.nl/", "query": "arsenal"})
    b = memory_key("find_ticket_links", {"url": "https://x.nl/", "query": "chelsea"})
    assert a != b


def test_tweede_aanroep_binnen_gesprek_hergebruikt_het_resultaat(session) -> None:
    conversation = _conversation(session)
    calls = {"n": 0}

    def maker() -> dict:
        calls["n"] += 1
        return {"count": 3, "products": ["a", "b", "c"]}

    eerste = with_memory(session, conversation.id, "find_products", {"url": "https://x.nl/"}, maker)
    tweede = with_memory(session, conversation.id, "find_products", {"url": "https://x.nl/"}, maker)

    assert calls["n"] == 1, "de tweede aanroep had de dure maker() niet opnieuw mogen draaien"
    assert "from_memory" not in eerste
    assert tweede["from_memory"] is True
    assert tweede["count"] == 3 and tweede["products"] == ["a", "b", "c"]


def test_verschillende_url_binnen_hetzelfde_gesprek_botst_niet(session) -> None:
    conversation = _conversation(session)
    calls = {"n": 0}

    def maker() -> dict:
        calls["n"] += 1
        return {"count": calls["n"]}

    a = with_memory(session, conversation.id, "find_products", {"url": "https://x.nl/a"}, maker)
    b = with_memory(session, conversation.id, "find_products", {"url": "https://x.nl/b"}, maker)

    assert calls["n"] == 2
    assert a["count"] == 1 and b["count"] == 2


def test_verschillende_gesprekken_delen_geen_geheugen(session) -> None:
    een = _conversation(session)
    ander = _conversation(session)
    calls = {"n": 0}

    def maker() -> dict:
        calls["n"] += 1
        return {"count": calls["n"]}

    with_memory(session, een.id, "find_products", {"url": "https://x.nl/"}, maker)
    with_memory(session, ander.id, "find_products", {"url": "https://x.nl/"}, maker)

    assert calls["n"] == 2, "elk gesprek moet zijn eigen werkgeheugen hebben"


def test_verlopen_geheugen_wordt_niet_hergebruikt(session) -> None:
    conversation = _conversation(session)
    calls = {"n": 0}

    def maker() -> dict:
        calls["n"] += 1
        return {"count": calls["n"]}

    with_memory(session, conversation.id, "find_products", {"url": "https://x.nl/"}, maker)

    # Simuleer dat de eerdere poging te lang geleden was, zonder echt te wachten.
    session.refresh(conversation)
    entry = conversation.tool_memory[memory_key("find_products", {"url": "https://x.nl/"})]
    entry["at"] = time.time() - MEMORY_TTL_SECONDS - 1
    session.commit()

    tweede = with_memory(session, conversation.id, "find_products", {"url": "https://x.nl/"}, maker)
    assert calls["n"] == 2, "een verlopen entry hoort een nieuwe fetch te triggeren"
    assert "from_memory" not in tweede


def test_mislukte_poging_wordt_nooit_onthouden(session) -> None:
    conversation = _conversation(session)
    calls = {"n": 0}

    def stuk() -> dict:
        calls["n"] += 1
        raise ValueError("pagina niet bereikbaar")

    for _ in range(2):
        try:
            with_memory(session, conversation.id, "find_products", {"url": "https://x.nl/"}, stuk)
        except ValueError:
            pass

    assert calls["n"] == 2, "een mislukte poging mag nooit als geldig resultaat gecached worden"


def test_zonder_gesprek_wordt_nooit_gecached(session) -> None:
    calls = {"n": 0}

    def maker() -> dict:
        calls["n"] += 1
        return {"count": calls["n"]}

    with_memory(session, None, "find_products", {"url": "https://x.nl/"}, maker)
    with_memory(session, None, "find_products", {"url": "https://x.nl/"}, maker)
    assert calls["n"] == 2


def test_onbestaand_gesprek_valt_terug_op_altijd_uitvoeren(session) -> None:
    calls = {"n": 0}

    def maker() -> dict:
        calls["n"] += 1
        return {"count": calls["n"]}

    onbestaand = uuid.uuid4()
    with_memory(session, onbestaand, "find_products", {"url": "https://x.nl/"}, maker)
    with_memory(session, onbestaand, "find_products", {"url": "https://x.nl/"}, maker)
    assert calls["n"] == 2


def test_oudste_entries_vallen_af_boven_de_grens(session) -> None:
    from app.newsletter.tool_memory import MAX_ENTRIES

    conversation = _conversation(session)
    for i in range(MAX_ENTRIES + 3):
        with_memory(
            session, conversation.id, "find_products", {"url": f"https://x.nl/{i}"},
            lambda i=i: {"count": i},
        )
    session.refresh(conversation)
    assert len(conversation.tool_memory) == MAX_ENTRIES
