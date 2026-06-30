"""Integratie-tests voor de templates-repository (echte Postgres via fixtures)."""

from __future__ import annotations

from app.repositories import templates as repo
from app.repositories import tenants as tenants_repo
from app.schemas import TenantCreate

MARKER_HTML = "<html><!-- ##BANNERS## --></html>"


def _tenant(session):
    return tenants_repo.create_tenant(session, TenantCreate(slug="ftg", name="FTG"))


def test_first_template_is_default(session) -> None:
    t = _tenant(session)
    tpl = repo.create_template(session, tenant_id=t.id, name="Basis", html=MARKER_HTML)
    assert tpl.is_default is True


def test_second_template_not_default_unless_asked(session) -> None:
    t = _tenant(session)
    repo.create_template(session, tenant_id=t.id, name="A", html=MARKER_HTML)
    b = repo.create_template(session, tenant_id=t.id, name="B", html=MARKER_HTML)
    assert b.is_default is False


def test_set_default_is_exclusive(session) -> None:
    t = _tenant(session)
    a = repo.create_template(session, tenant_id=t.id, name="A", html=MARKER_HTML)
    b = repo.create_template(session, tenant_id=t.id, name="B", html=MARKER_HTML)
    repo.set_default(session, t.id, b.id)
    templates = {x.name: x.is_default for x in repo.list_templates(session, t.id)}
    assert templates == {"A": False, "B": True}
    assert repo.get_default_template(session, t.id).id == b.id


def test_styles_are_sanitized_on_write(session) -> None:
    t = _tenant(session)
    tpl = repo.create_template(
        session,
        tenant_id=t.id,
        name="A",
        html=MARKER_HTML,
        styles={"button_bg": "#abcdef", "font_family": "evil", "x": "1"},
    )
    assert tpl.styles == {"button_bg": "#abcdef"}  # font/extra weggegooid


def test_update_styles_only(session) -> None:
    t = _tenant(session)
    tpl = repo.create_template(session, tenant_id=t.id, name="A", html=MARKER_HTML)
    updated = repo.update_styles(session, tpl.id, {"text_color": "#111111"})
    assert updated.styles == {"text_color": "#111111"}
    assert updated.html == MARKER_HTML  # layout ongemoeid


def test_delete_promotes_next_default(session) -> None:
    t = _tenant(session)
    a = repo.create_template(session, tenant_id=t.id, name="A", html=MARKER_HTML)
    b = repo.create_template(session, tenant_id=t.id, name="B", html=MARKER_HTML)
    repo.delete_template(session, a.id)  # a was default
    remaining = repo.list_templates(session, t.id)
    assert len(remaining) == 1
    assert remaining[0].id == b.id
    assert remaining[0].is_default is True
