"""Feiten uit eerder verstuurde campagnes in het verzendplatform (alleen-lezen).

get_recent_newsletters kent alleen nieuwsbrieven die in deze app zijn gemaakt. Een
klant die al jaren mailt (Runderkamp: 139 campagnes in ActiveCampaign) heeft daar
prijzen, voorwaarden en reviews in staan die de chat anders niet kent, waardoor
die blokken leeg bleven. Deze tool leest de laatste verstuurde campagnes als kale
tekst.

Een feit uit een oude campagne is niet per se nog waar. Daarom komt elke campagne
met haar verzenddatum terug, plus een vaste instructie (in code, niet alleen in de
prompt) om de datum te noemen en prijzen op de site te controleren.

Eerst ActiveCampaign; Brevo en Klaviyo melden netjes dat het nog niet kan.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.newsletter.tool_context import ToolContext, load_tenant
from app.services.esp_connection import ESP_ERRORS, EspFactories, connect

DEFAULT_LIMIT = 3
MAX_LIMIT = 5

LET_OP = (
    "Feiten hieruit (prijzen, voorwaarden, reviews, data) waren waar op de datum van "
    "die campagne, niet per se nu. Noem bij gebruik de datum van de bron aan de "
    "gebruiker. Controleer een prijs eerst op de site (find_products of de pagina "
    "zelf); staat hij daar niet, vraag de gebruiker of hij nog klopt. Neem een review "
    "alleen letterlijk over, met naam zoals in de campagne. Verzin niets bij."
)

SCHEMA = {
    "name": "get_esp_campaigns",
    "description": "De laatst VERSTUURDE campagnes uit het verzendplatform van dit bedrijf "
    "(ook campagnes die buiten deze app zijn gemaakt): datum, naam, onderwerp en de tekst "
    "van de mail. Gebruik dit als bron van FEITEN die je anders niet hebt, zoals prijzen, "
    "voorwaarden (bv. minimum aantal personen, bezorggebied) en echte reviews, vooral als "
    "de template vakken heeft voor prijs, stappen of review. Alleen-lezen. Feiten hieruit "
    "zijn mogelijk verouderd: volg de instructie in 'let_op'.",
    "input_schema": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": f"Aantal campagnes (standaard {DEFAULT_LIMIT}, max {MAX_LIMIT})",
            },
        },
    },
}


def _limit(tool_input: dict) -> int:
    try:
        limit = int(tool_input.get("limit") or DEFAULT_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    return max(1, min(limit, MAX_LIMIT))


def _datum(sent_at: str) -> str:
    """ISO-tijd van het platform naar dd-mm-jjjj (Nederlandse tijd); anders zoals het is."""
    try:
        moment = datetime.fromisoformat(sent_at)
    except ValueError:
        return sent_at or "onbekend"
    if moment.tzinfo is not None:
        moment = moment.astimezone(ZoneInfo("Europe/Amsterdam"))
    return moment.strftime("%d-%m-%Y")


def _tool_get_esp_campaigns(ctx: ToolContext, tool_input: dict) -> dict:
    factories = EspFactories(ctx.brevo_factory, ctx.klaviyo_factory, ctx.activecampaign_factory)
    conn = connect(ctx.session, ctx.cipher, load_tenant(ctx), factories)
    reader = getattr(conn.client, "get_past_campaigns", None)
    if reader is None:
        return {
            "count": 0,
            "campagnes": [],
            "message": f"Oude campagnes lezen kan nog niet voor {conn.label}.",
        }
    try:
        campagnes = reader(limit=_limit(tool_input))
    except ESP_ERRORS as exc:
        raise ValueError(f"{conn.label}: oude campagnes konden niet worden gelezen ({exc})") from exc
    return {
        "count": len(campagnes),
        "campagnes": [
            {
                "datum": _datum(c.sent_at),
                "naam": c.name,
                "onderwerp": c.subject,
                "tekst": c.text,
            }
            for c in campagnes
        ],
        "let_op": LET_OP,
    }


HANDLERS = {"get_esp_campaigns": _tool_get_esp_campaigns}
