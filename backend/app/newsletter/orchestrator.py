"""Claude tool-use orchestratie (manual agentic loop).

Draait de gespreks-loop: stuurt berichten naar Claude, voert tool-calls uit via
de meegegeven dispatch-functie, en gaat door tot Claude klaar is. De Anthropic-
client wordt geinjecteerd zodat tests een fake kunnen meegeven.

Model claude-sonnet-4-6 met adaptive thinking en effort 'medium': sterk genoeg voor
deze tool-taak en ~40% goedkoper per token dan Opus. De harde garanties (link moet
200 zijn, prijs live gescrapet, concept pas na toestemming) zitten in code, niet in
de effort. Geen budget_tokens (gebruik
adaptive thinking). De system-prompt + tools worden gecachet (prompt caching), zodat
dat vaste deel niet elke loop-stap opnieuw vol wordt afgerekend.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_OUTPUT_TOKENS = 16000
MAX_ITERATIONS = 12

# dispatch(name, tool_input) -> dict met het toolresultaat
ToolDispatch = Callable[[str, dict], dict]


class AnthropicLike(Protocol):
    """Minimale interface die we van de Anthropic-client gebruiken (injecteerbaar)."""

    @property
    def messages(self) -> Any: ...


@dataclass
class ConversationResult:
    final_text: str
    stop_reason: str
    iterations: int
    messages: list[dict] = field(default_factory=list)


def _text_from(content: list) -> str:
    return "".join(getattr(b, "text", "") for b in content if getattr(b, "type", None) == "text")


def run_agent_turn(
    client: AnthropicLike,
    *,
    system: str,
    messages: list[dict],
    tools: list[dict],
    dispatch: ToolDispatch,
    model: str = DEFAULT_MODEL,
    max_iterations: int = MAX_ITERATIONS,
) -> ConversationResult:
    """Voer één agent-beurt uit tot Claude stopt of een limiet bereikt is."""
    convo: list[dict] = list(messages)
    # Cache de system-prompt (rendert na de tools, dus dit cachet tools + system samen).
    # Dat vaste prefix wordt elke loop-stap en elke beurt opnieuw verstuurd; gecachet
    # kost het daarna ~10% i.p.v. de volle prijs.
    cached_system = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

    for iteration in range(1, max_iterations + 1):
        response = client.messages.create(
            model=model,
            max_tokens=MAX_OUTPUT_TOKENS,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            system=cached_system,
            tools=tools,
            messages=convo,
        )
        convo.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "tool_use":
            convo.append({"role": "user", "content": _run_tools(response.content, dispatch)})
            continue
        if response.stop_reason == "pause_turn":
            continue  # server-side tool pauze: opnieuw sturen om door te gaan

        # end_turn, refusal, max_tokens, stop_sequence: beurt is klaar
        return ConversationResult(
            final_text=_text_from(response.content),
            stop_reason=response.stop_reason,
            iterations=iteration,
            messages=convo,
        )

    raise RuntimeError(f"agent-beurt bereikte de iteratielimiet ({max_iterations})")


def _run_tools(content: list, dispatch: ToolDispatch) -> list[dict]:
    """Voer alle tool_use-blokken uit en geef de tool_result-blokken terug."""
    results: list[dict] = []
    for block in content:
        if getattr(block, "type", None) != "tool_use":
            continue
        try:
            output = dispatch(block.name, dict(block.input))
            result_content = json.dumps(output, ensure_ascii=False)
            is_error = False
        except Exception as exc:  # tool-fout terug naar Claude, niet de loop laten crashen
            result_content = f"Fout bij tool '{block.name}': {exc}"
            is_error = True
        results.append(
            {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_content,
                "is_error": is_error,
            }
        )
    return results
