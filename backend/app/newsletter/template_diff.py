"""Leesbaar verschil tussen twee versies van een template.

De tool-proof-knop verandert een geplakte export op tientallen plekken. Zonder
zicht daarop moet de admin de code zelf vergelijken; met een unified diff kan de
UI precies tonen wat er is vervangen. Puur tekstwerk, geen HTML-parser: we willen
laten zien wat er letterlijk anders is, niet wat de browser ervan maakt.
"""

from __future__ import annotations

from difflib import unified_diff

# Een grote Stripo-export levert duizenden regels; de UI heeft genoeg aan het
# begin en de admin kan de volledige HTML altijd in het tekstvak lezen.
MAX_DIFF_LINES = 2000


def unified_html_diff(
    before: str,
    after: str,
    *,
    before_label: str = "origineel",
    after_label: str = "tool-proof",
    context: int = 3,
) -> str:
    """Unified diff tussen twee HTML-teksten; lege string als er niets wijzigde."""
    lines = list(
        unified_diff(
            (before or "").splitlines(keepends=True),
            (after or "").splitlines(keepends=True),
            fromfile=before_label,
            tofile=after_label,
            n=context,
        )
    )
    if not lines:
        return ""
    if len(lines) > MAX_DIFF_LINES:
        overslagen = len(lines) - MAX_DIFF_LINES
        lines = lines[:MAX_DIFF_LINES]
        lines.append(f"\n... ({overslagen} regels niet getoond)\n")
    return "".join(lines)
