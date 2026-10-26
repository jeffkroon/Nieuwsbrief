-- Migration: mail_016_ontbrekende_tabellen
-- Tabellen die de modellen (backend/app/db/models.py) wel hebben, maar die in geen
-- enkele migratie in deze map stonden.
--
-- mail.images is destijds aangemaakt als "migratie 003" (commit 5bd59e9, beeldbeheer
-- per bedrijf), maar dat bestand is nooit in de repo gekomen. PRODUCTIE HEEFT DEZE
-- TABEL AL. Alles hier is idempotent (if not exists), dus veilig om ook daar te
-- draaien; het doel is dat een verse database (tests, nieuwe omgeving) uit de
-- migraties hetzelfde schema krijgt als productie.

create table if not exists mail.images (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references mail.tenants(id) on delete cascade,
  category      text not null,
  filename      text not null,
  description   text,
  storage_path  text not null,
  url           text not null,
  created_at    timestamptz not null default now()
);

-- Zelfde lijn als de andere tabellen: RLS aan, geen policies (de backend verbindt
-- als postgres-user en omzeilt RLS). Opnieuw aanzetten is een no-op.
alter table mail.images enable row level security;
