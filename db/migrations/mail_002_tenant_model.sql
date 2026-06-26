-- Migration: mail_002_tenant_model
-- Beslissing 2026-06-26: 1 domein = 1 tenant (geen apart merk-niveau),
-- eigen Brevo-account per klant (versleutelde secret per tenant).
--
-- Wijzigingen:
--   - brand-config verhuist naar mail.tenants.config (jsonb)
--   - mail.brands en alle brand_id-verwijzingen vervallen
--   - nieuwe tabel mail.tenant_secrets voor versleutelde secrets

-- 1. brand_id-verwijzingen verwijderen
alter table mail.conversations drop column if exists brand_id;
alter table mail.newsletters   drop column if exists brand_id;

-- 2. merk-tabel vervalt
drop table if exists mail.brands;

-- 3. brand-config op de tenant zelf
alter table mail.tenants add column if not exists config jsonb not null default '{}'::jsonb;

-- 4. versleutelde secrets per tenant (bv. Brevo API-key)
--    value_encrypted bevat app-niveau ciphertext (Fernet); de master key staat
--    in de backend-env, nooit in de database.
create table mail.tenant_secrets (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references mail.tenants(id) on delete cascade,
  kind            text not null,                       -- bv. 'brevo_api_key'
  value_encrypted text not null,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (tenant_id, kind)
);

create index idx_tenant_secrets_tenant on mail.tenant_secrets(tenant_id);

create trigger trg_tenant_secrets_updated_at
  before update on mail.tenant_secrets
  for each row execute function mail.set_updated_at();

alter table mail.tenant_secrets enable row level security;
