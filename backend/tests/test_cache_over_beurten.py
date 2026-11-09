"""Prompt-cache over beurten heen: eerdere berichten komen byte-identiek terug.

De orchestrator zet een cache-markering op het laatste blok. Dat helpt de volgende
beurt alleen als alles daarvoor precies gelijk is aan wat de vorige beurt stuurde,
inclusief de stand-notitie die toen bij het gebruikersbericht hing.
"""

from __future__ import annotations

import uuid

from app.db.models import Conversation, Message
from app.newsletter.current_state import STATE_INTRO, UNCHANGED_NOTE
from tests.test_conversations_routes import (  # noqa: F401 - fake_anthropic is een fixture
    FakeResponse,
    FakeText,
    FakeToolUse,
    _tenant,
    fake_anthropic,
)


def _normalized(messages: list[dict]) -> list[dict]:
    """Berichten zoals de API ze leest: tekst als blokken, zonder cache-markering.

    Een kale string en één tekstblok zijn voor de API hetzelfde; de markering
    bepaalt alleen waar de cache eindigt, niet wat er in de prefix staat.
    """
    out = []
    for m in messages:
        content = m["content"]
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content
        out.append(
            {
                "role": m["role"],
                "content": [
                    {k: v for k, v in b.items() if k != "cache_control"} for b in blocks
                ],
            }
        )
    return out


def _zet_stand(session, gesprek_id: str, stand: dict) -> None:
    conversation = session.get(Conversation, uuid.UUID(gesprek_id))
    conversation.last_preview = stand
    session.commit()


def _beurt(client, gesprek_id: str, tekst: str) -> None:
    resp = client.post(f"/conversations/{gesprek_id}/messages", json={"message": tekst})
    assert resp.status_code == 200, resp.text


def test_vorige_beurt_komt_byte_identiek_terug(client, session, fake_anthropic) -> None:
    tenant = _tenant(session)
    fake = fake_anthropic(
        [
            FakeResponse([FakeText("Waarover?")], "end_turn"),
            # Beurt 2 doet ook een tool-stap: die valt bij de volgende beurt weg,
            # maar het gebruikersbericht met zijn stand moet gelijk blijven.
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
    _zet_stand(session, gid, {"intro_1": "Jouw herfst, jouw glow", "header_title": "Herfst"})
    _beurt(client, gid, "andere kop")

    vorige = fake.messages.calls[1]["messages"]  # eerste call van beurt 2
    nieuw = fake.messages.calls[3]["messages"]  # eerste call van beurt 3
    assert _normalized(nieuw[: len(vorige)]) == _normalized(vorige)
    # Het oude bericht draagt zijn eigen (oude) stand, het nieuwe de huidige.
    assert "Jouw herfst, jouw glow" not in nieuw[2]["content"][-1]["text"]
    assert "Jouw herfst, jouw glow" in nieuw[-1]["content"][-1]["text"]
    assert nieuw[-1]["content"][0]["text"] == "andere kop"


def test_stand_wordt_bij_het_juiste_bericht_opgeslagen(client, session, fake_anthropic) -> None:
    tenant = _tenant(session)
    fake = fake_anthropic(
        [FakeResponse([FakeText("ok")], "end_turn") for _ in range(3)]
    )
    gid = client.post(
        "/conversations", json={"tenant_id": str(tenant.id), "message": "start"}
    ).json()["conversation_id"]
    _zet_stand(session, gid, {"subject": "Herfst"})
    _beurt(client, gid, "tweede")
    _beurt(client, gid, "derde")  # stand ongewijzigd

    session.expire_all()
    berichten = (
        session.query(Message)
        .filter_by(conversation_id=uuid.UUID(gid))
        .order_by(Message.created_at)
        .all()
    )
    users = [m for m in berichten if m.role == "user"]
    # Zonder voorbeeld wordt niets toegevoegd of opgeslagen.
    assert users[0].metadata_ == {}
    assert fake.messages.calls[0]["messages"][-1]["content"][-1]["text"] == "start"
    # De stand van VÓÓR de beurt hoort bij het bericht, precies zoals verstuurd.
    verstuurd = fake.messages.calls[1]["messages"][-1]["content"][-1]["text"]
    assert users[1].metadata_["state_note"] == verstuurd
    assert verstuurd.startswith(STATE_INTRO) and "Herfst" in verstuurd
    # Ongewijzigde stand: alleen een korte verwijzing.
    assert users[2].metadata_["state_note"] == UNCHANGED_NOTE
    assert all(not m.metadata_ for m in berichten if m.role == "assistant")
    # De stand komt niet in de berichttekst terecht.
    assert not any(STATE_INTRO in m.content for m in berichten)


def test_oude_berichten_zonder_metadata_breken_niets(client, session, fake_anthropic) -> None:
    """Gesprekken van vóór deze wijziging: geen notitie opgeslagen, dus niets aanhangen."""
    from app.repositories import conversations as repo

    tenant = _tenant(session)
    fake = fake_anthropic([FakeResponse([FakeText("ok")], "end_turn")])
    conversation = repo.create_conversation(session, tenant_id=tenant.id)
    repo.add_message(session, conversation.id, "user", "oud bericht")
    repo.add_message(session, conversation.id, "assistant", "oud antwoord")
    _zet_stand(session, str(conversation.id), {"subject": "Herfst"})

    _beurt(client, str(conversation.id), "nieuw bericht")

    verstuurd = fake.messages.calls[0]["messages"]
    assert verstuurd[0] == {"role": "user", "content": "oud bericht"}
    assert verstuurd[1] == {"role": "assistant", "content": "oud antwoord"}
    laatste = verstuurd[-1]["content"]
    assert laatste[0]["text"] == "nieuw bericht"
    assert laatste[-1]["text"].startswith(STATE_INTRO)
