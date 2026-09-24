"""JSON-schema's van de tools die Claude in de chat mag aanroepen.

Alleen beschrijvingen en invoerschema's; het uitvoeren zit in de *_tools-modules.
preview_newsletter wordt afgeleid van create_newsletter_draft, zodat de twee nooit
uit elkaar lopen.
"""

from __future__ import annotations

import copy

from app.newsletter.history_tool import SCHEMA as _HISTORY_SCHEMA
from app.newsletter.styles import COLOR_KEYS, EMAIL_SAFE_FONTS, FONT_KEY, SPACING_KEYS

TOOL_DEFINITIONS = [
    {
        "name": "get_brand_config",
        "description": "Haal de merk-configuratie (kleuren, afzender, socials, claude_prompt, "
        "matches_url) van de huidige tenant op. De huisstijl staat al in je instructies: "
        "alleen aanroepen als je een configuratieveld mist, niet elke beurt.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "analyze_website_tone",
        "description": "Analyseer de tone of voice en schrijfstijl van de klantensite, zodat je "
        "de teksten in dezelfde stijl schrijft. Optioneel een specifieke URL; anders de "
        "website_url uit de brand-config. Roep dit aan voor je teksten schrijft.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Optionele pagina-URL om de stijl van te lezen"}
            },
        },
    },
    {
        "name": "list_images",
        "description": "Lijst de geüploade foto's van deze tenant, met bestandsnaam, omschrijving, "
        "categorie en url. Roep eerst ZONDER categorie aan om alles te zien. Gebruik dit om een bannerfoto "
        "te kiezen en per wedstrijd de juiste clubfoto te matchen op bestandsnaam/omschrijving "
        "(bv. een Arsenal-wedstrijd -> een arsenal-foto).",
        "input_schema": {
            "type": "object",
            "properties": {"category": {"type": "string", "description": "Optioneel; weglaten geeft alle foto's met hun categorie, zodat je niet hoeft te gokken welke categorieen er zijn."}},
            "required": [],
        },
    },
    {
        "name": "find_matches",
        "description": "Haal de ECHTE, beschikbare wedstrijden van de klantensite op, met "
        "thuisclub, uitclub, de echte ticket-URL en de vanafprijs. Gebruik UITSLUITEND "
        "wedstrijden uit deze lijst. Optioneel een specifieke listing-URL meegeven; anders "
        "wordt de matches_url uit de brand-config gebruikt.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Optionele listing-/competitiepagina-URL"}
            },
        },
    },
    {
        "name": "find_ticket_links",
        "description": "Zoek bereikbare pagina's op de klantensite die passen bij een zoekopdracht: "
        "club-, competitie- of wedstrijdpagina's, maar ook cases, blogposts, producten, acties of "
        "andere inhoud. Gebruik dit altijd om een geldige, echte link te vinden voor een blok. "
        "Optioneel een specifieke pagina-URL om in te zoeken (bv. de bron-URL van de nieuwsbrief-soort).",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Bijvoorbeeld een clubnaam, competitie, of het soort inhoud ('recente blogposts', 'cases')"},
                "url": {"type": "string", "description": "Optionele pagina-URL om in te zoeken"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "find_products",
        "description": "Haal de producten van een collectie- of overzichtspagina van de "
        "klantensite: naam, prijs, productfoto en product-URL, alles exact zoals op de "
        "pagina. Gebruik dit voor product-nieuwsbrieven zodat de gebruiker uit ECHTE "
        "producten kiest; foto en prijs komen zo altijd van de site. Leest ALLE pagina's van "
        "de collectie (niet alleen de eerste) en meldt het totaal en of de catalogus volledig "
        "is. Zoek je iets specifieks (bv. 'zilveren ringen'), geef dan query mee: die filtert "
        "de hele catalogus. Zonder url wordt de bron-URL van de nieuwsbrief-soort of de "
        "website gebruikt.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Collectie-/overzichtspagina om te scannen, bv. de source_url van de gekozen nieuwsbrief-soort"},
                "query": {"type": "string", "description": "Optioneel: zoekwoorden om de catalogus te filteren, bv. 'zilveren ringen' of 'armband goud'"},
            },
        },
    },
    {
        "name": "find_page_images",
        "description": "Foto's op een pagina van de klantensite die als BANNER/header kunnen: "
        "liggend beeld (minimaal 600px breed) en vierkante webshopfoto's die de shop zelf liggend "
        "bijsnijdt. Gemeten, ontdaan van logo's, iconen, pixels, videoframes en egale beelden, en "
        "elk met een 'beschrijving' van wat er echt op staat (kies op thema). Bedoeld voor de BANNER, "
        "niet voor productfoto's. Gebruik dit als list_images geen bannerfoto heeft: bijna elke "
        "site heeft zelf een liggende hero-foto. GEBRUIK DIT NOOIT om te checken of een los "
        "product/wedstrijd/club een foto heeft: die foto's zijn vaak vierkant of staand (tellen "
        "hier dus niet mee, ook al bestaan ze) en worden AUTOMATISCH gevonden door "
        "preview_newsletter/create_newsletter_draft (via de og:image van de eigen pagina). "
        "Kijk na preview_newsletter naar image_url in matches_used/clubs_used/items_used om te "
        "zien wat er echt is gebruikt; 0 resultaten hier zegt daar niets over. Toon de opties met "
        "naam en formaat en laat de gebruiker kiezen; verzin nooit zelf een beeld-URL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Pagina-URL om foto's van te halen; zonder URL de homepage van het bedrijf"},
            },
        },
    },
    {
        "name": "find_banner",
        "description": "Haal het eigen bannerbeeld van een pagina van de klantensite "
        "(bv. de collectiepagina waar de nieuwsbrief over gaat). Het beeld wordt "
        "genormaliseerd naar mail-formaat en in code gecheckt op bereikbaarheid. "
        "Heeft de pagina zelf geen banner, dan krijg je de banners van de gelinkte "
        "collecties als 'candidates' terug: toon die en laat de gebruiker kiezen. "
        "Gebruik dit voor de headerfoto als er geen passende bannerfoto in "
        "list_images('banner') staat; laat de gebruiker het resultaat bevestigen.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Pagina-URL om de banner van te pakken, bv. de collectie- of source_url van de gekozen nieuwsbrief-soort"},
            },
        },
    },
    {
        "name": "create_newsletter_draft",
        "description": "Render de nieuwsbrief en zet hem als CONCEPT klaar bij het "
        "verzendplatform van dit bedrijf (Brevo, Klaviyo of ActiveCampaign). Verstuurt "
        "niets. Is er in dit gesprek al een concept gemaakt, dan wordt dat bijgewerkt "
        "(zelfde campagne) zolang het daar nog een concept is. Gebruik "
        "alleen echte inhoud (find_matches/find_products/find_ticket_links); links en "
        "prijzen worden live gevalideerd.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "theme": {"type": "string"},
                "header_title": {"type": "string", "description": "Korte pakkende kop op de headerfoto"},
                "header_subtitle": {"type": "string", "description": "Korte ondertitel onder de kop"},
                "header_cta_text": {"type": "string", "description": "Tekst van de knop op de headerfoto, bv. 'Bekijk alle wedstrijden'. De link is automatisch gelijk aan main_cta_url."},
                "intro_1": {"type": "string"},
                "intro_2": {"type": "string"},
                "main_cta_text": {"type": "string"},
                "main_cta_url": {"type": "string"},
                "slot_cta_text": {"type": "string"},
                "slot_cta_url": {"type": "string"},
                "preview_text": {"type": "string"},
                "confirmed": {"type": "boolean", "description": "Zet alleen op true NADAT de gebruiker expliciet toestemming heeft gegeven om het concept in Brevo aan te maken"},
                "new_draft": {"type": "boolean", "description": "Standaard wordt een concept dat in DIT gesprek al is aangemaakt BIJGEWERKT (zelfde campagne) in plaats van een nieuw concept te maken. Zet alleen op true als de gebruiker expliciet een APART, extra concept wil (bv. een tweede variant)."},
                "header_image_url": {"type": "string", "description": "De bannerfoto: een BESTANDSNAAM uit list_images('banner') (bv. 'allianz-arena.jpg'), of de volledige banner_url die find_banner teruggaf. Nooit een zelf verzonnen URL."},
                "header_text_color": {"type": "string", "description": "Optioneel: hex-kleur voor de kop en ondertitel op de bannerfoto, bv. '#ffffff'. Alleen meegeven als de gebruiker om een andere kleur vraagt; standaard geldt de kopkleur uit de stijl-builder."},
                "matches": {
                    "type": "array",
                    "description": "Wedstrijdblokken. Mag leeg zijn voor een ALGEMENE nieuwsbrief "
                    "(zonder losse wedstrijden); zorg dan dat de knoppen naar een bereikbare "
                    "algemene/competitie-/clubpagina verwijzen.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "home": {"type": "string"},
                            "away": {"type": "string"},
                            "url": {"type": "string", "description": "Bereikbare ticket-URL (uit find_matches of find_ticket_links)"},
                            "price": {"type": "string", "description": "Handmatige vanafprijs. Zonder price_override alleen de terugval als de site geen prijs heeft; met price_override=true wint deze prijs van de site."},
                            "price_override": {"type": "boolean", "description": "Zet ALLEEN op true als de gebruiker EXPLICIET een eigen prijs voor dit blok heeft opgegeven; dan wint 'price' van de site-prijs. Nooit op eigen initiatief gebruiken."},
                            "image_url": {"type": "string", "description": "BESTANDSNAAM van de gematchte foto uit list_images (niet de volledige URL)"},
                            "label": {"type": "string", "description": "Optioneel kort badge-label op de kaart, bv. 'NIEUW' of 'TOPPER'. Alleen zetten als de gebruiker erom vraagt of het duidelijk klopt."},
                        },
                        "required": ["home", "away", "url"],
                    },
                },
                "clubs": {
                    "type": "array",
                    "description": "Club-blokken (i.p.v. of naast wedstrijden): per club een naam en "
                    "een bereikbare clubpagina-URL (uit find_ticket_links). Optioneel price/image_url.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "url": {"type": "string", "description": "Bereikbare clubpagina-URL"},
                            "price": {"type": "string", "description": "Handmatige vanafprijs. Zonder price_override alleen de terugval als de site geen prijs heeft; met price_override=true wint deze prijs van de site."},
                            "price_override": {"type": "boolean", "description": "Zet ALLEEN op true als de gebruiker EXPLICIET een eigen prijs voor dit blok heeft opgegeven; dan wint 'price' van de site-prijs. Nooit op eigen initiatief gebruiken."},
                            "image_url": {"type": "string", "description": "BESTANDSNAAM van de clubfoto uit list_images (niet de volledige URL)"},
                            "stadium": {"type": "string", "description": "Naam van het stadion (klein lettertype in het blok)"},
                            "city": {"type": "string", "description": "Naam van de stad (klein lettertype in het blok)"},
                            "label": {"type": "string", "description": "Optioneel kort badge-label op de kaart, bv. 'VROEGBOEKKORTING' of 'NIEUW'. Alleen zetten als de gebruiker erom vraagt of het duidelijk klopt."},
                        },
                        "required": ["name", "url"],
                    },
                },
                "items": {
                    "type": "array",
                    "description": "Generieke inhoudsblokken voor niet-voetbal nieuwsbrieven "
                    "(cases, blogposts, producten, acties, vacatures). Per item een titel, "
                    "korte subtitel en een BEREIKBARE pagina-URL (uit find_ticket_links).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "subtitle": {"type": "string", "description": "Korte ondertitel (klein lettertype in het blok)"},
                            "url": {"type": "string", "description": "Bereikbare pagina-URL (uit find_ticket_links)"},
                            "button_text": {"type": "string", "description": "Knoptekst van dit blok, bv. 'Lees de case' of 'SHOP NU'. Gebruik de knoptekst van de nieuwsbrief-soort."},
                            "price": {"type": "string", "description": "Optionele prijs (bv. uit find_products). Wordt zonder price_override live her-gecheckt op de pagina (site wint). Weglaten = geen prijs tonen."},
                            "price_override": {"type": "boolean", "description": "Zet ALLEEN op true als de gebruiker EXPLICIET een eigen prijs voor dit blok heeft opgegeven; dan wint 'price' van de site-prijs. Nooit op eigen initiatief gebruiken."},
                            "image_url": {"type": "string", "description": "Foto: de image_url uit find_products (volledige URL) of een BESTANDSNAAM uit list_images. Weglaten = automatisch de productfoto (og:image) van de pagina."},
                            "label": {"type": "string", "description": "Optioneel kort badge-label, bv. 'NIEUW'"},
                        },
                        "required": ["title", "url"],
                    },
                },
                "custom_fields": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "Template-eigen invulvakken: sommige templates hebben vrije "
                    "tekstvakken ({{VAK_*}}). De preview-uitvoer meldt welke vakken de gekozen "
                    "template heeft. Vul per vak de tekst, sleutel = vaknaam (bv. 'ARTIKEL_TITEL'). "
                    "COPY SCHRIJF JE ZELF, FEITEN NOOIT: merk-/marketingteksten (artikelen, "
                    "kolommen, Q&A over het assortiment, banners) schrijf je zelf in de tone of "
                    "voice en passend bij het thema, precies zoals de intro's. Maar vakken die "
                    "echte feiten vereisen (namen van personen, interviews, projecten, prijzen, "
                    "quotes, datums, foto-URL's) vul je ALLEEN met informatie die de gebruiker gaf "
                    "of die je met tools hebt opgehaald; ontbreekt die, laat het vak dan leeg of "
                    "vraag ernaar. Vakken die je leeg laat zijn veilig: een ##SECTIE##-blok zonder "
                    "inhoud wordt automatisch uit de mail weggelaten (een los vak buiten zo'n blok "
                    "wordt een lege tekst).",
                },
                "sections": {
                    "type": "array",
                    "description": "OPTIONELE opbouw voor templates met de "
                    "<!-- ##SECTIES## --> marker: de secties worden in deze volgorde "
                    "gerenderd (de opzet die je met de gebruiker hebt besproken). "
                    "Weglaten = de vaste opzet van de template.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": ["hero", "text", "blocks", "button"],
                                     "description": "hero = klikbare foto; text = alinea; blocks = de gekozen wedstrijden/clubs/items; button = losse knop"},
                            "text": {"type": "string", "description": "Tekst (voor text en button)"},
                            "url": {"type": "string", "description": "Bereikbare link (voor hero en button)"},
                            "image_url": {"type": "string", "description": "Hero-foto: BESTANDSNAAM uit list_images of volledige URL"},
                            "style": {"type": "string", "enum": ["cards", "banners"],
                                      "description": "Voor blocks: cards (naast elkaar) of banners (onder elkaar)"},
                        },
                        "required": ["kind"],
                    },
                },
            },
            "required": [
                "subject",
                "theme",
                "intro_1",
                "intro_2",
                "main_cta_text",
                "main_cta_url",
                "slot_cta_text",
                "slot_cta_url",
            ],
        },
    },
]


# preview_newsletter heeft exact dezelfde velden als create_newsletter_draft, maar
# zonder 'confirmed' (er gaat niets naar Brevo). We leiden de schema af zodat de twee
# nooit uit elkaar lopen.
_draft_def = next(t for t in TOOL_DEFINITIONS if t["name"] == "create_newsletter_draft")
_preview_schema = copy.deepcopy(_draft_def["input_schema"])
_preview_schema["properties"].pop("confirmed", None)
_preview_schema["properties"].pop("new_draft", None)
TOOL_DEFINITIONS.append(
    {
        "name": "preview_newsletter",
        "description": "Render een VOORBEELD van de nieuwsbrief en toon het direct aan de "
        "gebruiker in het voorbeeldpaneel naast de chat. Maakt NIETS aan in Brevo. Roep dit "
        "ALTIJD eerst aan en laat de gebruiker het voorbeeld zien, voordat je toestemming "
        "vraagt voor create_newsletter_draft. Zelfde velden (zonder 'confirmed'); links en "
        "prijzen worden net zo live gevalideerd en gescrapet.",
        "input_schema": _preview_schema,
    }
)


_STYLE_KEY_UITLEG = {
    "button_bg": "achtergrondkleur van de knoppen op de product-/wedstrijdkaarten",
    "button_text": "tekstkleur op de kaart-knoppen",
    "hero_button_bg": "achtergrondkleur van de knop op de bannerfoto (volgt button_bg tot je 'm zet)",
    "hero_button_text": "tekstkleur op de bannerknop",
    "cta_button_bg": "achtergrondkleur van de grote knop onderaan (volgt button_bg tot je 'm zet)",
    "cta_button_text": "tekstkleur op de onderste knop",
    "accent": "accentkleur (o.a. banner-elementen en kaart-titels)",
    "heading_color": "kopkleur op de headerfoto",
    "text_color": "kleur van de introtekst",
    "link_color": "linkkleur in lopende tekst",
    "page_bg": "achtergrond van de hele e-mail",
    "footer_bg": "achtergrond van de footer-balk",
    "footer_text": "tekstkleur in de footer",
    "card_bg": "achtergrond van een kaart",
    "card_border": "randkleur van een kaart",
    "block_border": "randkleur van het wedstrijd-/productblok",
    "price_color": "kleur van prijsbedragen",
    "badge_bg": "achtergrond van badge-labels",
    "home_color": "thuisclubnaam in het wedstrijdblok",
    "away_color": "uitclubnaam in het wedstrijdblok",
}

# Stijl voor ALLEEN deze nieuwsbrief: de template blijft de vaste basis; deze
# overrides gaan alleen mee in de render van dit gesprek (en erven mee via
# last_preview). De template zelf pas je aan in de stijl-builder, niet via chat.
_STYLE_OVERRIDES_SCHEMA = {
    "type": "object",
    "description": (
        "Kleuren/lettertype/witruimte voor ALLEEN deze nieuwsbrief; de template "
        "blijft ongewijzigd als basis. Geef alleen de sleutels die moeten "
        "afwijken; hex-kleuren zoals '#000000'. Sleutels: "
        + "; ".join(f"{k} = {v}" for k, v in _STYLE_KEY_UITLEG.items())
        + "; font_family (mail-veilig lettertype); witruimte in px (0-200): "
        + ", ".join(SPACING_KEYS)
        + " (banner->intro, intro->producten, producten->tekst, tekst->onderste "
        "knop). Render daarna altijd opnieuw."
    ),
    "properties": {
        **{key: {"type": "string"} for key in COLOR_KEYS},
        FONT_KEY: {"type": "string", "enum": sorted(EMAIL_SAFE_FONTS)},
        **{key: {"type": "integer"} for key in SPACING_KEYS},
    },
}
_draft_def["input_schema"]["properties"]["style_overrides"] = _STYLE_OVERRIDES_SCHEMA
_preview_schema["properties"]["style_overrides"] = _STYLE_OVERRIDES_SCHEMA

TOOL_DEFINITIONS.append(_HISTORY_SCHEMA)
