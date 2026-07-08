-- Token-verbruik per Claude-call: meten welke functie/welk gesprek wat kost.
-- Bewust geen foreign keys: een logtabel mag deletes nooit blokkeren.
create table mail.llm_usage (
  id                     uuid primary key default gen_random_uuid(),
  tenant_id              uuid,
  conversation_id        uuid,
  model                  text not null,
  purpose                text not null,
  input_tokens           integer not null default 0,
  output_tokens          integer not null default 0,
  cache_creation_tokens  integer not null default 0,
  cache_read_tokens      integer not null default 0,
  created_at             timestamptz not null default now()
);

create index idx_llm_usage_created on mail.llm_usage(created_at);
create index idx_llm_usage_tenant on mail.llm_usage(tenant_id);

alter table mail.llm_usage enable row level security;
