"""Звуковой сигнал: уровень, обнаружение речи, чтение WAV, шум для проверки.

Система должна сама замечать, что с ней заговорили, — кнопку «говорю» никто
не нажимает. Для этого сигнал режется на кадры по 20 мс и у каждого
считается уровень. Речь громче шума комнаты, поэтому порог привязан к шуму:
пока говорящий молчит, уровень шума оценивается заново с каждым кадром, а
речь начинается там, где несколько кадров подряд заметно громче этого
уровня, и кончается после достаточно долгой паузы.
"""

from __future__ import annotations

import math
import wave
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from sluhach import config

#: уровень полной тишины (цифровой ноль), дБ
SILENCE_DB = -100.0
FULL_SCALE = 32768.0


def to_samples(pcm: bytes) -> np.ndarray:
    """16-разрядные отсчёты из байтов PCM (младший байт первым, один канал)."""
    return np.frombuffer(pcm[:len(pcm) - len(pcm) % 2], dtype="<i2")


def level_db(samples: np.ndarray) -> float:
    """Среднеквадратичный уровень в дБ относительно полной шкалы: 0 — предел, тише — меньше."""
    if not len(samples):
        return SILENCE_DB
    rms = math.sqrt(float(np.mean(np.square(samples.astype(np.float64))))) / FULL_SCALE
    return max(SILENCE_DB, 20.0 * math.log10(rms)) if rms > 0 else SILENCE_DB


# --- обнаружение речи -----------------------------------------------------------

@dataclass
class VadSettings:
    rate: int = config.SAMPLE_RATE
    frame_ms: int = config.FRAME_MS
    start_margin_db: float = config.VAD_START_MARGIN_DB
    end_margin_db: float = config.VAD_END_MARGIN_DB
    min_level_db: float = config.VAD_MIN_LEVEL_DB
    start_frames: int = config.VAD_START_FRAMES
    start_window: int = config.VAD_START_WINDOW
    end_silence_ms: int = config.VAD_END_SILENCE_MS
    preroll_ms: int = config.VAD_PREROLL_MS
    max_utterance_ms: int = config.VAD_MAX_UTTERANCE_MS
    min_speech_ms: int = config.VAD_MIN_SPEECH_MS

    @property
    def frame_samples(self) -> int:
        return self.rate * self.frame_ms // 1000

    def frames(self, ms: float) -> int:
        return max(1, round(ms / self.frame_ms))


@dataclass
class VadEvent:
    kind: str                                   # start | speech | end | drop
    frames: list[np.ndarray] = field(default_factory=list)      # start: звук перед началом речи
    duration_ms: int = 0                        # end, drop: длительность фразы без конечной паузы
    level_db: float = SILENCE_DB                # end, drop: средний уровень фразы
    forced: bool = False                        # end: фраза оборвана по предельной длине


class Vad:
    """Обнаружение речи по энергии кадров; порог следит за шумом комнаты.

    Кадры подаются по одному через `push`. В тишине детектор оценивает шум:
    вверх оценка ползёт медленно (иначе её поднимала бы сама речь), вниз
    падает быстро. Первые кадры идут только на оценку шума — иначе шумный
    микрофон открывал бы «фразу» сразу после включения.
    """

    WARMUP_FRAMES = 15           # 300 мс на первую оценку шума
    NOISE_UP = 0.04              # доля, на которую оценка шума идёт вверх за кадр
    NOISE_DOWN = 0.25            # и вниз
    NOISE_RANGE = (-90.0, -20.0)

    def __init__(self, settings: VadSettings | None = None) -> None:
        self.settings = settings or VadSettings()
        self.noise_db = -60.0
        self.speaking = False
        self._warmup: list[float] = []
        self._recent: deque[bool] = deque(maxlen=self.settings.start_window)
        self._preroll: deque[np.ndarray] = deque(maxlen=self.settings.frames(self.settings.preroll_ms))
        self._total = 0              # кадров во фразе
        self._voiced = 0             # из них громких
        self._silence = 0            # тихих кадров подряд в конце
        self._levels: list[float] = []

    @property
    def start_threshold(self) -> float:
        return max(self.noise_db + self.settings.start_margin_db, self.settings.min_level_db)

    @property
    def end_threshold(self) -> float:
        return max(self.noise_db + self.settings.end_margin_db, self.settings.min_level_db - 3.0)

    def reset(self) -> None:
        """Забывает начатую фразу (например, система сама заговорила); оценка шума остаётся."""
        self.speaking = False
        self._recent.clear()
        self._preroll.clear()
        self._total = self._voiced = self._silence = 0
        self._levels = []

    def raise_floor(self, level: float) -> None:
        """Считает звук такого уровня шумом: распознаватель не нашёл в нём слов.

        Порог поднимается ровно настолько, чтобы тот же звук фразу больше не
        открывал; когда шум стихнет, оценка за доли секунды вернётся вниз.
        """
        low, high = self.NOISE_RANGE
        self.noise_db = min(high, max(low, self.noise_db, level - self.settings.start_margin_db + 2.0))

    def _track_noise(self, level: float) -> None:
        low, high = self.NOISE_RANGE
        rate = self.NOISE_DOWN if level < self.noise_db else self.NOISE_UP
        self.noise_db = min(high, max(low, self.noise_db + rate * (level - self.noise_db)))

    def push(self, frame: np.ndarray) -> list[VadEvent]:
        level = level_db(frame)
        settings = self.settings

        if len(self._warmup) < self.WARMUP_FRAMES:
            self._warmup.append(level)
            self._preroll.append(frame)
            if len(self._warmup) == self.WARMUP_FRAMES:
                low, high = self.NOISE_RANGE
                self.noise_db = min(high, max(low, float(np.median(self._warmup))))
            return []

        if not self.speaking:
            loud = level >= self.start_threshold
            self._recent.append(loud)
            self._preroll.append(frame)
            if not loud:
                self._track_noise(level)
            if sum(self._recent) < settings.start_frames:
                return []
            self.speaking = True
            self._total = len(self._preroll)
            self._voiced = sum(self._recent)
            self._silence = 0
            self._levels = [level]
            before = list(self._preroll)
            self._preroll.clear()
            self._recent.clear()
            return [VadEvent("start", frames=before)]

        events = [VadEvent("speech", frames=[frame])]
        self._total += 1
        if level >= self.end_threshold:
            self._voiced += 1
            self._silence = 0
            self._levels.append(level)
        else:
            self._silence += 1

        ended = self._silence >= settings.frames(settings.end_silence_ms)
        forced = not ended and self._total >= settings.frames(settings.max_utterance_ms)
        if not ended and not forced:
            return events

        duration = (self._total - self._silence) * settings.frame_ms
        mean = float(np.mean(self._levels)) if self._levels else SILENCE_DB
        short = self._voiced * settings.frame_ms < settings.min_speech_ms
        if forced:
            # звук не стихает четверть минуты — это не фраза, а новый шум комнаты
            self.raise_floor(mean)
        self.reset()
        events.append(VadEvent("drop" if short else "end", duration_ms=duration, level_db=mean, forced=forced))
        return events


def split_frames(samples: np.ndarray, frame_samples: int) -> list[np.ndarray]:
    """Режет сигнал на кадры; неполный хвост отбрасывается."""
    return [samples[i:i + frame_samples] for i in range(0, len(samples) - frame_samples + 1, frame_samples)]


# --- файлы и шум (для проверки распознавания) -------------------------------------

def resample(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    """Передискретизация линейной интерполяцией; перед понижением частоты — сглаживание."""
    if source_rate == target_rate or not len(samples):
        return samples
    data = samples.astype(np.float64)
    if source_rate > target_rate:
        width = max(1, round(source_rate / target_rate))
        data = np.convolve(data, np.ones(width) / width, mode="same")
    count = int(len(data) * target_rate / source_rate)
    positions = np.arange(count) * (source_rate / target_rate)
    return np.interp(positions, np.arange(len(data)), data).round().astype(np.int16)


def read_wav(path: Path, rate: int = config.SAMPLE_RATE) -> np.ndarray:
    """Отсчёты WAV-файла: один канал, 16 разрядов, частота rate."""
    with wave.open(str(path), "rb") as source:
        if source.getsampwidth() != 2:
            raise ValueError(f"{path.name}: нужен 16-разрядный WAV")
        channels, source_rate = source.getnchannels(), source.getframerate()
        samples = to_samples(source.readframes(source.getnframes()))
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1).round().astype(np.int16)
    return resample(samples, source_rate, rate)


def write_wav(path: Path, samples: np.ndarray, rate: int = config.SAMPLE_RATE) -> None:
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(rate)
        target.writeframes(samples.astype("<i2").tobytes())


def pad(samples: np.ndarray, before_ms: int, after_ms: int, rate: int = config.SAMPLE_RATE) -> np.ndarray:
    """Добавляет тишину до и после фразы — как в записи с микрофона."""
    head = np.zeros(rate * before_ms // 1000, dtype=np.int16)
    tail = np.zeros(rate * after_ms // 1000, dtype=np.int16)
    return np.concatenate([head, samples, tail])


def add_noise(samples: np.ndarray, snr_db: float, rng: np.random.Generator) -> np.ndarray:
    """Примешивает белый шум с заданным отношением сигнал/шум (дБ).

    Мощность сигнала считается по звучащим кадрам, а не по всей записи с
    паузами: иначе у фразы с длинной тишиной шум вышел бы слабее заявленного.
    """
    if not len(samples):
        return samples
    frames = split_frames(samples, config.SAMPLE_RATE * config.FRAME_MS // 1000) or [samples]
    powers = np.array([float(np.mean(np.square(frame.astype(np.float64)))) for frame in frames])
    voiced = powers[powers >= powers.max() * 0.01] if powers.max() > 0 else powers
    signal_power = float(voiced.mean()) if len(voiced) else 0.0
    if signal_power <= 0:
        return samples
    noise_power = signal_power / (10 ** (snr_db / 10))
    noise = rng.normal(0.0, math.sqrt(noise_power), len(samples))
    return np.clip(samples.astype(np.float64) + noise, -32768, 32767).round().astype(np.int16)
