"""Link naar het concept in het verzendplatform van de klant.

Na het aanmaken van een concept moet de accountmanager het nog controleren en
versturen. Zonder link is dat zelf zoeken in een ander systeem.

Eerlijkheid boven gemak: alleen voor Brevo is de URL-vorm van een losse campagne
te bevestigen (https://app.brevo.com/marketing-campaign/edit/<id>). Voor Klaviyo
en ActiveCampaign linken we naar het campagne-overzicht in plaats van een
zelfbedachte URL die volgend jaar stilletjes op een 404 uitkomt. `is_deeplink`
zegt welke van de twee het is, zodat de UI het juiste woord kan gebruiken.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

BREVO_CAMPAIGN = "https://app.brevo.com/marketing-campaign/edit/{id}"
KLAVIYO_OVERZICHT = "https://www.klaviyo.com/campaigns"
ACTIVECAMPAIGN_OVERZICHT = "{app}/app/campaigns"

_ACCOUNT = re.compile(r"^https://([a-z0-9-]+)\.(?:api-us[0-9]+|activehosted)\.com", re.I)


@dataclass(frozen=True)
class EspLink:
    url: str
    label: str
    is_deeplink: bool


def campaign_link(esp: str, campaign_ref: str | None, *, api_url: str = "") -> EspLink | None:
    """Waar staat dit concept? None als we er niets zinnigs over kunnen zeggen."""
    if esp == "brevo":
        if not campaign_ref:
            return None
        return EspLink(
            url=BREVO_CAMPAIGN.format(id=campaign_ref),
            label="Open in Brevo",
            is_deeplink=True,
        )
    if esp == "klaviyo":
        return EspLink(url=KLAVIYO_OVERZICHT, label="Open Klaviyo-campagnes", is_deeplink=False)
    if esp == "activecampaign":
        app = _app_url(api_url)
        if not app:
            return None
        return EspLink(
            url=ACTIVECAMPAIGN_OVERZICHT.format(app=app),
            label="Open ActiveCampaign-campagnes",
            is_deeplink=False,
        )
    return None


def _app_url(api_url: str) -> str:
    """De API-URL (<account>.api-us1.com) omzetten naar de dashboard-URL."""
    match = _ACCOUNT.match((api_url or "").strip())
    return f"https://{match.group(1)}.activehosted.com" if match else ""
