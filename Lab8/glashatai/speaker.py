"""Диктор: текст -> предложения -> звук выбранным голосом.

Здесь сходится всё: разбор текста (text/), синтезаторы (engines/) и
обработка звука (dsp.py). Порядок для каждого предложения:

1. нормализованное предложение отдаётся движку выбранного голоса — в том
   виде, который движок понимает лучше (см. Sentence.render);
2. темп и высоту, которых движок не умеет, доделывает dsp.py;
3. тишина по краям срезается, уровень приводится к −18 дБ, края плавно
   нарастают и затухают — голоса разных движков звучат одинаково громко и
   без щелчков на стыках;
4. громкость (если её не регулирует страница) и паузы между предложениями
   и абзацами добавляются при сборке всего текста.

Синтезированные предложения хранятся в памяти (по ключу «голос, темп,
высота, живость, текст»): повторное чтение и шаг назад не синтезируются
заново.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

import numpy as np

from glashatai import config, dsp
from glashatai.engines import Audio, EngineError, Settings, Voice, formant, split_voice
from glashatai.engines.piper import PiperEngine
from glashatai.engines.sapi import SapiEngine
from glashatai.text import Document, Lexicon, ReadingOptions, Sentence, TextReader, UserLexicon

log = logging.getLogger("glashatai.speaker")


@dataclass
class Spoken:
    """Синтезированное предложение и сведения о синтезе."""
    audio: Audio
    voice: str              # голос, которым оно сказано на самом деле
    engine_ms: float        # время синтеза
    cached: bool = False
    fallback: bool = False  # выбранного голоса нет — прочитано голосом по умолчанию


class Speaker:
    def __init__(self, reader: TextReader | None = None, piper: PiperEngine | None = None,
                 sapi: SapiEngine | None = None) -> None:
        self.reader = reader or TextReader(Lexicon(user=UserLexicon()))
        self.piper = piper or PiperEngine()
        self.sapi = sapi or SapiEngine()
        self._cache: OrderedDict[str, Audio] = OrderedDict()
        self._cache_bytes = 0
        self._lock = threading.Lock()
        self._voices: list[Voice] | None = None
        self._voices_at = 0.0

    # --- голоса ---------------------------------------------------------------------------

    def voices(self, refresh: bool = False) -> list[Voice]:
        """Все голоса: нейросетевые, собственные, Windows и браузера."""
        if self._voices is None or refresh or time.time() - self._voices_at > 60:
            found = list(self.piper.voices())
            found += [Voice(f"formant:{v.id}", "formant", v.title, v.gender, True, v.note,
                            ["rate", "pitch", "liveliness"]) for v in formant.VOICES.values()]
            found += self.sapi.voices()
            found.append(Voice("browser:auto", "browser", "Голос браузера", "", True,
                               "немецкий голос самого браузера (Web Speech API)", ["rate", "pitch"]))
            self._voices = found
            self._voices_at = time.time()
        return self._voices

    def voice(self, voice_id: str) -> Voice | None:
        return next((v for v in self.voices() if v.id == voice_id), None)

    def default_voice(self) -> str:
        found = self.voice(config.DEFAULT_VOICE)
        if found is not None and found.available:
            return found.id
        for candidate in self.voices():
            if candidate.engine == "piper" and candidate.available:
                return candidate.id
        return config.FALLBACK_VOICE

    def usable(self, voice_id: str) -> tuple[str, bool]:
        """Голос, которым можно читать: выбранный или (если его нет) голос по умолчанию."""
        found = self.voice(voice_id)
        if found is not None and found.available and found.engine != "browser":
            return voice_id, False
        return self.default_voice(), True

    # --- текст ----------------------------------------------------------------------------

    def prepare(self, text: str, options: ReadingOptions | None = None) -> Document:
        return self.reader.prepare(text[: config.MAX_TEXT_CHARS], options)

    def sentence(self, text: str, options: ReadingOptions | None = None, heading: bool = False,
                 continued: bool = False) -> Sentence:
        sentence = self.reader.sentence(text[: config.MAX_SENTENCE_CHARS * 4], options)
        sentence.heading = heading
        sentence.continued = continued
        return sentence

    # --- звук -----------------------------------------------------------------------------

    def _key(self, sentence: Sentence, settings: Settings, voice_id: str, phonetic: bool) -> str:
        raw = f"{voice_id}|{settings.key()[1:]}|{phonetic}|{sentence.kind}|{sentence.continued}|" \
              f"{sentence.render('say')}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _remember(self, key: str, audio: Audio) -> None:
        size = audio.samples.nbytes
        with self._lock:
            self._cache[key] = audio
            self._cache_bytes += size
            limit = config.CACHE_MEMORY_MB * 1024 * 1024
            while self._cache_bytes > limit and self._cache:
                _, old = self._cache.popitem(last=False)
                self._cache_bytes -= old.samples.nbytes

    def _recall(self, key: str) -> Audio | None:
        with self._lock:
            audio = self._cache.get(key)
            if audio is not None:
                self._cache.move_to_end(key)
            return audio

    def synthesize(self, sentence: Sentence, settings: Settings, phonetic: bool = True) -> Spoken:
        """Предложение -> звук, приведённый к общему уровню; громкость не применяется."""
        voice_id, fallback = self.usable(settings.voice)
        key = self._key(sentence, settings, voice_id, phonetic)
        cached = self._recall(key)
        if cached is not None:
            return Spoken(cached, voice_id, 0.0, cached=True, fallback=fallback)
        started = time.perf_counter()
        audio = self._engine(sentence, voice_id, settings, phonetic)
        engine_ms = (time.perf_counter() - started) * 1000
        samples = dsp.trim(audio.samples, audio.rate, keep_ms=30)
        if len(samples):
            samples = dsp.fade(dsp.normalize(samples, audio.rate, config.TARGET_LEVEL_DB), audio.rate, 6)
        else:
            # читать нечего (например, одна ссылка «[12]») — короткая тишина, а не пустой файл
            samples = dsp.silence(60, audio.rate)
        audio = Audio(samples.astype(np.float32), audio.rate)
        self._remember(key, audio)
        return Spoken(audio, voice_id, engine_ms, fallback=fallback)

    def _engine(self, sentence: Sentence, voice_id: str, settings: Settings, phonetic: bool) -> Audio:
        engine, name, speaker = split_voice(voice_id)
        if engine == "piper":
            audio = self.piper.synthesize(sentence, name, speaker, settings, phonetic)
            if abs(settings.pitch) >= 0.05:
                audio = Audio(dsp.pitch_shift(audio.samples, audio.rate, settings.pitch), audio.rate)
            return audio
        if engine == "formant":
            samples, rate = formant.synthesize(sentence.render("say"), name, sentence.kind, settings.rate,
                                               settings.pitch, intonation=0.3 + 1.4 * settings.liveliness)
            return Audio(samples, rate)
        if engine == "sapi":
            audio = self.sapi.synthesize_text(sentence.render("plain"), name, settings)
            if abs(settings.pitch) >= 0.05:
                audio = Audio(dsp.pitch_shift(audio.samples, audio.rate, settings.pitch), audio.rate)
            return audio
        raise EngineError(f"неизвестный голос «{voice_id}»")

    def speak(self, text: str, settings: Settings, options: ReadingOptions | None = None,
              volume: bool = True) -> Spoken:
        """Короткий текст целиком (одно или несколько предложений) — для закладки и других программ."""
        document = self.prepare(text, options)
        parts: list[np.ndarray] = []
        rate = None
        voice = settings.voice
        engine_ms = 0.0
        fallback = False
        sentences = document.sentences
        for index, sentence in enumerate(sentences):
            spoken = self.synthesize(sentence, settings)
            voice, fallback = spoken.voice, spoken.fallback
            engine_ms += spoken.engine_ms
            if rate is None:
                rate = spoken.audio.rate
            parts.append(dsp.resample(spoken.audio.samples, spoken.audio.rate, rate))
            if index + 1 < len(sentences):
                pause = 0 if sentence.continued else (
                    settings.paragraph_pause if sentences[index + 1].paragraph != sentence.paragraph
                    else settings.sentence_pause)
                parts.append(dsp.silence(pause, rate))
        rate = rate or formant.SAMPLE_RATE
        samples = dsp.concatenate(parts)
        if volume:
            samples = dsp.apply_volume(samples, settings.volume)
        return Spoken(Audio(samples, rate), voice, engine_ms, fallback=fallback)

    def render(self, text: str, settings: Settings, options: ReadingOptions | None = None) -> Spoken:
        """Весь текст одной записью — для «Сохранить в файл»."""
        return self.speak(text, settings, options, volume=True)


def wav_name(text: str) -> str:
    """Имя файла записи по первым словам текста."""
    words = "".join(ch if ch.isalnum() else " " for ch in text[:80]).split()[:5]
    return ("-".join(words) or "glashatai") + ".wav"
