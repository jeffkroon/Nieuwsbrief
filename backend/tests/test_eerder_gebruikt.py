"""Vorige teksten (`_eerder`) in de stand: bijgewerkt na een gelukte render,
nooit in een render-invoer, Newsletter.input of de geërfde velden."""

from __future__ import annotations

import uuid

import pytest

from app.db.models import Newsletter
from app.newsletter.earlier_values import EARLIER_KEY
from app.newsletter.preview_content import content_from_draft_input
from app.newsletter.tools import execute_tool
from app.repositories import conversations as conversations_repo
from app.repositories import secrets as secrets_repo
from tests.test_newsletter_build import ALGEMEEN, PREVIEW, _ctx, _handler, _stand
from tests.test_tools import FakeBrevo, _tenant


def _gesprek_met_ctx(session, cipher, **kwargs):
    tenant = _tenant(session)
    gesprek = conversations_repo.create_conversation(session, tenant_id=tenant.id)
    return tenant, gesprek, _ctx(session, cipher, tenant, conversation_id=gesprek.id, **kwargs)


def test_eerder_groeit_alleen_bij_een_echte_wijziging(session, cipher) -> None:
    _, gesprek, ctx = _gesprek_met_ctx(session, cipher)
    execute_tool("preview_newsletter", PREVIEW, ctx)
    execute_tool("preview_newsletter", {"intro_2": PREVIEW["intro_2"]}, ctx)
    assert EARLIER_KEY not in _stand(session, gesprek.id)

    for kop in ["Kop 1", "Kop 2", "Kop 3", "Kop 4", "Kop 3"]:
        execute_tool("preview_newsletter", {"header_title": kop}, ctx)
    eerder = _stand(session, gesprek.id)[EARLIER_KEY]
    # Max 3, nieuwste eerst, zonder dubbele en zonder de actieve waarde.
    assert eerder == {"header_title": ["Kop 4", "Kop 2", "Kop 1"]}


def test_mislukte_render_verandert_eerder_niet(session, cipher) -> None:
    _, gesprek, ctx = _gesprek_met_ctx(
        session, cipher, handler=_handler(weg=("https://x/weg",))
    )
    execute_tool("preview_newsletter", PREVIEW, ctx)
    execute_tool("preview_newsletter", {"intro_1": "Tweede"}, ctx)
    voor = _stand(session, gesprek.id)
    with pytest.raises(ValueError):
        execute_tool(
            "preview_newsletter", {"intro_1": "Derde", "main_cta_url": "https://x/weg"}, ctx
        )
    assert _stand(session, gesprek.id) == voor
    assert voor[EARLIER_KEY] == {"intro_1": [PREVIEW["intro_1"]]}


def test_eerder_lekt_niet_in_concept_of_geerfde_velden(session, cipher) -> None:
    tenant, gesprek, ctx = _gesprek_met_ctx(session, cipher, brevo=FakeBrevo("k"))
    secrets_repo.set_tenant_secret(session, cipher, tenant.id, "brevo_api_key", "k")
    execute_tool("preview_newsletter", PREVIEW, ctx)
    execute_tool("preview_newsletter", {"intro_1": "Nieuw"}, ctx)
    assert EARLIER_KEY in _stand(session, gesprek.id)

    # Ook een door de assistent meegestuurde `_eerder` telt niet als invoer.
    uit = execute_tool(
        "create_newsletter_draft",
        {"confirmed": True, EARLIER_KEY: {"intro_1": ["verzonnen"]}},
        ctx,
    )
    rij = session.get(Newsletter, uuid.UUID(uit["newsletter_id"]))
    assert EARLIER_KEY not in rij.input
    assert rij.input == {**PREVIEW, "intro_1": "Nieuw"}
    assert "verzonnen" not in str(_stand(session, gesprek.id))


def test_eerder_heeft_geen_effect_op_het_hervatte_voorbeeld() -> None:
    stand = {**PREVIEW, "intro_1": "Nieuw"}
    met_eerder = {**stand, EARLIER_KEY: {"intro_1": ["Oud"], "subject": ["Ander"]}}
    assert content_from_draft_input(met_eerder) == content_from_draft_input(stand)


def test_concept_zonder_eerdere_preview_bewaart_alleen_invoer(session, cipher) -> None:
    tenant, gesprek, ctx = _gesprek_met_ctx(session, cipher, brevo=FakeBrevo("k"))
    secrets_repo.set_tenant_secret(session, cipher, tenant.id, "brevo_api_key", "k")
    uit = execute_tool("create_newsletter_draft", ALGEMEEN, ctx)
    rij = session.get(Newsletter, uuid.UUID(uit["newsletter_id"]))
    assert EARLIER_KEY not in rij.input
