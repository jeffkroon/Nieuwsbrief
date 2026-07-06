"""Routes voor het beheren van foto's per bedrijf (upload los/bulk, lijst, categorieën)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.deps import get_session, get_storage, require_tenant_access
from app.repositories import images as repo
from app.repositories import tenants as tenants_repo
from app.schemas import ImageCategoriesRead, ImageCategoriesSet, ImageRead
from app.services.storage import ImageStorage, StorageError

router = APIRouter(
    prefix="/tenants/{tenant_id}", tags=["images"],
    # Klant-sessies kunnen alleen bij hun eigen bedrijf (admins/team bij alles).
    dependencies=[Depends(require_tenant_access)],
)


def _require_tenant(session: Session, tenant_id: uuid.UUID):
    tenant = tenants_repo.get_tenant(session, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="tenant niet gevonden")
    return tenant


def _safe_name(name: str) -> str:
    base = (name or "foto").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return base.replace(" ", "-") or "foto"


@router.get("/image-categories", response_model=ImageCategoriesRead)
def get_categories(tenant_id: uuid.UUID, session: Session = Depends(get_session)) -> ImageCategoriesRead:
    tenant = _require_tenant(session, tenant_id)
    return ImageCategoriesRead(categories=repo.tenant_categories(tenant))


@router.put("/image-categories", response_model=ImageCategoriesRead)
def set_categories(
    tenant_id: uuid.UUID,
    body: ImageCategoriesSet,
    session: Session = Depends(get_session),
) -> ImageCategoriesRead:
    tenant = _require_tenant(session, tenant_id)
    # 'banner' is altijd aanwezig; bewaar de overige (ontdubbeld, schoon).
    custom: list[str] = []
    for c in body.categories:
        c = c.strip().lower()
        if c and c != repo.BANNER_CATEGORY and c not in custom:
            custom.append(c)
    new_config = {**tenant.config, "image_categories": custom}
    tenants_repo.update_tenant(session, tenant_id, _config_update(new_config))
    return ImageCategoriesRead(categories=[repo.BANNER_CATEGORY, *custom])


@router.get("/images", response_model=list[ImageRead])
def list_images(
    tenant_id: uuid.UUID,
    category: str | None = None,
    session: Session = Depends(get_session),
) -> list[ImageRead]:
    _require_tenant(session, tenant_id)
    return repo.list_images(session, tenant_id, category)


@router.post("/images", response_model=list[ImageRead], status_code=status.HTTP_201_CREATED)
def upload_images(
    tenant_id: uuid.UUID,
    category: str = Form(...),
    files: list[UploadFile] = File(...),
    descriptions: list[str] | None = Form(None),
    session: Session = Depends(get_session),
    storage: ImageStorage = Depends(get_storage),
) -> list[ImageRead]:
    tenant = _require_tenant(session, tenant_id)
    category = category.strip().lower()
    if category not in repo.tenant_categories(tenant):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"onbekende categorie '{category}'. Beschikbaar: {repo.tenant_categories(tenant)}",
        )

    # Bucket bestaat (idempotent).
    try:
        storage.ensure_bucket()  # type: ignore[attr-defined]
    except (StorageError, AttributeError):
        pass

    created = []
    for i, upload in enumerate(files):
        name = _safe_name(upload.filename)
        path = f"{tenant_id}/{category}/{uuid.uuid4().hex}-{name}"
        content = upload.file.read()
        try:
            stored = storage.upload(path, content, upload.content_type or "application/octet-stream")
        except StorageError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=f"upload mislukt: {exc}") from exc
        description = descriptions[i] if descriptions and i < len(descriptions) else None
        created.append(
            repo.create_image(
                session,
                tenant_id=tenant_id,
                category=category,
                filename=name,
                description=description,
                storage_path=stored.storage_path,
                url=stored.url,
            )
        )
    return created


@router.delete("/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_image(
    tenant_id: uuid.UUID,
    image_id: uuid.UUID,
    session: Session = Depends(get_session),
    storage: ImageStorage = Depends(get_storage),
) -> Response:
    image = repo.get_image(session, image_id)
    if image is None or image.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="foto niet gevonden")
    try:
        storage.delete(image.storage_path)
    except StorageError:
        pass  # DB-rij hoe dan ook opruimen
    repo.delete_image(session, image_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _config_update(new_config: dict):
    from app.schemas import TenantUpdate

    return TenantUpdate(config=new_config)
