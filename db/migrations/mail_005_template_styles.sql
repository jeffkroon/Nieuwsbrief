-- Stijl per template: kleuren en lettertype die een bedrijf zelf mag kiezen.
-- Waarden worden in de backend gesaneerd (alleen geldige hex-kleuren + een vaste
-- lijst mail-veilige lettertypes) voordat ze worden opgeslagen.

alter table mail.templates
  add column styles jsonb not null default '{}'::jsonb;
