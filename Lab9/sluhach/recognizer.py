"""Распознавание речи: Vosk (Kaldi) на этом компьютере.

Vosk — свободная библиотека распознавания на основе Kaldi: акустическая
модель (нейросеть TDNN) оценивает фонемы, декодер на взвешенных конечных
автоматах собирает из них слова по словарю и языковой модели. Модель у
каждого языка своя, поэтому выбор языка — это выбор модели.

Распознаватель потоковый: звук подаётся кусками, и после каждого куска можно
спросить промежуточный текст — так пользователь видит слова, пока говорит.
Модели загружаются при первом обращении (доли секунды) и дальше остаются в
памяти. Если пакета vosk или модели нет, система сообщает об этом и
предлагает распознавание в браузере, а не падает.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from sluhach import config

log = logging.getLogger("sluhach.recognizer")

#: состояния модели языка
STATES = {
    "ready": "готова",
    "loading": "загружается",
    "idle": "загрузится при первой фразе",
    "missing": "модель не скачана",
    "no-package": "не установлен пакет vosk",
    "error": "ошибка загрузки",
}


class RecognizerError(Exception):
    """Распознавание недоступно; текст показывается пользователю."""


@dataclass
class Recognition:
    text: str = ""
    confidence: float = 0.0                       # средняя уверенность распознавателя в словах, 0…1
    words: list[dict] = field(default_factory=list)       # слова с уверенностью и временем
    ms: float = 0.0                               # сколько длилось распознавание

    def to_dict(self) -> dict:
        return {"text": self.text, "confidence": round(self.confidence, 3), "ms": round(self.ms, 1)}


class VoskStream:
    """Распознавание одной фразы по мере поступления звука."""

    def __init__(self, recognizer) -> None:
        self._recognizer = recognizer
        self._parts: list[str] = []
        self._words: list[dict] = []
        self.ms = 0.0

    def _take(self, raw: str) -> None:
        result = json.loads(raw)
        if result.get("text"):
            self._parts.append(result["text"])
            self._words.extend(result.get("result", []))

    def accept(self, pcm: bytes) -> None:
        started = time.perf_counter()
        # True — декодер сам счёл фразу законченной (пауза внутри фразы): её
        # текст забирается, и распознавание продолжается с чистого листа
        if self._recognizer.AcceptWaveform(pcm):
            self._take(self._recognizer.Result())
        self.ms += (time.perf_counter() - started) * 1000

    def partial(self) -> str:
        started = time.perf_counter()
        current = json.loads(self._recognizer.PartialResult()).get("partial", "")
        self.ms += (time.perf_counter() - started) * 1000
        return " ".join(part for part in (*self._parts, current) if part)

    def finish(self) -> Recognition:
        started = time.perf_counter()
        self._take(self._recognizer.FinalResult())
        self.ms += (time.perf_counter() - started) * 1000
        scores = [float(word.get("conf", 0.0)) for word in self._words]
        return Recognition(" ".join(self._parts), sum(scores) / len(scores) if scores else 0.0,
                           list(self._words), self.ms)


class VoskEngine:
    """Модели Vosk по языкам: наличие, загрузка, распознавание."""

    name = "vosk"

    def __init__(self, models_dir: Path | None = None, models: dict[str, str] | None = None) -> None:
        self.models_dir = models_dir or config.MODELS_DIR
        self.models = dict(models or config.VOSK_MODELS)
        self._loaded: dict[str, object] = {}
        self._errors: dict[str, str] = {}
        self._loading: set[str] = set()
        self._lock = threading.Lock()
        self._locks = {language: threading.Lock() for language in self.models}
        self._package: bool | None = None

    # --- что есть на диске ------------------------------------------------------

    def model_path(self, language: str) -> Path:
        return self.models_dir / self.models.get(language, "")

    def installed(self, language: str) -> bool:
        return language in self.models and (self.model_path(language) / "am" / "final.mdl").exists()

    def package(self) -> bool:
        if self._package is None:
            try:
                import vosk

                vosk.SetLogLevel(-1)                 # Kaldi пишет в консоль десятки строк на модель
                self._package = True
            except Exception:  # noqa: BLE001 — нет пакета или не загрузилась его библиотека
                self._package = False
        return self._package

    def state(self, language: str) -> str:
        if not self.package():
            return "no-package"
        if language in self._loaded:
            return "ready"
        if language in self._errors:
            return "error"
        if language in self._loading:
            return "loading"
        return "idle" if self.installed(language) else "missing"

    def available(self, language: str) -> bool:
        return self.state(language) in {"ready", "loading", "idle"}

    def status(self) -> dict:
        """Состояние распознавателя для страницы."""
        languages = {}
        for language, name in self.models.items():
            state = self.state(language)
            languages[language] = {"model": name, "state": state, "text": STATES[state],
                                   "available": self.available(language), "error": self._errors.get(language, "")}
        return {"engine": self.name, "package": self.package(), "languages": languages}

    # --- загрузка -------------------------------------------------------------------

    def load(self, language: str):
        """Модель языка; первая загрузка занимает доли секунды, дальше — из памяти."""
        model = self._loaded.get(language)
        if model is not None:
            return model
        if not self.package():
            raise RecognizerError("не установлен пакет vosk: pip install vosk")
        if not self.installed(language):
            raise RecognizerError(f"нет модели Vosk для языка «{config.language_name(language)}»: "
                                  "python tools/get_models.py")
        with self._locks[language]:
            model = self._loaded.get(language)
            if model is not None:
                return model
            import vosk

            self._loading.add(language)
            started = time.perf_counter()
            try:
                model = vosk.Model(str(self.model_path(language)))
            except Exception as problem:  # noqa: BLE001
                self._errors[language] = str(problem) or type(problem).__name__
                raise RecognizerError(f"модель {self.models[language]} не загрузилась: {problem}") from problem
            finally:
                self._loading.discard(language)
            self._errors.pop(language, None)
            self._loaded[language] = model
            log.info("модель %s загружена за %.0f мс", self.models[language], (time.perf_counter() - started) * 1000)
            return model

    def warm_up(self, languages: tuple[str, ...] = config.LANGUAGE_CODES) -> None:
        """Загружает модели заранее, чтобы первая фраза не ждала."""
        for language in languages:
            if self.package() and self.installed(language):
                try:
                    self.load(language)
                except RecognizerError:
                    log.exception("модель языка %s не загрузилась", language)

    def start_in_background(self) -> None:
        threading.Thread(target=self.warm_up, name="sluhach-models", daemon=True).start()

    # --- распознавание ------------------------------------------------------------------

    def stream(self, language: str, rate: int = config.SAMPLE_RATE) -> VoskStream:
        import vosk

        recognizer = vosk.KaldiRecognizer(self.load(language), rate)
        recognizer.SetWords(True)                    # вместе со словами — уверенность в каждом
        return VoskStream(recognizer)

    def recognize(self, samples: np.ndarray, language: str, rate: int = config.SAMPLE_RATE,
                  chunk_ms: int = 100) -> Recognition:
        """Распознаёт готовую запись, подавая её кусками, как с микрофона."""
        stream = self.stream(language, rate)
        pcm = samples.astype("<i2").tobytes()
        step = 2 * rate * chunk_ms // 1000
        for offset in range(0, len(pcm), step):
            stream.accept(pcm[offset:offset + step])
        return stream.finish()
