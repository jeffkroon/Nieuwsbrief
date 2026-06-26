# GitHub Actions: Setup en Workflow

Dit document beschrijft hoe je de GitHub Actions-infrastructuur opzet (fase 1 van het plan).
Voer dit pas uit nadat fase 0 (lokale MVP-test) succesvol is afgerond.

---

## Stap 1: Repository aanmaken

1. Ga naar github.com en log in.
2. Klik op **New repository**.
3. Naam: `nieuwsbrief-automation`
4. Visibility: **Private**
5. Voeg geen README, .gitignore of licentie toe (we committen zelf).
6. Klik **Create repository**.

---

## Stap 2: Bestanden committen

Commit de volgende bestanden vanuit de lokale `Email Marketing/`-map naar de nieuwe repo.
Zorg dat de mapstructuur exact klopt:

```
nieuwsbrief-automation/
├── .github/
│   └── workflows/
│       └── nieuwsbrief.yml
├── .claude/
│   └── skills/
│       └── nieuwsbrief-versturen/
│           └── SKILL.md
├── templates/
│   ├── nieuwsbrief-main.html
│   ├── nieuwsbrief-banner.html
│   └── brand/
│       ├── voetbalreizenxl.json
│       ├── voetbalticketshop.json
│       └── voetbaltrips.json
└── README.md
```

Let op: commit de `.env` **niet**. Voeg een `.gitignore` toe met daarin `.env`.

---

## Stap 3: GitHub Secrets instellen

Ga naar de repo op GitHub: **Settings, Secrets and variables, Actions, New repository secret**.

Voeg twee secrets toe:

| Naam | Waarde |
|---|---|
| `BREVO_API_KEY` | Kopieer uit `.env` |
| `ANTHROPIC_API_KEY` | Kopieer van console.anthropic.com |

Secrets zijn versleuteld en nooit zichtbaar nadat ze zijn opgeslagen.

---

## Stap 4: Workflow-bestand committen

Maak het bestand `.github/workflows/nieuwsbrief.yml` aan met onderstaande inhoud.

```yaml
name: Nieuwsbrief aanmaken

on:
  workflow_dispatch:
    inputs:
      domein:
        description: 'Domein'
        required: true
        type: choice
        options:
          - voetbalreizenxl
          - voetbalticketshop
          - voetbaltrips
      thema:
        description: 'Thema van de nieuwsbrief'
        required: true
      wedstrijden:
        description: 'Wedstrijden, kommagescheiden slugs'
        required: true

jobs:
  aanmaken:
    runs-on: ubuntu-latest
    timeout-minutes: 10

    steps:
      - name: Checkout repo
        uses: actions/checkout@v4

      - name: Install Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'

      - name: Install Claude Code CLI
        run: npm install -g @anthropic-ai/claude-code

      - name: Voer nieuwsbrief-skill uit
        run: |
          SKILL=$(cat .claude/skills/nieuwsbrief-versturen/SKILL.md)
          claude -p "$SKILL

          Voer deze skill nu uit met de volgende input:
          Domein: ${{ inputs.domein }}
          Thema: ${{ inputs.thema }}
          Wedstrijden: ${{ inputs.wedstrijden }}" \
            --allowedTools "Read,Write,Bash,WebFetch" \
            --max-turns 30
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          BREVO_API_KEY: ${{ secrets.BREVO_API_KEY }}
```

---

## Stap 5: Handmatige testrun via GitHub UI

1. Ga naar de repo op GitHub.
2. Klik op **Actions**.
3. Klik in de linkerkolom op **Nieuwsbrief aanmaken**.
4. Klik op **Run workflow** (rechts).
5. Vul in:
   - Domein: `voetbalreizenxl`
   - Thema: `Champions League finale week`
   - Wedstrijden: `real-madrid-dortmund,barcelona-psg`
6. Klik **Run workflow**.
7. Klik op de run om de live log te bekijken.

Verwacht resultaat in de log:
```
Campagne aangemaakt als concept. ID: 1234. Controleer en verstuur vanuit Brevo.
```

Controleer daarna in Brevo onder **Campaigns** of de campagne als concept verschijnt.

---

## Workflow-parameters uitgelegd

| Input | Type | Beschrijving |
|---|---|---|
| `domein` | dropdown | Bepaalt welke brand config geladen wordt |
| `thema` | tekst | Komt in onderwerpregel en intro-tekst |
| `wedstrijden` | tekst | Kommagescheiden slugs, exact zoals in de wedstrijd-URL |

Voorbeeld wedstrijden-input: `real-madrid-dortmund,barcelona-psg,ajax-juventus`

De slug moet overeenkomen met het pad in de wedstrijd-URL van de website.
Voorbeeld: als de URL `https://www.voetbalreizenxl.nl/wedstrijden/real-madrid-dortmund` is,
dan is de slug `real-madrid-dortmund`.

---

## Foutopsporing

**Workflow start niet:**
- Controleer of `nieuwsbrief.yml` exact in `.github/workflows/` staat.
- Controleer of de YAML-syntax klopt (geen tabs, correcte inspringing).

**Claude Code fout "authentication failed":**
- Controleer of het secret `ANTHROPIC_API_KEY` correct is ingesteld.

**Brevo fout HTTP 401:**
- Controleer of het secret `BREVO_API_KEY` correct is ingesteld.

**Brevo fout HTTP 400 "missing_parameter":**
- Controleer of `lijst_id` in de brand config een integer is (geen string).
- Controleer of `brand_email` een geverifieerd afzenderadres is in Brevo.

**Tijdslimiet overschreden (timeout-minutes: 10):**
- Claude Code neemt soms meerdere iteraties voor scraping.
- Vergroot `timeout-minutes` naar 15 als dit structureel optreedt.

---

## Notificaties bij fouten

GitHub stuurt automatisch een e-mail naar de repo-eigenaar als een workflow mislukt.
Stel dit in via: **GitHub, Settings, Notifications, Actions**.

Voor actievere monitoring: stel een Slack-integratie in via de GitHub-app in Slack
(GitHub app, /github subscribe {owner}/{repo} workflows).
