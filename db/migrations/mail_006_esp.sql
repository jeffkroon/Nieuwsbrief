-- ESP-ondersteuning naast Brevo (Klaviyo): campagne-referentie als tekst.
-- Klaviyo-campagne-ids zijn strings; Brevo blijft brevo_campaign_id (int) gebruiken.

alter table mail.newsletters
  add column esp_campaign_ref text;
