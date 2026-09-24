"""Response-schema's voor het kostenoverzicht (GET /admin/usage)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel


class UsageTokens(BaseModel):
    calls: int
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int


class UsageBreakdownRow(UsageTokens):
    """Een model x doel binnen een bedrijf. cost_usd None = onbekend model."""

    model: str
    purpose: str
    cost_usd: float | None


class UsageSummary(UsageTokens):
    """Opgeteld verbruik. cost_usd telt alleen calls met een bekende prijs;
    unpriced_calls zegt hoeveel calls daarbuiten vielen (onbekend model)."""

    cost_usd: float
    unpriced_calls: int
    conversations: int
    avg_cost_per_conversation_usd: float | None


class TenantUsage(UsageSummary):
    tenant_id: uuid.UUID | None
    name: str
    slug: str | None
    breakdown: list[UsageBreakdownRow]


class UsageReport(BaseModel):
    days: int
    currency: str = "USD"
    estimate: bool = True
    totals: UsageSummary
    tenants: list[TenantUsage]
