-- Compact werkgeheugen per gesprek voor de dure data-tools (find_products,
-- find_matches, find_ticket_links, find_banner, find_page_images).
--
-- Zonder dit riep de assistent dezelfde tool soms twee keer aan met exact
-- dezelfde URL binnen één gesprek (bv. na "yes doe deze" nog een keer
-- find_products), wat een extra pagina-fetch + LLM-extractie kost. Dit is
-- ALLEEN een geheugen voor het KIEZEN uit resultaten; de prijs/bereikbaarheid
-- van wat de gebruiker uiteindelijk kiest wordt bij create_newsletter_draft
-- nog steeds altijd live opnieuw gevalideerd (zie _validated_items/_matches/
-- _clubs en de validatie-cache die daar bij het concept wordt geleegd).
-- NULL = nog niets opgehaald in dit gesprek.
alter table mail.conversations
  add column tool_memory jsonb;
