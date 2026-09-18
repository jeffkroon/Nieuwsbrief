-- Versiegeschiedenis van templates.
--
-- Een template overschrijven (handmatig, of door een nieuwe tool-proof-run) was
-- onomkeerbaar: het origineel was daarna weg. Elke opslag bewaart nu eerst de
-- vorige inhoud, zodat terugzetten een klik is.
--
-- `source` zegt waar de versie vandaan komt: upload, toolproof, handmatig of
-- terugzetten. `actor` is de rol/gebruiker die de wijziging deed (mag leeg zijn).
create table mail.template_versions (
  id           uuid primary key default gen_random_uuid(),
  template_id  uuid not null references mail.templates(id) on delete cascade,
  tenant_id    uuid not null references mail.tenants(id) on delete cascade,
  name         text not null,
  html         text not null,
  styles       jsonb not null default '{}'::jsonb,
  source       text not null default 'handmatig',
  actor        text,
  created_at   timestamptz not null default now()
);

create index idx_template_versions_template
  on mail.template_versions(template_id, created_at desc);

alter table mail.template_versions enable row level security;
