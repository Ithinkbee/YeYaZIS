"""Автоматическая реакция на речевой сигнал: звук с микрофона -> события.

Слушатель получает звук кусками, как его присылает браузер, и сам решает,
где в нём речь: режет на кадры, отдаёт их детектору (audio.Vad), а пока
детектор слышит речь — распознавателю. Наружу идут события, из которых
страница составляет уведомления о происходящем:

    level         уровень сигнала, оценка шума и порог (пять раз в секунду)
    speech_start  началась фраза
    partial       промежуточный текст, пока человек говорит
    speech_end    фраза закончилась (или оказалась щелчком: dropped)
    final         распознанная фраза с уверенностью и временем распознавания
    error         распознавание недоступно
"""

from __future__ import annotations

import time

import numpy as np

from sluhach import audio, config
from sluhach.recognizer import RecognizerError

#: как часто (в кадрах) звук уходит в распознаватель и обновляется промежуточный текст
BATCH_FRAMES = 5
#: как часто (в кадрах) сообщается уровень сигнала
LEVEL_FRAMES = 10
#: пределы настроек, которые меняет пользователь
MARGIN_RANGE = (4.0, 24.0)
PAUSE_RANGE = (300, 2000)


class Listener:
    """Один разговор: поток звука на входе, события на выходе."""

    def __init__(self, engine, language: str = config.DEFAULT_LANGUAGE,
                 settings: audio.VadSettings | None = None) -> None:
        self.engine = engine
        self.language = language
        self.settings = settings or audio.VadSettings()
        self.vad = audio.Vad(self.settings)
        self._buffer = b""
        self._stream = None
        self._batch: list[np.ndarray] = []
        self._partial = ""
        self._frames = 0
        self._peak = audio.SILENCE_DB
        self._started = 0.0

    # --- настройки ------------------------------------------------------------------

    def set_language(self, language: str) -> None:
        if language in config.LANGUAGES and language != self.language:
            self.language = language
            self.reset()

    def configure(self, margin_db: float | None = None, pause_ms: float | None = None) -> None:
        """Чувствительность (на сколько дБ речь громче шума) и пауза конца фразы."""
        if margin_db is not None:
            self.settings.start_margin_db = min(MARGIN_RANGE[1], max(MARGIN_RANGE[0], float(margin_db)))
            self.settings.end_margin_db = max(3.0, self.settings.start_margin_db - 4.0)
        if pause_ms is not None:
            self.settings.end_silence_ms = int(min(PAUSE_RANGE[1], max(PAUSE_RANGE[0], float(pause_ms))))

    def reset(self) -> None:
        """Бросает начатую фразу: сменился язык или система сама заговорила."""
        self.vad.reset()
        self._buffer = b""
        self._stream = None
        self._batch = []
        self._partial = ""

    # --- звук ---------------------------------------------------------------------------

    def feed(self, pcm: bytes) -> list[dict]:
        """Принимает очередной кусок звука (PCM, 16 разрядов, 16 кГц) и возвращает события."""
        events: list[dict] = []
        self._buffer += pcm
        size = self.settings.frame_samples * 2
        while len(self._buffer) >= size:
            frame = audio.to_samples(self._buffer[:size])
            self._buffer = self._buffer[size:]
            self._frame(frame, events)
        return events

    def _frame(self, frame: np.ndarray, events: list[dict]) -> None:
        self._frames += 1
        self._peak = max(self._peak, audio.level_db(frame))
        for event in self.vad.push(frame):
            if event.kind == "start":
                self._start(event, events)
            elif event.kind == "speech" and self._stream is not None:
                self._batch.extend(event.frames)
                if len(self._batch) >= BATCH_FRAMES:
                    self._flush(events)
            elif event.kind in {"end", "drop"}:
                self._finish(event, events)
        if self._frames % LEVEL_FRAMES == 0:
            events.append({"type": "level", "db": round(self._peak, 1), "noise": round(self.vad.noise_db, 1),
                           "threshold": round(self.vad.start_threshold, 1), "speaking": self.vad.speaking})
            self._peak = audio.SILENCE_DB

    def _start(self, event: audio.VadEvent, events: list[dict]) -> None:
        try:
            self._stream = self.engine.stream(self.language, self.settings.rate)
        except RecognizerError as problem:
            self._stream = None
            self.vad.reset()
            events.append({"type": "error", "message": str(problem)})
            return
        self._started = time.perf_counter()
        self._partial = ""
        self._batch = list(event.frames)
        events.append({"type": "speech_start", "noise": round(self.vad.noise_db, 1),
                       "threshold": round(self.vad.start_threshold, 1)})
        self._flush(events)

    def _flush(self, events: list[dict]) -> None:
        if self._stream is None or not self._batch:
            return
        self._stream.accept(np.concatenate(self._batch).astype("<i2").tobytes())
        self._batch = []
        text = self._stream.partial()
        if text and text != self._partial:
            self._partial = text
            events.append({"type": "partial", "text": text})

    def _finish(self, event: audio.VadEvent, events: list[dict]) -> None:
        stream = self._stream
        if stream is None:
            return
        if event.kind == "drop":
            # всплеск короче слова: хлопок, щелчок мыши
            self._stream, self._batch = None, []
            events.append({"type": "speech_end", "dropped": True, "duration_ms": event.duration_ms})
            return
        self._flush(events)
        self._stream = None
        result = stream.finish()
        if not result.text:
            # детектор открыл фразу, а слов в ней нет — значит, это шум комнаты
            self.vad.raise_floor(event.level_db)
        events.append({"type": "speech_end", "dropped": False, "duration_ms": event.duration_ms,
                       "forced": event.forced})
        events.append({
            "type": "final", "text": result.text, "confidence": round(result.confidence, 3),
            "duration_ms": event.duration_ms, "recognition_ms": round(result.ms, 1),
            "level_db": round(event.level_db, 1), "language": self.language,
            "latency_ms": round((time.perf_counter() - self._started) * 1000, 1),
        })
