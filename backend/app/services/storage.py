"""Opslag van geüploade foto's in Supabase Storage.

Uploadt naar een publieke bucket en geeft de publieke CDN-URL terug (e-mailfoto's
moeten publiek bereikbaar zijn). De client is injecteerbaar zodat tests een fake
kunnen meegeven.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx


class StorageError(Exception):
    pass


@dataclass(frozen=True)
class StoredImage:
    storage_path: str
    url: str


class ImageStorage(Protocol):
    def upload(self, path: str, content: bytes, content_type: str) -> StoredImage: ...
    def delete(self, path: str) -> None: ...


class SupabaseStorage:
    def __init__(
        self,
        base_url: str,
        service_key: str,
        *,
        bucket: str = "tenant-images",
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not base_url or not service_key:
            raise StorageError("SUPABASE_URL en SUPABASE_SERVICE_ROLE_KEY zijn vereist voor opslag")
        self._base = base_url.rstrip("/")
        self._key = service_key
        self._bucket = bucket
        self._client = client
        self._timeout = timeout

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._key}", "apikey": self._key}

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        headers = {**self._headers, **kwargs.pop("headers", {})}
        if self._client is not None:
            return self._client.request(method, url, headers=headers, **kwargs)
        with httpx.Client(timeout=self._timeout) as client:
            return client.request(method, url, headers=headers, **kwargs)

    def ensure_bucket(self) -> None:
        """Maak de publieke bucket aan (idempotent: bestaat-al wordt genegeerd)."""
        resp = self._request(
            "POST",
            f"{self._base}/storage/v1/bucket",
            json={"id": self._bucket, "name": self._bucket, "public": True},
        )
        if resp.status_code not in (200, 201, 409):
            raise StorageError(f"kon bucket niet aanmaken: HTTP {resp.status_code} {resp.text}")

    def upload(self, path: str, content: bytes, content_type: str) -> StoredImage:
        resp = self._request(
            "POST",
            f"{self._base}/storage/v1/object/{self._bucket}/{path}",
            content=content,
            headers={"Content-Type": content_type, "x-upsert": "true"},
        )
        if resp.status_code not in (200, 201):
            raise StorageError(f"upload mislukt: HTTP {resp.status_code} {resp.text}")
        url = f"{self._base}/storage/v1/object/public/{self._bucket}/{path}"
        return StoredImage(storage_path=path, url=url)

    def delete(self, path: str) -> None:
        resp = self._request("DELETE", f"{self._base}/storage/v1/object/{self._bucket}/{path}")
        if resp.status_code not in (200, 204, 404):
            raise StorageError(f"verwijderen mislukt: HTTP {resp.status_code} {resp.text}")
