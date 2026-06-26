"""Rendert nieuwsbrief-HTML uit een template, brand-config en content.

Pure functies, geen I/O: zelfde input geeft altijd zelfde output. Brevo-runtime
placeholders zoals `{{ contact.EMAIL }}` en `{{ unsubscribe }}` blijven staan; die
worden bewust niet vervangen.
"""

from __future__ import annotations

from app.newsletter.models import Match, NewsletterContent

BANNER_MARKER = "<!-- ##BANNERS## -->"

REQUIRED_BRAND_FIELDS = (
    "brand_name",
    "brand_email",
    "brand_adres",
    "brand_postcode_stad",
    "brand_telefoon",
    "brand_kvk",
    "website_url",
    "base_tickets_url",
    "primary_color",
    "logo_url",
    "header_image_url",
    "dummy_image_url",
    "facebook_url",
    "instagram_url",
    "youtube_url",
)

# Decoratieve kleuren in de banner (niet merk-specifiek geconfigureerd).
_HOME_COLOR = "#00AEEF"
_AWAY_COLOR = "#1a3a6e"


def _require_brand_fields(brand: dict) -> None:
    missing = [f for f in REQUIRED_BRAND_FIELDS if not brand.get(f)]
    if missing:
        raise ValueError(f"brand-config mist verplichte velden: {', '.join(missing)}")


def club_image_url(club: str, brand: dict) -> str:
    """Zoek de clubafbeelding op. Lege of ontbrekende waarde valt terug op dummy."""
    key = club.lower().replace(" ", "-")
    url = brand.get("club_images", {}).get(key, "")
    return url or brand["dummy_image_url"]


def render_banner(match: Match, brand: dict) -> str:
    """Bouw het HTML-tabelblok voor één wedstrijd. De link is de echte ticket-URL."""
    color = brand["primary_color"]
    img_url = club_image_url(match.home, brand)
    link = match.url
    return f"""
<table cellspacing="0" cellpadding="0" border="0" role="presentation" width="584" align="center"
  class="banner-wrap"
  style="table-layout:fixed; width:584px; border:3px solid {color}; border-radius:6px; border-collapse:separate; background-color:#ffffff;">
<tbody><tr>
  <td width="220" class="img-col"
    style="width:220px; overflow:hidden; padding:0; border-radius:4px 0 0 4px; vertical-align:middle; background-color:#ffffff;">
    <img src="{img_url}" width="220" height="220" border="0" alt="{match.home}"
      class="banner-img" style="display:block; width:220px; height:220px;">
  </td>
  <td valign="middle" align="center" class="content-col"
    style="padding:18px 16px 18px 12px; text-align:center; vertical-align:middle; background-color:#ffffff; border-radius:0 4px 4px 0;">
    <p class="home-name"
      style="margin:0 0 4px 0; font-family:Impact,'Arial Black',Arial,sans-serif; font-size:20px; font-weight:900; color:{_HOME_COLOR}; text-transform:uppercase; letter-spacing:1px; line-height:1.1;">{match.home.upper()}</p>
    <p class="vs-line"
      style="margin:0 0 4px 0; font-family:Arial,sans-serif; font-size:11px; color:#aaaaaa; letter-spacing:2px;">&#8212; VS &#8212;</p>
    <p class="away-name"
      style="margin:0 0 12px 0; font-family:Impact,'Arial Black',Arial,sans-serif; font-size:20px; font-weight:900; color:{_AWAY_COLOR}; text-transform:uppercase; letter-spacing:1px; line-height:1.1;">{match.away.upper()}</p>
    <table align="center" cellspacing="0" cellpadding="0" border="0" role="presentation"
      style="margin:0 auto 12px auto; border:2px solid #dddddd; border-radius:50px; background:#ffffff;">
    <tbody><tr><td align="center" class="price-pill" style="width:90px; padding:9px 12px; text-align:center;">
      <span class="price-va" style="display:block; font-family:Arial,sans-serif; font-size:11px; color:#666; line-height:1.4;">v.a.</span>
      <span class="price-amount" style="display:block; font-family:Arial,sans-serif; font-size:17px; font-weight:bold; color:#111; line-height:1.2;">&euro;&nbsp;{match.price}</span>
    </td></tr></tbody></table>
    <table align="center" cellspacing="0" cellpadding="0" border="0" role="presentation"
      style="background:{color}; border-radius:4px; border-collapse:separate;">
    <tbody><tr><td class="cta-btn" style="padding:12px 18px; border-radius:4px;">
      <a href="{link}" target="_blank"
        style="color:#ffffff; font-family:Arial,sans-serif; font-size:14px; font-weight:bold; text-decoration:none; white-space:nowrap;">Bestel tickets</a>
    </td></tr></tbody></table>
  </td>
</tr></tbody></table>
<table cellspacing="0" cellpadding="0" border="0" width="100%" style="table-layout:fixed;">
<tbody><tr><td height="8" style="font-size:8px; line-height:8px;">&nbsp;</td></tr></tbody></table>"""


def render_newsletter(template: str, brand: dict, content: NewsletterContent) -> str:
    """Vul placeholders en banners in. Geeft de volledige HTML terug."""
    _require_brand_fields(brand)
    if not content.matches:
        raise ValueError("nieuwsbrief heeft minstens één wedstrijd nodig")

    replacements = {
        "{{EMAIL_TITEL}}": f"{content.theme} | {brand['brand_name']}",
        "{{WEBSITE_URL}}": brand["website_url"],
        "{{HEADER_IMAGE_URL}}": brand["header_image_url"],
        "{{LOGO_URL}}": brand["logo_url"],
        "{{BRAND_NAME}}": brand["brand_name"],
        "{{BRAND_ADRES}}": brand["brand_adres"],
        "{{BRAND_POSTCODE_STAD}}": brand["brand_postcode_stad"],
        "{{BRAND_EMAIL}}": brand["brand_email"],
        "{{BRAND_TELEFOON}}": brand["brand_telefoon"],
        "{{BRAND_KVK}}": brand["brand_kvk"],
        "{{FACEBOOK_URL}}": brand["facebook_url"],
        "{{INSTAGRAM_URL}}": brand["instagram_url"],
        "{{YOUTUBE_URL}}": brand["youtube_url"],
        "{{INTRO_1}}": content.intro_1,
        "{{INTRO_2}}": content.intro_2,
        "{{HOOFD_CTA_TEKST}}": content.main_cta_text,
        "{{HOOFD_CTA_URL}}": content.main_cta_url,
        "{{SLOT_CTA_TEKST}}": content.slot_cta_text,
        "{{SLOT_CTA_URL}}": content.slot_cta_url,
    }
    html = template
    for placeholder, value in replacements.items():
        html = html.replace(placeholder, value)

    banners = "".join(render_banner(m, brand) for m in content.matches)
    return html.replace(BANNER_MARKER, banners)
