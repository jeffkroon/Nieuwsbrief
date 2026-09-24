"""Route-tests voor GET /admin/usage (echte Postgres via de conftest-fixtures)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.db.models import LlmUsage, Tenant

MILJOEN = 1_000_000


def _tenant(session, slug: str, name: str) -> Tenant:
    tenant = Tenant(slug=slug, name=name)
    session.add(tenant)
    session.commit()
    return tenant


def _usage(tenant_id, conv_id=None, *, model="claude-sonnet-5", purpose="chat", **tokens):
    return LlmUsage(
        tenant_id=tenant_id, conversation_id=conv_id, model=model, purpose=purpose,
        input_tokens=tokens.get("input_tokens", 0),
        output_tokens=tokens.get("output_tokens", 0),
        cache_creation_tokens=tokens.get("cache_creation_tokens", 0),
        cache_read_tokens=tokens.get("cache_read_tokens", 0),
    )


@pytest.fixture
def seeded(session):
    bakker = _tenant(session, "bakkerij", "Bakkerij Jansen")
    fiets = _tenant(session, "fietsen", "Fietsen BV")
    conv_a, conv_b = uuid.uuid4(), uuid.uuid4()
    rows = [
        _usage(bakker.id, conv_a, input_tokens=MILJOEN),  # $2
        _usage(bakker.id, conv_a, output_tokens=MILJOEN),  # $10
        _usage(bakker.id, conv_b, cache_creation_tokens=MILJOEN),  # 1h: $4
        _usage(bakker.id, model="claude-sonnet-5", purpose="toolproof",
               cache_creation_tokens=MILJOEN),  # 5m: $2.50, geen gesprek
        _usage(fiets.id, uuid.uuid4(), model="claude-haiku-4-5-20251001",
               input_tokens=MILJOEN),  # $1
        _usage(None, model="claude-sonnet-5", purpose="prefill", input_tokens=MILJOEN),  # $2
        _usage(fiets.id, uuid.uuid4(), model="raadsel-model", input_tokens=MILJOEN),
    ]
    session.add_all(rows)
    session.commit()
    # Een oude regel valt buiten de standaardperiode van 30 dagen.
    oud = _usage(bakker.id, uuid.uuid4(), input_tokens=50 * MILJOEN)
    session.add(oud)
    session.commit()
    session.execute(
        text("update mail.llm_usage set created_at = now() - interval '40 days' where id = :id"),
        {"id": oud.id},
    )
    session.commit()
    return bakker, fiets


def test_usage_overzicht_per_bedrijf(client, seeded) -> None:
    bakker, fiets = seeded
    resp = client.get("/admin/usage")
    assert resp.status_code == 200
    body = resp.json()
    assert body["days"] == 30 and body["estimate"] is True

    tenants = {t["name"]: t for t in body["tenants"]}
    assert set(tenants) == {"Bakkerij Jansen", "Fietsen BV", "zonder bedrijf"}

    b = tenants["Bakkerij Jansen"]
    assert b["slug"] == "bakkerij" and b["tenant_id"] == str(bakker.id)
    assert b["calls"] == 4
    assert b["cost_usd"] == pytest.approx(18.5)
    assert b["conversations"] == 2
    assert b["avg_cost_per_conversation_usd"] == pytest.approx(8.0)  # (2+10+4)/2
    purposes = {(r["model"], r["purpose"]): r for r in b["breakdown"]}
    assert purposes[("claude-sonnet-5", "toolproof")]["cost_usd"] == pytest.approx(2.5)
    assert purposes[("claude-sonnet-5", "chat")]["calls"] == 3

    f = tenants["Fietsen BV"]
    assert f["cost_usd"] == pytest.approx(1.0)
    assert f["unpriced_calls"] == 1
    onbekend = [r for r in f["breakdown"] if r["model"] == "raadsel-model"]
    assert onbekend[0]["cost_usd"] is None

    z = tenants["zonder bedrijf"]
    assert z["tenant_id"] is None and z["conversations"] == 0
    assert z["avg_cost_per_conversation_usd"] is None

    totals = body["totals"]
    assert totals["calls"] == 7
    assert totals["cost_usd"] == pytest.approx(21.5)
    assert totals["conversations"] == 4
    assert totals["unpriced_calls"] == 1
    # Duurste bedrijf eerst.
    assert body["tenants"][0]["name"] == "Bakkerij Jansen"


def test_langere_periode_telt_oude_regels_mee(client, seeded) -> None:
    body = client.get("/admin/usage?days=90").json()
    bakker = next(t for t in body["tenants"] if t["name"] == "Bakkerij Jansen")
    assert bakker["calls"] == 5
    assert bakker["cost_usd"] == pytest.approx(118.5)


def test_leeg_overzicht(client) -> None:
    body = client.get("/admin/usage?days=7").json()
    assert body["tenants"] == [] and body["totals"]["cost_usd"] == 0


@pytest.mark.parametrize("days", ["0", "367", "-1", "abc"])
def test_days_wordt_gevalideerd(client, days: str) -> None:
    assert client.get(f"/admin/usage?days={days}").status_code == 422


@pytest.mark.parametrize("days", ["1", "366"])
def test_days_grenzen_zijn_toegestaan(client, days: str) -> None:
    assert client.get(f"/admin/usage?days={days}").status_code == 200


def test_bedrijvenscherm_toont_ai_kosten(client) -> None:
    html = client.get("/").text
    assert 'id="usageCard"' in html and 'id="usageDays"' in html
    assert "(schatting op basis van tokens)" in html
    js = client.get("/static/usage.js")
    assert js.status_code == 200
    assert "/admin/usage?days=" in js.text
    assert ".innerHTML" not in js.text  # bedrijfsnamen alleen via textContent


def test_usage_is_alleen_voor_admins(client) -> None:
    from app.deps import current_role
    from app.main import app

    app.dependency_overrides[current_role] = lambda: "company"
    try:
        assert client.get("/admin/usage").status_code == 403
    finally:
        app.dependency_overrides.pop(current_role, None)
