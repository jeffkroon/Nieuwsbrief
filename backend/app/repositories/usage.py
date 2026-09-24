"""Leesqueries op mail.llm_usage voor het kostenoverzicht.

Alles wordt in SQL opgeteld (group by): we laden nooit alle losse regels.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.db.models import LlmUsage, Tenant
from app.services.usage_costs import TokenCounts


@dataclass(frozen=True)
class UsageGroup:
    """Opgeteld verbruik voor een bedrijf x model x doel (x wel/geen gesprek)."""

    tenant_id: uuid.UUID | None
    tenant_name: str | None
    tenant_slug: str | None
    model: str
    purpose: str
    in_conversation: bool
    calls: int
    tokens: TokenCounts


@dataclass(frozen=True)
class ConversationCounts:
    """Aantal unieke gesprekken per bedrijf, plus het totaal over alle bedrijven."""

    per_tenant: dict[uuid.UUID | None, int]
    total: int


def _since(days: int):
    return LlmUsage.created_at >= func.now() - func.make_interval(0, 0, 0, days)


def usage_groups(session: Session, days: int) -> list[UsageGroup]:
    """Verbruik van de laatste `days` dagen, opgeteld per bedrijf, model en doel."""
    in_conv = LlmUsage.conversation_id.is_not(None).label("in_conversation")
    stmt = (
        select(
            LlmUsage.tenant_id,
            Tenant.name,
            Tenant.slug,
            LlmUsage.model,
            LlmUsage.purpose,
            in_conv,
            func.count().label("calls"),
            func.coalesce(func.sum(LlmUsage.input_tokens), 0),
            func.coalesce(func.sum(LlmUsage.output_tokens), 0),
            func.coalesce(func.sum(LlmUsage.cache_creation_tokens), 0),
            func.coalesce(func.sum(LlmUsage.cache_read_tokens), 0),
        )
        .outerjoin(Tenant, Tenant.id == LlmUsage.tenant_id)
        .where(_since(days))
        .group_by(
            LlmUsage.tenant_id, Tenant.name, Tenant.slug,
            LlmUsage.model, LlmUsage.purpose, in_conv,
        )
    )
    return [_to_group(row) for row in session.execute(stmt)]


def _to_group(row) -> UsageGroup:
    tenant_id, name, slug, model, purpose, in_conv, calls, inp, out, cw, cr = row
    return UsageGroup(
        tenant_id=tenant_id,
        tenant_name=name,
        tenant_slug=slug,
        model=model,
        purpose=purpose,
        in_conversation=bool(in_conv),
        calls=int(calls),
        tokens=TokenCounts(int(inp), int(out), int(cw), int(cr)),
    )


def conversation_counts(session: Session, days: int) -> ConversationCounts:
    """Unieke gesprekken met Claude-verbruik in de periode, per bedrijf en totaal."""
    per_tenant_stmt = (
        select(LlmUsage.tenant_id, func.count(distinct(LlmUsage.conversation_id)))
        .where(_since(days))
        .group_by(LlmUsage.tenant_id)
    )
    total_stmt = select(func.count(distinct(LlmUsage.conversation_id))).where(_since(days))
    per_tenant = {tid: int(n) for tid, n in session.execute(per_tenant_stmt)}
    return ConversationCounts(per_tenant=per_tenant, total=int(session.scalar(total_stmt) or 0))
