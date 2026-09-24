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
    "find_page_images": "Foto's op de pagina bekijken",
    "preview_newsletter": "Voorbeeld samenstellen",
    "create_newsletter_draft": "Concept klaarzetten",
    "get_recent_newsletters": "Eerdere nieuwsbrieven bekijken",
}


def describe(event: ToolEvent) -> str:
    """Een regel over wat er zojuist is gedaan; nooit leeg."""
    if event.error:
        return f"{_bezig(event.name)}: mislukt ({_kort(event.error)})"
    resultaat = event.result or {}
    maker = _MAKERS.get(event.name)
    regel = maker(event.input or {}, resultaat) if maker is not None else None
    regel = regel or f"{_bezig(event.name)}: klaar"
    # Uit het werkgeheugen van dit gesprek (tool_memory.py): geen nieuwe pagina-fetch
    # of LLM-extractie, zodat zichtbaar blijft waarom dit stapje meteen klaar was.
    if resultaat.get("from_memory"):
        regel += " (al eerder in dit gesprek opgehaald)"
    return regel


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
    totaal = resultaat.get("total_in_catalog")
    zoek = resultaat.get("query")
    aantal = resultaat.get("count", len(producten))
    if totaal is not None and zoek:
        regel = f"{aantal} producten voor '{zoek}' gevonden in {totaal}"
    elif totaal is not None:
        regel = f"{totaal} producten opgehaald"
    else:
        regel = f"{len(producten)} items opgehaald"
    regel += f" van {bron}" if bron else ""
    if totaal is not None and not resultaat.get("complete", True):
        regel += " (niet volledig)"
    return regel


def _afbeeldingen(invoer: dict, resultaat: dict) -> str:
    images = resultaat.get("images") or []
    categorie = (invoer.get("category") or "").strip()
    if categorie:
        return f"{len(images)} foto's in de bibliotheek onder '{categorie}'"
    categorieen = resultaat.get("categories") or []
    if not images:
        return "Bibliotheek is leeg voor dit bedrijf"
    return f"{len(images)} foto's in de bibliotheek ({', '.join(categorieen)})"


def _banner(invoer: dict, resultaat: dict) -> str:
    bron = _pad(resultaat.get("source_url") or invoer.get("url") or "")
    waar = f" op {bron}" if bron else ""
    kandidaten = len(resultaat.get("candidates") or [])
    if resultaat.get("banner_url"):
        alternatieven = len(resultaat.get("alternatives") or [])
        extra = f", plus {alternatieven} alternatieven" if alternatieven else ""
        return f"Banner gevonden{waar}{extra}"
    if kandidaten:
        return f"Geen og:image-banner{waar}, wel {kandidaten} foto's om uit te kiezen"
    return f"Geen bruikbare bannerfoto{waar}"


def _pagina_fotos(invoer: dict, resultaat: dict) -> str:
    bron = _pad(resultaat.get("source_url") or invoer.get("url") or "")
    aantal = resultaat.get("count", len(resultaat.get("images") or []))
    return f"{aantal} bruikbare foto's gevonden" + (f" op {bron}" if bron else "")


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
    if resultaat.get("updated_existing_draft"):
        return f"Bestaand concept bijgewerkt in {esp} met {blokken} blokken; niets verstuurd"
    return f"Concept aangemaakt in {esp} met {blokken} blokken; niets verstuurd"


def _eerdere(invoer: dict, resultaat: dict) -> str:
    aantal = resultaat.get("count") or 0
    return f"{aantal} eerdere nieuwsbrieven bekeken" if aantal else "Nog geen eerdere nieuwsbrieven"


def _tone(invoer: dict, resultaat: dict) -> str:
    return "Schrijfstijl bepaald" if resultaat.get("tone_of_voice") else "Schrijfstijl opgehaald"


_MAKERS = {
    "find_matches": _matches,
    "find_ticket_links": _links,
    "find_products": _producten,
    "list_images": _afbeeldingen,
    "find_banner": _banner,
    "find_page_images": _pagina_fotos,
    "preview_newsletter": _voorbeeld,
    "create_newsletter_draft": _concept,
    "analyze_website_tone": _tone,
    "get_recent_newsletters": _eerdere,
}
