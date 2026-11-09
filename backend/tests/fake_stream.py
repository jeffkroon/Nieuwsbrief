"""Nabootsing van client.beta.messages.stream() voor tests met een fake Claude.

Bouwt dezelfde events als de SDK (anthropic 0.112, BetaMessageStream): per blok
`content_block_delta`-events met `text_delta`, `thinking_delta` of
`input_json_delta`. `text_stream` filtert precies zoals de SDK, op
`delta.type == "text_delta"`, zodat thinking en tool-invoer er net als in het
echt niet in zitten. `get_final_message()` geeft het volledige antwoord.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from types import SimpleNamespace


def _delta(delta: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(type="content_block_delta", delta=delta)


def stream_events(content: list) -> list[SimpleNamespace]:
    """De delta-events voor een antwoord; tekst in stukjes van een woord."""
    events: list[SimpleNamespace] = []
    for block in content:
        soort = getattr(block, "type", None)
        if soort == "text":
            for stuk in re.findall(r"\S+\s*|\s+", block.text):
                events.append(_delta(SimpleNamespace(type="text_delta", text=stuk)))
        elif soort == "thinking":
            events.append(_delta(SimpleNamespace(type="thinking_delta", thinking=block.thinking)))
        elif soort == "tool_use":
            events.append(
                _delta(SimpleNamespace(type="input_json_delta", partial_json=json.dumps(block.input)))
            )
    return events


class FakeStream:
    """Context-manager met events, `text_stream` en `get_final_message()`."""

    def __init__(self, response) -> None:
        self._response = response
        self._events = stream_events(getattr(response, "content", []))
        self.text_stream = self._text()

    def __enter__(self) -> "FakeStream":
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def __iter__(self) -> Iterator[SimpleNamespace]:
        return iter(self._events)

    def _text(self) -> Iterator[str]:
        for event in self:
            if event.type == "content_block_delta" and event.delta.type == "text_delta":
                yield event.delta.text

    def get_final_message(self):
        return self._response
