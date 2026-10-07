"""Синтезаторы речи: общий вид и настройки чтения.

Голос задаётся строкой «движок:имя» — «piper:de_DE-thorsten-medium»,
«piper:de_DE-thorsten_emotional-medium#angry» (диктор многоголосой модели
после «#»), «formant:karl», «sapi:Microsoft Hedda Desktop», «browser:auto».
Каждый движок отдаёт список своих голосов — и тех, что установлены, и тех,
что можно установить, — и превращает предложение в звук.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from glashatai import config


@dataclass
class Voice:
    id: str                     # «piper:de_DE-thorsten-medium»
    engine: str                 # piper | formant | sapi | browser
    title: str                  # «Thorsten»
    gender: str = ""
    available: bool = True
    note: str = ""
    #: что умеет движок сам; остальное делает dsp.py
    native: list[str] = field(default_factory=list)     # rate, pitch, liveliness

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Settings:
    """Настройки чтения с проверкой границ."""
    voice: str = config.DEFAULT_VOICE
    rate: float = 1.0           # темп
    pitch: float = 0.0          # высота, полутоны
    volume: float = 85.0        # громкость, %
    liveliness: float = 0.5     # живость интонации, 0…1
    sentence_pause: int = 350   # пауза после предложения, мс
    paragraph_pause: int = 800  # пауза после абзаца, мс

    @classmethod
    def from_dict(cls, raw: dict | None) -> "Settings":
        raw = raw or {}
        settings = cls()

        def number(name: str, low: float, high: float, cast=float):
            try:
                value = cast(raw[name])
            except (KeyError, TypeError, ValueError):
                return
            if value != value:          # NaN
                return
            setattr(settings, name, cast(min(high, max(low, value))))

        if isinstance(raw.get("voice"), str) and 0 < len(raw["voice"]) <= 200:
            settings.voice = raw["voice"]
        number("rate", *config.RATE_RANGE)
        number("pitch", *config.PITCH_RANGE)
        number("volume", *config.VOLUME_RANGE)
        number("liveliness", *config.LIVELINESS_RANGE)
        number("sentence_pause", *config.SENTENCE_PAUSE_RANGE, cast=int)
        number("paragraph_pause", *config.PARAGRAPH_PAUSE_RANGE, cast=int)
        return settings

    def to_dict(self) -> dict:
        return asdict(self)

    def key(self) -> tuple:
        """Всё, от чего зависит звук предложения (громкость и паузы — нет)."""
        return self.voice, round(self.rate, 3), round(self.pitch, 2), round(self.liveliness, 3)


class EngineError(RuntimeError):
    """Синтезатор не смог произнести текст."""


@dataclass
class Audio:
    samples: np.ndarray
    rate: int

    @property
    def seconds(self) -> float:
        return len(self.samples) / self.rate if self.rate else 0.0


def split_voice(voice_id: str) -> tuple[str, str, str | None]:
    """«piper:модель#диктор» -> (piper, модель, диктор)."""
    engine, _, name = voice_id.partition(":")
    name, _, speaker = name.partition("#")
    return engine, name, speaker or None
