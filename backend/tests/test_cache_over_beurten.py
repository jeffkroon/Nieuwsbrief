"""Prompt-cache over beurten heen, met maar één (de huidige) stand per verzoek.

De tekst van het laatste gebruikersbericht krijgt een cache-markering; de stand
komt erachter. Een beurt later moet alles tot en met dat tekstblok exact gelijk
zijn aan wat de vorige beurt stuurde (de markering zelf telt niet mee in de
prefix), en er mag nergens een oude stand in de geschiedenis staan.
"""

from __future__ import annotations

import uuid

from app.db.models import Conversation, Message
from app.newsletter.current_state import EARLIER_LABEL, STATE_INTRO
from app.newsletter.orchestrator import CACHE_CONTROL
from tests.test_conversations_routes import (  # noqa: F401 - fake_anthropic is een fixture
    FakeResponse,
    FakeText,
    FakeToolUse,
    _tenant,
    fake_anthropic,
)

# Maximaal aantal cache-markeringen per verzoek volgens de API.
MAX_BREAKPOINTS = 4


def _zet_stand(session, gesprek_id: str, stand: dict) -> None:
    conversation = session.get(Conversation, uuid.UUID(gesprek_id))
    conversation.last_preview = stand
    session.commit()


def _beurt(client, gesprek_id: str, tekst: str) -> None:
    resp = client.post(f"/conversations/{gesprek_id}/messages", json={"message": tekst})
    assert resp.status_code == 200, resp.text


def _blocks(message: dict) -> list:
    content = message["content"]
    return content if isinstance(content, list) else [{"type": "text", "text": content}]


def _is_stand(block) -> bool:
    return isinstance(block, dict) and str(block.get("text", "")).startswith(STATE_INTRO)


def _zonder_markering(value):
    """Zelfde structuur zonder cache_control (dat deel hoort niet bij de prefix)."""
    if isinstance(value, dict):
        return {k: _zonder_markering(v) for k, v in value.items() if k != "cache_control"}
    if isinstance(value, list):
        return [_zonder_markering(v) for v in value]
    return value


def _markeringen(value) -> int:
    if isinstance(value, dict):
        eigen = 1 if "cache_control" in value else 0
        return eigen + sum(_markeringen(v) for v in value.values())
    if isinstance(value, list):
        return sum(_markeringen(v) for v in value)
    return 0


def _laatste_echte_gebruikersbericht(messages: list[dict]) -> int:
    """Index van het laatste gebruikersbericht met tekst (geen tool-resultaten)."""
    return max(
        i for i, m in enumerate(messages)
        if m["role"] == "user" and any(
            isinstance(b, dict) and b.get("type") == "text" for b in _blocks(m)
        )
    )


def _gesprek_met_drie_beurten(client, session, fake_anthropic):
    tenant = _tenant(session)
    fake = fake_anthropic(
        [
            FakeResponse([FakeText("Waarover?")], "end_turn"),
            # Beurt 2 doet een tool-stap: ook die verzoeken krijgen precies één stand.
            FakeResponse([FakeToolUse("tu_1", "get_brand_config", {})], "tool_use"),
            FakeResponse([FakeText("Voorbeeld staat klaar.")], "end_turn"),
            FakeResponse([FakeText("Kop aangepast.")], "end_turn"),
        ]
    )
    gid = client.post(
        "/conversations", json={"tenant_id": str(tenant.id), "message": "herfstnieuwsbrief"}
    ).json()["conversation_id"]
    _zet_stand(session, gid, {"intro_1": "Jouw herfst", "header_title": "Herfst"})
    _beurt(client, gid, "maak de teksten beter")
    _zet_stand(
        session, gid,
        {"intro_1": "Jouw herfst, jouw glow", "header_title": "Herfst",
         "_eerder": {"intro_1": ["Jouw herfst"]}},
    )
    _beurt(client, gid, "andere kop")
    return gid, fake.messages.calls


def test_elk_verzoek_heeft_precies_een_stand_in_het_laatste_bericht(
    client, session, fake_anthropic
) -> None:
    _, calls = _gesprek_met_drie_beurten(client, session, fake_anthropic)
    assert len(calls) == 4
    for call in calls[1:]:  # beurt 1 had nog geen voorbeeld
        messages = call["messages"]
        plekken = [
            i for i, m in enumerate(messages) for b in _blocks(m) if _is_stand(b)
        ]
        assert plekken == [_laatste_echte_gebruikersbericht(messages)]
    assert not any(_is_stand(b) for m in calls[0]["messages"] for b in _blocks(m))
    # De oude stand ("Jouw herfst" als actieve intro) staat nergens meer in beurt 3.
    laatste = calls[3]["messages"]
    stand = _blocks(laatste[-1])[-1]["text"]
    huidig, eerder = stand.split(EARLIER_LABEL)
    assert "Jouw herfst, jouw glow" in huidig
    assert '"intro_1":["Jouw herfst"]' in eerder


def test_vorige_beurt_komt_tot_en_met_de_tekst_identiek_terug(
    client, session, fake_anthropic
) -> None:
    _, calls = _gesprek_met_drie_beurten(client, session, fake_anthropic)
    for vorige, nieuw in ((calls[0], calls[1]), (calls[1], calls[3])):
        oud = vorige["messages"]
        tekst = _blocks(oud[-1])[0]
        # De tekst van het laatste gebruikersbericht draagt de cache-markering.
        assert tekst["cache_control"] == CACHE_CONTROL
        prefix_oud = [*oud[:-1], {"role": "user", "content": [tekst]}]
        teruggespeeld = nieuw["messages"][len(oud) - 1]
        prefix_nieuw = [
            *nieuw["messages"][: len(oud) - 1],
            {"role": "user", "content": _blocks(teruggespeeld)[:1]},
        ]
        assert _zonder_markering(prefix_nieuw) == _zonder_markering(prefix_oud)
        # Het teruggespeelde bericht is alleen die tekst: geen stand, zelfde vorm.
        assert _zonder_markering(teruggespeeld) == _zonder_markering(
            {"role": "user", "content": [tekst]}
        )


def test_maximaal_vier_cache_markeringen_per_verzoek(client, session, fake_anthropic) -> None:
    _, calls = _gesprek_met_drie_beurten(client, session, fake_anthropic)
    for call in calls:
        totaal = sum(_markeringen(call.get(k)) for k in ("system", "tools", "messages"))
        assert 1 <= totaal <= MAX_BREAKPOINTS


def test_er_staat_nergens_een_stand_in_de_opgeslagen_metadata(
    client, session, fake_anthropic
) -> None:
    gid, _ = _gesprek_met_drie_beurten(client, session, fake_anthropic)
    session.expire_all()
    berichten = session.query(Message).filter_by(conversation_id=uuid.UUID(gid)).all()
    assert len(berichten) == 6
    assert all(m.metadata_ == {} for m in berichten)
    assert not any(STATE_INTRO in m.content for m in berichten)


def test_oude_berichten_spelen_terug_in_dezelfde_vorm(client, session, fake_anthropic) -> None:
    """Gesprekken van vóór deze wijziging: gewoon tekst, dus zelfde vorm als nieuw."""
    from app.repositories import conversations as repo

    tenant = _tenant(session)
    fake = fake_anthropic([FakeResponse([FakeText("ok")], "end_turn")])
    conversation = repo.create_conversation(session, tenant_id=tenant.id)
    repo.add_message(session, conversation.id, "user", "oud bericht", metadata={"x": 1})
    repo.add_message(session, conversation.id, "assistant", "oud antwoord")
    _zet_stand(session, str(conversation.id), {"subject": "Herfst"})

    _beurt(client, str(conversation.id), "nieuw bericht")

    verstuurd = fake.messages.calls[0]["messages"]
    assert verstuurd[0] == {"role": "user", "content": [{"type": "text", "text": "oud bericht"}]}
    assert verstuurd[1] == {"role": "assistant", "content": "oud antwoord"}
    assert _blocks(verstuurd[-1])[0]["text"] == "nieuw bericht"
    assert _is_stand(_blocks(verstuurd[-1])[-1])
