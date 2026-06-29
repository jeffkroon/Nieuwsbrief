"""Tests voor de Supabase Storage-client (httpx MockTransport, geen echte calls)."""

from __future__ import annotations

import httpx
import pytest

from app.services.storage import StorageError, SupabaseStorage

BASE = "https://proj.supabase.co"


def _storage(handler) -> SupabaseStorage:
    return SupabaseStorage(BASE, "service-key", bucket="imgs", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_upload_returns_public_url() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["ctype"] = request.headers.get("content-type")
        return httpx.Response(200, json={"Key": "imgs/x"})

    stored = _storage(handler).upload("tenant/club/arsenal.jpg", b"bytes", "image/jpeg")
    assert stored.url == f"{BASE}/storage/v1/object/public/imgs/tenant/club/arsenal.jpg"
    assert captured["url"].endswith("/storage/v1/object/imgs/tenant/club/arsenal.jpg")
    assert captured["auth"] == "Bearer service-key"
    assert captured["ctype"] == "image/jpeg"


def test_upload_error_raises() -> None:
    with pytest.raises(StorageError, match="upload mislukt"):
        _storage(lambda r: httpx.Response(400, text="bad")).upload("p", b"x", "image/png")


def test_ensure_bucket_tolerates_existing() -> None:
    # 409 (bestaat al) mag geen fout geven.
    _storage(lambda r: httpx.Response(409, text="exists")).ensure_bucket()


def test_delete_tolerates_404() -> None:
    _storage(lambda r: httpx.Response(404, text="gone")).delete("p")


def test_requires_credentials() -> None:
    with pytest.raises(StorageError):
        SupabaseStorage("", "")
