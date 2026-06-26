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
SecretKind = Literal["brevo_api_key"]


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


# --- Conversation turns (chat) --------------------------------------------
class ConversationStart(BaseModel):
    tenant_id: uuid.UUID
    channel: Channel = "web"
    message: str = Field(min_length=1)


class MessageSend(BaseModel):
    message: str = Field(min_length=1)


class ConversationReply(BaseModel):
    conversation_id: uuid.UUID
    reply: str
    stop_reason: str


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
    status: NewsletterStatus
    error: str | None
    created_at: datetime
    updated_at: datetime
