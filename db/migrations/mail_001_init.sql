-- Migration: mail_001_init
-- Schema voor het multi-tenant nieuwsbrief-product (FastAPI + Claude API tool-use -> Brevo concept).
-- Standalone: geen koppeling met hub. RLS staat aan op alle tabellen; de backend verbindt
-- als de `postgres`-user (bypass RLS). De anon/authenticated rollen krijgen geen rechten,
-- waardoor het schema niet via de Supabase anon-key benaderbaar is.

create schema if not exists mail;

-- Gedeelde trigger voor automatisch bijwerken van updated_at.
create or replace function mail.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- ---------------------------------------------------------------------------
-- mail.tenants  -- elke klant/bedrijf dat het product gebruikt
-- ---------------------------------------------------------------------------
create table mail.tenants (
  id           uuid primary key default gen_random_uuid(),
  slug         text not null unique,
  name         text not null,
  status       text not null default 'active'
                 check (status in ('active', 'paused', 'archived')),
  brevo_list_id integer,                         -- standaard Brevo-lijst voor deze tenant
  settings     jsonb not null default '{}'::jsonb,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create trigger trg_tenants_updated_at
  before update on mail.tenants
  for each row execute function mail.set_updated_at();

-- ---------------------------------------------------------------------------
-- mail.brands  -- merk-configuratie per tenant (bv. voetbalreizenxl, voetbalticketshop)
-- ---------------------------------------------------------------------------
create table mail.brands (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references mail.tenants(id) on delete cascade,
  slug        text not null,
  name        text not null,
  config      jsonb not null default '{}'::jsonb,  -- kleuren, logo, afzender, template-refs
  is_active   boolean not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (tenant_id, slug)
);

create index idx_brands_tenant on mail.brands(tenant_id);

create trigger trg_brands_updated_at
  before update on mail.brands
  for each row execute function mail.set_updated_at();

-- ---------------------------------------------------------------------------
-- mail.conversations  -- chat-sessie waarin een nieuwsbrief wordt opgesteld
-- ---------------------------------------------------------------------------
create table mail.conversations (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null references mail.tenants(id) on delete cascade,
  brand_id     uuid references mail.brands(id) on delete set null,
  channel      text not null check (channel in ('slack', 'web', 'api')),
  external_ref text,                              -- slack thread ts / web sessie-id
  status       text not null default 'active'
                 check (status in ('active', 'completed', 'abandoned')),
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index idx_conversations_tenant on mail.conversations(tenant_id);
create index idx_conversations_external_ref on mail.conversations(external_ref);

create trigger trg_conversations_updated_at
  before update on mail.conversations
  for each row execute function mail.set_updated_at();

-- ---------------------------------------------------------------------------
-- mail.messages  -- berichten binnen een gesprek (chat-state)
-- ---------------------------------------------------------------------------
create table mail.messages (
  id              uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references mail.conversations(id) on delete cascade,
  role            text not null check (role in ('user', 'assistant', 'system', 'tool')),
  content         text not null,
  metadata        jsonb not null default '{}'::jsonb,  -- tool-calls, token-usage e.d.
  created_at      timestamptz not null default now()
);

create index idx_messages_conversation on mail.messages(conversation_id, created_at);

-- ---------------------------------------------------------------------------
-- mail.newsletters  -- gegenereerde nieuwsbrief + Brevo concept-referentie
-- ---------------------------------------------------------------------------
create table mail.newsletters (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references mail.tenants(id) on delete cascade,
  brand_id          uuid references mail.brands(id) on delete set null,
  conversation_id   uuid references mail.conversations(id) on delete set null,
  theme             text,
  subject           text,
  html              text,
  input             jsonb not null default '{}'::jsonb,  -- gestructureerde input (wedstrijden, thema)
  brevo_campaign_id integer,                              -- concept-campagne-id in Brevo
  status            text not null default 'draft'
                      check (status in ('draft', 'generating', 'ready', 'approved', 'sent', 'failed')),
  error             text,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create index idx_newsletters_tenant_status on mail.newsletters(tenant_id, status);
create index idx_newsletters_conversation on mail.newsletters(conversation_id);

create trigger trg_newsletters_updated_at
  before update on mail.newsletters
  for each row execute function mail.set_updated_at();

-- ---------------------------------------------------------------------------
-- mail.audit_events  -- audit trail voor belangrijke acties
-- ---------------------------------------------------------------------------
create table mail.audit_events (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid references mail.tenants(id) on delete set null,
  actor       text,                               -- slack-user, systeem, api-key
  action      text not null,
  entity_type text,
  entity_id   uuid,
  data        jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now()
);

create index idx_audit_events_tenant on mail.audit_events(tenant_id, created_at);

-- ---------------------------------------------------------------------------
-- RLS aanzetten op alle tabellen (backend draait als postgres-user en omzeilt RLS;
-- zonder policies blijven anon/authenticated geblokkeerd).
-- ---------------------------------------------------------------------------
alter table mail.tenants        enable row level security;
alter table mail.brands         enable row level security;
alter table mail.conversations  enable row level security;
alter table mail.messages       enable row level security;
alter table mail.newsletters    enable row level security;
alter table mail.audit_events   enable row level security;
