# Nieuwsbrief-product: Masterplan

**Status:** architectuur vastgesteld 2026-06-26. Vervangt het oude plan (Slack +
GitHub Actions + Claude Code CLI). Dat oude pad is verlaten.

**Doel:** een schaalbaar, multi-tenant product waarin een accountmanager per klant
via een chat-interface in natuurlijke taal een nieuwsbrief laat opstellen. De
backend bouwt de nieuwsbrief met Claude (tool-use) en templates, en zet die via de
Brevo-API klaar als **concept**. Er wordt nooit automatisch verstuurd: een mens
controleert en verstuurt vanuit Brevo.

---

## Kernbeslissingen (2026-06-26)

| Beslissing | Keuze |
|---|---|
| Architectuur | FastAPI-backend + Claude API tool-use + Postgres (Supabase). Vervangt de oude CI-flow volledig. |
| Tenant-model | 1 domein = 1 tenant. Geen apart merk-niveau (`voetbalreizenxl`, `voetbalticketshop`, `voetbaltrips` = 3 losse tenants). |
| Brand-config | Per tenant opgeslagen als jsonb-kolom op `mail.tenants`. |
| Brevo-toegang | Eigen Brevo-account per klant. API-key versleuteld opgeslagen per tenant. |
| Interface | Web-chat als doel. Volgorde: eerst backend + API + tests, daarna web-chat, Slack optioneel later. |
| Verzenden | Backend dwingt af: alleen concept aanmaken, nooit verzenden. |

---

## Architectuur

```
Accountmanager (web-chat)
  typt in natuurlijke taal: "nieuwsbrief over thema X, wedstrijden Y"
    -> FastAPI-backend
        -> laadt tenant + brand-config uit Postgres (mail-schema)
        -> Claude API (claude-opus-4-8) met tool-use:
             - get_brand_config(tenant)
             - fetch_match_price(url)        (vanafprijs ophalen)
             - render_newsletter(input)      (HTML uit templates)
             - create_brevo_draft(...)       (concept in Brevo, NOOIT verzenden)
        -> slaat gesprek + concept op (mail.conversations, mail.messages, mail.newsletters)
          -> accountmanager controleert het concept in Brevo en verstuurt handmatig
```

---

## Datamodel (schema `mail`)

Zie `db/migrations/`. Na revisie 002:

| Tabel | Doel |
|---|---|
| `mail.tenants` | Eén per domein. Bevat brand-config (jsonb) + Brevo-lijst-id. |
| `mail.tenant_secrets` | Versleutelde secrets per tenant (o.a. Brevo API-key). |
| `mail.conversations` | Chat-sessie waarin een nieuwsbrief wordt opgesteld. |
| `mail.messages` | Berichten binnen een gesprek (incl. tool-calls in metadata). |
| `mail.newsletters` | Gegenereerde nieuwsbrief + Brevo concept-referentie + status. |
| `mail.audit_events` | Audit trail. |

RLS staat aan op alle tabellen. De backend verbindt als de `postgres`-user en
omzeilt RLS; de anon-key is geblokkeerd en het `mail`-schema wordt niet via
PostgREST geexposed.

---

## Canoniek brand-config-contract

Bron van waarheid is de jsonb in `mail.tenants.config`. Veldnamen volgen het
bestaande bestand `clients/football-travel-group/templates/brand/voetbalreizenxl.json`:

| Veld | Type | Beschrijving |
|---|---|---|
| `brand_name` | string | Weergavenaam afzender |
| `brand_email` | string | Geverifieerd Brevo-afzenderadres |
| `brand_adres`, `brand_postcode_stad`, `brand_telefoon`, `brand_kvk` | string | NAW + KvK |
| `website_url`, `base_tickets_url` | string | Domein en basispad wedstrijd-URLs |
| `primary_color`, `footer_color` | string | Hex-kleuren |
| `logo_url`, `header_image_url`, `dummy_image_url` | string | Afbeeldings-URLs (Brevo CDN) |
| `facebook_url`, `instagram_url`, `youtube_url` | string | Socials |
| `claude_prompt` | string | Instructie voor intro-generatie (placeholders `{{thema}}`, `{{wedstrijden}}`) |
| `club_images` | object | Sleutel: club-slug, waarde: afbeeldings-URL. Lege waarde valt terug op `dummy_image_url`. |

Let op: het oude `SKILL.md` gebruikte afwijkende namen (`club_afbeeldingen`,
`fallback_afbeelding_url`). Die zijn vervangen door `club_images` en
`dummy_image_url`.

---

## Fasen

### Fase 0: Datamodel (gereed)
- [x] `mail`-schema + tabellen (migratie 001)
- [x] Schema-revisie: tenant-model + secrets (migratie 002)
- [x] Seed voetbalreizenxl als tenant

### Fase 1: Backend-fundament (gereed)
- [x] DB-sessielaag + config (`SUPABASE_CONNECTION_STRING` via pooler)
- [x] Secret-encryptie (Fernet, master key in env)
- [x] Repository-laag per entiteit
- [x] CRUD-routes tenants + health, met tests (96% coverage)

### Fase 2: Content-pipeline (Claude tool-use) (gereed)
- [x] Tools: `get_brand_config`, `fetch_match_price`, `create_newsletter_draft`
- [x] Brevo-client dwingt concept af (geen verzend/plan-methode)
- [x] Conversation-orchestratie (Claude API, claude-opus-4-8, adaptive thinking)
- [x] HTML-template geport naar `backend/app/newsletter/html/`
- [x] Conversations-route + service (gesprek + berichten opslaan)
- [x] Live end-to-end bewezen: Brevo concept-campagne 902 aangemaakt (status draft)

### Fase 3: Web-chat interface (gereed)
- [x] Chat-frontend (`backend/app/static/index.html`), door FastAPI geserveerd op `/`
- [x] Tenant-selectie + gespreksgeschiedenis per gesprek

### Fase 4: Uitrol overige tenants (te doen)
- [ ] voetbalticketshop, voetbaltrips als tenants + brand-config + Brevo-koppeling
- [ ] Per tenant eigen Brevo API-key via `PUT /tenants/{id}/secrets`

---

## Lokaal draaien

```bash
cd backend && python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
# Chat: http://localhost:8000/   |   API-docs: http://localhost:8000/docs
```

Vereist in repo-root `.env`: `SUPABASE_CONNECTION_STRING`, `SECRET_ENCRYPTION_KEY`,
`ANTHROPIC_API_KEY`. Brevo-key per tenant via `PUT /tenants/{id}/secrets`.

---

## Bekende risico's en mitigaties

| Risico | Mitigatie |
|---|---|
| Prijsscraping breekt bij websitewijziging | Tool valt terug op tekst "op aanvraag" |
| Per ongeluk versturen | `create_brevo_draft` kan technisch alleen concepten aanmaken |
| Brevo API-keys lekken | Versleuteld in `mail.tenant_secrets`, master key in env, nooit in logs |
| `htmlContent` te groot | Max 1 MB per Brevo API; ruim onder limiet |

---

## Referenties

- Brevo Campaign API: `docs/brevo-api-reference.md`
- Datamodel: `db/migrations/`
- ORM-modellen: `backend/app/db/models.py`
- API-schema's: `backend/app/schemas.py`
