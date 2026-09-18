"""Tool-stappen vertalen naar een leesbare regel voor in de chat.

Een beurt duurt soms een minuut: pagina's ophalen, prijzen controleren, links
narekenen. Zonder terugkoppeling ziet de gebruiker alleen "Aan het werk...".
Deze module maakt van een ruwe `ToolEvent` een zin die vertelt wat er gebeurde,
inclusief de aantallen die de gebruiker wil weten (hoeveel wedstrijden, welke
pagina, hoeveel prijzen gecontroleerd).

Puur en zonder afhankelijkheden op de orchestrator, zodat het los te testen is.
"""

from __future__ import annotations

from app.newsletter.orchestrator import ToolEvent

# Wat de assistent aan het doen is per tool, als er (nog) geen resultaat is.
_BEZIG = {
    "get_brand_config": "Bedrijfsgegevens ophalen",
    "analyze_website_tone": "Schrijfstijl van de website analyseren",
    "list_images": "Beschikbare afbeeldingen bekijken",
    "find_matches": "Wedstrijden zoeken op de site",
    "find_ticket_links": "Links controleren op de site",
    "find_products": "Aanbod ophalen van de site",
    "find_banner": "Bannerfoto zoeken",
    "preview_newsletter": "Voorbeeld samenstellen",
    "create_newsletter_draft": "Concept klaarzetten",
}


def describe(event: ToolEvent) -> str:
    """Een regel over wat er zojuist is gedaan; nooit leeg."""
    if event.error:
        return f"{_bezig(event.name)}: mislukt ({_kort(event.error)})"
    resultaat = event.result or {}
    maker = _MAKERS.get(event.name)
    if maker is not None:
        regel = maker(event.input or {}, resultaat)
        if regel:
            return regel
    return f"{_bezig(event.name)}: klaar"


def _bezig(naam: str) -> str:
    return _BEZIG.get(naam, naam.replace("_", " ").capitalize())


def _kort(tekst: str, grens: int = 120) -> str:
    tekst = " ".join((tekst or "").split())
    return tekst if len(tekst) <= grens else tekst[: grens - 1] + "..."


def _pad(url: str) -> str:
    """Alleen het pad tonen; de volledige URL maakt de regel onleesbaar."""
    if not url:
        return ""
    zonder = url.split("://", 1)[-1]
    pad = "/" + zonder.split("/", 1)[1] if "/" in zonder else zonder
    return _kort(pad, 60)


def _matches(invoer: dict, resultaat: dict) -> str:
    aantal = resultaat.get("count", len(resultaat.get("matches") or []))
    bron = _pad(resultaat.get("source_url") or invoer.get("url") or "")
    return f"{aantal} wedstrijden gevonden" + (f" op {bron}" if bron else "")


def _links(invoer: dict, resultaat: dict) -> str:
    links = resultaat.get("links") or resultaat.get("results") or []
    bron = _pad(invoer.get("url") or resultaat.get("source_url") or "")
    return f"{len(links)} links gecontroleerd" + (f" op {bron}" if bron else "")


def _producten(invoer: dict, resultaat: dict) -> str:
    producten = resultaat.get("products") or []
    bron = _pad(invoer.get("url") or resultaat.get("source_url") or "")
    return f"{len(producten)} items opgehaald" + (f" van {bron}" if bron else "")


def _afbeeldingen(invoer: dict, resultaat: dict) -> str:
    images = resultaat.get("images") or []
    categorie = invoer.get("category") or ""
    return f"{len(images)} afbeeldingen bekeken" + (f" in '{categorie}'" if categorie else "")


def _banner(invoer: dict, resultaat: dict) -> str:
    return "Bannerfoto gekozen" if resultaat.get("banner_url") else "Geen bannerfoto gevonden"


def _voorbeeld(invoer: dict, resultaat: dict) -> str:
    leeg = resultaat.get("unfilled_fields") or []
    basis = "Voorbeeld gerenderd"
    return f"{basis}; {len(leeg)} invulvakken nog leeg" if leeg else basis


def _concept(invoer: dict, resultaat: dict) -> str:
    esp = (resultaat.get("esp") or "het verzendplatform").capitalize()
    blokken = sum(
        len(resultaat.get(sleutel) or [])
        for sleutel in ("matches_used", "clubs_used", "items_used")
    )
    return f"Concept aangemaakt in {esp} met {blokken} blokken; niets verstuurd"


def _tone(invoer: dict, resultaat: dict) -> str:
    return "Schrijfstijl bepaald" if resultaat.get("tone_of_voice") else "Schrijfstijl opgehaald"


_MAKERS = {
    "find_matches": _matches,
    "find_ticket_links": _links,
    "find_products": _producten,
    "list_images": _afbeeldingen,
    "find_banner": _banner,
    "preview_newsletter": _voorbeeld,
    "create_newsletter_draft": _concept,
    "analyze_website_tone": _tone,
}
