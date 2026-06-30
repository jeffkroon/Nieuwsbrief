-- Nieuwsbrief-templates per bedrijf.
-- Layout (html) wordt door Dunion-admins beheerd; styles (kleuren/lettertype, in
-- mail_005) mag een bedrijf zelf aanpassen. Eén template per tenant kan standaard zijn.

create table mail.templates (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references mail.tenants(id) on delete cascade,
  name        text not null,
  html        text not null,
  is_default  boolean not null default false,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (tenant_id, name)
);

create index idx_templates_tenant on mail.templates(tenant_id);

create trigger trg_templates_updated_at
  before update on mail.templates
  for each row execute function mail.set_updated_at();

alter table mail.templates enable row level security;
