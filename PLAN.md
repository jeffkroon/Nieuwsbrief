# FTG Nieuwsbrief Automatisering: Masterplan

**Doel:** Accountmanagers triggeren via Slack een geautomatiseerde nieuwsbrief-bouwer.
Claude Code laadt brand-configuratie, scrapt vanafprijzen, vult HTML-templates in en
zet de campagne klaar als **concept in Brevo**. Het team controleert en verstuurt
handmatig vanuit de Brevo-interface.

**MVP-domein:** voetbalreizenxl
**Huidige status:** Documentatie gereed, bouw gestart

---

## Architectuur

```
Accountmanager
  klikt shortcut in Slack
    → invult formulier (domein, thema, wedstrijden)
      → HTTP POST naar GitHub API (met GitHub PAT)
        → GitHub Actions runner (ubuntu-latest)
          → claude -p "$(cat SKILL.md) ..." --allowedTools "Read,Write,Bash,WebFetch"
            → laadt brand config JSON
            → scrapt vanafprijzen per wedstrijd (WebFetch)
            → genereert intro-tekst (eigen taalmodel)
            → vult HTML-templates in
            → POST /v3/emailCampaigns naar Brevo
              → campagne staat als CONCEPT in Brevo
                → accountmanager controleert en verstuurt handmatig
```

---

## Bestandsstructuur (volledig)

```
Email Marketing/
├── .claude/
│   └── skills/
│       └── nieuwsbrief-versturen/
│           └── SKILL.md                    ← de hersenen van de automatisering
├── docs/
│   ├── brevo-api-reference.md              ← volledige Brevo campaign API docs
│   ├── github-actions-setup.md             ← GitHub Actions setup + YAML
│   └── slack-workflow-setup.md             ← Slack Workflow Builder handleiding
├── templates/
│   ├── nieuwsbrief-main.html               ← hoofdtemplate (nog bouwen)
│   ├── nieuwsbrief-banner.html             ← bannertemplate per wedstrijd (nog bouwen)
│   └── brand/
│       ├── voetbalreizenxl.json            ← brand config (invullen)
│       ├── voetbalticketshop.json          ← brand config (nog aanmaken)
│       └── voetbaltrips.json               ← brand config (nog aanmaken)
├── .env                                    ← API keys (nooit committen)
├── CLAUDE.md
└── PLAN.md                                 ← dit bestand
```

---

## Fasen

### Fase 0: MVP — lokaal testen (geen GitHub/Slack)

Doel: de volledige content-pipeline aantonen zonder infrastructuur.
Één commando op de lokale machine, campagne verschijnt als concept in Brevo.

**Checklist fase 0:**

| Stap | Taak | Status |
|---|---|---|
| 0.1 | `BREVO_API_KEY` toevoegen aan `.env` | Te doen |
| 0.2 | `templates/brand/voetbalreizenxl.json` volledig invullen | Te doen |
| 0.3 | `templates/nieuwsbrief-banner.html` bouwen | Te doen |
| 0.4 | `templates/nieuwsbrief-main.html` bouwen | Te doen |
| 0.5 | `.claude/skills/nieuwsbrief-versturen/SKILL.md` gereed | Gereed |
| 0.6 | Brevo lijst-ID opzoeken (Brevo: Contacts, Lists) | Te doen |
| 0.7 | Lokale testrun uitvoeren | Te doen |
| 0.8 | Concept controleren in Brevo en goedkeuren | Te doen |

**Lokale testrun (uitvoeren vanuit `Email Marketing/`):**

```bash
set -a; source .env; set +a

claude -p "$(cat .claude/skills/nieuwsbrief-versturen/SKILL.md)

Voer deze skill nu uit met de volgende input:
Domein: voetbalreizenxl
Thema: Champions League finale week
Wedstrijden: real-madrid-dortmund,barcelona-psg" \
  --allowedTools "Read,Write,Bash,WebFetch" \
  --max-turns 30
```

Verwacht resultaat: "Campagne aangemaakt als concept. ID: {id}. Controleer in Brevo."

---

### Fase 1: GitHub Actions

**Checklist fase 1:**

| Stap | Taak | Tijdsinschatting |
|---|---|---|
| 1.1 | GitHub repo `nieuwsbrief-automation` aanmaken | 10 min |
| 1.2 | Bestanden committen (templates, brand configs, SKILL.md) | 15 min |
| 1.3 | GitHub Secrets instellen: `BREVO_API_KEY`, `ANTHROPIC_API_KEY` | 5 min |
| 1.4 | `.github/workflows/nieuwsbrief.yml` committen | 10 min |
| 1.5 | Handmatige test via GitHub UI (Actions, Run workflow) | 20 min |

Volledige workflow YAML en setup-instructies: zie `docs/github-actions-setup.md`

---

### Fase 2: Slack-koppeling

**Checklist fase 2:**

| Stap | Taak | Tijdsinschatting |
|---|---|---|
| 2.1 | Verifieer Slack Pro abonnement (vereist voor HTTP-stap) | 5 min |
| 2.2 | GitHub fine-grained PAT aanmaken | 5 min |
| 2.3 | Slack Workflow Builder inrichten | 30 min |
| 2.4 | End-to-end test: Slack trigger, Actions log, Brevo concept | 30 min |

Volledige Slack-instructies: zie `docs/slack-workflow-setup.md`

---

### Fase 3: Overige domeinen

| Stap | Taak |
|---|---|
| 3.1 | `templates/brand/voetbalticketshop.json` aanmaken |
| 3.2 | `templates/brand/voetbaltrips.json` aanmaken |
| 3.3 | Brevo lijst-ID per domein opzoeken en invullen |
| 3.4 | End-to-end test per domein |

---

## Brand config: verplichte velden

Elk `templates/brand/{domein}.json` heeft de volgende velden nodig.
Zie `templates/brand/voetbalreizenxl.json` voor het volledige voorbeeld.

| Veld | Type | Beschrijving |
|---|---|---|
| `brand_name` | string | Weergavenaam afzender |
| `brand_email` | string | Geverifieerd Brevo-afzenderadres |
| `brand_adres` | string | Straat + huisnummer |
| `brand_postcode_stad` | string | Postcode + stad |
| `brand_telefoon` | string | Telefoonnummer |
| `brand_kvk` | string | KvK-nummer |
| `website_url` | string | Hoofddomein (https://) |
| `base_tickets_url` | string | Basispad voor wedstrijd-URLs |
| `primary_color` | string | Hex-kleur knoppen en accenten |
| `footer_color` | string | Hex-kleur footer-balk |
| `logo_url` | string | URL naar logo (Brevo CDN) |
| `header_image_url` | string | URL naar header-afbeelding (Brevo CDN) |
| `lijst_id` | integer | Brevo contactlijst-ID |
| `facebook_url` | string | Facebook-pagina URL |
| `instagram_url` | string | Instagram-profiel URL |
| `youtube_url` | string | YouTube-kanaal URL |
| `claude_prompt` | string | Instructie voor intro-tekst generatie |
| `fallback_afbeelding_url` | string | Fallback als club niet in `club_afbeeldingen` |
| `club_afbeeldingen` | object | Sleutel: club-slug, waarde: afbeeldings-URL |

---

## Bekende risico's en mitigaties

| Risico | Mitigatie |
|---|---|
| Prijsscraping breekt bij websitewijziging | SKILL.md heeft fallback "op aanvraag" |
| SKILL.md in `-p` mode werkt anders | Volledige SKILL.md als prompt meegeven, niet via slash command |
| Geen foutmelding naar Slack bij Actions-fout | Team monitort via GitHub Actions e-mailnotificaties |
| GitHub PAT zichtbaar voor Slack admins | Fine-grained token: alleen 1 repo, alleen Actions write |
| Slack Pro vereist | Verifieer voor start fase 2 |
| `htmlContent` te groot | Max 1 MB per Brevo API; template + banners blijft ruim onder limiet |

---

## Referenties

- Brevo Campaign API: `docs/brevo-api-reference.md`
- GitHub Actions setup: `docs/github-actions-setup.md`
- Slack Workflow Builder: `docs/slack-workflow-setup.md`
- Skill-logica: `.claude/skills/nieuwsbrief-versturen/SKILL.md`
