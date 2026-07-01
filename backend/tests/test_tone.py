"""Tests voor de tone-of-voice service (cachen + eenmalig analyseren)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.repositories import tenants as tenants_repo
from app.schemas import TenantCreate
from app.services import tone as tone_service


@dataclass
class _FakeText:
    text: str
    type: str = "text"


@dataclass
class _FakeResp:
    content: list


@dataclass
class _FakeMessages:
    payload: dict
    calls: list = field(default_factory=list)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResp([_FakeText(json.dumps(self.payload))])


class _FakeLLM:
    def __init__(self, payload: dict) -> None:
        self.messages = _FakeMessages(payload=payload)


def test_ensure_tone_returns_cached_without_network(session) -> None:
    t = tenants_repo.create_tenant(
        session,
        TenantCreate(slug="x", name="X", config={"website_url": "https://x.nl", "tone_of_voice": "Sportief."}),
    )
    llm = _FakeLLM({"tone_of_voice": "MAG NIET AANGEROEPEN"})
    assert tone_service.ensure_tone(session, t, llm) == "Sportief."
    assert llm.messages.calls == []  # geen analyse: gebruikte de cache


def test_analyze_and_store_caches_tone(session, monkeypatch) -> None:
    t = tenants_repo.create_tenant(
        session, TenantCreate(slug="y", name="Y", config={"website_url": "https://y.nl"})
    )
    # Mock de fetch zodat er geen echt netwerk nodig is.
    monkeypatch.setattr(tone_service.extraction, "fetch_page", lambda url, c=None: (200, "<html>welkom</html>"))
    llm = _FakeLLM({"tone_of_voice": "Warm en persoonlijk."})

    tone = tone_service.analyze_and_store_tone(session, t, llm)
    assert tone == "Warm en persoonlijk."
    # Opgeslagen in config -> volgende keer uit de cache.
    assert tone_service.get_cached_tone(t) == "Warm en persoonlijk."


def test_ensure_tone_none_without_website(session) -> None:
    t = tenants_repo.create_tenant(session, TenantCreate(slug="z", name="Z", config={}))
    assert tone_service.ensure_tone(session, t, _FakeLLM({})) is None
