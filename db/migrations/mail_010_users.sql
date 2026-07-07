-- Klant-gebruikers: koppelt een Supabase-Auth-account (id = auth-user-id) aan
-- één bedrijf. Identiteit (wachtwoord, resets) leeft bij Supabase Auth;
-- autorisatie (welk bedrijf mag deze gebruiker zien) leeft hier.
-- Bewust geen foreign key naar auth.users: de koppeling blijft los zodat de
-- testdatabase zonder auth-schema werkt en een auth-cleanup ons niet raakt.
create table mail.users (
  id          uuid primary key,
  tenant_id   uuid not null references mail.tenants(id) on delete cascade,
  email       text not null unique,
  created_at  timestamptz not null default now()
);

create index idx_users_tenant on mail.users(tenant_id);

alter table mail.users enable row level security;
