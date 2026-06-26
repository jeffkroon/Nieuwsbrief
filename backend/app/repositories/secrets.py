"""Repository voor tenant-secrets. Versleutelt bij opslaan, ontsleutelt bij ophalen.

De plaintext-waarde verlaat deze module nooit richting opslag; alleen ciphertext
gaat de database in. value_encrypted wordt nooit teruggegeven aan de API-laag.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import TenantSecret
from app.services.crypto import SecretCipher


def set_tenant_secret(
    session: Session,
    cipher: SecretCipher,
    tenant_id: uuid.UUID,
    kind: str,
    plaintext: str,
) -> TenantSecret:
    """Upsert: maakt aan of werkt bij op (tenant_id, kind)."""
    encrypted = cipher.encrypt(plaintext)
    existing = session.scalar(
        select(TenantSecret).where(
            TenantSecret.tenant_id == tenant_id, TenantSecret.kind == kind
        )
    )
    if existing is not None:
        existing.value_encrypted = encrypted
        secret = existing
    else:
        secret = TenantSecret(tenant_id=tenant_id, kind=kind, value_encrypted=encrypted)
        session.add(secret)
    session.commit()
    session.refresh(secret)
    return secret


def get_tenant_secret(
    session: Session,
    cipher: SecretCipher,
    tenant_id: uuid.UUID,
    kind: str,
) -> str | None:
    """Geeft de ontsleutelde plaintext terug, of None als de secret ontbreekt."""
    secret = session.scalar(
        select(TenantSecret).where(
            TenantSecret.tenant_id == tenant_id, TenantSecret.kind == kind
        )
    )
    if secret is None:
        return None
    return cipher.decrypt(secret.value_encrypted)
