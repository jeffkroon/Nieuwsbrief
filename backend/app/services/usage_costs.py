"""Kosten van Claude-calls schatten op basis van de tokens in mail.llm_usage.

mail.llm_usage bewaart alleen tokens, geen bedragen. Hier staan de officiele
Anthropic-prijzen (USD per miljoen tokens, stand september 2026) en pure
functies die daar een schatting van maken. Een onbekend model levert None op
(in de UI: "onbekend"), nooit een crash: meten mag niets breken.

Aanname over cache-schrijven: llm_usage slaat alleen het totaal aantal
cache_creation_tokens op, niet of dat een 1-uurs of 5-minuten cache was.
Alleen de orchestrator (de chat-loop, purpose "chat") zet cache_control met
ttl "1h" (zie newsletter/orchestrator.py CACHE_CONTROL). Alle andere doelen
(toolproof, prefill, fotobeschrijving) zetten geen cache_control; mocht daar
toch cache-schrijven verschijnen, dan rekenen we het standaard 5-minuten
tarief. Voeg een doel toe aan ONE_HOUR_CACHE_PURPOSES zodra het ook de
1-uurs cache gaat gebruiken.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

PER_MILLION = Decimal(1_000_000)

# Doelen die een 1-uurs prompt-cache schrijven (zie de aanname hierboven).
ONE_HOUR_CACHE_PURPOSES: frozenset[str] = frozenset({"chat"})

# Een model-id mag een datum-achtervoegsel hebben: claude-sonnet-5-20260901.
_DATED_SUFFIX = re.compile(r"^-\d{8}$")


@dataclass(frozen=True)
class ModelPrice:
    """Prijzen in USD per miljoen tokens."""

    input: Decimal
    output: Decimal
    cache_write_1h: Decimal
    cache_write_5m: Decimal
    cache_read: Decimal


@dataclass(frozen=True)
class PriceEntry:
    """Model-id plus prijs. prefix_match: elk id dat hiermee begint telt mee."""

    model_id: str
    price: ModelPrice
    prefix_match: bool = False


def _price(inp: str, out: str, w1h: str, w5m: str, read: str) -> ModelPrice:
    return ModelPrice(Decimal(inp), Decimal(out), Decimal(w1h), Decimal(w5m), Decimal(read))


PRICE_TABLE: tuple[PriceEntry, ...] = (
    PriceEntry("claude-sonnet-5", _price("2", "10", "4", "2.50", "0.20")),
    PriceEntry("claude-haiku-4-5", _price("1", "5", "2", "1.25", "0.10"), prefix_match=True),
    PriceEntry("claude-opus-5-5", _price("4", "20", "8", "5", "0.20")),
    PriceEntry("claude-fable-5-1", _price("10", "50", "20", "12.50", "0.25")),
)


@dataclass(frozen=True)
class TokenCounts:
    """Tokensommen zoals ze in mail.llm_usage staan."""

    input: int = 0
    output: int = 0
    cache_creation: int = 0
    cache_read: int = 0

    def plus(self, other: "TokenCounts") -> "TokenCounts":
        return TokenCounts(
            input=self.input + other.input,
            output=self.output + other.output,
            cache_creation=self.cache_creation + other.cache_creation,
            cache_read=self.cache_read + other.cache_read,
        )


def _matches(entry: PriceEntry, model: str) -> bool:
    if model == entry.model_id:
        return True
    if not model.startswith(entry.model_id):
        return False
    if entry.prefix_match:
        return True
    return bool(_DATED_SUFFIX.match(model[len(entry.model_id):]))


def price_for_model(model: str | None) -> ModelPrice | None:
    """Prijs van een model-id, of None als we het model niet kennen."""
    if not model:
        return None
    normalized = model.strip().lower()
    return next((e.price for e in PRICE_TABLE if _matches(e, normalized)), None)


def cache_write_rate(price: ModelPrice, purpose: str | None) -> Decimal:
    """1-uurs tarief voor doelen met een 1-uurs cache, anders het 5-minuten tarief."""
    if purpose in ONE_HOUR_CACHE_PURPOSES:
        return price.cache_write_1h
    return price.cache_write_5m


def estimate_cost(model: str | None, purpose: str | None, tokens: TokenCounts) -> Decimal | None:
    """Geschatte kosten in USD, of None bij een onbekend model."""
    price = price_for_model(model)
    if price is None:
        return None
    total = (
        Decimal(tokens.input) * price.input
        + Decimal(tokens.output) * price.output
        + Decimal(tokens.cache_creation) * cache_write_rate(price, purpose)
        + Decimal(tokens.cache_read) * price.cache_read
    )
    return total / PER_MILLION
