"""Unit-tests voor de Claude-orchestratie met een fake Anthropic-client."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.newsletter.orchestrator import DEFAULT_MODEL, run_agent_turn


@dataclass
class FakeText:
    text: str
    type: str = "text"


@dataclass
class FakeToolUse:
    id: str
    name: str
    input: dict
    type: str = "tool_use"


@dataclass
class FakeResponse:
    content: list
    stop_reason: str


@dataclass
class FakeMessages:
    responses: list
    calls: list = field(default_factory=list)

    def create(self, **kwargs):
        # Snapshot de messages-lijst: de orchestrator hergebruikt en muteert 'm.
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


class FakeAnthropic:
    def __init__(self, responses: list) -> None:
        self.messages = FakeMessages(responses=list(responses))


TOOLS = [{"name": "get_brand_config", "description": "x", "input_schema": {"type": "object"}}]


def _run(responses, dispatch=lambda n, i: {"ok": True}):
    client = FakeAnthropic(responses)
    result = run_agent_turn(
        client,
        system="sys",
        messages=[{"role": "user", "content": "maak een nieuwsbrief"}],
        tools=TOOLS,
        dispatch=dispatch,
    )
    return client, result


def test_simple_end_turn() -> None:
    _, result = _run([FakeResponse([FakeText("Klaar!")], "end_turn")])
    assert result.final_text == "Klaar!"
    assert result.stop_reason == "end_turn"
    assert result.iterations == 1


def test_tool_use_then_end_turn() -> None:
    calls = []

    def dispatch(name, tool_input):
        calls.append((name, tool_input))
        return {"config": {"primary_color": "#FF7200"}}

    responses = [
        FakeResponse([FakeToolUse("tu_1", "get_brand_config", {})], "tool_use"),
        FakeResponse([FakeText("Concept staat klaar in Brevo.")], "end_turn"),
    ]
    client, result = _run(responses, dispatch)

    assert calls == [("get_brand_config", {})]
    assert result.final_text == "Concept staat klaar in Brevo."
    assert result.iterations == 2
    # Tweede create-call kreeg het tool_result mee in de laatste user-message.
    second_messages = client.messages.calls[1]["messages"]
    tool_result_msg = second_messages[-1]
    assert tool_result_msg["role"] == "user"
    assert tool_result_msg["content"][0]["type"] == "tool_result"
    assert tool_result_msg["content"][0]["tool_use_id"] == "tu_1"
    assert tool_result_msg["content"][0]["is_error"] is False


def test_tool_error_is_reported_not_raised() -> None:
    def dispatch(name, tool_input):
        raise ValueError("kapotte tool")

    responses = [
        FakeResponse([FakeToolUse("tu_1", "get_brand_config", {})], "tool_use"),
        FakeResponse([FakeText("Sorry, dat lukte niet.")], "end_turn"),
    ]
    client, result = _run(responses, dispatch)

    tool_result = client.messages.calls[1]["messages"][-1]["content"][0]
    assert tool_result["is_error"] is True
    assert "kapotte tool" in tool_result["content"]
    assert result.final_text == "Sorry, dat lukte niet."


def test_request_uses_correct_model_and_thinking() -> None:
    client, _ = _run([FakeResponse([FakeText("ok")], "end_turn")])
    first = client.messages.calls[0]
    assert first["model"] == DEFAULT_MODEL
    assert first["thinking"] == {"type": "adaptive"}
    assert first["output_config"] == {"effort": "high"}


def test_system_prompt_is_cached() -> None:
    # De system-prompt moet als cache_control-blok meegaan (prompt caching), zodat het
    # vaste prefix niet elke call vol wordt afgerekend.
    client, _ = _run([FakeResponse([FakeText("ok")], "end_turn")])
    system = client.messages.calls[0]["system"]
    assert isinstance(system, list)
    assert system[0]["cache_control"] == {"type": "ephemeral"}


def test_pause_turn_continues() -> None:
    responses = [
        FakeResponse([], "pause_turn"),
        FakeResponse([FakeText("hervat en klaar")], "end_turn"),
    ]
    _, result = _run(responses)
    assert result.final_text == "hervat en klaar"
    assert result.iterations == 2


def test_iteration_limit_raises() -> None:
    # Blijft altijd om tools vragen -> moet de limiet raken.
    forever = [FakeResponse([FakeToolUse(f"tu_{i}", "get_brand_config", {})], "tool_use") for i in range(20)]
    client = FakeAnthropic(forever)
    with pytest.raises(RuntimeError, match="iteratielimiet"):
        run_agent_turn(
            client,
            system="s",
            messages=[{"role": "user", "content": "hi"}],
            tools=TOOLS,
            dispatch=lambda n, i: {"ok": True},
            max_iterations=3,
        )