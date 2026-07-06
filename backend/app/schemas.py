"""Pydantic v2 schema's voor de API-laag van het nieuwsbrief-product.

Gescheiden van de ORM-modellen (backend/app/db/models.py): deze types valideren
input aan de systeemgrens en vormen de response-contracten. `from_attributes`
maakt directe serialisatie vanuit ORM-objecten mogelijk.

Secrets (Brevo API-keys) worden nooit teruggelezen in een response.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TenantStatus = Literal["active", "paused", "archived"]
Channel = Literal["slack", "web", "api"]
ConversationStatus = Literal["active", "completed", "abandoned"]
MessageRole = Literal["user", "assistant", "system", "tool"]
NewsletterStatus = Literal["draft", "generating", "ready", "approved", "sent", "failed"]
SecretKind = Literal["brevo_api_key", "klaviyo_api_key"]


class _ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Tenant ---------------------------------------------------------------
class TenantCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1)
    status: TenantStatus = "active"
    brevo_list_id: int | None = None
    config: dict = Field(default_factory=dict)
    settings: dict = Field(default_factory=dict)


class TenantUpdate(BaseModel):
    name: str | None = None
    status: TenantStatus | None = None
    brevo_list_id: int | None = None
    config: dict | None = None
    settings: dict | None = None


class TenantRead(_ORMModel):
    id: uuid.UUID
    slug: str
    name: str
    status: TenantStatus
    brevo_list_id: int | None
    config: dict
    settings: dict
    created_at: datetime
    updated_at: datetime


class TenantPasswordSet(BaseModel):
    """Klant-login-wachtwoord voor een bedrijf (alleen schrijven, nooit teruggeven)."""

    password: str = Field(min_length=8, max_length=128)


class TenantPrefillRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    website_url: str = Field(min_length=4)


class TenantPrefillResult(BaseModel):
    """Voorstel voor een nieuw bedrijf, van de website gehaald (admin controleert)."""

    config: dict
    content_types: list[dict]
    notes: list[str]


class EspListsRequest(BaseModel):
    """Lijsten ophalen bij het verzendplatform (voor de lijst-kiezer bij onboarding).

    Key komt uit het formulier (net geplakt) of, bij een bestaand bedrijf, uit de
    versleutelde opslag via tenant_id.
    """

    esp: Literal["brevo", "klaviyo"]
    api_key: str | None = None
    tenant_id: uuid.UUID | None = None


class EspListsResult(BaseModel):
    lists: list[dict]


# --- Tenant secret (alleen schrijven, nooit teruglezen) -------------------
class TenantSecretSet(BaseModel):
    kind: SecretKind
    value: str = Field(min_length=1)  # plaintext; backend versleutelt voor opslag


# --- Conversation ---------------------------------------------------------
class ConversationCreate(BaseModel):
    tenant_id: uuid.UUID
    channel: Channel
    external_ref: str | None = None


class ConversationRead(_ORMModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    channel: Channel
    external_ref: str | None
    status: ConversationStatus
    created_at: datetime
    updated_at: datetime


# --- Images ----------------------------------------------------------------
class ImageRead(_ORMModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    category: str
    filename: str
    description: str | None
    url: str
    created_at: datetime


class ImageCategoriesSet(BaseModel):
    categories: list[str] = Field(default_factory=list)


class ImageCategoriesRead(BaseModel):
    categories: list[str]


# --- Templates -------------------------------------------------------------
# De HTML (layout) wordt door Dunion-admins beheerd; `styles` (kleuren/lettertype)
# mag een bedrijf zelf aanpassen via TemplateStyleUpdate.
class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    html: str = Field(min_length=1)
    styles: dict = Field(default_factory=dict)
    is_default: bool = False


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    html: str | None = None
    styles: dict | None = None


class TemplateStyleUpdate(BaseModel):
    styles: dict = Field(default_factory=dict)


class TemplateRead(_ORMModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    html: str
    styles: dict
    is_default: bool
    created_at: datetime
    updated_at: datetime


class TemplateSummary(_ORMModel):
    """Lijst-weergave zonder de zware HTML-payload."""

    id: uuid.UUID
    name: str
    styles: dict
    is_default: bool
    created_at: datetime
    updated_at: datetime


class TemplateValidation(BaseModel):
    ok: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TemplateValidateRequest(BaseModel):
    html: str = Field(min_length=1)


class TemplatePreviewRequest(BaseModel):
    template_id: uuid.UUID | None = None
    html: str | None = None
    styles: dict = Field(default_factory=dict)


class TemplateToolproofRequest(BaseModel):
    html: str = Field(min_length=1)


class TemplateToolproofResult(BaseModel):
    """Resultaat van de AI-omzetting naar placeholders, incl. code-verificatie."""

    ok: bool
    html: str
    applied: list[str]
    failed: list[str]
    checks_passed: list[str]
    checks_failed: list[str]
    warnings: list[str]
    notes: list[str]


# --- Conversation turns (chat) --------------------------------------------
# Max berichtlengte: ruim genoeg om een nieuwsbrief te beschrijven, maar voorkomt dat
# iemand een enorme lap tekst plakt die elke tool-stap opnieuw (duur) wordt meegestuurd.
MAX_MESSAGE_CHARS = 8000


class ConversationStart(BaseModel):
    tenant_id: uuid.UUID
    channel: Channel = "web"
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    template_id: uuid.UUID | None = None  # gekozen layout; None = standaard van het bedrijf


class MessageSend(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    template_id: uuid.UUID | None = None


class ConversationReply(BaseModel):
    conversation_id: uuid.UUID
    reply: str
    stop_reason: str
    preview_html: str | None = None  # voorbeeld-HTML voor het paneel naast de chat


# --- Message --------------------------------------------------------------
class MessageCreate(BaseModel):
    conversation_id: uuid.UUID
    role: MessageRole
    content: str = Field(min_length=1)
    metadata: dict = Field(default_factory=dict)


class MessageRead(_ORMModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    role: MessageRole
    content: str
    # ORM-attribuut heet metadata_ (metadata is gereserveerd in SQLAlchemy)
    metadata: dict = Field(validation_alias="metadata_")
    created_at: datetime


# --- Newsletter -----------------------------------------------------------
class NewsletterCreate(BaseModel):
    tenant_id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    theme: str | None = None
    subject: str | None = None
    input: dict = Field(default_factory=dict)


class NewsletterRead(_ORMModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    conversation_id: uuid.UUID | None
    theme: str | None
    subject: str | None
    html: str | None
    input: dict
    brevo_campaign_id: int | None
    esp_campaign_ref: str | None = None
    status: NewsletterStatus
    error: str | None
    created_at: datetime
    updated_at: datetime
