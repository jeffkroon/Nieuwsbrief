"""API-tests voor het beeldbeheer per bedrijf (upload, lijst, categorieën)."""

from __future__ import annotations

import uuid

import pytest

from app.deps import get_storage
from app.main import app
from app.repositories import tenants as tenants_repo
from app.schemas import TenantCreate
from app.services.storage import StoredImage


class FakeStorage:
    def __init__(self) -> None:
        self.uploaded: list[tuple[str, str]] = []
        self.deleted: list[str] = []

    def ensure_bucket(self) -> None:
        pass

    def upload(self, path: str, content: bytes, content_type: str) -> StoredImage:
        self.uploaded.append((path, content_type))
        return StoredImage(storage_path=path, url=f"https://cdn.fake/{path}")

    def delete(self, path: str) -> None:
        self.deleted.append(path)


@pytest.fixture
def fake_storage():
    storage = FakeStorage()
    app.dependency_overrides[get_storage] = lambda: storage
    yield storage
    app.dependency_overrides.pop(get_storage, None)


def _tenant(session):
    return tenants_repo.create_tenant(session, TenantCreate(slug="ftg", name="FTG"))


def test_categories_banner_always_present(client, session) -> None:
    t = _tenant(session)
    # Standaard: alleen banner.
    assert client.get(f"/tenants/{t.id}/image-categories").json()["categories"] == ["banner"]
    # Instellen: banner blijft vooraan, dubbele banner wordt ontdubbeld.
    resp = client.put(
        f"/tenants/{t.id}/image-categories", json={"categories": ["club", "banner", "wedstrijd"]}
    )
    assert resp.json()["categories"] == ["banner", "club", "wedstrijd"]


def test_upload_single_and_list(client, session, fake_storage) -> None:
    t = _tenant(session)
    client.put(f"/tenants/{t.id}/image-categories", json={"categories": ["club"]})
    resp = client.post(
        f"/tenants/{t.id}/images",
        data={"category": "club"},
        files=[("files", ("arsenal.jpg", b"imgdata", "image/jpeg"))],
    )
    assert resp.status_code == 201
    body = resp.json()
    assert len(body) == 1
    assert body[0]["filename"] == "arsenal.jpg"
    assert body[0]["url"].startswith("https://cdn.fake/")
    assert fake_storage.uploaded  # echt naar storage gestuurd
    # Lijst per categorie.
    listed = client.get(f"/tenants/{t.id}/images", params={"category": "club"}).json()
    assert len(listed) == 1 and listed[0]["filename"] == "arsenal.jpg"


def test_upload_bulk(client, session, fake_storage) -> None:
    t = _tenant(session)
    client.put(f"/tenants/{t.id}/image-categories", json={"categories": ["club"]})
    resp = client.post(
        f"/tenants/{t.id}/images",
        data={"category": "club"},
        files=[
            ("files", ("arsenal.jpg", b"a", "image/jpeg")),
            ("files", ("chelsea.jpg", b"b", "image/jpeg")),
        ],
    )
    assert resp.status_code == 201
    assert {im["filename"] for im in resp.json()} == {"arsenal.jpg", "chelsea.jpg"}


def test_upload_unknown_category_rejected(client, session, fake_storage) -> None:
    t = _tenant(session)
    resp = client.post(
        f"/tenants/{t.id}/images",
        data={"category": "bestaatniet"},
        files=[("files", ("x.jpg", b"a", "image/jpeg"))],
    )
    assert resp.status_code == 400


def test_delete_image(client, session, fake_storage) -> None:
    t = _tenant(session)
    client.put(f"/tenants/{t.id}/image-categories", json={"categories": ["club"]})
    created = client.post(
        f"/tenants/{t.id}/images",
        data={"category": "club"},
        files=[("files", ("arsenal.jpg", b"a", "image/jpeg"))],
    ).json()[0]
    resp = client.delete(f"/tenants/{t.id}/images/{created['id']}")
    assert resp.status_code == 204
    assert fake_storage.deleted  # ook uit storage verwijderd
    assert client.get(f"/tenants/{t.id}/images").json() == []


def test_upload_missing_tenant_404(client, fake_storage) -> None:
    resp = client.post(
        f"/tenants/{uuid.uuid4()}/images",
        data={"category": "club"},
        files=[("files", ("x.jpg", b"a", "image/jpeg"))],
    )
    assert resp.status_code == 404
