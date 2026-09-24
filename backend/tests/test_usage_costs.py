"""Unit-tests voor de kostenschatting en de rapportopbouw (geen database)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.repositories.usage import ConversationCounts, UsageGroup
from app.services.usage_costs import (
    ONE_HOUR_CACHE_PURPOSES,
    TokenCounts,
    estimate_cost,
    price_for_model,
)
from app.services.usage_report import (
    DELETED_TENANT_NAME,
    NO_TENANT_NAME,
    breakdown,
    build_report,
    summarize,
)

MILJOEN = 1_000_000


@pytest.mark.parametrize(
    ("model", "verwacht"),
    [
        ("claude-sonnet-5", Decimal("2")),
        ("claude-sonnet-5-20260901", Decimal("2")),
        ("claude-haiku-4-5", Decimal("1")),
        ("claude-haiku-4-5-20251001", Decimal("1")),
        ("claude-opus-5-5", Decimal("4")),
        ("claude-fable-5-1", Decimal("10")),
        ("CLAUDE-SONNET-5", Decimal("2")),
    ],
)
def test_bekende_modellen_hebben_een_inputprijs(model: str, verwacht: Decimal) -> None:
    assert price_for_model(model).input == verwacht


@pytest.mark.parametrize(
    "model", ["claude-sonnet-4-6", "claude-sonnet-5-5", "onbekend", "", None, "gpt-4o"]
)
def test_onbekend_model_geeft_none(model) -> None:
    assert price_for_model(model) is None
    assert estimate_cost(model, "chat", TokenCounts(input=MILJOEN)) is None


def test_elk_tokensoort_telt_mee_tegen_het_juiste_tarief() -> None:
    assert estimate_cost("claude-sonnet-5", "toolproof", TokenCounts(input=MILJOEN)) == 2
    assert estimate_cost("claude-sonnet-5", "toolproof", TokenCounts(output=MILJOEN)) == 10
    assert estimate_cost("claude-sonnet-5", "toolproof", TokenCounts(cache_read=MILJOEN)) == Decimal(
        "0.20"
    )


def test_chat_schrijft_1_uurs_cache_andere_doelen_5_minuten() -> None:
    assert "chat" in ONE_HOUR_CACHE_PURPOSES
    tokens = TokenCounts(cache_creation=MILJOEN)
    assert estimate_cost("claude-sonnet-5", "chat", tokens) == 4
    assert estimate_cost("claude-sonnet-5", "prefill", tokens) == Decimal("2.50")
    assert estimate_cost("claude-haiku-4-5", "chat", tokens) == 2
    assert estimate_cost("claude-haiku-4-5", "fotobeschrijving", tokens) == Decimal("1.25")


def test_gemengde_call_optellen() -> None:
    tokens = TokenCounts(input=1200, output=340, cache_creation=800, cache_read=7600)
    # 1200*2 + 340*10 + 800*4 + 7600*0.2 = 2400 + 3400 + 3200 + 1520 = 10520
    assert estimate_cost("claude-sonnet-5", "chat", tokens) == Decimal("0.01052")


def test_tokencounts_plus_is_immutabel() -> None:
    a = TokenCounts(1, 2, 3, 4)
    b = a.plus(TokenCounts(10, 20, 30, 40))
    assert a == TokenCounts(1, 2, 3, 4)
    assert b == TokenCounts(11, 22, 33, 44)


# -- rapportopbouw ------------------------------------------------------------------

T1 = uuid.uuid4()


def _group(**kw) -> UsageGroup:
    base = dict(
        tenant_id=T1, tenant_name="Bakkerij", tenant_slug="bakkerij",
        model="claude-sonnet-5", purpose="chat", in_conversation=True,
        calls=1, tokens=TokenCounts(input=MILJOEN),
    )
    return UsageGroup(**{**base, **kw})


def test_summary_telt_onbekende_modellen_apart() -> None:
    groups = [_group(calls=3), _group(model="mysterie", calls=2)]
    summary = summarize(groups, conversations=2)
    assert summary.calls == 5
    assert summary.cost_usd == 2.0
    assert summary.unpriced_calls == 2
    assert summary.avg_cost_per_conversation_usd == 1.0


def test_gemiddelde_negeert_calls_buiten_gesprekken() -> None:
    groups = [_group(), _group(purpose="toolproof", in_conversation=False)]
    summary = summarize(groups, conversations=1)
    assert summary.cost_usd == 4.0
    assert summary.avg_cost_per_conversation_usd == 2.0


def test_geen_gesprekken_geeft_geen_gemiddelde() -> None:
    assert summarize([_group(in_conversation=False)], 0).avg_cost_per_conversation_usd is None


def test_breakdown_voegt_gesprek_en_los_samen_en_markeert_onbekend() -> None:
    rows = breakdown([
        _group(calls=1), _group(calls=2, in_conversation=False), _group(model="x", calls=4),
    ])
    assert [(r.model, r.purpose, r.calls, r.cost_usd) for r in rows] == [
        ("claude-sonnet-5", "chat", 3, 4.0),
        ("x", "chat", 4, None),
    ]


def test_build_report_labels_en_sortering() -> None:
    weg = uuid.uuid4()
    groups = [
        _group(),
        _group(tenant_id=None, tenant_name=None, tenant_slug=None, model="claude-opus-5-5"),
        _group(tenant_id=weg, tenant_name=None, tenant_slug=None, calls=1,
               tokens=TokenCounts(input=10)),
    ]
    counts = ConversationCounts(per_tenant={T1: 1, None: 2}, total=3)
    report = build_report(30, groups, counts)
    assert [t.name for t in report.tenants] == ["zonder bedrijf", "Bakkerij", DELETED_TENANT_NAME]
    assert report.tenants[0].name == NO_TENANT_NAME
    assert report.tenants[0].conversations == 2
    assert report.tenants[2].conversations == 0
    assert report.totals.conversations == 3
    assert report.totals.cost_usd == pytest.approx(6.00002)
    assert report.estimate is True and report.currency == "USD"


def test_leeg_rapport() -> None:
    report = build_report(7, [], ConversationCounts(per_tenant={}, total=0))
    assert report.tenants == []
    assert report.totals.calls == 0 and report.totals.cost_usd == 0
    assert report.totals.avg_cost_per_conversation_usd is None
