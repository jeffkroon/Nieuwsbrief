-- Seed: voetbalreizenxl als tenant (model na migratie 002: 1 domein = 1 tenant)
-- Idempotent: draai veilig opnieuw. Brand-config 1-op-1 uit
-- clients/football-travel-group/templates/brand/voetbalreizenxl.json
-- De Brevo API-key hoort NIET hier; die wordt versleuteld via mail.tenant_secrets gezet.

insert into mail.tenants (slug, name, status, brevo_list_id, config)
values (
  'voetbalreizenxl',
  'VoetbalreizenXL',
  'active',
  null,
  '{
    "brand_name": "VoetbalreizenXL",
    "brand_email": "info@voetbalreizenxl.nl",
    "brand_adres": "Julianaweg 141 JK",
    "brand_postcode_stad": "1131 DH Volendam",
    "brand_telefoon": "+31 85 303 6791",
    "brand_kvk": "76484211",
    "website_url": "https://www.voetbalreizenxl.nl",
    "base_tickets_url": "https://www.voetbalreizenxl.nl/tickets/",
    "matches_url": "https://www.voetbalreizenxl.nl/tickets/premier-league/",
    "primary_color": "#FF7200",
    "footer_color": "#6a6a6b",
    "logo_url": "https://img.mailinblue.com/1912392/images/content_library/original/67e3dfe76fdd629320b258bf.png",
    "header_image_url": "https://img.mailinblue.com/1912392/images/content_library/original/6a33f375cc06a38604651bf4.png",
    "dummy_image_url": "https://img.mailinblue.com/1912392/images/content_library/original/6a3a77fcd96ea0808185e2c3.png",
    "facebook_url": "https://www.facebook.com/VoetbalreizenXL",
    "instagram_url": "https://www.instagram.com/voetbalreizenxl/",
    "youtube_url": "https://www.youtube.com/channel/UCpcwvlMVymT2rWQN5TsGJlw",
    "claude_prompt": "Schrijf een enthousiaste nieuwsbrief-intro over het thema {{thema}} voor voetbalfans die reizen naar wedstrijden: {{wedstrijden}}. Stijl: direct, sportief, geen emojis, geen em-dashes. Twee alineas, maximaal 60 woorden per alinea. Nederlands.",
    "club_images": {
      "chelsea": "", "arsenal": "", "liverpool": "", "manchester-city": "",
      "manchester-united": "", "tottenham": "", "crystal-palace": "", "hull-city": "",
      "west-ham": "", "newcastle": "", "aston-villa": "", "brighton": "", "everton": "",
      "fulham": "", "brentford": "", "nottingham-forest": "", "leicester": "", "wolves": "",
      "southampton": "", "ipswich": ""
    }
  }'::jsonb
)
on conflict (slug) do update set
  name = excluded.name,
  config = excluded.config;
