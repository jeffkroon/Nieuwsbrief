"""CRUD-routes voor tenants en het zetten van tenant-secrets."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.deps import get_cipher, get_session
from app.repositories import secrets as secrets_repo
from app.repositories import tenants as repo
from app.schemas import TenantCreate, TenantRead, TenantSecretSet, TenantUpdate
from app.services.crypto import SecretCipher

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.post("", response_model=TenantRead, status_code=status.HTTP_201_CREATED)
def create_tenant(data: TenantCreate, session: Session = Depends(get_session)) -> TenantRead:
    if repo.get_tenant_by_slug(session, data.slug) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=f"tenant met slug '{data.slug}' bestaat al"
        )
    return repo.create_tenant(session, data)


@router.get("", response_model=list[TenantRead])
def list_tenants(session: Session = Depends(get_session)) -> list[TenantRead]:
    return repo.list_tenants(session)


@router.get("/{tenant_id}", response_model=TenantRead)
def get_tenant(tenant_id: uuid.UUID, session: Session = Depends(get_session)) -> TenantRead:
    tenant = repo.get_tenant(session, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="tenant niet gevonden")
    return tenant


@router.patch("/{tenant_id}", response_model=TenantRead)
def update_tenant(
    tenant_id: uuid.UUID, data: TenantUpdate, session: Session = Depends(get_session)
) -> TenantRead:
    tenant = repo.update_tenant(session, tenant_id, data)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="tenant niet gevonden")
    return tenant


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tenant(tenant_id: uuid.UUID, session: Session = Depends(get_session)) -> Response:
    if not repo.delete_tenant(session, tenant_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="tenant niet gevonden")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{tenant_id}/secrets", status_code=status.HTTP_204_NO_CONTENT)
def set_tenant_secret(
    tenant_id: uuid.UUID,
    body: TenantSecretSet,
    session: Session = Depends(get_session),
    cipher: SecretCipher = Depends(get_cipher),
) -> Response:
    if repo.get_tenant(session, tenant_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="tenant niet gevonden")
    secrets_repo.set_tenant_secret(session, cipher, tenant_id, body.kind, body.value)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
