#!/usr/bin/env python3
"""
Demo: nieuwe campagne aanmaken als concept op basis van campagne 871.
Verstuurt NIETS. Campagne staat na afloop als concept (draft) in Brevo.

Gebruik:
  python demo-campagne.py
  python demo-campagne.py --naam "Mijn campagne" --onderwerp "Onderwerp hier"
"""

import json
import os
import re
import subprocess
import sys
import argparse
from datetime import datetime
from pathlib import Path

# .env inladen
env_path = Path(__file__).resolve().parent.parent / ".env"
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

BREVO_BASE = "https://api.brevo.com/v3"
TEMPLATE_ID = 871

# Argumenten
parser = argparse.ArgumentParser()
parser.add_argument("--naam", default=None, help="Campagnenaam (intern in Brevo)")
parser.add_argument("--onderwerp", default=None, help="Onderwerpregel van de e-mail")
parser.add_argument("--intro1", default=None, help="Eerste alinea intro-tekst")
parser.add_argument("--intro2", default=None, help="Tweede alinea intro-tekst")
args = parser.parse_args()

today = datetime.now().strftime("%Y-%m-%d")
campaign_naam = args.naam or f"DEMO - Automatisering test {today}"
campaign_onderwerp = args.onderwerp or "DEMO: Zo werkt de nieuwsbrief-automatisering"

intro1 = args.intro1 or (
    "Dit is een automatisch gegenereerde demo-nieuwsbrief. "
    "De content wordt door Claude Code gegenereerd op basis van een thema en een lijst wedstrijden. "
    "Deze campagne is aangemaakt als concept en wordt niet verstuurd."
)
intro2 = args.intro2 or (
    "Via Slack geeft een accountmanager het thema en de wedstrijden op. "
    "Claude Code haalt de HTML op van een bestaande campagne, vervangt de tekst "
    "en zet de nieuwe campagne klaar als concept in Brevo."
)


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


# Stap 1: Template ophalen
print(f"Stap 1: Campagne {TEMPLATE_ID} ophalen als template...")
template = brevo_get(f"/emailCampaigns/{TEMPLATE_ID}")

if "htmlContent" not in template:
    print(f"Fout: htmlContent niet gevonden. Brevo-antwoord: {template}")
    sys.exit(1)

html = template["htmlContent"]
print(f"  Template: {template['name']}")
print(f"  Sender ID: {template['sender']['id']} ({template['sender']['name']})")
print(f"  HTML-grootte: {len(html):,} tekens")

# Stap 2: Intro-tekst vervangen
print("Stap 2: Intro-tekst vervangen...")

nieuwe_div_inhoud = (
    f'<p class="default" style="margin: 0;">{intro1}</p>'
    f'<p class="default" style="margin: 0;"><br></p>'
    f'<p class="default" style="margin: 0;">{intro2}</p>'
)

# De intro-tekst zit in de td met class r13-i, binnen een <div>
patroon = r'(<td[^>]+class="r13-i nl2go-default-textstyle"[^>]*>\s*<div>)(.+?)(</div>\s*</td>)'
nieuwe_html, vervangingen = re.subn(patroon, rf'\1{nieuwe_div_inhoud}\3', html, flags=re.DOTALL)

if vervangingen > 0:
    print(f"  Intro-tekst vervangen ({vervangingen} blok(ken))")
else:
    print("  Waarschuwing: intro-patroon niet gevonden, HTML ongewijzigd gebruikt")
    nieuwe_html = html

# Stap 3: Nieuwe campagne aanmaken als concept
print(f"Stap 3: Concept-campagne aanmaken in Brevo...")
print(f"  Naam:      {campaign_naam}")
print(f"  Onderwerp: {campaign_onderwerp}")

payload = {
    "name": campaign_naam,
    "subject": campaign_onderwerp,
    "sender": {
        "id": template["sender"]["id"]
    },
    "type": "classic",
    "htmlContent": nieuwe_html
    # Geen scheduledAt: blijft als draft
    # Geen recipients: kan later toegevoegd worden bij echte verzending
}

http_code, response = brevo_post("/emailCampaigns", payload)

if http_code == 201:
    campaign_id = response.get("id")
    print()
    print("=" * 50)
    print("Campagne aangemaakt als concept (draft).")
    print(f"Campagne-ID: {campaign_id}")
    print("Status: draft — er is NIETS verstuurd.")
    print("Controleer in Brevo onder Campaigns.")
    print("=" * 50)
else:
    print(f"Fout bij aanmaken campagne (HTTP {http_code}):")
    print(json.dumps(response, indent=2))
    sys.exit(1)
