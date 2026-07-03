"""API-tests voor de tenant-routes (FastAPI TestClient + echte Postgres)."""

from __future__ import annotations

import uuid


def _payload(slug="voetbalreizenxl") -> dict:
    return {"slug": slug, "name": "VoetbalreizenXL", "config": {"primary_color": "#FF7200"}}


def test_health(client) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_tenant(client) -> None:
    resp = client.post("/tenants", json=_payload())
    assert resp.status_code == 201
    body = resp.json()
    assert body["slug"] == "voetbalreizenxl"
    assert body["status"] == "active"
    assert body["config"]["primary_color"] == "#FF7200"
    assert uuid.UUID(body["id"])


def test_create_duplicate_slug_conflict(client) -> None:
    client.post("/tenants", json=_payload())
    resp = client.post("/tenants", json=_payload())
    assert resp.status_code == 409


def test_list_tenants(client) -> None:
    client.post("/tenants", json=_payload("ajax"))
    client.post("/tenants", json=_payload("feyenoord"))
    resp = client.get("/tenants")
    assert resp.status_code == 200
    assert [t["slug"] for t in resp.json()] == ["ajax", "feyenoord"]


def test_get_tenant(client) -> None:
    created = client.post("/tenants", json=_payload()).json()
    resp = client.get(f"/tenants/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_get_missing_tenant_404(client) -> None:
    assert client.get(f"/tenants/{uuid.uuid4()}").status_code == 404


def test_update_tenant(client) -> None:
    created = client.post("/tenants", json=_payload()).json()
    resp = client.patch(f"/tenants/{created['id']}", json={"name": "Nieuw"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Nieuw"


def test_delete_tenant(client) -> None:
    created = client.post("/tenants", json=_payload()).json()
    assert client.delete(f"/tenants/{created['id']}").status_code == 204
    assert client.get(f"/tenants/{created['id']}").status_code == 404


def test_invalid_status_rejected(client) -> None:
    bad = _payload() | {"status": "onzin"}
    assert client.post("/tenants", json=bad).status_code == 422


def test_set_secret(client) -> None:
    created = client.post("/tenants", json=_payload()).json()
    resp = client.put(
        f"/tenants/{created['id']}/secrets",
        json={"kind": "brevo_api_key", "value": "xkeysib-geheim"},
    )
    assert resp.status_code == 204


def test_set_secret_missing_tenant_404(client) -> None:
    resp = client.put(
        f"/tenants/{uuid.uuid4()}/secrets",
        json={"kind": "brevo_api_key", "value": "x"},
    )
    assert resp.status_code == 404


def test_company_role_cannot_manage_tenants(client) -> None:
    # Bedrijven beheren (aanmaken/wijzigen/verwijderen/secrets) is alleen voor Dunion-admin.
    import uuid as _uuid

    from app.deps import current_role
    from app.main import app

    created = client.post("/tenants", json=_payload("gated")).json()  # als admin
    app.dependency_overrides[current_role] = lambda: "company"
    try:
        assert client.post("/tenants", json=_payload("ander")).status_code == 403
        assert client.patch(f"/tenants/{created['id']}", json={"name": "X"}).status_code == 403
        assert client.delete(f"/tenants/{created['id']}").status_code == 403
        assert client.put(
            f"/tenants/{created['id']}/secrets", json={"kind": "brevo_api_key", "value": "x"}
        ).status_code == 403
        # Lezen mag wel (nodig voor de klant-dropdown).
        assert client.get("/tenants").status_code == 200
    finally:
        app.dependency_overrides.pop(current_role, None)


def test_prefill_endpoint(client, session, monkeypatch) -> None:
    from app.deps import get_anthropic_client
    from app.main import app
    from app.services import company_prefill
    from tests.test_company_prefill import HOME_HTML, LLM_PAYLOAD, FakeLLM, _fake_fetch

    monkeypatch.setattr(
        company_prefill.extraction, "fetch_page",
        _fake_fetch({"https://shop.nl": (200, HOME_HTML)}),
    )
    app.dependency_overrides[get_anthropic_client] = lambda: FakeLLM(LLM_PAYLOAD)
    try:
        resp = client.post("/tenants/prefill", json={"name": "Shop NL", "website_url": "shop.nl"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["config"]["brand_email"] == "hallo@shop.nl"
        assert body["config"]["website_url"] == "https://shop.nl"  # https aangevuld
        assert body["content_types"][0]["button_text"] == "SHOP NU"
    finally:
        app.dependency_overrides.pop(get_anthropic_client, None)


def test_prefill_is_admin_only(client) -> None:
    from app.deps import current_role
    from app.main import app

    app.dependency_overrides[current_role] = lambda: "company"
    try:
        resp = client.post("/tenants/prefill", json={"name": "X", "website_url": "https://x.nl"})
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(current_role, None)


def test_esp_lists_endpoint(client, monkeypatch) -> None:
    from app.routes import tenants as tenants_routes

    class FakeKlaviyo:
        def __init__(self, key: str) -> None:
            assert key == "pk_plakwerk"

        def get_lists(self):
            return [{"id": "L1", "name": "Nieuwsbrief"}]

    monkeypatch.setattr(tenants_routes, "KlaviyoClient", FakeKlaviyo)
    resp = client.post("/tenants/esp-lists", json={"esp": "klaviyo", "api_key": "pk_plakwerk"})
    assert resp.status_code == 200
    assert resp.json()["lists"] == [{"id": "L1", "name": "Nieuwsbrief"}]


def test_esp_lists_requires_key(client) -> None:
    resp = client.post("/tenants/esp-lists", json={"esp": "klaviyo"})
    assert resp.status_code == 400
    assert "API-key" in resp.json()["detail"]


def test_esp_lists_admin_only(client) -> None:
    from app.deps import current_role
    from app.main import app

    app.dependency_overrides[current_role] = lambda: "company"
    try:
        resp = client.post("/tenants/esp-lists", json={"esp": "brevo", "api_key": "x"})
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(current_role, None)
