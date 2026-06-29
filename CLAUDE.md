# Email Marketing

Werkruimte voor e-mailmarketing van Dunion Online Marketing. Twee actieve projecten:
1. **Dunion nieuwsbrief** (actief): LinkedIn-posts naar HTML-nieuwsbrief via `/newsletter`
2. **FTG nieuwsbrief-automatisering** (in bouw): Slack-getriggerde campagnes via Brevo

---

## Mapstructuur

```
Email Marketing/
├── .claude/
│   ├── commands/
│   │   └── newsletter.md          ← /newsletter skill (Dunion LinkedIn-flow)
│   └── skills/
│       └── nieuwsbrief-versturen/SKILL.md  ← FTG Brevo-flow
├── clients/
│   ├── dunion/                    ← actief: LinkedIn-nieuwsbrief
│   │   ├── newsletter-config.json ← LinkedIn-URL, default_posts
│   │   ├── newsletter-template.html
│   │   └── newsletters/           ← gegenereerde HTML (gitignored)
│   ├── football-travel-group/     ← in bouw: Brevo-campagnes
│   │   ├── templates/
│   │   │   ├── voetbalreizenxl-main.html
│   │   │   └── brand/voetbalreizenxl.json
│   │   ├── images/{clubs,headers}/ ← club- en headerafbeeldingen
│   │   ├── scripts/               ← demo-*.py (Brevo concept-campagnes)
│   │   └── afbeeldingen/          ← test-assets
│   └── intersport-theo-tol/       ← nieuw
│       ├── context.md
│       └── newsletters/           ← gegenereerde HTML (gitignored)
├── docs/                          ← Brevo/GitHub Actions/Slack naslag
├── tools/
│   └── fetch_linkedin_posts.py    ← Apify-scraper voor LinkedIn
├── .env                           ← API keys (niet committen)
├── CLAUDE.md                      ← dit bestand
└── PLAN.md                        ← FTG automatisering bouwplan
```

Klantmappen gebruiken `kebab-case` (geen spaties).

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
| `APIFY_API_KEY` | LinkedIn-scraper voor /newsletter skill |
| `BREVO_API_KEY` | FTG campagnes aanmaken via Brevo API |
| `ANTHROPIC_API_KEY` | Claude Code in GitHub Actions (niet lokaal nodig) |

---

## Gedragsregels

1. Schrijf nooit naar een andere dienstmap dan `Email Marketing/`.
2. Sla klantoutput op in `clients/{klant}/newsletters/` of `clients/{klant}/reports/`.
3. Lees `.env` via `python-dotenv` of shell-variabelen; druk nooit API-sleutels af in output.
4. Communiceer in het Nederlands, tenzij de klant expliciet om een andere taal vraagt.
5. Gebruik geen em-dashes in output; gebruik een komma of dubbele punt.

---

## FTG-project: snel naslaan

- Alles staat onder `clients/football-travel-group/`
- Brand configs: `clients/football-travel-group/templates/brand/{domein}.json`
- Templates: `clients/football-travel-group/templates/`
- Demo-scripts: `clients/football-travel-group/scripts/demo-*.py` (paden zijn relatief aan de FTG-map)
- Skill voor lokale test: `.claude/skills/nieuwsbrief-versturen/SKILL.md`
- Volledig bouwplan: `PLAN.md`
- MVP-domein: **voetbalreizenxl** (brand config en main-template al aanwezig)
