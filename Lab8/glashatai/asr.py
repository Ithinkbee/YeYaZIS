"""Распознаватель речи Vosk — «слушатель» для проверки разборчивости.

Разборчивость синтезированной речи обычно измеряют на людях: они слушают
фразы и записывают услышанное. Здесь слушает распознаватель Vosk (Kaldi,
малая немецкая модель, та же, что в работе № 9): синтезированная фраза
распознаётся, и считается доля ошибок в словах (WER) относительно текста,
который синтезатор должен был сказать. Распознаватель строже человека —
он не знает, о чём текст, — поэтому числа — нижняя оценка разборчивости;
зато их можно повторить и сравнить голоса и темпы между собой.

Для работы системы модуль не нужен; модель скачивает tools/evaluate.py.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np

from glashatai import config, dsp

RATE = 16000


class Recognizer:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or config.MODELS_DIR / config.VOSK_MODEL
        self._model = None
        self._lock = threading.Lock()

    def available(self) -> bool:
        try:
            import vosk  # noqa: F401
        except ImportError:
            return False
        return (self.directory / "am").exists() or (self.directory / "conf").exists()

    def _load(self):
        with self._lock:
            if self._model is None:
                from vosk import Model, SetLogLevel

                SetLogLevel(-1)
                self._model = Model(str(self.directory))
            return self._model

    def recognize(self, samples: np.ndarray, rate: int) -> str:
        """Звук -> распознанный текст (строчными буквами)."""
        from vosk import KaldiRecognizer

        model = self._load()
        audio = dsp.resample(np.asarray(samples, dtype=np.float32), rate, RATE)
        # тишина по краям — распознавателю нужно время, чтобы «включиться» и закончить фразу
        audio = np.concatenate([dsp.silence(200, RATE), audio, dsp.silence(400, RATE)])
        pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
        recognizer = KaldiRecognizer(model, RATE)
        recognizer.AcceptWaveform(pcm)
        return json.loads(recognizer.FinalResult()).get("text", "")
