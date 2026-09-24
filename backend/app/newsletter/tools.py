"""Tool-laag voor de Claude-orchestratie.

Publiek aanspreekpunt: de tool-schema's (tool_schemas), de context (tool_context)
en de dispatcher die ze uitvoert tegen de database, de site-extractie en Brevo. Alle
neveneffecten (DB-writes, Brevo-call) gebeuren hier, niet in het taalmodel.

Site-agnostisch: `find_matches` laat het LLM de echte wedstrijden + prijzen + URL's
van de klantensite halen. `create_newsletter_draft` valideert elke URL hard
(moet bestaan) en scrapet de prijs live van die pagina, zodat link en prijs altijd
echt zijn, ongeacht hoe de site is opgebouwd.

Uitvoering per onderwerp: site_tools (site en fotobibliotheek lezen),
block_validation (links, prijzen, foto's), newsletter_build (renderen + preview) en
draft_tool (concept bij het verzendplatform).
"""

from __future__ import annotations

from collections.abc import Callable

from app.newsletter import draft_tool, newsletter_build, site_tools
from app.newsletter.tool_context import DEFAULT_TEMPLATE, ToolContext
from app.newsletter.tool_schemas import TOOL_DEFINITIONS

__all__ = ["DEFAULT_TEMPLATE", "TOOL_DEFINITIONS", "ToolContext", "execute_tool"]

_DISPATCH: dict[str, Callable[[ToolContext, dict], dict]] = {
    **site_tools.HANDLERS,
    **newsletter_build.HANDLERS,
    **draft_tool.HANDLERS,
}


def execute_tool(name: str, tool_input: dict, ctx: ToolContext) -> dict:
    handler = _DISPATCH.get(name)
    if handler is None:
        raise ValueError(f"onbekende tool: {name}")
    return handler(ctx, tool_input)
