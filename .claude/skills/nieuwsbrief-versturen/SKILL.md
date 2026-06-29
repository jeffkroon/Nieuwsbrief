# Skill: nieuwsbrief-versturen

Je bent een geautomatiseerde nieuwsbrief-bouwer voor FTG voetbaldomeinen.
Je maakt een HTML e-mailcampagne aan als **concept (draft)** in Brevo.
Er wordt niets verstuurd: het team controleert en verstuurt handmatig.

## Invoer

Je ontvangt via de prompt:
- `Domein`: een van `voetbalreizenxl`, `voetbalticketshop`, `voetbaltrips`
- `Thema`: korte omschrijving van het nieuwsbrief-thema
- `Wedstrijden`: kommagescheiden lijst van wedstrijd-slugs (bijv. `real-madrid-dortmund,barcelona-psg`)

---

## Stap 1: Brand config inladen

Lees het bestand `clients/football-travel-group/templates/brand/{domein}.json`.

Sla de volgende variabelen op voor gebruik in latere stappen:
- `brand_name`, `brand_email`, `brand_adres`, `brand_postcode_stad`
- `brand_telefoon`, `brand_kvk`
- `website_url`, `base_tickets_url`
- `primary_color`, `footer_color`
- `logo_url`, `header_image_url`
- `lijst_id` (integer)
- `facebook_url`, `instagram_url`, `youtube_url`
- `claude_prompt`
- `fallback_afbeelding_url`
- `club_afbeeldingen` (object met club-slug als sleutel)

Als het bestand niet bestaat of een verplicht veld ontbreekt: stop en meld welk veld ontbreekt.

---

## Stap 2: Wedstrijden verwerken

Split de wedstrijden-string op komma. Verwijder spaties rondom elke slug.

Per wedstrijd:
- Splits de slug op het eerste koppelteken om thuisclub en uitclub af te leiden.
  Voorbeeld: `real-madrid-dortmund` = thuisclub `real-madrid`, uitclub `dortmund`.
  Let op: clubnamen kunnen zelf koppeltekens bevatten. Gebruik de `club_afbeeldingen`-sleutels
  als richtlijn voor hoe clubnamen gespeld zijn.
- Zoek de afbeeldings-URL op: gebruik de thuisclub-slug als sleutel in `club_afbeeldingen`.
  Als de sleutel niet bestaat, gebruik `fallback_afbeelding_url`.
- Stel de wedstrijd-URL samen: `{base_tickets_url}{slug}` (bijv. `https://www.voetbalreizenxl.nl/wedstrijden/real-madrid-dortmund`).

Sla per wedstrijd op: `slug`, `thuisclub_naam`, `uitclub_naam`, `afbeelding_url`, `wedstrijd_url`.

Zet clubnamen om naar leesbare tekst: vervang koppeltekens door spaties en zet elk woord met
een hoofdletter (bijv. `real-madrid` wordt `Real Madrid`).

---

## Stap 3: Vanafprijzen ophalen

Per wedstrijd: haal de pagina op via WebFetch met URL `{wedstrijd_url}`.

Zoek in de HTML/tekst naar een prijs. Kijk naar:
- Tekst die begint met "vanaf", "v.a.", "from"
- Bedragen in het formaat `€ 123` of `€123,-`
- Elementen met klassen als `price`, `vanaf-prijs`, `ticket-price`

Gebruik de eerste prijs die je vindt als vanafprijs (bijv. `€ 189`).

Als de pagina niet laadt of geen herkenbare prijs bevat: gebruik de tekst `op aanvraag`.

Sla per wedstrijd op: `prijs`.

---

## Stap 4: Banners opbouwen

Lees het bestand `clients/football-travel-group/templates/nieuwsbrief-banner.html`.

Dit template bevat de volgende placeholders:
- `{{primary_color}}` — accent- en knopkleur
- `{{afbeelding_url}}` — URL naar de wedstrijdafbeelding
- `{{alt_tekst}}` — alt-tekst: `{thuisclub_naam} vs {uitclub_naam}`
- `{{thuisclub}}` — leesbare naam thuisclub
- `{{uitclub}}` — leesbare naam uitclub
- `{{prijs}}` — vanafprijs of "op aanvraag"
- `{{wedstrijd_url}}` — volledige URL naar de wedstrijdpagina

Vul het template in voor elke wedstrijd afzonderlijk.
Voeg alle ingevulde banners samen tot één `banners_html` string (direct achter elkaar, geen scheiding).

---

## Stap 5: Intro-tekst genereren

Neem de `claude_prompt` uit de brand config.
Vervang `{{thema}}` met het opgegeven thema.
Vervang `{{wedstrijden}}` met de leesbare wedstrijdennamen (bijv. "Real Madrid vs Dortmund, Barcelona vs PSG").

Schrijf op basis van deze instructie een intro-tekst bestaand uit precies twee alinea's:
- Alinea 1: stel het thema voor en wek enthousiasme.
- Alinea 2: introduceer de wedstrijden en roep op tot actie.
- Elk maximaal 60 woorden.
- Stijl: enthousiast, direct, sportief, geen emojis, geen em-dashes.
- Taal: Nederlands.

Sla op als `intro_1` (eerste alinea) en `intro_2` (tweede alinea).

---

## Stap 6: Hoofdtemplate invullen

Lees het bestand `clients/football-travel-group/templates/nieuwsbrief-main.html`.

Stel de campagne-specifieke waarden samen:
- `email_titel` = `{thema} | {brand_name}`
- `hoofd_cta_tekst` = `Bekijk alle wedstrijden`
- `hoofd_cta_url` = `{website_url}`
- `slot_cta_tekst` = `Bekijk het volledige aanbod`
- `slot_cta_url` = `{website_url}`

Vervang alle placeholders in het hoofdtemplate:

Brand-niveau (komen uit brand config):
- `{{primary_color}}`, `{{footer_color}}`, `{{logo_url}}`
- `{{website_url}}`, `{{brand_name}}`
- `{{brand_adres}}`, `{{brand_postcode_stad}}`
- `{{brand_email}}`, `{{brand_telefoon}}`, `{{brand_kvk}}`
- `{{facebook_url}}`, `{{instagram_url}}`, `{{youtube_url}}`
- `{{header_image_url}}`, `{{header_link_url}}` (= `website_url`)

Campagne-niveau:
- `{{email_titel}}`
- `{{intro_1}}`, `{{intro_2}}`
- `{{hoofd_cta_tekst}}`, `{{hoofd_cta_url}}`
- `{{banners_html}}`
- `{{slot_cta_tekst}}`, `{{slot_cta_url}}`

Controleer dat er geen onvervangen `{{...}}` placeholders meer in de HTML staan.
Sla de ingevulde HTML op als `/tmp/nieuwsbrief.html`.

---

## Stap 7: Campagne aanmaken in Brevo als concept

Voer het volgende Python-script uit via Bash.
Het script leest de HTML, bouwt de JSON-payload en stuurt die naar Brevo.
De omgevingsvariabele `BREVO_API_KEY` moet beschikbaar zijn.

```bash
python3 - <<'PYEOF'
import json, os, subprocess, sys

domein = "DOMEIN_PLACEHOLDER"
thema = "THEMA_PLACEHOLDER"
brand_name = "BRAND_NAME_PLACEHOLDER"
brand_email = "BRAND_EMAIL_PLACEHOLDER"
lijst_id = LIJST_ID_PLACEHOLDER
email_titel = "THEMA_PLACEHOLDER | BRAND_NAME_PLACEHOLDER"

with open("/tmp/nieuwsbrief.html", "r", encoding="utf-8") as f:
    html = f.read()

payload = {
    "name": f"{domein} - {thema}",
    "subject": email_titel,
    "sender": {
        "name": brand_name,
        "email": brand_email
    },
    "type": "classic",
    "htmlContent": html,
    "recipients": {
        "listIds": [lijst_id]
    }
}

result = subprocess.run(
    [
        "curl", "-s", "-w", "\n%{http_code}",
        "-X", "POST",
        "https://api.brevo.com/v3/emailCampaigns",
        "-H", f"api-key: {os.environ['BREVO_API_KEY']}",
        "-H", "Content-Type: application/json",
        "-d", json.dumps(payload)
    ],
    capture_output=True, text=True
)

lines = result.stdout.strip().split("\n")
http_code = lines[-1]
body = "\n".join(lines[:-1])

try:
    response = json.loads(body)
except Exception:
    print(f"Fout: onverwacht antwoord van Brevo (HTTP {http_code}):\n{body}")
    sys.exit(1)

if http_code == "201":
    campaign_id = response.get("id")
    print(f"Campagne aangemaakt als concept. ID: {campaign_id}. Controleer en verstuur vanuit Brevo.")
else:
    print(f"Fout bij aanmaken campagne (HTTP {http_code}):")
    print(json.dumps(response, indent=2))
    sys.exit(1)
PYEOF
```

Vervang vóór uitvoering de volgende placeholders in het script met de werkelijke waarden
die je in stap 1 hebt opgeslagen:
- `DOMEIN_PLACEHOLDER` → de waarde van `domein`
- `THEMA_PLACEHOLDER` → het opgegeven thema
- `BRAND_NAME_PLACEHOLDER` → `brand_name` uit config
- `BRAND_EMAIL_PLACEHOLDER` → `brand_email` uit config
- `LIJST_ID_PLACEHOLDER` → `lijst_id` uit config (integer, geen quotes)

---

## Stap 8: Afsluiten

Print de uitvoer van stap 7 en stop.

De campagne staat als concept in Brevo. Er is niets verstuurd.
Het team controleert de campagne in de Brevo-interface en verstuurt handmatig.
