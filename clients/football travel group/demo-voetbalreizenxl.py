#!/usr/bin/env python3
"""
Demo: VoetbalreizenXL nieuwsbrief aanmaken als concept in Brevo.
Gebruikt templates/voetbalreizenxl-main.html + templates/brand/voetbalreizenxl.json.
Verstuurt NIETS. Campagne staat na afloop als concept (draft) in Brevo.
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ── Paden ─────────────────────────────────────────────────────────────────────

BASE        = Path(__file__).parent
TEMPLATE    = BASE / "templates" / "voetbalreizenxl-main.html"
BRAND_JSON  = BASE / "templates" / "brand" / "voetbalreizenxl.json"
ENV_FILE    = BASE / ".env"

# ── .env inladen ──────────────────────────────────────────────────────────────

if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())

API_KEY = os.environ.get("BREVO_API_KEY")
if not API_KEY:
    print("Fout: BREVO_API_KEY niet gevonden in .env")
    sys.exit(1)

BREVO_BASE = "https://api.brevo.com/v3"

# ── Campagne-inhoud (pas hier aan per nieuwsbrief) ────────────────────────────

THEMA     = "Kerst in Londen"
ONDERWERP = "Kerst in Londen: voetbal op z'n best"

INTRO_1 = (
    "December in Londen is een ervaring op zich. De stad licht op, de sfeer in en "
    "rond de stadions is elektrisch en op het veld wordt er gespeeld met alles erop "
    "en eraan. Kerstvoetbal in Engeland is een traditie die nergens anders zo voelt als hier."
)
INTRO_2 = (
    "Wij hebben drie wedstrijden voor je geselecteerd die je dit seizoen niet wilt missen. "
    "Combineer een dag vol voetbal met een weekendje Londen en maak er een trip van "
    "om nooit te vergeten."
)

HOOFD_CTA_TEKST = "Bekijk alle kerst-wedstrijden"
HOOFD_CTA_URL   = "https://www.voetbalreizenxl.nl/tickets/premier-league/"
SLOT_CTA_TEKST  = "Plan jouw kersttrip naar Londen"
SLOT_CTA_URL    = "https://www.voetbalreizenxl.nl/tickets/premier-league/"

WEDSTRIJDEN = [
    {
        "thuisclub": "Chelsea",
        "uitclub":   "Crystal Palace",
        "prijs":     "299,-",
        "slug":      "chelsea-crystal-palace",
    },
    {
        "thuisclub": "Tottenham",
        "uitclub":   "Manchester United",
        "prijs":     "249,-",
        "slug":      "tottenham-hotspur-manchester-united",
    },
    {
        "thuisclub": "Crystal Palace",
        "uitclub":   "Hull City",
        "prijs":     "129,-",
        "slug":      "crystal-palace-hull-city",
    },
]

# ── Hulpfuncties ──────────────────────────────────────────────────────────────

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


def club_image_url(club_naam: str, brand: dict) -> str:
    """Zoek afbeelding op via club_images lookup. Fallback: dummy_image_url."""
    sleutel = club_naam.lower().replace(" ", "-")
    url = brand.get("club_images", {}).get(sleutel, "")
    return url if url else brand["dummy_image_url"]


def genereer_banner(wedstrijd: dict, brand: dict) -> str:
    """Bouw een banner-tabelblok op basis van een wedstrijd-dict."""
    img_url    = club_image_url(wedstrijd["thuisclub"], brand)
    link       = f"{brand['base_tickets_url']}{wedstrijd['slug']}/"
    thuisclub  = wedstrijd["thuisclub"].upper()
    uitclub    = wedstrijd["uitclub"].upper()
    prijs      = wedstrijd["prijs"]

    return f"""
<table cellspacing="0" cellpadding="0" border="0" role="presentation" width="584" align="center"
  class="banner-wrap"
  style="table-layout:fixed; width:584px; border:3px solid #FF7200; border-radius:6px; border-collapse:separate; background-color:#ffffff;">
<tbody><tr>
  <td width="220" class="img-col"
    style="width:220px; overflow:hidden; padding:0; border-radius:4px 0 0 4px; vertical-align:middle; background-color:#ffffff;">
    <img src="{img_url}" width="220" height="220" border="0" alt="{wedstrijd['thuisclub']}"
      class="banner-img"
      style="display:block; width:220px; height:220px;">
  </td>
  <td valign="middle" align="center" class="content-col"
    style="padding:18px 16px 18px 12px; text-align:center; vertical-align:middle; background-color:#ffffff; border-radius:0 4px 4px 0;">
    <p class="home-name"
      style="margin:0 0 4px 0; font-family:Impact,'Arial Black',Arial,sans-serif; font-size:20px; font-weight:900; color:#00AEEF; text-transform:uppercase; letter-spacing:1px; line-height:1.1;">{thuisclub}</p>
    <p class="vs-line"
      style="margin:0 0 4px 0; font-family:Arial,sans-serif; font-size:11px; color:#aaaaaa; letter-spacing:2px;">&#8212; VS &#8212;</p>
    <p class="away-name"
      style="margin:0 0 12px 0; font-family:Impact,'Arial Black',Arial,sans-serif; font-size:20px; font-weight:900; color:#1a3a6e; text-transform:uppercase; letter-spacing:1px; line-height:1.1;">{uitclub}</p>
    <table align="center" cellspacing="0" cellpadding="0" border="0" role="presentation"
      style="margin:0 auto 12px auto; border:2px solid #dddddd; border-radius:50px; background:#ffffff;">
    <tbody><tr><td align="center" class="price-pill" style="width:90px; padding:9px 12px; text-align:center;">
      <span class="price-va" style="display:block; font-family:Arial,sans-serif; font-size:11px; color:#666; line-height:1.4;">v.a.</span>
      <span class="price-amount" style="display:block; font-family:Arial,sans-serif; font-size:17px; font-weight:bold; color:#111; line-height:1.2;">&euro;&nbsp;{prijs}</span>
    </td></tr></tbody></table>
    <table align="center" cellspacing="0" cellpadding="0" border="0" role="presentation"
      style="background:#FF7200; border-radius:4px; border-collapse:separate;">
    <tbody><tr><td class="cta-btn" style="padding:12px 18px; border-radius:4px;">
      <a href="{link}" target="_blank"
        style="color:#ffffff; font-family:Arial,sans-serif; font-size:14px; font-weight:bold; text-decoration:none; white-space:nowrap;">Bestel tickets</a>
    </td></tr></tbody></table>
  </td>
</tr></tbody></table>
<table cellspacing="0" cellpadding="0" border="0" width="100%" style="table-layout:fixed;">
<tbody><tr><td height="8" style="font-size:8px; line-height:8px;">&nbsp;</td></tr></tbody></table>"""


# ── Uitvoering ────────────────────────────────────────────────────────────────

print("Stap 1: Brand config en template inladen...")
brand    = json.loads(BRAND_JSON.read_text(encoding="utf-8"))
html     = TEMPLATE.read_text(encoding="utf-8")
print(f"  Brand: {brand['brand_name']}")
print(f"  Template: {TEMPLATE.name} ({len(html):,} tekens)")

print("Stap 2: Placeholders invullen...")
vervangingen = {
    "{{EMAIL_TITEL}}":      f"{THEMA} | {brand['brand_name']}",
    "{{WEBSITE_URL}}":      brand["website_url"],
    "{{HEADER_IMAGE_URL}}": brand["header_image_url"],
    "{{LOGO_URL}}":         brand["logo_url"],
    "{{BRAND_NAME}}":       brand["brand_name"],
    "{{BRAND_ADRES}}":      brand["brand_adres"],
    "{{BRAND_POSTCODE_STAD}}": brand["brand_postcode_stad"],
    "{{BRAND_EMAIL}}":      brand["brand_email"],
    "{{BRAND_TELEFOON}}":   brand["brand_telefoon"],
    "{{BRAND_KVK}}":        brand["brand_kvk"],
    "{{FACEBOOK_URL}}":     brand["facebook_url"],
    "{{INSTAGRAM_URL}}":    brand["instagram_url"],
    "{{YOUTUBE_URL}}":      brand["youtube_url"],
    "{{INTRO_1}}":          INTRO_1,
    "{{INTRO_2}}":          INTRO_2,
    "{{HOOFD_CTA_TEKST}}":  HOOFD_CTA_TEKST,
    "{{HOOFD_CTA_URL}}":    HOOFD_CTA_URL,
    "{{SLOT_CTA_TEKST}}":   SLOT_CTA_TEKST,
    "{{SLOT_CTA_URL}}":     SLOT_CTA_URL,
}
for placeholder, waarde in vervangingen.items():
    html = html.replace(placeholder, waarde)

print("Stap 3: Banners genereren...")
banners_html = ""
for w in WEDSTRIJDEN:
    img = club_image_url(w["thuisclub"], brand)
    is_dummy = img == brand["dummy_image_url"]
    print(f"  {w['thuisclub']} vs {w['uitclub']} - v.a. {w['prijs']} {'(dummy img)' if is_dummy else ''}")
    banners_html += genereer_banner(w, brand)

html = html.replace("<!-- ##BANNERS## -->", banners_html)

print("Stap 4: Campagne aanmaken als concept in Brevo...")
naam = f"{brand['brand_name']} - {THEMA} - {datetime.now().strftime('%Y-%m-%d')}"
print(f"  Naam:      {naam}")
print(f"  Onderwerp: {ONDERWERP}")

payload = {
    "name":        naam,
    "subject":     ONDERWERP,
    "previewText": f"{INTRO_1[:80]}...",
    "sender": {
        "name":  brand["brand_name"],
        "email": brand["brand_email"],
    },
    "type":        "classic",
    "htmlContent": html,
    # Geen scheduledAt: blijft draft
    # Geen recipients: toe te voegen voor echte verzending
}

http_code, response = brevo_post("/emailCampaigns", payload)

if http_code == 201:
    campaign_id = response.get("id")
    print()
    print("=" * 55)
    print("Campagne aangemaakt als concept (draft).")
    print(f"Campagne-ID : {campaign_id}")
    print(f"Wedstrijden : {len(WEDSTRIJDEN)}")
    print(f"Status      : draft - er is NIETS verstuurd.")
    print("Controleer in Brevo onder Campaigns.")
    print("=" * 55)
else:
    print(f"Fout (HTTP {http_code}):")
    print(json.dumps(response, indent=2))
    sys.exit(1)
