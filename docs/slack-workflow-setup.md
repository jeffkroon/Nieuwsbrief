# Slack Workflow Builder: Setup

Dit document beschrijft hoe je de Slack-koppeling opzet (fase 2 van het plan).
Voer dit pas uit nadat fase 1 (GitHub Actions test) succesvol is afgerond.

**Vereiste:** Slack Pro of hoger (de HTTP-request stap is niet beschikbaar op het gratis plan).

---

## Stap 1: GitHub PAT aanmaken

De Slack-workflow moet GitHub Actions kunnen triggeren. Daarvoor heb je een
fine-grained Personal Access Token (PAT) nodig.

1. Ga naar **github.com, Settings, Developer settings, Personal access tokens, Fine-grained tokens**.
2. Klik **Generate new token**.
3. Vul in:
   - **Token name:** `slack-nieuwsbrief-trigger`
   - **Expiration:** 1 jaar
   - **Resource owner:** jouw account of organisatie
   - **Repository access:** Only selected repositories, kies `nieuwsbrief-automation`
4. Onder **Permissions, Repository permissions:**
   - **Actions:** Read and write
   - Alle andere rechten: No access
5. Klik **Generate token**.
6. Kopieer de token direct (wordt daarna niet meer getoond).

Bewaar de token veilig. Je hebt hem nodig in stap 3.

---

## Stap 2: Slack Workflow Builder openen

1. Open Slack.
2. Klik links onderaan op **Automations** (of zoek via de zoekbalk).
3. Klik op **New workflow** of **Workflow Builder**.
4. Klik **Create workflow**.
5. Geef de workflow een naam: `Nieuwsbrief aanmaken`.

---

## Stap 3: Trigger instellen

1. Klik op **Start the workflow when...**.
2. Kies **A shortcut is used**.
3. Vul in:
   - **Shortcut name:** `Nieuwsbrief aanmaken`
   - **Short description:** `Maak een nieuwsbrief-concept aan in Brevo`
4. Kies een kanaal waar de shortcut beschikbaar moet zijn, of kies **Anywhere in Slack**.
5. Klik **Save**.

---

## Stap 4: Formulier toevoegen

1. Klik op **Add step**.
2. Kies **Collect information in a form**.
3. Voeg drie velden toe:

**Veld 1:**
- Label: `Domein`
- Type: Select from a list
- Opties: `voetbalreizenxl`, `voetbalticketshop`, `voetbaltrips`
- Verplicht: Ja

**Veld 2:**
- Label: `Thema`
- Type: Short answer
- Placeholder: bijv. `Champions League finale week`
- Verplicht: Ja

**Veld 3:**
- Label: `Wedstrijden (kommagescheiden slugs)`
- Type: Short answer
- Placeholder: bijv. `real-madrid-dortmund,barcelona-psg`
- Verplicht: Ja

4. Klik **Save**.

---

## Stap 5: HTTP-request toevoegen

1. Klik op **Add step**.
2. Zoek naar **Send an HTTP request** (of: **Make an HTTP request**).
3. Vul in:

**URL:**
```
https://api.github.com/repos/{owner}/nieuwsbrief-automation/actions/workflows/nieuwsbrief.yml/dispatches
```
Vervang `{owner}` door je GitHub-gebruikersnaam of organisatienaam.

**Method:** POST

**Headers:**

| Naam | Waarde |
|---|---|
| `Authorization` | `Bearer {jouw-github-pat}` |
| `Accept` | `application/vnd.github.v3+json` |
| `Content-Type` | `application/json` |

Vervang `{jouw-github-pat}` door de token uit stap 1.

**Request body:**
```json
{
  "ref": "main",
  "inputs": {
    "domein": "{{Stap 1 - Domein}}",
    "thema": "{{Stap 1 - Thema}}",
    "wedstrijden": "{{Stap 1 - Wedstrijden (kommagescheiden slugs)}}"
  }
}
```

Gebruik de Slack variabelenamen exact zoals ze in het formulier zijn ingesteld.
In Slack Workflow Builder kun je variabelen invoegen via de `{...}`-knop naast het tekstveld.

4. Klik **Save**.

---

## Stap 6: Bevestigingsbericht toevoegen

1. Klik op **Add step**.
2. Kies **Send a message**.
3. **Send message to:** de gebruiker die de shortcut heeft gebruikt (`@person who clicked`).
4. **Message:**
```
Nieuwsbrief "{{Stap 1 - Thema}}" voor {{Stap 1 - Domein}} wordt aangemaakt.
Check Brevo over circa 2 minuten onder Campaigns.
```

5. Klik **Save**.

---

## Stap 7: Workflow publiceren

1. Klik **Publish** of **Turn on**.
2. De shortcut is nu beschikbaar in Slack.

---

## De shortcut gebruiken

1. Open een Slack-kanaal of DM.
2. Klik op het bliksemschicht-icoon (Shortcuts) in de berichtenbar.
3. Zoek op `Nieuwsbrief aanmaken`.
4. Klik op de shortcut.
5. Vul het formulier in en klik **Submit**.
6. Slack stuurt een bevestigingsbericht.
7. Na circa 2 minuten staat de campagne als concept in Brevo.

---

## GitHub Actions bewaken vanuit Slack

Optioneel: koppel GitHub-notificaties aan een Slack-kanaal via de officiële GitHub-app.

```
/github subscribe {owner}/nieuwsbrief-automation workflows:{event:"workflow_run" branch:"main"}
```

Je krijgt dan een bericht in Slack als een workflow-run slaagt of mislukt.

---

## Foutopsporing

**HTTP-request stap niet beschikbaar:**
- Controleer of het Slack-abonnement Pro of hoger is.

**GitHub geeft HTTP 404 terug:**
- Controleer of de repository-naam en owner exact kloppen in de URL.
- Controleer of de workflow-bestandsnaam exact `nieuwsbrief.yml` is.

**GitHub geeft HTTP 401 of 403 terug:**
- De PAT is verlopen of heeft onvoldoende rechten.
- Maak een nieuwe PAT aan (stap 1) en update de header in de workflow.

**Campagne verschijnt niet in Brevo:**
- Bekijk de GitHub Actions-log voor foutmeldingen.
- Controleer of `BREVO_API_KEY` en `ANTHROPIC_API_KEY` correct zijn ingesteld als Secrets.
