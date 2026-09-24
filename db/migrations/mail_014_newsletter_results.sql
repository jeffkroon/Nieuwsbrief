-- Resultaten van een nieuwsbrief uit het verzendplatform (alleen-lezen opgehaald).
--
-- stats: genormaliseerde tellers en percentages (verzonden, afgeleverd, unieke
-- opens/kliks, afmeldingen, bounces, open_rate/click_rate als fractie) plus de
-- status in het platform. NULL = nog nooit opgehaald.
-- stats_fetched_at: wanneer; gebruikt als afkoeltijd, want Klaviyo staat maar
-- 2 rapporten per minuut en 225 per dag toe.
--
-- Zodra het platform 'verzonden' meldt, zet de backend newsletters.status op
-- 'sent' (die waarde stond al in de check-constraint).
alter table mail.newsletters
  add column stats jsonb,
  add column stats_fetched_at timestamptz;
