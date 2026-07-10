"""Rendert nieuwsbrief-HTML uit een template, brand-config en content.

Pure functies, geen I/O: zelfde input geeft altijd zelfde output. Brevo-runtime
placeholders zoals `{{ contact.EMAIL }}` en `{{ unsubscribe }}` blijven staan; die
worden bewust niet vervangen.
"""

from __future__ import annotations

import re

from app.newsletter.card_block import render_template_cards
from app.newsletter.custom_fields import fill_custom_fields
from app.newsletter.models import (
    PRICE_ON_REQUEST,
    Club,
    Item,
    Match,
    NewsletterContent,
    Section,
)
from app.newsletter.styles import effective_styles, style_replacements

BANNER_MARKER = "<!-- ##BANNERS## -->"
CARD_MARKER = "<!-- ##CARDS## -->"
SECTIONS_MARKER = "<!-- ##SECTIES## -->"

# Onze interne placeholders zijn HOOFDLETTERS_MET_UNDERSCORE zonder spaties. Brevo-tags
# ({{ contact.EMAIL }}, {{ unsubscribe }}) hebben spaties/kleine letters en matchen dus
# niet: die blijven bewust staan. Hiermee strippen we alleen ongevulde eigen placeholders,
# zodat elke template-structuur schoon rendert.
_INTERNAL_PLACEHOLDER = re.compile(r"{{[A-Z0-9_]+}}")

# Alleen wat de mail echt nodig heeft is verplicht; adres/telefoon/KVK/socials zijn
# optioneel en worden bij ontbreken netjes weggelaten (zie _footer_contact).
REQUIRED_BRAND_FIELDS = (
    "brand_name",
    "brand_email",
    "website_url",
    "primary_color",
    "logo_url",
    "dummy_image_url",
)


def _require_brand_fields(brand: dict) -> None:
    missing = [f for f in REQUIRED_BRAND_FIELDS if not brand.get(f)]
    if missing:
        raise ValueError(f"brand-config mist verplichte velden: {', '.join(missing)}")


def club_image_url(club: str, brand: dict) -> str:
    """Zoek de clubafbeelding op. Lege of ontbrekende waarde valt terug op dummy."""
    key = club.lower().replace(" ", "-")
    url = brand.get("club_images", {}).get(key, "")
    return url or brand["dummy_image_url"]


def _price_parts(price: str) -> tuple[str, str]:
    """Splits een prijs in ("v.a.", bedrag) voor de prijs-pil.

    De prijs bevat al een euroteken (bv "€ 249"); geen extra € toevoegen.
    Bij "op aanvraag" tonen we geen "v.a." en geen bedrag-opmaak.
    """
    if price == PRICE_ON_REQUEST:
        return "", "op aanvraag"
    return "v.a.", price


def _price_pill(price_va: str, price_amount: str, price_c: str) -> str:
    """De ronde prijs-pil ("v.a." + bedrag) in de wedstrijd- en clubbanners."""
    return f"""<table align="center" cellspacing="0" cellpadding="0" border="0" role="presentation"
      style="margin:0 auto 12px auto; border:2px solid #dddddd; border-radius:50px; background:#ffffff;">
    <tbody><tr><td align="center" class="price-pill" style="width:90px; padding:9px 12px; text-align:center;">
      <span class="price-va" style="display:block; font-family:Arial,sans-serif; font-size:11px; color:#666; line-height:1.4;">{price_va}</span>
      <span class="price-amount" style="display:block; font-family:Arial,sans-serif; font-size:17px; font-weight:bold; color:{price_c}; line-height:1.2;">{price_amount}</span>
    </td></tr></tbody></table>"""


def _banner_title(text: str, color: str) -> str:
    """De grote titelregel (22px, hoofdletters) van club- en itembanners."""
    return f"""<p class="home-name"
      style="margin:0 0 6px 0; font-family:Impact,'Arial Black',Arial,sans-serif; font-size:22px; font-weight:900; color:{color}; text-transform:uppercase; letter-spacing:1px; line-height:1.1;">{text.upper()}</p>"""


def _subtitle_line(text: str | None) -> str:
    """Optionele kleine regel onder de titel (stadion/stad of item-subtitel)."""
    if not text:
        return ""
    return (
        f'<p class="club-venue" style="margin:0 0 10px 0; font-family:Arial,Helvetica,sans-serif; '
        f'font-size:11px; color:#888888; line-height:1.3;">{text}</p>'
    )


def _banner_shell(
    *, st: dict, img_url: str, img_alt: str, body: str, button_text: str, button_url: str
) -> str:
    """Gedeelde omlijsting van alle bannerblokken.

    Buitentabel met rand, foto-kolom links, de titelregels/prijs (body) rechts,
    de knop eronder en de vaste spacer na het blok.
    """
    color = st["block_border"]
    btn_bg, btn_text = st["button_bg"], st["button_text"]
    return f"""
<table cellspacing="0" cellpadding="0" border="0" role="presentation" width="584" align="center"
  class="banner-wrap"
  style="table-layout:fixed; width:584px; border:3px solid {color}; border-radius:6px; border-collapse:separate; background-color:#ffffff;">
<tbody><tr>
  <td width="220" class="img-col"
    style="width:220px; overflow:hidden; padding:0; border-radius:4px 0 0 4px; vertical-align:middle; background-color:#ffffff;">
    <img src="{img_url}" width="220" height="220" border="0" alt="{img_alt}"
      class="banner-img" style="display:block; width:220px; height:220px;">
  </td>
  <td valign="middle" align="center" class="content-col"
    style="padding:18px 16px 18px 12px; text-align:center; vertical-align:middle; background-color:#ffffff; border-radius:0 4px 4px 0;">
    {body}
    <table align="center" cellspacing="0" cellpadding="0" border="0" role="presentation"
      style="background:{btn_bg}; border-radius:4px; border-collapse:separate;">
    <tbody><tr><td class="cta-btn" style="padding:12px 18px; border-radius:4px;">
      <a href="{button_url}" target="_blank"
        style="color:{btn_text}; font-family:Arial,sans-serif; font-size:14px; font-weight:bold; text-decoration:none; white-space:nowrap;">{button_text}</a>
    </td></tr></tbody></table>
  </td>
</tr></tbody></table>
<table cellspacing="0" cellpadding="0" border="0" width="100%" style="table-layout:fixed;">
<tbody><tr><td height="8" style="font-size:8px; line-height:8px;">&nbsp;</td></tr></tbody></table>"""


def render_banner(match: Match, brand: dict) -> str:
    """Bouw het HTML-tabelblok voor één wedstrijd. De link is de echte ticket-URL."""
    st = effective_styles(brand)
    home_c, away_c = st["home_color"], st["away_color"]
    price_va, price_amount = _price_parts(match.price)
    body = f"""<p class="home-name"
      style="margin:0 0 4px 0; font-family:Impact,'Arial Black',Arial,sans-serif; font-size:20px; font-weight:900; color:{home_c}; text-transform:uppercase; letter-spacing:1px; line-height:1.1;">{match.home.upper()}</p>
    <p class="vs-line"
      style="margin:0 0 4px 0; font-family:Arial,sans-serif; font-size:11px; color:#aaaaaa; letter-spacing:2px;">&#8212; VS &#8212;</p>
    <p class="away-name"
      style="margin:0 0 12px 0; font-family:Impact,'Arial Black',Arial,sans-serif; font-size:20px; font-weight:900; color:{away_c}; text-transform:uppercase; letter-spacing:1px; line-height:1.1;">{match.away.upper()}</p>
    {_price_pill(price_va, price_amount, st["price_color"])}"""
    return _banner_shell(
        st=st,
        img_url=match.image_url or club_image_url(match.home, brand),
        img_alt=match.home,
        body=body,
        button_text="Bestel tickets",
        button_url=match.url,
    )


def render_club_banner(club: Club, brand: dict) -> str:
    """Bouw een club-blok: clubnaam, foto, prijs en een link naar de clubpagina."""
    st = effective_styles(brand)
    price_va, price_amount = _price_parts(club.price)
    venue = " · ".join(p for p in (club.stadium, club.city) if p)
    body = f"""{_banner_title(club.name, st["away_color"])}
    {_subtitle_line(venue)}
    {_price_pill(price_va, price_amount, st["price_color"])}"""
    return _banner_shell(
        st=st,
        img_url=club.image_url or club_image_url(club.name, brand),
        img_alt=club.name,
        body=body,
        button_text="Bekijk alle wedstrijden",
        button_url=club.url,
    )


def render_item_banner(item: Item, brand: dict) -> str:
    """Bouw een generiek item-blok (case, blog, product, actie) in banner-stijl.

    Zelfde opmaak als het clubblok, maar de prijs is optioneel en de knoptekst
    komt uit het item zelf (bv. "Lees de case" of "Bekijk aanbieding").
    """
    st = effective_styles(brand)
    price_html = ""
    if item.price:
        # Prijs zonder "v.a."-regel: items tonen alleen het (letterlijke) bedrag.
        price_html = (
            '<table align="center" cellspacing="0" cellpadding="0" border="0" role="presentation" '
            'style="margin:0 auto 12px auto; border:2px solid #dddddd; border-radius:50px; background:#ffffff;">'
            '<tbody><tr><td align="center" class="price-pill" style="width:90px; padding:9px 12px; text-align:center;">'
            f'<span class="price-amount" style="display:block; font-family:Arial,sans-serif; font-size:17px; '
            f'font-weight:bold; color:{st["price_color"]}; line-height:1.2;">{item.price}</span>'
            "</td></tr></tbody></table>"
        )
    body = f"""{_banner_title(item.title, st["away_color"])}
    {_subtitle_line(item.subtitle)}
    {price_html}"""
    return _banner_shell(
        st=st,
        img_url=item.image_url or club_image_url(item.title, brand),
        img_alt=item.title,
        body=body,
        button_text=item.button_text,
        button_url=item.url,
    )


def _card_cell(
    *, title: str, subtitle: str, img_url: str, price: str | None, button_text: str,
    button_url: str, brand: dict, label: str | None = None,
) -> str:
    """Eén kaart-cel (foto boven, optioneel label, naam, subtitel, prijs, knop).

    price=None betekent: geen prijsregel tonen (voor items zonder prijs, zoals blogs).
    """
    st = effective_styles(brand)
    if not price:
        price_va, price_amount = "", ""
    elif price == PRICE_ON_REQUEST:
        price_va, price_amount = "", "op aanvraag"
    else:
        price_va, price_amount = "v.a.", price
    label_html = (
        f'<span style="display:inline-block; font-family:{st["font"]}; font-size:9px; '
        'font-weight:bold; padding:3px 7px; border-radius:3px; letter-spacing:0.5px; '
        f'margin-bottom:6px; background:{st["badge_bg"]}; color:#ffffff;">{label.upper()}</span><br>'
        if label
        else ""
    )
    subtitle_html = (
        f'<p style="margin:0 0 10px 0; font-family:{st["font"]}; font-size:11px; '
        f'color:#999999; line-height:1.4;">{subtitle}</p>'
        if subtitle
        else ""
    )
    va_html = (
        f'<span style="display:block; font-family:{st["font"]}; font-size:10px; color:#888888; '
        f'line-height:1.2; margin:0;">{price_va}</span>'
        if price_va
        else ""
    )
    price_amount_html = (
        f'<span style="display:block; font-family:{st["font"]}; font-size:22px; font-weight:bold; '
        f'color:{st["price_color"]}; line-height:1.1; margin:0 0 6px 0;">{price_amount}</span>'
        if price_amount
        else ""
    )
    return f"""<td class="card-cell" width="290" valign="top" style="width:290px; vertical-align:top;">
  <table class="card" cellspacing="0" cellpadding="0" border="0" width="290"
    style="width:290px; border:2px solid {st["card_border"]}; border-radius:6px; border-collapse:separate; background:{st["card_bg"]}; vertical-align:top;">
  <tbody>
    <tr><td style="padding:0; line-height:0; font-size:0; border-radius:4px 4px 0 0; overflow:hidden;">
      <img src="{img_url}" width="290" height="290" border="0" alt="{title}" class="card-img-el" style="display:block; width:290px; height:290px;">
    </td></tr>
    <tr><td style="padding:14px 14px 16px 14px;">
      {label_html}<p style="margin:0 0 3px 0; font-family:Impact,'Arial Black',Arial,sans-serif; font-size:18px; font-weight:900; color:{st["accent"]}; text-transform:uppercase; letter-spacing:1px; line-height:1.2;">{title.upper()}</p>
      {subtitle_html}
      {va_html}
      {price_amount_html}
      <table cellspacing="0" cellpadding="0" border="0" width="100%" style="border-radius:4px; border-collapse:separate; background:{st["button_bg"]};">
      <tbody><tr><td align="center" style="padding:10px; border-radius:4px;">
        <a href="{button_url}" target="_blank" style="color:{st["button_text"]}; font-family:{st["font"]}; font-size:13px; font-weight:bold; text-decoration:none; white-space:nowrap;">{button_text}</a>
      </td></tr></tbody></table>
    </td></tr>
  </tbody></table>
</td>"""


def _empty_card_cell() -> str:
    """Lege cel om een oneven laatste kaart links uit te lijnen op 290px."""
    return '<td class="card-cell" width="290" style="width:290px;">&nbsp;</td>'


def render_cards(
    matches: tuple[Match, ...],
    clubs: tuple[Club, ...],
    brand: dict,
    items: tuple[Item, ...] = (),
) -> str:
    """Render wedstrijden, clubs en generieke items als een responsive 2-koloms kaart-grid.

    Wedstrijden worden 'HOME' met ondertitel 'vs AWAY'; clubs de clubnaam met
    stadion/stad; items hun eigen titel/subtitel/knoptekst. Leeg geeft "" terug.
    """
    cells: list[str] = []
    for m in matches:
        cells.append(
            _card_cell(
                title=m.home,
                subtitle=f"vs {m.away}",
                img_url=m.image_url or club_image_url(m.home, brand),
                price=m.price,
                button_text="Bestel tickets",
                button_url=m.url,
                brand=brand,
                label=m.label,
            )
        )
    for c in clubs:
        venue = " &bull; ".join(p for p in (c.stadium, c.city) if p)
        cells.append(
            _card_cell(
                title=c.name,
                subtitle=venue,
                img_url=c.image_url or club_image_url(c.name, brand),
                price=c.price,
                button_text="Bekijk alle wedstrijden",
                button_url=c.url,
                brand=brand,
                label=c.label,
            )
        )
    for it in items:
        cells.append(
            _card_cell(
                title=it.title,
                subtitle=it.subtitle or "",
                img_url=it.image_url or club_image_url(it.title, brand),
                price=it.price,
                button_text=it.button_text,
                button_url=it.url,
                brand=brand,
                label=it.label,
            )
        )
    if not cells:
        return ""

    spacer = '<td class="card-spacer" width="10" style="width:10px; font-size:0; line-height:0;">&nbsp;</td>'
    gap = (
        '<table cellspacing="0" cellpadding="0" border="0" width="100%"><tbody><tr>'
        '<td height="14" style="font-size:14px; line-height:14px;">&nbsp;</td></tr></tbody></table>'
    )
    rows: list[str] = []
    for i in range(0, len(cells), 2):
        left = cells[i]
        right = cells[i + 1] if i + 1 < len(cells) else _empty_card_cell()
        rows.append(
            '<table class="card-outer" cellspacing="0" cellpadding="0" border="0" width="590" align="center" '
            'style="width:590px; table-layout:fixed; border-collapse:collapse;"><tbody><tr>'
            f"{left}{spacer}{right}"
            "</tr></tbody></table>"
        )
    # Trailing gap zodat wat na de kaarten komt (bv. de slot-knop) niet te dicht aansluit.
    return gap.join(rows) + gap


def _section_hero(section: Section) -> str:
    """Klikbare foto over de volle breedte (zoals de hero in webshop-templates)."""
    img = (
        f'<img src="{section.image_url}" width="600" alt="" '
        'style="display:block;outline:none;text-decoration:none;height:auto;width:100%;">'
    )
    inner = f'<a href="{section.url}" target="_blank" style="display:block;">{img}</a>' if section.url else img
    return (
        '<table cellspacing="0" cellpadding="0" border="0" role="presentation" width="100%" '
        'style="table-layout:fixed;"><tbody><tr><td style="padding:0; font-size:0; line-height:0;">'
        f"{inner}</td></tr></tbody></table>"
    )


def _section_text(section: Section, st: dict) -> str:
    return (
        '<table cellspacing="0" cellpadding="0" border="0" role="presentation" width="100%" '
        'style="table-layout:fixed;"><tbody><tr><td style="padding:22px 40px;">'
        f'<p style="margin:0; font-family:{st["font"]}; font-size:15px; line-height:1.6; '
        f'color:{st["text_color"]};">{section.text}</p>'
        "</td></tr></tbody></table>"
    )


def _section_button(section: Section, st: dict) -> str:
    return (
        '<table cellspacing="0" cellpadding="0" border="0" role="presentation" width="100%" '
        'style="table-layout:fixed;"><tbody><tr><td align="center" style="padding:10px 20px 24px;">'
        '<table cellspacing="0" cellpadding="0" border="0" role="presentation" '
        f'style="background:{st["cta_button_bg"]}; border-radius:4px; border-collapse:separate;">'
        '<tbody><tr><td align="center" style="padding:13px 30px; border-radius:4px;">'
        f'<a href="{section.url}" target="_blank" style="color:{st["cta_button_text"]}; '
        f'font-family:{st["font"]}; font-size:14px; font-weight:bold; text-decoration:none; '
        f'white-space:nowrap; display:inline-block;">{section.text}</a>'
        "</td></tr></tbody></table></td></tr></tbody></table>"
    )


def render_sections(content: NewsletterContent, brand: dict) -> str:
    """Render de opzet-secties in volgorde (voor templates met de ##SECTIES##-marker).

    Elke sectie-soort wordt in code gerenderd (garanties blijven in code); "blocks"
    hergebruikt de bestaande kaart-/banner-renderers voor de gekozen inhoud.
    """
    st = effective_styles(brand)
    parts: list[str] = []
    for section in content.sections:
        if section.kind == "hero" and section.image_url:
            parts.append(_section_hero(section))
        elif section.kind == "text" and section.text:
            parts.append(_section_text(section, st))
        elif section.kind == "button" and section.text and section.url:
            parts.append(_section_button(section, st))
        elif section.kind == "blocks":
            if section.style == "banners":
                blocks = "".join(render_banner(m, brand) for m in content.matches)
                blocks += "".join(render_club_banner(c, brand) for c in content.clubs)
                blocks += "".join(render_item_banner(i, brand) for i in content.items)
            else:
                blocks = render_cards(content.matches, content.clubs, brand, content.items)
            parts.append(blocks)
    return "".join(parts)


def _footer_contact(brand: dict) -> str:
    """Contactregels voor de footer: alleen wat het bedrijf heeft ingevuld.

    Zo is een telefoonnummer of KVK niet verplicht en blijven er geen lege
    labels ("Tel:") achter in de mail.
    """
    lines: list[str] = []
    if brand.get("brand_adres"):
        lines.append(brand["brand_adres"])
    if brand.get("brand_postcode_stad"):
        lines.append(brand["brand_postcode_stad"])
    if brand.get("brand_email"):
        lines.append(f"E-mail: {brand['brand_email']}")
    if brand.get("brand_telefoon"):
        lines.append(f"Tel: {brand['brand_telefoon']}")
    if brand.get("brand_kvk"):
        lines.append(f"KVK-nummer: {brand['brand_kvk']}")
    return "<br>".join(lines)


def _render_hero_cta(brand: dict, content: NewsletterContent) -> str:
    """Bouw de CTA-knop over de headerfoto.

    De tekst is instelbaar (header_cta_text); de LINK is altijd dezelfde als de
    hoofd-knop (main_cta_url), zodat beide knoppen naar dezelfde plek gaan.
    """
    # Fallback op de hoofd-knoptekst (verplicht veld): de knop heeft dus ALTIJD
    # tekst, ook voor niet-voetbalklanten (geen hardcoded voetbaltekst meer).
    text = content.header_cta_text or content.main_cta_text
    url = content.main_cta_url  # verplicht veld; de knop op de foto volgt de hoofd-knop
    st = effective_styles(brand)
    return (
        '<table align="center" cellspacing="0" cellpadding="0" border="0" role="presentation" '
        f'style="margin:0 auto; background:{st["hero_button_bg"]}; border-radius:4px; border-collapse:separate;">'
        '<tbody><tr><td class="hero-cta" style="padding:13px 24px; border-radius:4px;">'
        f'<a href="{url}" target="_blank" style="color:{st["hero_button_text"]}; font-family:{st["font"]}; '
        'font-size:15px; font-weight:bold; text-decoration:none; white-space:nowrap; display:inline-block;">'
        f"{text}</a></td></tr></tbody></table>"
    )


def render_newsletter(template: str, brand: dict, content: NewsletterContent) -> str:
    """Vul placeholders en banners in. Geeft de volledige HTML terug.

    Zonder wedstrijden levert dit een algemene nieuwsbrief op (alleen header, intro
    en knoppen, geen wedstrijdblokken).
    """
    _require_brand_fields(brand)

    replacements = {
        "{{EMAIL_TITEL}}": f"{content.theme} | {brand['brand_name']}",
        "{{HEADER_IMAGE_URL}}": content.header_image_url or brand.get("header_image_url", ""),
        "{{HEADER_TITEL}}": content.header_title or content.theme,
        "{{HEADER_SUBTITEL}}": content.header_subtitle or "",
        "{{HEADER_CTA}}": _render_hero_cta(brand, content),
        # Voor templates die hun EIGEN heroknop-markup behouden (toolproof):
        # alleen de knoptekst wisselt; de link is {{HOOFD_CTA_URL}} in de markup.
        "{{HEADER_CTA_TEKST}}": content.header_cta_text or content.main_cta_text,
        "{{WEBSITE_URL}}": brand["website_url"],
        "{{LOGO_URL}}": brand["logo_url"],
        "{{BRAND_NAME}}": brand["brand_name"],
        "{{BRAND_ADRES}}": brand.get("brand_adres", ""),
        "{{BRAND_POSTCODE_STAD}}": brand.get("brand_postcode_stad", ""),
        "{{BRAND_EMAIL}}": brand["brand_email"],
        "{{BRAND_TELEFOON}}": brand.get("brand_telefoon", ""),
        "{{BRAND_KVK}}": brand.get("brand_kvk", ""),
        "{{FOOTER_CONTACT}}": _footer_contact(brand),
        "{{FACEBOOK_URL}}": brand.get("facebook_url") or brand["website_url"],
        "{{INSTAGRAM_URL}}": brand.get("instagram_url") or brand["website_url"],
        "{{YOUTUBE_URL}}": brand.get("youtube_url") or brand["website_url"],
        "{{INTRO_1}}": content.intro_1,
        "{{INTRO_2}}": content.intro_2,
        "{{HOOFD_CTA_TEKST}}": content.main_cta_text,
        "{{HOOFD_CTA_URL}}": content.main_cta_url,
        "{{SLOT_CTA_TEKST}}": content.slot_cta_text,
        "{{SLOT_CTA_URL}}": content.slot_cta_url,
        **style_replacements(brand),
    }
    # Per-nieuwsbrief kopkleur (bv. "maak de titel wit"): wint van de stijl-builder.
    if content.header_text_color:
        replacements["{{STYLE_HEADING_COLOR}}"] = content.header_text_color
    html = template
    for placeholder, value in replacements.items():
        html = html.replace(placeholder, value)

    banners = "".join(render_banner(m, brand) for m in content.matches)
    banners += "".join(render_club_banner(c, brand) for c in content.clubs)
    banners += "".join(render_item_banner(i, brand) for i in content.items)
    html = html.replace(BANNER_MARKER, banners)
    # Kaart-stijl blok (alternatief voor banners): een template gebruikt het ene OF het
    # andere; de marker die er niet is, is gewoon een no-op.
    html = html.replace(
        CARD_MARKER, render_cards(content.matches, content.clubs, brand, content.items)
    )
    # Opzet-composer: secties in de gekozen volgorde op de secties-marker (shell-templates).
    html = html.replace(SECTIONS_MARKER, render_sections(content, brand))
    # Template-eigen kaarten: het ##KAART##-blok herhaalt de markup van de klant
    # zelf per blok (het ontwerp blijft van de klant, wij vullen alleen de data).
    html = render_template_cards(html, brand, content, image_fallback=club_image_url)
    # Template-eigen invulvakken ({{VAK_*}}); secties zonder inhoud vervallen in code.
    html = fill_custom_fields(html, dict(content.custom_fields))
    # Ruim ongevulde eigen placeholders op (bv. als een template een veld weglaat of
    # een onbekende toevoegt), zodat er nooit een rauwe {{IETS}} in de mail belandt.
    return _INTERNAL_PLACEHOLDER.sub("", html)
