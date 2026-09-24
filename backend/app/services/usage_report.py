"""Bouwt het kostenoverzicht uit opgetelde llm_usage-groepen (pure functies).

Invoer komt uit repositories/usage.py; prijzen uit services/usage_costs.py.
Bedragen zijn een schatting op basis van tokens, geen factuur.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from decimal import Decimal
from functools import reduce
from itertools import groupby

from app.repositories.usage import ConversationCounts, UsageGroup
from app.schemas_usage import TenantUsage, UsageBreakdownRow, UsageReport, UsageSummary
from app.services.usage_costs import TokenCounts, estimate_cost

NO_TENANT_NAME = "zonder bedrijf"
DELETED_TENANT_NAME = "verwijderd bedrijf"
COST_DECIMALS = 6


def _usd(value: Decimal) -> float:
    return round(float(value), COST_DECIMALS)


def _group_cost(group: UsageGroup) -> Decimal | None:
    return estimate_cost(group.model, group.purpose, group.tokens)


def _sum_tokens(groups: Iterable[UsageGroup]) -> TokenCounts:
    return reduce(lambda acc, g: acc.plus(g.tokens), groups, TokenCounts())


def _known_cost(groups: Iterable[UsageGroup]) -> Decimal:
    costs = (_group_cost(g) for g in groups)
    return sum((c for c in costs if c is not None), Decimal(0))


def _unpriced_calls(groups: Iterable[UsageGroup]) -> int:
    return sum(g.calls for g in groups if _group_cost(g) is None)


def _token_fields(groups: Sequence[UsageGroup]) -> dict:
    tokens = _sum_tokens(groups)
    return {
        "calls": sum(g.calls for g in groups),
        "input_tokens": tokens.input,
        "output_tokens": tokens.output,
        "cache_creation_tokens": tokens.cache_creation,
        "cache_read_tokens": tokens.cache_read,
    }


def _average(groups: Sequence[UsageGroup], conversations: int) -> float | None:
    """Kosten van gesprek-calls gedeeld door het aantal gesprekken.

    Calls zonder gesprek (toolproof, prefill, fotobeschrijving) tellen niet mee,
    anders lijkt een gesprek duurder dan het is.
    """
    if conversations <= 0:
        return None
    in_conv = [g for g in groups if g.in_conversation]
    return _usd(_known_cost(in_conv) / conversations)


def summarize(groups: Sequence[UsageGroup], conversations: int) -> UsageSummary:
    return UsageSummary(
        **_token_fields(groups),
        cost_usd=_usd(_known_cost(groups)),
        unpriced_calls=_unpriced_calls(groups),
        conversations=conversations,
        avg_cost_per_conversation_usd=_average(groups, conversations),
    )


def _breakdown_row(model: str, purpose: str, groups: Sequence[UsageGroup]) -> UsageBreakdownRow:
    costs = [_group_cost(g) for g in groups]
    cost = None if any(c is None for c in costs) else _usd(sum(costs, Decimal(0)))
    return UsageBreakdownRow(model=model, purpose=purpose, cost_usd=cost, **_token_fields(groups))


def breakdown(groups: Sequence[UsageGroup]) -> list[UsageBreakdownRow]:
    """Een regel per model x doel (wel/geen gesprek samengevoegd), duurste eerst."""
    key = lambda g: (g.model, g.purpose)  # noqa: E731
    rows = [
        _breakdown_row(model, purpose, list(items))
        for (model, purpose), items in groupby(sorted(groups, key=key), key=key)
    ]
    return sorted(rows, key=lambda r: (-(r.cost_usd or 0), r.model, r.purpose))


def tenant_label(group: UsageGroup) -> str:
    if group.tenant_id is None:
        return NO_TENANT_NAME
    return group.tenant_name or DELETED_TENANT_NAME


def _tenant_usage(groups: Sequence[UsageGroup], conversations: int) -> TenantUsage:
    first = groups[0]
    return TenantUsage(
        **summarize(groups, conversations).model_dump(),
        tenant_id=first.tenant_id,
        name=tenant_label(first),
        slug=first.tenant_slug,
        breakdown=breakdown(groups),
    )


def _by_tenant(groups: Sequence[UsageGroup]) -> dict[uuid.UUID | None, list[UsageGroup]]:
    result: dict[uuid.UUID | None, list[UsageGroup]] = {}
    for group in groups:  # één doorloop; volgorde van eerste voorkomen blijft behouden
        result.setdefault(group.tenant_id, []).append(group)
    return result


def build_report(
    days: int, groups: Sequence[UsageGroup], counts: ConversationCounts
) -> UsageReport:
    tenants = [
        _tenant_usage(items, counts.per_tenant.get(tid, 0))
        for tid, items in _by_tenant(groups).items()
    ]
    return UsageReport(
        days=days,
        totals=summarize(groups, counts.total),
        tenants=sorted(tenants, key=lambda t: (-t.cost_usd, t.name)),
    )
