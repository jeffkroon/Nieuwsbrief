#!/usr/bin/env python3
"""
Demo: Bundesliga-campagne als concept op basis van campagne 871 (Premier League).
Vervangt: intro-tekst, club-afbeeldingen, club-links, CTA-tekst, UTM-parameters.
Verstuurt NIETS. Campagne staat na afloop als concept (draft) in Brevo.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# .env inladen
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())

API_KEY = os.environ.get("BREVO_API_KEY")
if not API_KEY:
    print("Fout: BREVO_API_KEY niet gevonden in .env")
    sys.exit(1)

BREVO_BASE  = "https://api.brevo.com/v3"
TEMPLATE_ID = 871
BASE_URL    = "https://www.number1-voetbalreizen.nl"
UTM_OUD     = "NR1%20Premier%20League%20Schema%2019-6-2026"
UTM_NIEUW   = "NR1%20Bundesliga%202026-2027"

# ── Bundesliga content ────────────────────────────────────────────────────────

INTRO_1 = (
    "Het nieuwe Bundesliga-seizoen staat voor de deur en de mooiste wedstrijden "
    "zijn al bekend. Van het Allianz Arena in München tot het Signal Iduna Park "
    "in Dortmund: dit seizoen biedt voetbalfans topwedstrijden in iconische stadions."
)
INTRO_2 = (
    "Bekijk het aanbod en reserveer je reis naar Bayern München, Borussia Dortmund, "
    "Bayer Leverkusen, RB Leipzig of Eintracht Frankfurt. "
    "Wij regelen tickets, hotel en vervoer, jij geniet van de Bundesliga."
)

# Vijf clubs: (oud src in 871-HTML, nieuw src, oud pad, nieuw pad, alt-tekst)
CLUB_VERVANGINGEN = [
    {
        "oud_src":  "6a329faeb3d4086ffec58e8d.png",   # Manchester City
        "nieuw_src": "https://static.number1-voetbalreizen.nl/site/storage/files/208611/voetbalreis-bayern-munchen-1.1200x900.jpg",
        "oud_pad":  "voetbalreizen-manchester-city",
        "nieuw_pad": "voetbalreizen-bayern-munchen",
        "alt":      "Voetbalreizen Bayern München",
    },
    {
        "oud_src":  "6a329fae8251c9e35829edb4.png",   # Liverpool
        "nieuw_src": "https://static.number1-voetbalreizen.nl/site/storage/files/208636/voetbalreizen_borussia_dortmund.1200x900.jpeg",
        "oud_pad":  "voetbalreizen-liverpool",
        "nieuw_pad": "voetbalreizen-borussia-dortmund",
        "alt":      "Voetbalreizen Borussia Dortmund",
    },
    {
        "oud_src":  "6a329fae8251c9e35829edb6.png",   # Arsenal
        "nieuw_src": "https://static.number1-voetbalreizen.nl/site/storage/files/208595/voetbalreizen_bayer_04_leverkusen.1200x900.jpg",
        "oud_pad":  "voetbalreizen-arsenal",
        "nieuw_pad": "voetbalreizen-bayer-leverkusen",
        "alt":      "Voetbalreizen Bayer Leverkusen",
    },
    {
        "oud_src":  "6a329fae900836a937211362.png",   # Tottenham
        "nieuw_src": "https://static.number1-voetbalreizen.nl/site/storage/files/208745/voetbalreizen_rb_leipzig-1.1200x900.jpg",
        "oud_pad":  "voetbalreizen-tottenham-hotspur",
        "nieuw_pad": "voetbalreizen-rb-leipzig",
        "alt":      "Voetbalreizen RB Leipzig",
    },
    {
        "oud_src":  "6a329fae8251c9e35829edb5.png",   # Manchester United
        "nieuw_src": "https://static.number1-voetbalreizen.nl/site/storage/files/208667/voetbalreizen_eintracht_frankfurt.1200x900.png",
        "oud_pad":  "voetbalreizen-manchester-united",
        "nieuw_pad": "voetbalreizen-eintracht-frankfurt",
        "alt":      "Voetbalreizen Eintracht Frankfurt",
    },
]

CTA_OUD_PAD  = "voetbalreizen-premier-league"
CTA_NIEUW_PAD = "voetbalreizen-bundesliga"
CTA_TEKST_1_OUD  = "Ontdek alle voetbalreizen naar Engeland"
CTA_TEKST_1_NIEUW = "Ontdek alle Bundesliga-voetbalreizen"
CTA_TEKST_2_OUD  = "Bekijk de mooiste wedstrijden"
CTA_TEKST_2_NIEUW = "Bekijk het Bundesliga-aanbod"

# ── Hulpfuncties ──────────────────────────────────────────────────────────────

def brevo_get(path):
    result = subprocess.run(
        ["curl", "-s", "-X", "GET", f"{BREVO_BASE}{path}",
         "-H", f"api-key: {API_KEY}",
         "-H", "accept: application/json"],
        capture_output=True
    )
    return json.loads(result.stdout.decode("utf-8"))


def brevo_post(path, payload):
    result = subprocess.run(
        ["curl", "-s", "-w", "\n%{http_code}",
         "-X", "POST", f"{BREVO_BASE}{path}",
         "-H", f"api-key: {API_KEY}",
         "-H", "Content-Type: application/json",
         "-d", json.dumps(payload, ensure_ascii=False).encode("utf-8")],
        capture_output=True
    )
    output = result.stdout.decode("utf-8").strip().split("\n")
    http_code = output[-1]
    body = json.loads("\n".join(output[:-1]))
    return int(http_code), body

# ── Uitvoering ────────────────────────────────────────────────────────────────

print(f"Stap 1: Campagne {TEMPLATE_ID} ophalen als template...")
template = brevo_get(f"/emailCampaigns/{TEMPLATE_ID}")

if "htmlContent" not in template:
    print(f"Fout: htmlContent niet gevonden. Antwoord: {template}")
    sys.exit(1)

html = template["htmlContent"]
print(f"  Template: {template['name']}")
print(f"  HTML-grootte: {len(html):,} tekens")

# 1. Intro-tekst vervangen
print("Stap 2: Intro-tekst vervangen...")
nieuwe_div = (
    f'<p class="default" style="margin: 0;">{INTRO_1}</p>'
    f'<p class="default" style="margin: 0;"><br></p>'
    f'<p class="default" style="margin: 0;">{INTRO_2}</p>'
)
patroon = r'(<td[^>]+class="r13-i nl2go-default-textstyle"[^>]*>\s*<div>)(.+?)(</div>\s*</td>)'
html, n = re.subn(patroon, rf'\1{nieuwe_div}\3', html, flags=re.DOTALL)
print(f"  {'Vervangen' if n else 'Niet gevonden (ongewijzigd)'}")

# 2. Club-afbeeldingen, links en alt-teksten vervangen
print("Stap 3: Club-afbeeldingen en links vervangen...")
for club in CLUB_VERVANGINGEN:
    # src vervangen (img.mailinblue.com URL bevat de unieke hash)
    html = html.replace(club["oud_src"], club["nieuw_src"])
    # href pad vervangen
    html = html.replace(club["oud_pad"], club["nieuw_pad"])
    # alt-tekst vervangen
    print(f"  {club['oud_pad'].replace('voetbalreizen-', '')} -> {club['nieuw_pad'].replace('voetbalreizen-', '')}")

# 3. CTA-knoppen: pad en tekst vervangen
print("Stap 4: CTA-knoppen aanpassen...")
html = html.replace(CTA_OUD_PAD, CTA_NIEUW_PAD)
html = html.replace(CTA_TEKST_1_OUD, CTA_TEKST_1_NIEUW)
html = html.replace(CTA_TEKST_2_OUD, CTA_TEKST_2_NIEUW)
print(f"  CTA pad: {CTA_OUD_PAD} ->{CTA_NIEUW_PAD}")
print(f"  Knoptekst 1: {CTA_TEKST_1_NIEUW}")
print(f"  Knoptekst 2: {CTA_TEKST_2_NIEUW}")

# 4. UTM-parameters bijwerken
print("Stap 5: UTM-parameters bijwerken...")
html = html.replace(UTM_OUD, UTM_NIEUW)
print(f"  utm_campaign: {UTM_NIEUW}")

# 5. Campagne aanmaken als concept
today = datetime.now().strftime("%Y-%m-%d")
naam      = f"NR1 Bundesliga 2026-2027 - {today}"
onderwerp = "Bundesliga 2026/2027: beleef de mooiste wedstrijden"
preheader = "Het nieuwe seizoen begint. Ontdek Bayern, Dortmund, Leverkusen, Leipzig en Frankfurt."

print(f"Stap 6: Concept-campagne aanmaken in Brevo...")
print(f"  Naam:      {naam}")
print(f"  Onderwerp: {onderwerp}")

payload = {
    "name":        naam,
    "subject":     onderwerp,
    "previewText": preheader,
    "sender":      {"id": template["sender"]["id"]},
    "type":        "classic",
    "htmlContent": html,
    # Geen scheduledAt ->blijft draft
    # Geen recipients ->toe te voegen vóór echte verzending
}

http_code, response = brevo_post("/emailCampaigns", payload)

if http_code == 201:
    campaign_id = response.get("id")
    print()
    print("=" * 55)
    print("Bundesliga-campagne aangemaakt als concept (draft).")
    print(f"Campagne-ID : {campaign_id}")
    print(f"Status      : draft — er is NIETS verstuurd.")
    print(f"Controleer in Brevo onder Campaigns.")
    print("=" * 55)
else:
    print(f"Fout (HTTP {http_code}):")
    print(json.dumps(response, indent=2))
    sys.exit(1)
