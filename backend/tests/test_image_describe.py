"""Tests voor het automatisch beschrijven van geuploade foto's."""

from __future__ import annotations

from dataclasses import dataclass

from app.newsletter.image_describe import (
    MAX_VISION_BYTES,
    ImageDescription,
    can_describe,
    describe_image,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 200


@dataclass
class FakeText:
    text: str
    type: str = "text"


@dataclass
class FakeResponse:
    content: list


class FakeLLM:
    def __init__(self, antwoord: str | None = None, fout: Exception | None = None) -> None:
        self._antwoord = antwoord
        self._fout = fout
        self.calls: list[dict] = []

    @property
    def messages(self):
        return self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._fout:
            raise self._fout
        return FakeResponse([FakeText(self._antwoord or "{}")])


def test_beschrijving_en_onderwerp_worden_gecombineerd() -> None:
    llm = FakeLLM('{"description": "spelers vieren een doelpunt", "subject": "AS Roma"}')
    resultaat = describe_image(llm, PNG, "image/png", filename="IMG_2831.png")
    assert resultaat.as_text() == "AS Roma: spelers vieren een doelpunt"


def test_onderwerp_wordt_niet_dubbel_genoemd() -> None:
    beschrijving = ImageDescription(description="Het stadion van AS Roma", subject="AS Roma")
    assert beschrijving.as_text() == "Het stadion van AS Roma"


def test_foto_wordt_als_afbeelding_meegestuurd() -> None:
    llm = FakeLLM('{"description": "een bal", "subject": null}')
    describe_image(llm, PNG, "image/png")
    inhoud = llm.calls[0]["messages"][0]["content"]
    assert inhoud[0]["type"] == "image"
    assert inhoud[0]["source"]["media_type"] == "image/png"
    assert inhoud[0]["source"]["type"] == "base64"


def test_onbekend_bestandstype_wordt_overgeslagen() -> None:
    llm = FakeLLM('{"description": "x", "subject": null}')
    assert describe_image(llm, PNG, "image/tiff") is None
    assert llm.calls == [], "er had geen dure call gedaan mogen worden"


def test_te_grote_foto_wordt_overgeslagen() -> None:
    llm = FakeLLM('{"description": "x", "subject": null}')
    assert describe_image(llm, b"x" * (MAX_VISION_BYTES + 1), "image/jpeg") is None
    assert llm.calls == []


def test_mislukte_herkenning_laat_de_upload_doorgaan() -> None:
    """Een foto zonder beschrijving is vervelend; een mislukte upload erger."""
    assert describe_image(FakeLLM(fout=RuntimeError("model down")), PNG, "image/png") is None


def test_onleesbaar_antwoord_geeft_geen_beschrijving() -> None:
    assert describe_image(FakeLLM("dit is geen json"), PNG, "image/png") is None


def test_lege_beschrijving_telt_niet() -> None:
    assert describe_image(FakeLLM('{"description": "  ", "subject": "x"}'), PNG, "image/png") is None


def test_can_describe_grenzen() -> None:
    assert can_describe("image/jpeg", 100) is True
    assert can_describe("image/svg+xml", 100) is False
    assert can_describe("image/png", 0) is False
