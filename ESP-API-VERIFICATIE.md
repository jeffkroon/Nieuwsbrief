# Verificatie verzendplatform-API's (18 september 2026)

Gecontroleerd tegen de officiële documentatie van Brevo, Klaviyo en ActiveCampaign:
sluit onze payload aan op wat de API verwacht? Hieronder per platform wat klopt,
wat fout was en wat nog open staat.

---

## Brevo: alles klopt

`POST /v3/emailCampaigns`, velden geverifieerd tegen de officiële schema-tabel:

| Ons veld | Status |
|---|---|
| `name` | verplicht, correct |
| `sender {name, email}` | verplicht, correct (of `sender.id`, niet allebei) |
| `subject` | verplicht zolang `abTesting` false is, correct |
| `htmlContent` | een van htmlContent/htmlUrl/templateId verplicht, correct |
| `recipients.listIds` | optioneel, correct (concept zonder lijst mag) |
| `previewText` | exacte spelling correct |
| `replyTo` | exacte spelling correct |
| `scheduledAt` | bewust weggelaten: campagne blijft concept |

- Succes = **201** met `{"id": <long>}`. Onze client controleert precies dat.
- Bevestigd: zonder `scheduledAt` staat de campagne in **draft**.
- `type: "classic"` staat niet meer in de huidige schema-tabel. Brevo accepteert het
  (legacy-veld) en het is nooit een foutbron geweest; laten staan, wel weten.
- Voor blok 3 (testmail): `POST /v3/emailCampaigns/{campaignId}/sendTest` met body
  `emailTo`. Dit is geen campagne verzenden.

## Klaviyo: correct, één blokkade opgelost

| Onderdeel | Status |
|---|---|
| `POST /api/templates`, `editor_type: "CODE"` | geldig (CODE en USER_DRAGGABLE zijn aanmaakbaar), succes **201** |
| Limiet 1.000 templates per account | bevestigd; daarom ruimen we de herbruikbare template op |
| `POST /api/campaigns` structuur | correct: `audiences.included`, `campaign-messages.data[].attributes.definition` |
| `content`-velden | correct: `subject`, `from_email`, `from_label`, `reply_to_email`, `preview_text` |
| `send_strategy` weggelaten | mag; verzenden gebeurt pas via een apart send-job-endpoint dat wij niet hebben |
| `POST /api/campaign-message-assign-template` | succes **200**, precies wat onze client verwacht |
| revision `2026-04-15` | geldige stabiele revisie; levenscyclus is 1 jaar stabiel + 1 jaar deprecated, dus bruikbaar tot ~april 2028. Nieuwste is 2026-07-15 |

**Wat fout was:** onze templates schrijven de afmeldlink als `{{ unsubscribe }}`
(Brevo-syntax), terwijl Klaviyo `{% unsubscribe %}` eist. Onze eigen Klaviyo-client
blokkeerde daarop, dus een Klaviyo-klant kon met de standaard-templates **geen enkel
concept aanmaken**. Opgelost met `app/newsletter/esp_tags.py`.

## ActiveCampaign: correct, maar de afmeldlink werkte niet

v1-API (`admin/api.php`), geverifieerd tegen de officiële parameterlijst:

| Onderdeel | Status |
|---|---|
| `message_add` velden | volledig correct: format, subject, fromname, fromemail, reply2, priority, charset, encoding, htmlconstructor, html, textconstructor, text, `p[listid]` (alle verplicht) |
| `campaign_create` velden | correct: type, name, sdate, status, public, tracklinks, `p[listid]`, `m[messageid]` |
| `status: 0` | bevestigd: **0 = draft**, 1 = scheduled |
| v1 deprecated? | nee, v1 wordt nog ondersteund; v3 krijgt de nieuwe functionaliteit. v3 heeft meerdere calls nodig voor wat v1 in één doet |
| response `id` | correct uitgelezen |

**Wat fout was:** ActiveCampaign verplicht een afmeldlink via de personalisatie-tag
`%UNSUBSCRIBELINK%`. Onze mails gingen eruit met de letterlijke tekst
`{{ unsubscribe }}` in de href: een kapotte afmeldlink bij elke AC-ontvanger.
Opgelost met dezelfde tag-omzetting.

---

## De fix: `app/newsletter/esp_tags.py`

Vlak voor het aanmaken van het concept worden platform-tags omgezet naar de syntax
van het doelplatform:

| | Brevo | Klaviyo | ActiveCampaign |
|---|---|---|---|
| afmeldlink | `{{ unsubscribe }}` | `{% unsubscribe %}` | `%UNSUBSCRIBELINK%` |
| e-mailadres ontvanger | `{{ contact.EMAIL }}` | `{{ person.email }}` | `%EMAIL%` |

Werkt in alle richtingen (een Klaviyo-template naar een Brevo-account net zo goed),
herkent ook de schrijfwijze zonder spaties, en meldt het als een nieuwsbrief
helemaal geen afmeldlink heeft. Daarnaast een waarschuwing boven 102 KB, de grens
waarboven Gmail en Klaviyo de mail afknippen ("Bericht is ingekort").

Bewust hier en niet in de template: een bedrijf kan van platform wisselen zonder dat
elke template om moet, en de byte-gelijke round-trip-garantie van tool-proof blijft
onaangeraakt (die gaat over de template, dit over de gerenderde uitvoer).

---

## Stand 24 september 2026

Bewust **geen testconcepten** aangemaakt in klantaccounts (keuze Jeff). Wat zonder
concepten kon, is gedaan:

**Afmeldlink: geverifieerd op de echte templates in productie** (alleen lezen). Alle
vijf templates hebben een afmeldlink, en na de platform-omzetting én het CSS-inlinen
staat de juiste tag erin:

| Template | Platform | Resultaat |
|---|---|---|
| Ohcascas / base template (standaard) | Klaviyo | `{% unsubscribe %}` |
| Ohcascas / Magazine | Klaviyo | `{% unsubscribe %}` |
| Thingsdata / nieuw test template (standaard) | Brevo | `{{ unsubscribe }}` |
| VoetbalreizenXL / Standaard layout (standaard) | Brevo | `{{ unsubscribe }}` |
| VoetbalreizenXL / Card Template | Brevo | `{{ unsubscribe }}` |

**Dubbele campagnenaam: opgelost in plaats van getest.** De naam is nu
`{merk} - {thema} (dd-mm-jjjj uu:mm)` en kan dus niet meer dubbel zijn, ongeacht wat
een platform ermee doet.

## Nog open

1. **Preheader in de inbox.** De velden (`previewText` bij Brevo, `preview_text` bij
   Klaviyo) zijn tegen de documentatie geverifieerd, maar of ze in de inbox verschijnen
   zie je pas bij een echte verzending.
2. **Klikken op de afmeldlink in een echte mail.** De tag klopt, maar het werkend
   afmelden zelf is nooit uitgeprobeerd.
3. **ActiveCampaign:** geen enkele klant zit erop; blijft ongetest tot er een AC-klant is.
4. **Geverifieerde afzender:** een onbevestigd afzendadres geeft een fout van het
   platform zelf; die geven we ongefilterd door.

**Controlelijst voor het eerstvolgende échte concept** (per platform één keer):
- Stuur vanuit het dashboard een testmail naar jezelf.
- Staat de preheader naast het onderwerp in de inbox?
- Klik op de afmeldlink: kom je op de afmeldpagina van het platform uit?
- Staan de productfoto's erin en kloppen de prijzen?
