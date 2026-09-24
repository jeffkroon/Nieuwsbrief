"""API-tests voor de conversations-routes met een fake Anthropic-client."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from app.deps import get_anthropic_client
from app.main import app
from app.repositories import tenants as tenants_repo
from app.schemas import TenantCreate

CONFIG = {
    "brand_name": "VoetbalreizenXL",
    "brand_email": "info@voetbalreizenxl.nl",
    "brand_adres": "Julianaweg 141 JK",
    "brand_postcode_stad": "1131 DH Volendam",
    "brand_telefoon": "+31 85 303 6791",
    "brand_kvk": "76484211",
    "website_url": "https://www.voetbalreizenxl.nl",
    "base_tickets_url": "https://www.voetbalreizenxl.nl/tickets/",
    "primary_color": "#FF7200",
    "logo_url": "https://cdn/logo.png",
    "header_image_url": "https://cdn/header.png",
    "dummy_image_url": "https://cdn/dummy.png",
    "facebook_url": "https://fb/x",
    "instagram_url": "https://ig/x",
    "youtube_url": "https://yt/x",
    "club_images": {},
    # Gecachte tone -> conversatie-service scrapet niet (geen netwerk in tests).
    "tone_of_voice": "Informeel, sportief, enthousiast.",
}


@dataclass
class FakeText:
    text: str
    type: str = "text"


@dataclass
class FakeToolUse:
    id: str
    name: str
    input: dict
    type: str = "tool_use"


@dataclass
class FakeResponse:
    content: list
    stop_reason: str


@dataclass
class FakeMessages:
    responses: list
    calls: list = field(default_factory=list)

    def create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


class FakeAnthropic:
    def __init__(self, responses: list) -> None:
        self.messages = FakeMessages(responses=list(responses))
        # De orchestrator draait op de beta-endpoint (context editing); zelfde fake.
        self.beta = SimpleNamespace(messages=self.messages)


@pytest.fixture
def fake_anthropic():
    holder = {}

    def install(responses: list) -> FakeAnthropic:
        fake = FakeAnthropic(responses)
        app.dependency_overrides[get_anthropic_client] = lambda: fake
        holder["fake"] = fake
        return fake

    yield install
    app.dependency_overrides.pop(get_anthropic_client, None)


def _tenant(session):
    return tenants_repo.create_tenant(
        session, TenantCreate(slug="voetbalreizenxl", name="VoetbalreizenXL", config=CONFIG)
    )


def test_start_conversation_simple(client, session, fake_anthropic) -> None:
    tenant = _tenant(session)
    fake_anthropic([FakeResponse([FakeText("Waarover wil je een nieuwsbrief?")], "end_turn")])

    resp = client.post(
        "/conversations",
        json={"tenant_id": str(tenant.id), "message": "Hi, maak een nieuwsbrief"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["reply"] == "Waarover wil je een nieuwsbrief?"
    assert body["stop_reason"] == "end_turn"
    assert uuid.UUID(body["conversation_id"])


def test_message_too_long_is_rejected(client, session) -> None:
    # Een enorme lap tekst wordt geweigerd (voorkomt dure input-spam).
    from app.schemas import MAX_MESSAGE_CHARS

    tenant = _tenant(session)
    resp = client.post(
        "/conversations",
        json={"tenant_id": str(tenant.id), "message": "x" * (MAX_MESSAGE_CHARS + 1)},
    )
    assert resp.status_code == 422  # puur validatie aan de grens, geen agent-call


def test_start_conversation_runs_tool(client, session, fake_anthropic) -> None:
    tenant = _tenant(session)
    fake_anthropic(
        [
            FakeResponse([FakeToolUse("tu_1", "get_brand_config", {})], "tool_use"),
            FakeResponse([FakeText("Ik gebruik de oranje huisstijl.")], "end_turn"),
        ]
    )
    resp = client.post(
        "/conversations", json={"tenant_id": str(tenant.id), "message": "welke kleur?"}
    )
    assert resp.status_code == 201
    assert resp.json()["reply"] == "Ik gebruik de oranje huisstijl."


def test_continue_conversation_keeps_history(client, session, fake_anthropic) -> None:
    tenant = _tenant(session)
    fake = fake_anthropic(
        [
            FakeResponse([FakeText("Eerste antwoord.")], "end_turn"),
            FakeResponse([FakeText("Tweede antwoord.")], "end_turn"),
        ]
    )
    start = client.post(
        "/conversations", json={"tenant_id": str(tenant.id), "message": "eerste vraag"}
    ).json()
    cont = client.post(
        f"/conversations/{start['conversation_id']}/messages", json={"message": "tweede vraag"}
    )
    assert cont.status_code == 200
    assert cont.json()["reply"] == "Tweede antwoord."
    # De tweede create-call kreeg de volledige geschiedenis mee (user, assistant, user).
    second_history = fake.messages.calls[1]["messages"]
    assert [m["role"] for m in second_history] == ["user", "assistant", "user"]
    assert second_history[0]["content"] == "eerste vraag"
    assert second_history[1]["content"] == "Eerste antwoord."
    # Het laatste bericht krijgt een cache-markering (geschiedenis-caching);
    # de tekst zelf blijft gelijk.
    assert second_history[2]["content"][0]["text"] == "tweede vraag"
    assert second_history[2]["content"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_start_missing_tenant_404(client, fake_anthropic) -> None:
    fake_anthropic([FakeResponse([FakeText("x")], "end_turn")])
    resp = client.post(
        "/conversations", json={"tenant_id": str(uuid.uuid4()), "message": "hi"}
    )
    assert resp.status_code == 404


def test_continue_missing_conversation_404(client, fake_anthropic) -> None:
    fake_anthropic([FakeResponse([FakeText("x")], "end_turn")])
    resp = client.post(f"/conversations/{uuid.uuid4()}/messages", json={"message": "hi"})
    assert resp.status_code == 404


def test_content_types_shape_the_system_prompt(client, session, fake_anthropic) -> None:
    # Een bedrijf met eigen nieuwsbrief-soorten krijgt een prompt zonder voetbal.
    cfg = {**CONFIG, "content_types": [
        {"kind": "items", "name": "Cases", "button_text": "Lees de case"},
    ]}
    tenant = tenants_repo.create_tenant(
        session, TenantCreate(slug="bureau", name="Marketingbureau", config=cfg)
    )
    fake = fake_anthropic([FakeResponse([FakeText("ok")], "end_turn")])
    resp = client.post(
        "/conversations", json={"tenant_id": str(tenant.id), "message": "nieuwsbrief over cases"}
    )
    assert resp.status_code == 201
    system_text = fake.messages.calls[0]["system"][0]["text"]
    assert "CASES" in system_text and "Lees de case" in system_text
    assert "find_matches" not in system_text  # geen voetbal-script voor dit bedrijf


def test_template_info_injected_in_prompt(client, session, fake_anthropic) -> None:
    # Bedrijf met een secties-template: de agent krijgt te horen dat 2b moet.
    from app.repositories import templates as templates_repo

    tenant = _tenant(session)
    templates_repo.create_template(
        session, tenant_id=tenant.id, name="Shell",
        html="<html><!-- ##SECTIES## -->{{ unsubscribe }}</html>",
    )
    fake = fake_anthropic([FakeResponse([FakeText("ok")], "end_turn")])
    client.post("/conversations", json={"tenant_id": str(tenant.id), "message": "hoi"})
    system_text = fake.messages.calls[0]["system"][0]["text"]
    assert "OPZET-SECTIES" in system_text and '"Shell"' in system_text


def test_fallback_template_warns_agent(client, session, fake_anthropic) -> None:
    # Bedrijf zonder eigen templates: de agent moet dit melden.
    cfg = {**CONFIG}
    tenant = tenants_repo.create_tenant(
        session, TenantCreate(slug="zonder-template", name="Zonder", config=cfg)
    )
    fake = fake_anthropic([FakeResponse([FakeText("ok")], "end_turn")])
    client.post("/conversations", json={"tenant_id": str(tenant.id), "message": "hoi"})
    system_text = fake.messages.calls[0]["system"][0]["text"]
    assert "GEEN eigen template" in system_text


def test_klaviyo_tenant_prompt_says_klaviyo(client, session, fake_anthropic) -> None:
    cfg = {**CONFIG, "esp": "klaviyo"}
    tenant = tenants_repo.create_tenant(
        session, TenantCreate(slug="klaviyo-shop", name="Shop", config=cfg)
    )
    fake = fake_anthropic([FakeResponse([FakeText("ok")], "end_turn")])
    client.post("/conversations", json={"tenant_id": str(tenant.id), "message": "hoi"})
    system_text = fake.messages.calls[0]["system"][0]["text"]
    assert "Klaviyo" in system_text and "Brevo" not in system_text


def test_template_choice_is_remembered_per_conversation(client, session, fake_anthropic) -> None:
    # Eerste beurt kiest een template; het vervolgbericht stuurt geen keuze mee
    # maar valt NIET terug op de standaard: de gekozen template blijft gelden.
    from app.repositories import templates as templates_repo

    tenant = _tenant(session)
    templates_repo.create_template(
        session, tenant_id=tenant.id, name="Standaard", is_default=True,
        html="<html>{{ unsubscribe }}</html>",
    )
    gekozen = templates_repo.create_template(
        session, tenant_id=tenant.id, name="Speciale Shell",
        html="<html><!-- ##SECTIES## -->{{ unsubscribe }}</html>",
    )
    fake = fake_anthropic(
        [
            FakeResponse([FakeText("ok")], "end_turn"),
            FakeResponse([FakeText("ok")], "end_turn"),
        ]
    )
    start = client.post(
        "/conversations",
        json={"tenant_id": str(tenant.id), "message": "hoi", "template_id": str(gekozen.id)},
    ).json()
    client.post(f"/conversations/{start['conversation_id']}/messages", json={"message": "verder"})
    # De tweede beurt (zonder template_id) gebruikt nog steeds de gekozen template.
    system_text = fake.messages.calls[1]["system"][0]["text"]
    assert '"Speciale Shell"' in system_text and "OPZET-SECTIES" in system_text


# --- Gesprekken teruglezen en streamen -------------------------------------
def _sse_events(tekst: str) -> list[dict]:
    import json

    return [
        json.loads(regel[len("data: "):])
        for regel in tekst.splitlines()
        if regel.startswith("data: ")
    ]


def test_stream_geeft_stappen_en_een_slotbericht(client, session, fake_anthropic) -> None:
    tenant = _tenant(session)
    fake_anthropic(
        [
            FakeResponse([FakeToolUse("t1", "get_brand_config", {})], "tool_use"),
            FakeResponse([FakeText("Ik gebruik de oranje huisstijl.")], "end_turn"),
        ]
    )
    resp = client.post(
        "/conversations/stream",
        json={"tenant_id": str(tenant.id), "message": "Maak een nieuwsbrief"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _sse_events(resp.text)
    soorten = [e["type"] for e in events]
    assert soorten[0] == "start"  # gesprek-id komt meteen, ook als het daarna misgaat
    assert "step" in soorten and soorten[-1] == "done"
    assert any("Bedrijfsgegevens" in e.get("text", "") for e in events if e["type"] == "step")

    slot = events[-1]
    assert slot["reply"] == "Ik gebruik de oranje huisstijl."
    assert uuid.UUID(slot["conversation_id"]) == uuid.UUID(events[0]["conversation_id"])


def test_stream_zet_het_gesprek_voort(client, session, fake_anthropic) -> None:
    tenant = _tenant(session)
    fake_anthropic([FakeResponse([FakeText("eerste")], "end_turn")])
    eerste = _sse_events(
        client.post(
            "/conversations/stream", json={"tenant_id": str(tenant.id), "message": "hoi"}
        ).text
    )[-1]

    fake_anthropic([FakeResponse([FakeText("tweede")], "end_turn")])
    tweede = _sse_events(
        client.post(
            "/conversations/stream",
            json={
                "tenant_id": str(tenant.id),
                "message": "en nu verder",
                "conversation_id": eerste["conversation_id"],
            },
        ).text
    )[-1]
    assert tweede["conversation_id"] == eerste["conversation_id"]

    detail = client.get(f"/conversations/{eerste['conversation_id']}").json()
    assert [m["content"] for m in detail["messages"]] == ["hoi", "eerste", "en nu verder", "tweede"]


def test_stream_meldt_een_fout_als_event(client, session, fake_anthropic) -> None:
    """Een kapotte AI-dienst mag geen kale 500 geven maar een leesbare melding."""
    tenant = _tenant(session)

    class _Stuk:
        def create(self, **kwargs):
            raise RuntimeError("iteratielimiet")

    fake = fake_anthropic([])
    fake.messages = _Stuk()
    fake.beta = SimpleNamespace(messages=_Stuk())

    events = _sse_events(
        client.post(
            "/conversations/stream", json={"tenant_id": str(tenant.id), "message": "hoi"}
        ).text
    )
    assert events[-1]["type"] == "error"
    assert "te veel stappen" in events[-1]["detail"]


def test_gesprekkenlijst_toont_titel_en_nieuwste_eerst(client, session, fake_anthropic) -> None:
    tenant = _tenant(session)
    for tekst in ("eerste vraag", "tweede vraag"):
        fake_anthropic([FakeResponse([FakeText("ok")], "end_turn")])
        client.post("/conversations", json={"tenant_id": str(tenant.id), "message": tekst})

    lijst = client.get(f"/conversations?tenant_id={tenant.id}").json()
    assert [g["title"] for g in lijst] == ["tweede vraag", "eerste vraag"]


def test_gesprekkenlijst_is_per_bedrijf_gescheiden(client, session, fake_anthropic) -> None:
    een = _tenant(session)
    ander = tenants_repo.create_tenant(
        session, TenantCreate(slug="ander", name="Ander", config=CONFIG)
    )
    fake_anthropic([FakeResponse([FakeText("ok")], "end_turn")])
    client.post("/conversations", json={"tenant_id": str(een.id), "message": "van bedrijf een"})

    assert client.get(f"/conversations?tenant_id={ander.id}").json() == []
    assert len(client.get(f"/conversations?tenant_id={een.id}").json()) == 1


def test_onbekend_gesprek_geeft_404(client, session) -> None:
    assert client.get(f"/conversations/{uuid.uuid4()}").status_code == 404


def test_stream_gebruikt_een_eigen_sessie_voor_de_beurt(client, session, fake_anthropic) -> None:
    """De beurt draait in een thread die doorloopt nadat de request-sessie al
    opgeruimd kan zijn; hij moet daarom zijn eigen sessie openen."""
    from app.deps import get_session_factory_dep
    from app.main import app

    gebruikt = []
    origineel = app.dependency_overrides[get_session_factory_dep]

    def _tellende_factory():
        maker = origineel()

        def _open():
            gebruikt.append(1)
            return maker()

        return _open

    app.dependency_overrides[get_session_factory_dep] = _tellende_factory
    try:
        tenant = _tenant(session)
        fake_anthropic([FakeResponse([FakeText("klaar")], "end_turn")])
        resp = client.post(
            "/conversations/stream", json={"tenant_id": str(tenant.id), "message": "hoi"}
        )
        assert resp.status_code == 200
        assert _sse_events(resp.text)[-1]["type"] == "done"
        assert gebruikt, "de beurt heeft geen eigen sessie geopend"
    finally:
        app.dependency_overrides[get_session_factory_dep] = origineel


def test_te_veel_gelijktijdige_beurten_geeft_een_nette_melding(client, session) -> None:
    """Elke beurt bezet een thread en een DB-connectie; zonder grens trekt een
    handvol verlaten chats de pool leeg."""
    from app.routes import conversations as route

    tenant = _tenant(session)
    bezet = []
    try:
        while route._beurt_plaatsen.acquire(blocking=False):
            bezet.append(1)
        resp = client.post(
            "/conversations/stream", json={"tenant_id": str(tenant.id), "message": "hoi"}
        )
        assert resp.status_code == 503
        assert "te veel gesprekken" in resp.json()["detail"]
    finally:
        for _ in bezet:
            route._beurt_plaatsen.release()


def test_volgende_beurt_krijgt_de_huidige_nieuwsbrief_mee(client, session, fake_anthropic) -> None:
    """Bug: bij 'maak de teksten beter' wist de assistent niet wat er in het voorbeeld
    stond (alleen tekst werd teruggespeeld) en begon hij opnieuw over banners."""
    from app.db.models import Conversation

    tenant = _tenant(session)
    fake = fake_anthropic(
        [
            FakeResponse([FakeText("Voorbeeld staat klaar.")], "end_turn"),
            FakeResponse([FakeText("Teksten aangepast.")], "end_turn"),
        ]
    )
    start = client.post(
        "/conversations", json={"tenant_id": str(tenant.id), "message": "herfstnieuwsbrief"}
    ).json()
    conversation = session.get(Conversation, uuid.UUID(start["conversation_id"]))
    conversation.last_preview = {"intro_1": "Jouw herfst, jouw glow", "header_image_url": "https://cdn/b.jpg"}
    session.commit()

    client.post(
        f"/conversations/{start['conversation_id']}/messages",
        json={"message": "de teksten zijn cringy, verbeter dat"},
    )
    laatste = fake.messages.calls[1]["messages"][-1]["content"]
    assert laatste[0]["text"] == "de teksten zijn cringy, verbeter dat"
    stand = laatste[-1]["text"]
    assert "HUIDIGE STAND" in stand
    assert "Jouw herfst, jouw glow" in stand and "https://cdn/b.jpg" in stand
    # De stand wordt niet als bericht opgeslagen (anders stapelen verouderde kopieën op).
    detail = client.get(f"/conversations/{start['conversation_id']}").json()
    assert not any("HUIDIGE STAND" in (m.get("content") or "") for m in detail["messages"])


def test_gesprek_verwijderen_houdt_de_nieuwsbrief(client, session, fake_anthropic) -> None:
    from app.db.models import Conversation, Message, Newsletter
    from app.repositories import newsletters as newsletters_repo

    tenant = _tenant(session)
    fake_anthropic([FakeResponse([FakeText("ok")], "end_turn")])
    gid = client.post(
        "/conversations", json={"tenant_id": str(tenant.id), "message": "weg ermee"}
    ).json()["conversation_id"]
    nb = newsletters_repo.create_newsletter(
        session, tenant_id=tenant.id, subject="Blijft", html="<p/>",
        conversation_id=uuid.UUID(gid), status="ready", brevo_campaign_id=1,
    )

    assert client.delete(f"/conversations/{gid}").status_code == 204
    session.expire_all()
    assert session.get(Conversation, uuid.UUID(gid)) is None
    assert session.query(Message).filter_by(conversation_id=uuid.UUID(gid)).count() == 0
    blijft = session.get(Newsletter, nb.id)
    assert blijft is not None and blijft.conversation_id is None
    assert client.get(f"/conversations?tenant_id={tenant.id}").json() == []
    assert client.delete(f"/conversations/{gid}").status_code == 404


def test_klant_kan_geen_gesprek_van_ander_bedrijf_verwijderen(client, session, fake_anthropic) -> None:
    from app.deps import SessionInfo, current_session_info

    een = _tenant(session)
    ander = tenants_repo.create_tenant(session, TenantCreate(slug="ander2", name="Ander", config=CONFIG))
    fake_anthropic([FakeResponse([FakeText("ok")], "end_turn")])
    gid = client.post(
        "/conversations", json={"tenant_id": str(een.id), "message": "van een"}
    ).json()["conversation_id"]
    app.dependency_overrides[current_session_info] = lambda: SessionInfo(role="company", tenant_id=ander.id)
    try:
        assert client.delete(f"/conversations/{gid}").status_code == 403
    finally:
        app.dependency_overrides.pop(current_session_info, None)
    assert client.get(f"/conversations/{gid}").status_code == 200
