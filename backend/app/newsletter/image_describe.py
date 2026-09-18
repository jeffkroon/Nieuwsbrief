"""Een geuploade foto zichzelf laten beschrijven.

`list_images` geeft de assistent de bestandsnaam en de beschrijving van elke foto.
Zonder beschrijving moet hij het op de bestandsnaam doen, en `IMG_2831.jpg` zegt
niets: dan kiest hij de verkeerde foto of valt terug op de dummy.

Haiku met beeldherkenning vult dat gat voor een fractie van een cent per foto. De
admin kan altijd zelf een beschrijving meegeven; die wint, er wordt nooit iets
overschreven. Mislukt de herkenning, dan gaat de upload gewoon door zonder
beschrijving: een foto zonder tekst is vervelend, een mislukte upload erger.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass

# Goedkoop model; het gaat om één korte beschrijving per foto.
DESCRIBE_MODEL = "claude-haiku-4-5"
MAX_TOKENS = 300

# Wat de beeld-API aankan; andere types slaan we over.
SUPPORTED_MEDIA_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")
# Ruim onder de limiet van de API; grotere foto's worden niet beschreven.
MAX_VISION_BYTES = 4 * 1024 * 1024

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "description": {"type": "string"},
        "subject": {"type": ["string", "null"]},
    },
    "required": ["description", "subject"],
}

_SYSTEM = (
    "Je krijgt een foto die gebruikt gaat worden in een e-mailnieuwsbrief. Geef een "
    "korte, feitelijke beschrijving in het Nederlands (maximaal 15 woorden) van wat "
    "er te zien is, zodat iemand de juiste foto kan kiezen zonder hem te bekijken. "
    "Herken je een specifiek onderwerp dat er zeker toe doet (een voetbalclub, een "
    "stadion, een stad, een herkenbaar product), geef dat dan als 'subject'; twijfel "
    "je, geef dan null. Verzin nooit een clubnaam of merk dat je niet duidelijk ziet."
)


@dataclass(frozen=True)
class ImageDescription:
    description: str
    subject: str | None = None

    def as_text(self) -> str:
        """Eén regel voor in de beeldbank; het onderwerp voorop, dat zoekt makkelijker."""
        if self.subject and self.subject.lower() not in self.description.lower():
            return f"{self.subject}: {self.description}"
        return self.description


def can_describe(media_type: str, size: int) -> bool:
    return media_type in SUPPORTED_MEDIA_TYPES and 0 < size <= MAX_VISION_BYTES


def describe_image(
    llm, content: bytes, media_type: str, *, filename: str = "", model: str = DESCRIBE_MODEL
) -> ImageDescription | None:
    """Beschrijf de foto; None als dat niet kan of niet lukt."""
    if not can_describe(media_type, len(content)):
        return None

    vraag = "Beschrijf deze foto."
    if filename:
        vraag += f" De bestandsnaam is {filename!r}; gebruik die alleen als hij klopt bij het beeld."

    try:
        response = llm.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=_SYSTEM,
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": base64.b64encode(content).decode(),
                            },
                        },
                        {"type": "text", "text": vraag},
                    ],
                }
            ],
        )
        data = _parse(response)
    except Exception:  # noqa: BLE001 - een upload mag hier nooit op stuklopen
        return None

    beschrijving = (data.get("description") or "").strip()
    if not beschrijving:
        return None
    onderwerp = (data.get("subject") or "").strip() or None
    return ImageDescription(description=beschrijving, subject=onderwerp)


def _parse(response) -> dict:
    tekst = "".join(
        getattr(blok, "text", "") for blok in response.content
        if getattr(blok, "type", None) == "text"
    )
    return json.loads(tekst) if tekst.strip() else {}
