"""Tests voor de kosten-verbeteringen: validatie-cache en token-logging."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.newsletter.validation_cache import ValidationCache

# -- ValidationCache (unit) ------------------------------------------------------


def test_cache_hit_within_ttl_and_expiry() -> None:
    clock = [0.0]
    cache = ValidationCache(ttl_seconds=10, time_fn=lambda: clock[0])
    assert cache.get(("price", "u")) == (False, None)
    cache.set(("price", "u"), "€ 99")
    assert cache.get(("price", "u")) == (True, "€ 99")
    clock[0] = 9.9
    assert cache.get(("price", "u"))[0] is True
    clock[0] = 10.0
    assert cache.get(("price", "u")) == (False, None)  # verlopen


def test_cache_evicts_oldest_beyond_max() -> None:
    cache = ValidationCache(ttl_seconds=100, max_entries=2, time_fn=lambda: 0.0)
    cache.set(("a",), 1)
    cache.set(("b",), 2)
    cache.set(("c",), 3)
    assert cache.get(("a",)) == (False, None)
    assert cache.get(("b",)) == (True, 2)
    assert cache.get(("c",)) == (True, 3)


def test_cache_stores_none_as_real_value() -> None:
    cache = ValidationCache(time_fn=lambda: 0.0)
    cache.set(("og", "u"), None)  # pagina zonder og-foto: ook dat is een antwoord
    assert cache.get(("og", "u")) == (True, None)


# -- validatie-cache in de prijs-checks (integratie) ------------------------------


@dataclass
class _FakeResp:
    text: str
    status_code: int = 200


@dataclass
class _CountingHttp:
    calls: int = 0

    def get(self, url):
        self.calls += 1
        return _FakeResp("<html><body>Wedstrijd € 99</body></html>")


class _CountingLLM:
    """Telt extractie-calls; geeft altijd een vaste prijs terug."""

    def __init__(self) -> None:
        self.calls = 0
        parent = self

        class _Messages:
            def create(self, **kwargs):
                parent.calls += 1

                class _Block:
                    type = "text"
                    text = '{"price": "€ 99", "source_url": "https://x.test/p"}'

                class _Resp:
                    content = [_Block()]

                return _Resp()

        self.messages = _Messages()


def _ctx(http):
    from app.newsletter.tools import ToolContext

    return ToolContext(
        session=None, tenant_id=uuid.uuid4(), cipher=None, http_client=http
    )


def test_resolve_price_uses_cache_on_second_render() -> None:
    from app.newsletter.tools import _resolve_price, _validation_cache

    _validation_cache.clear()
    http, llm = _CountingHttp(), _CountingLLM()
    ctx = _ctx(http)

    eerste = _resolve_price(ctx, llm, "https://x.test/p", None)
    tweede = _resolve_price(ctx, llm, "https://x.test/p", None)

    assert eerste == tweede
    assert http.calls == 1  # tweede render: geen nieuwe fetch
    assert llm.calls == 1  # en geen nieuwe Haiku-extractie


def test_require_reachable_cached_after_price_check() -> None:
    from app.newsletter.tools import _require_reachable, _resolve_price, _validation_cache

    _validation_cache.clear()
    http, llm = _CountingHttp(), _CountingLLM()
    ctx = _ctx(http)
    _resolve_price(ctx, llm, "https://x.test/p", None)
    _require_reachable(ctx, "https://x.test/p")  # al bewezen bereikbaar
    assert http.calls == 1


def test_price_override_only_checks_reachability_once() -> None:
    from app.newsletter.tools import _resolve_price, _validation_cache

    _validation_cache.clear()
    http, llm = _CountingHttp(), _CountingLLM()
    ctx = _ctx(http)
    p1 = _resolve_price(ctx, llm, "https://x.test/p", "129", override=True)
    p2 = _resolve_price(ctx, llm, "https://x.test/p", "129", override=True)
    assert p1 == p2 == "€ 129"
    assert http.calls == 1 and llm.calls == 0


# -- token-logging (integratie met DB) --------------------------------------------


@dataclass
class _FakeUsage:
    input_tokens: int = 1200
    output_tokens: int = 340
    cache_creation_input_tokens: int = 800
    cache_read_input_tokens: int = 7600


class _FakeAnthropicClient:
    """Nabootsing van de echte client: messages.create en beta.messages.create."""

    def __init__(self) -> None:
        class _Resp:
            usage = _FakeUsage()
            content = []

        class _Messages:
            def create(self, **kwargs):
                return _Resp()

        class _Beta:
            messages = _Messages()

        self.messages = _Messages()
        self.beta = _Beta()


def test_tracking_llm_records_both_apis(session) -> None:
    from app.db.models import LlmUsage
    from app.services.llm_usage import TrackingLLM

    tenant_id, conv_id = uuid.uuid4(), uuid.uuid4()
    tracked = TrackingLLM(
        _FakeAnthropicClient(), session, purpose="chat",
        tenant_id=tenant_id, conversation_id=conv_id,
    )
    tracked.messages.create(model="claude-haiku-4-5", max_tokens=10)
    tracked.beta.messages.create(model="claude-sonnet-4-6", max_tokens=10)

    rows = session.query(LlmUsage).order_by(LlmUsage.model).all()
    assert [(r.model, r.purpose) for r in rows] == [
        ("claude-haiku-4-5", "chat"),
        ("claude-sonnet-4-6", "chat"),
    ]
    assert rows[0].tenant_id == tenant_id and rows[0].conversation_id == conv_id
    assert rows[0].input_tokens == 1200 and rows[0].cache_read_tokens == 7600


def test_recording_failure_never_breaks_the_call(session) -> None:
    from app.services.llm_usage import TrackingLLM

    class _BrokenSession:
        def add(self, _):
            raise RuntimeError("db weg")

        def commit(self):
            raise RuntimeError("db weg")

        def rollback(self):
            raise RuntimeError("db nog steeds weg")

    tracked = TrackingLLM(_FakeAnthropicClient(), _BrokenSession(), purpose="chat")
    resp = tracked.messages.create(model="claude-haiku-4-5", max_tokens=10)
    assert resp is not None  # de Claude-call zelf slaagt gewoon


def test_draft_clears_validation_cache_for_live_validation() -> None:
    """Het definitieve concept mag nooit op gecachte validaties leunen."""
    import pytest

    from app.newsletter.tools import ToolContext, _tool_create_newsletter_draft, _validation_cache

    _validation_cache.clear()
    _validation_cache.set(("price", "https://x.test/p"), "€ 99")

    class _NoSecretSession:
        def get(self, *a, **k):
            return None

    ctx = ToolContext(session=_NoSecretSession(), tenant_id=uuid.uuid4(), cipher=None)
    # Zonder confirmed weigert de tool VOOR de build: cache blijft dan staan
    # (er wordt immers niets gerenderd).
    with pytest.raises(ValueError, match="toestemming"):
        _tool_create_newsletter_draft(ctx, {})
    assert _validation_cache.get(("price", "https://x.test/p"))[0] is True

    # Met confirmed strandt hij verderop (geen tenant), maar de cache is dan
    # al geleegd: het concept valideert altijd vers.
    with pytest.raises(ValueError):
        _tool_create_newsletter_draft(ctx, {"confirmed": True})
    assert _validation_cache.get(("price", "https://x.test/p"))[0] is False
