"""Beheer-routes voor Dunion-admins: het kostenoverzicht van Claude-gebruik."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.deps import get_session, require_admin
from app.repositories import usage as usage_repo
from app.schemas_usage import UsageReport
from app.services.usage_report import build_report

MIN_DAYS = 1
MAX_DAYS = 366
DEFAULT_DAYS = 30

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/usage", response_model=UsageReport)
def usage_overview(
    days: int = Query(DEFAULT_DAYS, ge=MIN_DAYS, le=MAX_DAYS),
    session: Session = Depends(get_session),
) -> UsageReport:
    """Geschatte AI-kosten per bedrijf, model en doel over de laatste `days` dagen."""
    groups = usage_repo.usage_groups(session, days)
    counts = usage_repo.conversation_counts(session, days)
    return build_report(days, groups, counts)
