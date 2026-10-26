"""Garanties in build_newsletter: escapen in de mail (niet naar het platform),
knop- en bannerlinks gecontroleerd, het concept bewaart de volledige invoer en de
stand van het gesprek wordt pas na een gelukte render opgeslagen."""

from __future__ import annotations

import uuid

import httpx
import pytest

from app.db.models import Conversation, Newsletter
from app.newsletter.tools import ToolContext, execute_tool
from app.repositories import conversations as conversations_repo
from app.repositories import images as images_repo
from app.repositories import secrets as secrets_repo

from tests.test_tools import DRAFT_INPUT, FakeBrevo, _http, _tenant

ALGEMEEN = {k: v for k, v in DRAFT_INPUT.items() if k != "matches"}
PREVIEW = {k: v for k, v in ALGEMEEN.items() if k != "confirmed"}
BANNER_URL = "https://cdn.test/banner.jpg"


def _handler(*, weg: tuple[str, ...] = (), geen_foto: tuple[str, ...] = (), log=None):
    """200 voor alles, 404 voor `weg`; foto-URL's krijgen een image-type."""

    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if log is not None:
            log.append(url)
        if url in weg:
            return httpx.Response(404, text="weg")
        if url.endswith((".jpg", ".png")):
            soort = "text/html" if url in geen_foto else "image/jpeg"
            return httpx.Response(200, content=b"x", headers={"content-type": soort})
        return httpx.Response(200, text="<html>ok</html>")

    return handle


def _ctx(session, cipher, tenant, *, handler=None, conversation_id=None, brevo=None):
    return ToolContext(
        session=session, tenant_id=tenant.id, cipher=cipher,
        conversation_id=conversation_id,
        brevo_factory=(lambda key: brevo) if brevo is not None else None,
        http_client=_http(handler or _handler()),
        preview_holder=[],
    )


def _voetbal_tenant(session):
    # De voetbal-template heeft een {{HEADER_IMAGE_URL}}-slot.
    tenant = _tenant(session)
    tenant.config = {**tenant.config, "template": "voetbalreizenxl-main"}
    session.commit()
    return tenant


# --- A: escapen in de mail, ruw naar het platform -------------------------------


def test_preview_escapet_intro_en_itemtitel(session, cipher) -> None:
    tenant = _tenant(session)
    ctx = _ctx(session, cipher, tenant)
    payload = {
        **PREVIEW,
        "intro_1": "<script>alert(1)</script> Tom & Jerry",
        "items": [{"title": 'Ring <img src=x onerror="y">', "url": "https://shop.test/ring"}],
    }
    execute_tool("preview_newsletter", payload, ctx)
    html = ctx.preview_holder[-1]
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt; Tom &amp; Jerry" in html
    assert "<img src=x" not in html.lower()
    assert "&lt;img src=x onerror=&quot;y&quot;&gt;" in html.lower()


def test_concept_stuurt_onderwerp_preheader_en_naam_ruw_naar_het_platform(
    session, cipher
) -> None:
    tenant = _tenant(session)
    secrets_repo.set_tenant_secret(session, cipher, tenant.id, "brevo_api_key", "k")
    brevo = FakeBrevo("k")
    ctx = _ctx(session, cipher, tenant, brevo=brevo)
    payload = {
        **ALGEMEEN,
        "subject": 'Tom & "Jerry" <3',
        "preview_text": "Kaas & wijn",
        "theme": "Kaas & Wijn",
        "intro_1": "A & B",
    }
    result = execute_tool("create_newsletter_draft", payload, ctx)
    call = brevo.calls[0]
    assert call["subject"] == 'Tom & "Jerry" <3'
    assert call["preview_text"] == "Kaas & wijn"
    assert call["name"].startswith("VoetbalreizenXL - Kaas & Wijn (")
    assert "A &amp; B" in call["html"]
    rij = session.get(Newsletter, uuid.UUID(result["newsletter_id"]))
    assert rij.subject == 'Tom & "Jerry" <3' and rij.theme == "Kaas & Wijn"
    assert rij.input["intro_1"] == "A & B"  # bewaarde invoer blijft ruw


# --- B: knop- en bannerlinks gecontroleerd ------------------------------------


@pytest.mark.parametrize("veld", ["main_cta_url", "slot_cta_url"])
def test_onbereikbare_knoplink_wordt_geweigerd(session, cipher, veld) -> None:
    tenant = _tenant(session)
    ctx = _ctx(session, cipher, tenant, handler=_handler(weg=("https://x/weg",)))
    with pytest.raises(ValueError, match=veld) as exc:
        execute_tool("preview_newsletter", {**PREVIEW, veld: "https://x/weg"}, ctx)
    assert "404" in str(exc.value)


def test_knoplink_met_onveilig_schema_wordt_geweigerd(session, cipher) -> None:
    tenant = _tenant(session)
    ctx = _ctx(session, cipher, tenant)
    with pytest.raises(ValueError, match="main_cta_url"):
        execute_tool("preview_newsletter", {**PREVIEW, "main_cta_url": "javascript:alert(1)"}, ctx)


def test_mailto_knop_mag_zonder_ophalen(session, cipher) -> None:
    tenant = _tenant(session)
    log: list[str] = []
    ctx = _ctx(session, cipher, tenant, handler=_handler(log=log))
    execute_tool("preview_newsletter", {**PREVIEW, "main_cta_url": "mailto:info@x.test"}, ctx)
    assert not any(u.startswith("mailto") for u in log)
    assert 'href="mailto:info@x.test"' in ctx.preview_holder[-1]


def test_volledige_header_url_moet_een_bereikbare_afbeelding_zijn(session, cipher) -> None:
    tenant = _voetbal_tenant(session)
    ctx = _ctx(session, cipher, tenant, handler=_handler(geen_foto=(BANNER_URL,)))
    with pytest.raises(ValueError, match="header_image_url"):
        execute_tool("preview_newsletter", {**PREVIEW, "header_image_url": BANNER_URL}, ctx)

    goed = _ctx(session, cipher, tenant)
    execute_tool("preview_newsletter", {**PREVIEW, "header_image_url": BANNER_URL}, goed)
    assert BANNER_URL in goed.preview_holder[-1]


def test_header_uit_eigen_bibliotheek_wordt_niet_opnieuw_gecheckt(session, cipher) -> None:
    tenant = _voetbal_tenant(session)
    images_repo.create_image(
        session, tenant_id=tenant.id, filename="zomer-banner.jpg",
        storage_path="p/z.jpg", url="https://opslag.test/zomer-banner.jpg", category="banner",
    )
    log: list[str] = []
    ctx = _ctx(session, cipher, tenant, handler=_handler(log=log))
    execute_tool("preview_newsletter", {**PREVIEW, "header_image_url": "zomer-banner.jpg"}, ctx)
    assert "https://opslag.test/zomer-banner.jpg" in ctx.preview_holder[-1]
    assert "https://opslag.test/zomer-banner.jpg" not in log


# --- C: het concept bewaart de volledige (samengevoegde) invoer -------------------


def test_concept_met_alleen_gewijzigde_velden_bewaart_volledige_invoer(session, cipher) -> None:
    tenant = _tenant(session)
    secrets_repo.set_tenant_secret(session, cipher, tenant.id, "brevo_api_key", "k")
    gesprek = conversations_repo.create_conversation(session, tenant_id=tenant.id)
    brevo = FakeBrevo("k")
    ctx = _ctx(session, cipher, tenant, conversation_id=gesprek.id, brevo=brevo)

    execute_tool("preview_newsletter", PREVIEW, ctx)
    result = execute_tool(
        "create_newsletter_draft", {"subject": "Alleen dit is nieuw", "confirmed": True}, ctx
    )

    rij = session.get(Newsletter, uuid.UUID(result["newsletter_id"]))
    assert rij.input == {**PREVIEW, "subject": "Alleen dit is nieuw"}
    assert "confirmed" not in rij.input and "new_draft" not in rij.input


def test_bijgewerkt_concept_bewaart_ook_de_volledige_invoer(session, cipher) -> None:
    from tests.test_tools import FakeBrevoMetUpdate

    tenant = _tenant(session)
    secrets_repo.set_tenant_secret(session, cipher, tenant.id, "brevo_api_key", "k")
    gesprek = conversations_repo.create_conversation(session, tenant_id=tenant.id)
    ctx = _ctx(session, cipher, tenant, conversation_id=gesprek.id, brevo=FakeBrevoMetUpdate("k"))

    eerste = execute_tool("create_newsletter_draft", ALGEMEEN, ctx)
    tweede = execute_tool(
        "create_newsletter_draft", {"intro_2": "Nieuwe tweede alinea", "confirmed": True}, ctx
    )

    assert tweede["updated_existing_draft"] is True
    rij = session.get(Newsletter, uuid.UUID(eerste["newsletter_id"]))
    assert rij.input == {**PREVIEW, "intro_2": "Nieuwe tweede alinea"}


def test_mislukt_platform_concept_bewaart_volledige_invoer(session, cipher) -> None:
    tenant = _tenant(session)
    secrets_repo.set_tenant_secret(session, cipher, tenant.id, "brevo_api_key", "k")
    gesprek = conversations_repo.create_conversation(session, tenant_id=tenant.id)
    ctx = _ctx(session, cipher, tenant, conversation_id=gesprek.id, brevo=FakeBrevo("k", fail=True))

    execute_tool("preview_newsletter", PREVIEW, ctx)
    with pytest.raises(Exception):
        execute_tool("create_newsletter_draft", {"confirmed": True}, ctx)

    rij = session.query(Newsletter).filter_by(tenant_id=tenant.id).one()
    assert rij.status == "failed" and rij.input == PREVIEW


# --- D: stand pas opslaan na een gelukte render --------------------------------


def _stand(session, gesprek_id) -> dict | None:
    session.expire_all()
    return session.get(Conversation, gesprek_id).last_preview


def test_mislukte_preview_laat_de_vorige_stand_ongemoeid(session, cipher) -> None:
    tenant = _tenant(session)
    gesprek = conversations_repo.create_conversation(session, tenant_id=tenant.id)
    ctx = _ctx(
        session, cipher, tenant, conversation_id=gesprek.id,
        handler=_handler(weg=("https://x/weg",)),
    )
    execute_tool("preview_newsletter", PREVIEW, ctx)
    assert _stand(session, gesprek.id) == PREVIEW

    with pytest.raises(ValueError):
        execute_tool("preview_newsletter", {"main_cta_url": "https://x/weg"}, ctx)
    with pytest.raises(ValueError, match="ongeldige stijl-overrides"):
        execute_tool("preview_newsletter", {"style_overrides": {"button_bg": "rood"}}, ctx)

    assert _stand(session, gesprek.id) == PREVIEW


def test_gelukte_preview_slaat_de_samengevoegde_stand_op(session, cipher) -> None:
    tenant = _tenant(session)
    gesprek = conversations_repo.create_conversation(session, tenant_id=tenant.id)
    ctx = _ctx(session, cipher, tenant, conversation_id=gesprek.id)
    execute_tool("preview_newsletter", PREVIEW, ctx)
    execute_tool("preview_newsletter", {"intro_1": "Nieuw"}, ctx)
    assert _stand(session, gesprek.id) == {**PREVIEW, "intro_1": "Nieuw"}
