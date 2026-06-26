# Brevo Email Campaign API: Volledige Referentie

Base URL: `https://api.brevo.com/v3`
Authenticatie: header `api-key: {BREVO_API_KEY}` bij elk request.

---

## Overzicht endpoints

| Methode | Pad | Wat het doet |
|---|---|---|
| POST | `/emailCampaigns` | Nieuwe campagne aanmaken (altijd als draft) |
| GET | `/emailCampaigns` | Lijst van alle campagnes |
| GET | `/emailCampaigns/{id}` | Details van één campagne |
| PUT | `/emailCampaigns/{id}` | Campagne bijwerken (alleen draft of scheduled) |
| PUT | `/emailCampaigns/{id}/status` | Status wijzigen |
| POST | `/emailCampaigns/{id}/sendNow` | Direct versturen |
| POST | `/emailCampaigns/{id}/sendTest` | Testmail sturen |
| POST | `/emailCampaigns/{id}/exportRecipients` | Ontvangers exporteren (async) |
| DELETE | `/emailCampaigns/{id}` | Verwijderen (alleen draft) |

---

## POST /emailCampaigns — Campagne aanmaken

Een nieuwe campagne wordt **altijd aangemaakt als concept (draft)**. Er wordt niets verstuurd.

### Request

```
POST https://api.brevo.com/v3/emailCampaigns
Headers:
  api-key: {BREVO_API_KEY}
  Content-Type: application/json
```

### Verplichte velden

| Veld | Type | Beschrijving |
|---|---|---|
| `name` | string | Interne campagnenaam (zichtbaar in Brevo-dashboard) |
| `sender.email` | string | Geverifieerd afzenderadres (of gebruik `sender.id`) |
| `sender.name` | string | Weergavenaam afzender |
| `subject` | string | Onderwerpregel (verplicht als `abTesting: false`) |

Gebruik `sender.email` OF `sender.id`, nooit beide.

### Content (kies precies één van de drie)

| Veld | Type | Beschrijving | Limiet |
|---|---|---|---|
| `htmlContent` | string | Volledige HTML als string | Min 10 tekens, max 1 MB |
| `htmlUrl` | string | URL naar extern HTML-bestand | Publiek bereikbaar |
| `templateId` | integer | ID van actief Brevo-template | Moet type "classic" zijn |

### Ontvangers

```json
"recipients": {
  "listIds": [12, 34],
  "segmentIds": [5],
  "exclusionListIds": [99],
  "exclusionSegmentIds": []
}
```

Gebruik `listIds` of `segmentIds`, maar wees consistent: als je later bijwerkt, moet je
hetzelfde type gebruiken als bij aanmaken.

### Verzending en planning

| Veld | Type | Beschrijving |
|---|---|---|
| `scheduledAt` | string | ISO 8601 UTC: `2026-07-01T10:00:00.000Z` |
| `sendAtBestTime` | boolean | Brevo bepaalt optimaal tijdstip per ontvanger (**premium**) |

Als `scheduledAt` weggelaten: campagne blijft draft totdat handmatig verstuurd.

### Optionele velden

| Veld | Type | Beschrijving |
|---|---|---|
| `previewText` | string | Preheader-tekst (zichtbaar onder onderwerpregel in inbox) |
| `replyTo` | string | Antwoordadres |
| `tag` | string | Intern label voor categorisering |
| `utmCampaign` | string | Waarde voor utm_campaign parameter (alfanumeriek + spaties) |
| `attachmentUrl` | string | URL naar bijlage (pdf, xlsx, docx, csv, jpg, png, zip, etc.) |
| `toField` | string | Personaliseer het "Aan:"-veld, bijv. `{FNAME} {LNAME}` |
| `params` | object | Variabelen voor Brevo template language `{{ contact.FIRSTNAME }}` |
| `mirrorActive` | boolean | Voeg "bekijk in browser"-link toe |
| `inlineImageActivation` | boolean | Embed afbeeldingen in e-mail (max 4 MB totaal, max 5.000 ontvangers) |

### A/B-testen (premium)

| Veld | Type | Beschrijving |
|---|---|---|
| `abTesting` | boolean | A/B-test inschakelen |
| `subjectA` | string | Onderwerpregel A (verplicht als `abTesting: true`) |
| `subjectB` | string | Onderwerpregel B (verplicht als `abTesting: true`) |
| `splitRule` | integer | Percentage van lijst dat de test ontvangt (1-50) |
| `winnerCriteria` | `"open"` of `"click"` | Metric voor winnaarsbepaling |
| `winnerDelay` | integer | Testduur in uren (max 168 = 7 dagen) |

`abTesting` en `sendAtBestTime` zijn onderling incompatibel.

### Response

```json
HTTP 201 Created
{ "id": 1234 }
```

Foutcodes (400):

| Code | Betekenis |
|---|---|
| `invalid_parameter` | Ongeldige veldwaarde |
| `missing_parameter` | Verplicht veld ontbreekt |
| `not_enough_credits` | Onvoldoende verstuurlimiet |
| `duplicate_parameter` | Zelfde veld tweemaal opgegeven |

HTTP 405: premiumfunctie (`sendAtBestTime`, `abTesting`) zonder juist abonnement.

### Voorbeeld (minimaal, HTML-content)

```bash
curl -s -X POST https://api.brevo.com/v3/emailCampaigns \
  -H "api-key: $BREVO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "voetbalreizenxl - Champions League week",
    "subject": "Champions League finale week | Voetbalreizen XL",
    "sender": {
      "name": "Voetbalreizen XL",
      "email": "info@voetbalreizenxl.nl"
    },
    "type": "classic",
    "htmlContent": "<html><body><p>Inhoud hier.</p></body></html>",
    "recipients": {
      "listIds": [12]
    }
  }'
```

---

## GET /emailCampaigns — Campagnes ophalen

```
GET https://api.brevo.com/v3/emailCampaigns?status=draft&limit=10
```

### Query parameters

| Parameter | Type | Beschrijving |
|---|---|---|
| `type` | string | `classic` of `trigger` |
| `status` | string | `draft`, `sent`, `queued`, `archive`, `suspended`, `in_process`, `in_review`, `cancelling`, `cancelled` |
| `startDate` | string | ISO 8601, begin van periode (alleen voor verzonden campagnes) |
| `endDate` | string | ISO 8601, eind van periode (max 2 jaar span) |
| `limit` | integer | Resultaten per pagina (standaard 50) |
| `offset` | integer | Startindex voor paginering (standaard 0) |
| `sort` | string | `asc` of `desc` op aanmaakdatum (standaard desc) |
| `excludeHtmlContent` | boolean | HTML weglaten uit response (sneller) |

---

## PUT /emailCampaigns/{id}/status — Status wijzigen

```
PUT https://api.brevo.com/v3/emailCampaigns/1234/status
Body: { "status": "archive" }
```

### Mogelijke statuswaarden

| Status | Betekenis |
|---|---|
| `draft` | Terugzetten naar concept |
| `archive` | Archiveren |
| `darchive` | Dearchiveren |
| `suspended` | Pauzeren |
| `sent` | Versturen (triggert verzending) |
| `queued` | In de wachtrij plaatsen |
| `cancel` | Lopende verzending annuleren |
| `replicate` | Dupliceren als nieuwe campagne |
| `replicateTemplate` | Dupliceren als template (alleen template-campagnes) |

Response: HTTP 204 (geen body bij succes).

---

## POST /emailCampaigns/{id}/sendNow — Direct versturen

```
POST https://api.brevo.com/v3/emailCampaigns/1234/sendNow
```

Geen request body nodig.

| Response | Betekenis |
|---|---|
| 204 | Campagne ingepland voor directe verzending |
| 400 | Campagne kan niet verstuurd worden |
| 402 | Onvoldoende credits |
| 404 | Campagne-ID niet gevonden |

---

## POST /emailCampaigns/{id}/sendTest — Testmail sturen

```
POST https://api.brevo.com/v3/emailCampaigns/1234/sendTest
Body: { "emailTo": ["accountmanager@dunion.nl"] }
```

Als `emailTo` leeg array: stuur naar de Brevo-testlijst van het account.

**Limiet: max 50 testmails per dag** (over alle campagnes samen).

| Response | Betekenis |
|---|---|
| 204 | Testmail verstuurd |
| 400 | Mislukt; response bevat `blackListedEmails`, `unexistingEmails`, `withoutListEmails` |
| 404 | Campagne niet gevonden |

---

## DELETE /emailCampaigns/{id} — Verwijderen

Alleen mogelijk voor campagnes met status `draft` (niet gepland, niet verzonden).

| Response | Betekenis |
|---|---|
| 204 | Verwijderd |
| 403 | Al gepland of verzonden: verwijderen niet toegestaan |
| 404 | Niet gevonden |

---

## Campaign lifecycle

```
(aanmaken)
    ↓
  draft ──→ scheduled (via scheduledAt of PUT /status queued)
    │              │
    │              ↓
    │        in_review (grote lijsten, Brevo review)
    │              │
    ↓              ↓
  sendNow → queued → in_process → sent
                                    │
                              (onveranderlijk;
                               niet verwijderbaar)

  draft/sent → archive → darchive → draft
  in_process → cancelling → cancelled
```

**Kritieke regel:** eenmaal `sent` is een campagne onveranderlijk en niet verwijderbaar.
Alleen `draft` en `scheduled` campagnes kunnen bijgewerkt worden via PUT.

---

## Beperkingen samengevat

| Beperking | Waarde |
|---|---|
| Max HTML-bestandsgrootte | 1 MB |
| Max afbeeldingsgrootte bij inline embed | 4 MB totaal |
| Max ontvangers bij inline afbeeldingen | 5.000 |
| Max testmails per dag | 50 |
| `sendAtBestTime` + `abTesting` | Incompatibel (kies één) |
| `sender.email` + `sender.id` | Incompatibel (kies één) |
| Bijwerken na verzending | Niet mogelijk |
| Verwijderen na inplannen | Niet mogelijk (403) |
| `sendAtBestTime` en `abTesting` | Vereisen premium abonnement |
