"""Gedeelde interface voor verzendplatform-adapters (ESP's).

Eén contract, meerdere implementaties (BrevoClient, KlaviyoClient): de draft-tool
kiest per bedrijf de adapter op basis van tenant.config["esp"]. Alle adapters maken
uitsluitend CONCEPTEN aan; geen enkele implementatie heeft een verzendmethode.
"""

from __future__ import annotations

from typing import Any, Protocol


class EspDraft(Protocol):
    """Resultaat van create_draft; campaign_id is int (Brevo) of str (Klaviyo)."""

    campaign_id: Any


class EspClient(Protocol):
    def create_draft(
        self,
        *,
        name: str,
        subject: str,
        sender_name: str,
        sender_email: str,
        html: str,
        list_ids: list | None = None,
        preview_text: str | None = None,
        reply_to: str | None = None,
    ) -> EspDraft: ...
