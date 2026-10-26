"""Scripts uit klant-HTML of serverdata draaien nooit in het dashboard (XSS).

Een template of nieuwsbrief is HTML van buiten: een <script> erin mag geen
toegang krijgen tot de sessie van wie het voorbeeld bekijkt. Daarom staat elk
voorbeeld in een zandbak, krijgt de HTML-response zelf een zandbak-CSP, en
gaat serverdata via textContent de pagina in.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.repositories import newsletters as newsletters_repo
from app.repositories import tenants as tenants_repo
from app.routes.images import _safe_name
from app.routes.templates import _veilige_naam
from app.schemas import TenantCreate

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
ZANDBAK = 'sandbox="allow-popups allow-popups-to-escape-sandbox"'
BRAND = {
    "brand_name": "Veilig",
    "brand_email": "info@example.com",
    "brand_adres": "Straat 1",
    "brand_postcode_stad": "1000 AA Amsterdam",
    "brand_telefoon": "+31 20 000 0000",
    "brand_kvk": "12345678",
    "website_url": "https://www.example.com",
    "primary_color": "#FF7200",
    "logo_url": "https://example.com/logo.png",
    "dummy_image_url": "https://example.com/dummy.png",
}


def _tenant(session, slug: str = "veilig", config: dict | None = None):
    return tenants_repo.create_tenant(
        session, TenantCreate(slug=slug, name="Veilig", config=config or {})
    )


# --- voorbeeld-responses ------------------------------------------------------
def test_nieuwsbrief_html_krijgt_zandbak_csp(client, session) -> None:
    tenant = _tenant(session)
    nieuwsbrief = newsletters_repo.create_newsletter(
        session, tenant_id=tenant.id, subject="X", html="<p>hallo</p><script>alert(1)</script>"
    )
    resp = client.get(f"/tenants/{tenant.id}/newsletters/{nieuwsbrief.id}/html")
    assert resp.status_code == 200
    assert resp.headers["content-security-policy"] == "sandbox"


def test_template_preview_krijgt_zandbak_csp(client, session) -> None:
    tenant = _tenant(session, slug="veilig-preview", config=BRAND)
    resp = client.post(f"/tenants/{tenant.id}/templates/preview", json={})
    assert resp.status_code == 200
    assert resp.headers["content-security-policy"] == "sandbox"


# --- iframes en innerHTML -------------------------------------------------------
def test_elk_voorbeeld_iframe_staat_in_een_zandbak() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    iframes = re.findall(r"<iframe\b[^>]*>", html)
    assert len(iframes) >= 4
    for iframe in iframes:
        assert ZANDBAK in iframe, iframe


@pytest.mark.parametrize("bestand", sorted(p.name for p in STATIC.glob("*.js")))
def test_geen_ingevulde_waarden_in_innerhtml(bestand: str) -> None:
    """innerHTML alleen met vaste tekst; serverdata gaat via textContent."""
    code = (STATIC / bestand).read_text(encoding="utf-8")
    for template in re.findall(r"innerHTML\s*=\s*`([^`]*)`", code):
        assert "${" not in template, f"{bestand}: innerHTML met ingevulde waarde: {template[:80]}"
    for regel in code.splitlines():
        if re.search(r"innerHTML\s*=", regel):
            assert not re.search(r"innerHTML\s*=\s*['\"][^'\"]*['\"]\s*\+", regel), regel


# --- bestandsnamen bij uploads ------------------------------------------------
@pytest.mark.parametrize("veilig", [_safe_name, _veilige_naam])
@pytest.mark.parametrize(
    ("invoer", "verwacht"),
    [
        ("foto.jpg", "foto.jpg"),
        ("mijn foto.png", "mijn-foto.png"),
        ("../../etc/passwd", "passwd"),
        ("C:\\map\\bad.gif", "bad.gif"),
        ('"><img src=x onerror=alert(1)>.png', "---img-src-x-onerror-alert-1--.png"),
        ("café ü.jpg", "caf---.jpg"),
    ],
)
def test_bestandsnaam_houdt_alleen_veilige_tekens_over(veilig, invoer, verwacht) -> None:
    assert veilig(invoer) == verwacht


@pytest.mark.parametrize("veilig", [_safe_name, _veilige_naam])
@pytest.mark.parametrize("invoer", ["", None, "map/"])
def test_bestandsnaam_is_nooit_leeg(veilig, invoer) -> None:
    naam = veilig(invoer)
    assert naam
    assert re.fullmatch(r"[A-Za-z0-9._-]+", naam)
