"""Repository voor de versiegeschiedenis van templates.

Er wordt een versie weggeschreven bij elke wijziging van de LAYOUT (aanmaken,
bijwerken, tool-proof, terugzetten). Een losse stijlwijziging (kleur, lettertype)
maakt geen versie: die is met een klik terug te draaien en zou de lijst vervuilen.

De lijst is per template begrensd; oudere versies vallen af zodat een template die
vaak wordt bijgewerkt de tabel niet laat volgroeien.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Template, TemplateVersion

# Waar een versie vandaan komt; alleen deze waarden komen in de UI voor.
SOURCES = ("upload", "toolproof", "handmatig", "terugzetten")
MAX_VERSIONS_PER_TEMPLATE = 50


def record_version(
    session: Session,
    template: Template,
    *,
    source: str = "handmatig",
    actor: str | None = None,
    commit: bool = True,
) -> TemplateVersion:
    """Leg de huidige inhoud van `template` vast als versie."""
    version = TemplateVersion(
        template_id=template.id,
        tenant_id=template.tenant_id,
        name=template.name,
        html=template.html,
        styles=dict(template.styles or {}),
        source=source if source in SOURCES else "handmatig",
        actor=actor,
    )
    session.add(version)
    session.flush()
    _prune(session, template.id)
    if commit:
        session.commit()
    return version


def list_versions(
    session: Session, template_id: uuid.UUID, *, limit: int = 25
) -> list[TemplateVersion]:
    query = (
        select(TemplateVersion)
        .where(TemplateVersion.template_id == template_id)
        .order_by(TemplateVersion.created_at.desc(), TemplateVersion.id.desc())
        .limit(limit)
    )
    return list(session.scalars(query))


def get_version(session: Session, version_id: uuid.UUID) -> TemplateVersion | None:
    return session.get(TemplateVersion, version_id)


def _prune(session: Session, template_id: uuid.UUID) -> None:
    """Houd alleen de nieuwste versies; de rest valt af."""
    keep = session.scalars(
        select(TemplateVersion.id)
        .where(TemplateVersion.template_id == template_id)
        .order_by(TemplateVersion.created_at.desc(), TemplateVersion.id.desc())
        .limit(MAX_VERSIONS_PER_TEMPLATE)
    ).all()
    if len(keep) < MAX_VERSIONS_PER_TEMPLATE:
        return
    session.execute(
        delete(TemplateVersion)
        .where(TemplateVersion.template_id == template_id)
        .where(TemplateVersion.id.notin_(keep))
    )
