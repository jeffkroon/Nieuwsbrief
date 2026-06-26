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
