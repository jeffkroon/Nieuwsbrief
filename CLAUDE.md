# Email Marketing

Werkruimte voor e-mailmarketing van Dunion Online Marketing. Twee projecten:
1. **Nieuwsbrief-product** (actief, in productie): multi-tenant FastAPI-backend in
   `backend/`. Een accountmanager of klant stelt via een web-chat in natuurlijke taal
   een nieuwsbrief op; Claude (tool-use) haalt echte inhoud van de klantensite, vult
   de template van het bedrijf en zet de mail als **concept** klaar in Brevo,
   Klaviyo of ActiveCampaign. Er wordt nooit automatisch verstuurd.
2. **Dunion nieuwsbrief** (actief): LinkedIn-posts naar HTML-nieuwsbrief via `/newsletter`

De oude FTG-route (Slack + GitHub Actions + Claude Code CLI) is verlaten; het
product hierboven vervangt die. Zie `PLAN.md` voor de opzet en de status.

---

## Mapstructuur

```
Email Marketing/
├── backend/                       ← nieuwsbrief-product (FastAPI)
│   ├── app/
│   │   ├── routes/                ← API: tenants, conversations, newsletters, templates, images, auth, admin
│   │   ├── newsletter/            ← chat-tools, prompts, renderer, templates, validatie
│   │   ├── services/              ← Brevo/Klaviyo/ActiveCampaign-clients, crypto, Supabase
│   │   ├── repositories/          ← database-toegang per tabel
│   │   ├── db/models.py           ← ORM-modellen (volgen db/migrations/)
│   │   └── static/                ← web-chat frontend, door FastAPI geserveerd op /
│   ├── tests/                     ← pytest tegen een echte Postgres (testcontainers, Docker)
│   ├── requirements.txt           ← runtime; requirements.lock = vergrendeld (Dockerfile)
│   ├── requirements-dev.txt       ← runtime + test-tools
│   └── Dockerfile
├── db/
│   ├── migrations/                ← mail_NNN_*.sql, handmatig toepassen op Supabase
│   └── seeds/
├── .do/app.yaml                   ← DigitalOcean App Platform-spec (1 instance)
├── .github/workflows/tests.yml    ← volledige testsuite op elke PR, 0 skipped
├── .claude/
│   ├── commands/
│   │   └── newsletter.md          ← /newsletter skill (Dunion LinkedIn-flow)
│   └── skills/
│       └── nieuwsbrief-versturen/SKILL.md  ← oude FTG Brevo-flow (lokaal testen)
├── clients/
│   ├── dunion/                    ← actief: LinkedIn-nieuwsbrief
│   │   ├── newsletter-config.json ← LinkedIn-URL, default_posts
│   │   ├── newsletter-template.html
│   │   └── newsletters/           ← gegenereerde HTML (gitignored)
│   ├── football-travel-group/     ← oorspronkelijke templates, brand-config en demo-scripts
│   │   ├── templates/
│   │   │   ├── voetbalreizenxl-main.html
│   │   │   └── brand/voetbalreizenxl.json
│   │   ├── images/{clubs,headers}/ ← club- en headerafbeeldingen
│   │   ├── scripts/               ← demo-*.py (Brevo concept-campagnes)
│   │   └── afbeeldingen/          ← test-assets
│   └── intersport-theo-tol/
│       ├── context.md
│       └── newsletters/           ← gegenereerde HTML (gitignored)
├── docs/                          ← Brevo-naslag; GitHub Actions/Slack-docs horen bij de verlaten route
├── tools/
│   └── fetch_linkedin_posts.py    ← Apify-scraper voor LinkedIn
├── .env                           ← API keys (niet committen)
├── CLAUDE.md                      ← dit bestand
└── PLAN.md                        ← masterplan nieuwsbrief-product
```

Klantmappen gebruiken `kebab-case` (geen spaties).

---

## Nieuwsbrief-product: snel naslaan

- **Deploy:** DigitalOcean App Platform, automatisch bij elke push op `main`
  (`.do/app.yaml`). Draait als één instance: rate limiters en caches staan in het geheugen.
- **Database:** Postgres in Supabase, schema `mail`. Migraties in `db/migrations/` worden
  **handmatig** toegepast; een deploy past niets toe. Code moet dus werken met het schema
  dat er al staat. Zie `db/migrations/README.md`.
- **Tests:** vanuit `backend/`: `python -m pytest`. Vereist Docker (testcontainers);
  CI faalt bij overgeslagen tests.
- **Secrets:** API-keys van klanten (ESP) staan versleuteld per tenant in de database;
  app-secrets staan in de DO-omgeving, nooit in de repo.

---

## Actieve skills

### /newsletter {klant}
Genereert HTML-nieuwsbrief op basis van recente LinkedIn-posts.
- Config: `clients/{klant}/newsletter-config.json`
- Template: `clients/{klant}/newsletter-template.html`
- Output: `clients/{klant}/newsletters/nieuwsbrief_YYYY-MM-DD.html`
- Vereist: `APIFY_API_KEY` in `.env`

---

## Omgevingsvariabelen (.env)

| Variabele | Gebruik |
|---|---|
| `SUPABASE_CONNECTION_STRING` | Backend: Postgres-verbinding (verplicht) |
| `SECRET_ENCRYPTION_KEY` | Backend: Fernet-sleutel voor de secrets per tenant (verplicht) |
| `ANTHROPIC_API_KEY` | Backend: Claude voor chat, extractie en fotobeschrijvingen |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_PUBLISHABLE_KEY` | Backend: opslag van foto's en klant-logins |
| `ACCESS_PASSWORD`, `ADMIN_PASSWORD` | Backend: wachtwoord-slot en admin-rol (leeg = geen slot, lokaal) |
| `BREVO_API_KEY` | Demo-scripts en lokale tests; in het product heeft elk bedrijf een eigen key |
| `APIFY_API_KEY` | LinkedIn-scraper voor /newsletter skill |

---

## Gedragsregels

1. Schrijf nooit naar een andere dienstmap dan `Email Marketing/`.
2. Sla klantoutput op in `clients/{klant}/newsletters/` of `clients/{klant}/reports/`.
3. Lees `.env` via `python-dotenv` of shell-variabelen; druk nooit API-sleutels af in output.
4. Communiceer in het Nederlands, tenzij de klant expliciet om een andere taal vraagt.
5. Gebruik geen em-dashes in output; gebruik een komma of dubbele punt.

---

## FTG-bestanden: snel naslaan

FTG (voetbalreizenxl e.a.) is inmiddels tenant in het nieuwsbrief-product; de bestanden
hieronder zijn het oorspronkelijke materiaal.

- Alles staat onder `clients/football-travel-group/`
- Brand configs: `clients/football-travel-group/templates/brand/{domein}.json`
- Templates: `clients/football-travel-group/templates/`
- Demo-scripts: `clients/football-travel-group/scripts/demo-*.py` (paden zijn relatief aan de FTG-map)
- Skill voor lokale test: `.claude/skills/nieuwsbrief-versturen/SKILL.md`
- Masterplan: `PLAN.md`
