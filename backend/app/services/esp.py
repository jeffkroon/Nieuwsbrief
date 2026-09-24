"""Gedeelde interface voor verzendplatform-adapters (ESP's).

Eén contract, meerdere implementaties (BrevoClient, KlaviyoClient,
ActiveCampaignClient): de draft-tool kiest per bedrijf de adapter op basis van
tenant.config["esp"]. Alle adapters maken of wijzigen uitsluitend CONCEPTEN en
lezen resultaten; geen enkele implementatie heeft een verzend- of planmethode.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

# Genormaliseerde campagnestatus, gelijk voor alle platforms.
DRAFT = "draft"
SCHEDULED = "scheduled"
SENDING = "sending"
SENT = "sent"
OTHER = "other"


class CampaignNotFound(Exception):
    """De campagne bestaat niet (meer) in het verzendplatform, bv. handmatig verwijderd."""


@dataclass(frozen=True)
class CampaignResults:
    """Resultaten van één campagne; None = het platform geeft dit getal niet."""

    status: str
    sent: int | None = None
    delivered: int | None = None
    opens_unique: int | None = None
    clicks_unique: int | None = None
    unsubscribes: int | None = None
    bounces: int | None = None
    open_rate: float | None = None
    click_rate: float | None = None

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "sent": self.sent,
            "delivered": self.delivered,
            "opens_unique": self.opens_unique,
            "clicks_unique": self.clicks_unique,
            "unsubscribes": self.unsubscribes,
            "bounces": self.bounces,
            "open_rate": self.open_rate,
            "click_rate": self.click_rate,
        }


def as_int(value: Any) -> int | None:
    """Getal uit een API-antwoord (soms als string), anders None."""
    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def sum_known(*values: int | None) -> int | None:
    """Som van de bekende getallen; None als het platform geen enkel getal gaf."""
    known = [v for v in values if v is not None]
    return sum(known) if known else None


def rate(part: int | None, base: int | None) -> float | None:
    """Percentage als fractie (0.25 = 25%); None zonder bruikbare basis."""
    if part is None or not base:
        return None
    return round(part / base, 4)


class EspDraft(Protocol):
    """Resultaat van create_draft; campaign_id is int (Brevo) of str (Klaviyo/AC)."""

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

    def get_campaign_status(self, campaign_id: Any) -> str: ...

    def update_draft(
        self,
        campaign_id: Any,
        *,
        subject: str,
        sender_name: str,
        sender_email: str,
        html: str,
        preview_text: str | None = None,
    ) -> None: ...

    def get_results(self, campaign_id: Any) -> CampaignResults: ...
