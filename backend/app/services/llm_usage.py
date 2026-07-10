"""Token-verbruik per Claude-call vastleggen in mail.llm_usage.

De Anthropic-API geeft bij elke response exact terug wat hij kostte (input,
output, cache-schrijven, cache-lezen). Dit legt dat per call vast, met een
doel-label (chat, toolproof, prefill), zodat kosten meetbaar zijn per bedrijf,
per gesprek en per functie in plaats van een schatting achteraf.

Het vastleggen mag NOOIT een verzoek laten falen: fouten worden ingeslikt.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import LlmUsage


def record_usage(
    session: Session,
    *,
    model: str,
    purpose: str,
    usage: object,
    tenant_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
) -> None:
    """Schrijf één usage-regel; slikt fouten in (meten mag nooit iets breken)."""
    try:
        session.add(
            LlmUsage(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                model=model or "onbekend",
                purpose=purpose,
                input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
                cache_creation_tokens=int(
                    getattr(usage, "cache_creation_input_tokens", 0) or 0
                ),
                cache_read_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
            )
        )
        session.commit()
    except Exception:
        try:
            session.rollback()
        except Exception:
            pass


class _RecordingStream:
    """Wikkelt een MessageStream zodat get_final_message() de usage registreert."""

    def __init__(self, stream, model, tracker: "TrackingLLM") -> None:
        self._stream = stream
        self._model = model
        self._tracker = tracker
        self._recorded = False

    def get_final_message(self):
        message = self._stream.get_final_message()
        # get_final_message() is idempotent bij de SDK; registreer daarom maar
        # één keer, anders zou herhaald aanroepen de kosten dubbel wegschrijven.
        if not self._recorded:
            self._recorded = True
            self._tracker._record(self._model, getattr(message, "usage", None))
        return message

    def __getattr__(self, name):
        return getattr(self._stream, name)


class _StreamManager:
    """Context-manager om client.messages.stream() heen die usage vastlegt."""

    def __init__(self, inner_cm, model, tracker: "TrackingLLM") -> None:
        self._inner_cm = inner_cm
        self._model = model
        self._tracker = tracker

    def __enter__(self):
        return _RecordingStream(self._inner_cm.__enter__(), self._model, self._tracker)

    def __exit__(self, *exc):
        return self._inner_cm.__exit__(*exc)


@dataclass
class _MessagesProxy:
    """Vervangt client.messages: zelfde create()/stream(), maar legt usage vast."""

    inner: object
    tracker: "TrackingLLM"

    def create(self, **kwargs):
        response = self.inner.create(**kwargs)
        self.tracker._record(kwargs.get("model"), getattr(response, "usage", None))
        return response

    def stream(self, **kwargs):
        return _StreamManager(self.inner.stream(**kwargs), kwargs.get("model"), self.tracker)


@dataclass
class _BetaProxy:
    inner: object
    tracker: "TrackingLLM"

    @property
    def messages(self) -> _MessagesProxy:
        return _MessagesProxy(self.inner.messages, self.tracker)


class TrackingLLM:
    """Dun laagje om de Anthropic-client dat elke call registreert.

    Dekt zowel client.messages.create (extracties, toolproof) als
    client.beta.messages.create (de orchestrator-loop). Alles wat verder op de
    client wordt opgevraagd gaat ongewijzigd door naar de echte client.
    """

    def __init__(
        self,
        inner,
        session: Session,
        *,
        purpose: str,
        tenant_id: uuid.UUID | None = None,
        conversation_id: uuid.UUID | None = None,
    ) -> None:
        self._inner = inner
        self._session = session
        self._purpose = purpose
        self._tenant_id = tenant_id
        self._conversation_id = conversation_id

    def _record(self, model: str | None, usage: object) -> None:
        if usage is None:
            return
        record_usage(
            self._session,
            model=model or "onbekend",
            purpose=self._purpose,
            usage=usage,
            tenant_id=self._tenant_id,
            conversation_id=self._conversation_id,
        )

    @property
    def messages(self) -> _MessagesProxy:
        return _MessagesProxy(self._inner.messages, self)

    @property
    def beta(self) -> _BetaProxy:
        return _BetaProxy(self._inner.beta, self)

    def __getattr__(self, name):
        return getattr(self._inner, name)
