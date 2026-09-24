-- Bij welk verzendplatform de campagne van een nieuwsbrief hoort.
--
-- Voorheen afgeleid uit welke kolom gevuld was (brevo_campaign_id vs
-- esp_campaign_ref), maar Klaviyo en ActiveCampaign delen esp_campaign_ref. Wisselt
-- een bedrijf tussen die twee, dan werd een oude campagne-id bij het verkeerde
-- platform aangeboden. Nu expliciet vastgelegd bij het aanmaken.
alter table mail.newsletters
  add column esp text;

-- Bestaande rijen: Brevo is eenduidig; de rest hoort bij het huidige platform van
-- het bedrijf (er is tot nu toe nooit van platform gewisseld).
update mail.newsletters n
set esp = case
  when n.brevo_campaign_id is not null then 'brevo'
  else coalesce(t.config->>'esp', 'brevo')
end
from mail.tenants t
where t.id = n.tenant_id
  and (n.brevo_campaign_id is not null or n.esp_campaign_ref is not null);
