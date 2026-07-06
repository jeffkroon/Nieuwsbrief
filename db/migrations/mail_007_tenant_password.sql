-- Per-bedrijf login: PBKDF2-wachtwoordhash op de tenant. NULL = geen klant-login
-- ingesteld; alleen admins/team kunnen dan bij dit bedrijf.
alter table mail.tenants
  add column password_hash text;
