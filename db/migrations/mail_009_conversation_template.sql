-- De gekozen template van een gesprek onthouden: een vervolgbericht zonder
-- expliciete keuze valt dan niet stil terug op de standaard-template.
alter table mail.conversations
  add column template_id uuid references mail.templates(id) on delete set null;
