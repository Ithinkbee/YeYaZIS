"""Обработка звука: громкость, темп, высота, WAV.

Синтезаторы умеют разное: Piper меняет темп сам, но не высоту; голоса
Windows — темп; собственный синтезатор — и темп, и высоту. Чтобы настройки
действовали одинаково на все голоса, недостающее делается здесь.

* **Громкость.** Каждая запись сначала приводится к одному уровню
  (−18 дБ относительно полной шкалы по громким участкам), затем ослабляется
  на 20·lg(громкость/100) дБ. Пики выше полной шкалы мягко ограничиваются.
* **Темп без изменения высоты** — WSOLA (waveform-similarity overlap-add):
  запись режется на перекрывающиеся окна по 40 мс; окна берутся из исходной
  записи с другим шагом, чем кладутся в новую, а точное место каждого
  окна (±10 мс) выбирается по наибольшей корреляции с продолжением
  предыдущего — так периоды голоса не рвутся и не слышно «бульканья».
* **Высота без изменения темпа** — растяжение WSOLA в 2^(n/12) раз и
  передискретизация обратно: длительность прежняя, тон выше или ниже на
  n полутонов (форманты сдвигаются вместе с тоном).
"""

from __future__ import annotations

import io
import math
import wave
from math import gcd

import numpy as np
from scipy.signal import lfilter, resample_poly


def silence(ms: float, rate: int) -> np.ndarray:
    return np.zeros(max(0, int(rate * ms / 1000)), dtype=np.float32)


def to_wav(samples: np.ndarray, rate: int) -> bytes:
    """Моно, 16 бит."""
    pcm = (np.clip(np.asarray(samples, dtype=np.float64), -1.0, 1.0) * 32767).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(int(rate))
        out.writeframes(pcm.tobytes())
    return buffer.getvalue()


def read_wav(data: bytes) -> tuple[np.ndarray, int]:
    """WAV (8/16/32 бит, моно или стерео) -> моно float32."""
    with wave.open(io.BytesIO(data), "rb") as source:
        rate = source.getframerate()
        width = source.getsampwidth()
        channels = source.getnchannels()
        raw = source.readframes(source.getnframes())
    if width == 2:
        samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
    elif width == 1:
        samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) / 128
    elif width == 4:
        samples = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2 ** 31
    else:
        raise ValueError("неподдерживаемый формат WAV")
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples.astype(np.float32), rate


def resample(samples: np.ndarray, rate: int, target: int) -> np.ndarray:
    if rate == target or len(samples) == 0:
        return np.asarray(samples, dtype=np.float32)
    divisor = gcd(int(rate), int(target))
    return resample_poly(samples, target // divisor, rate // divisor).astype(np.float32)


def frame_levels(samples: np.ndarray, rate: int, frame_ms: float = 20) -> np.ndarray:
    """Уровень по кадрам, дБ относительно полной шкалы."""
    size = max(1, int(rate * frame_ms / 1000))
    count = len(samples) // size
    if count == 0:
        return np.array([-120.0])
    frames = np.asarray(samples[: count * size], dtype=np.float64).reshape(count, size)
    rms = np.sqrt(np.mean(frames ** 2, axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-6))


def speech_level(samples: np.ndarray, rate: int) -> float:
    """Уровень речи: средняя мощность громких кадров (тише −50 дБ и паузы не считаются)."""
    levels = frame_levels(samples, rate)
    loud = levels[levels > max(-50.0, levels.max() - 30)]
    if len(loud) == 0:
        return -120.0
    return float(10 * np.log10(np.mean(10 ** (loud / 10))))


def soft_limit(samples: np.ndarray, ceiling: float = 0.97) -> np.ndarray:
    """Мягкое ограничение пиков: ниже 0,8 сигнал не меняется."""
    x = np.asarray(samples, dtype=np.float64)
    knee = 0.8 * ceiling
    over = np.abs(x) > knee
    if over.any():
        excess = (np.abs(x[over]) - knee) / (ceiling - knee)
        x[over] = np.sign(x[over]) * (knee + (ceiling - knee) * np.tanh(excess))
    return x.astype(np.float32)


def normalize(samples: np.ndarray, rate: int, target_db: float) -> np.ndarray:
    level = speech_level(samples, rate)
    if level < -100:
        return np.asarray(samples, dtype=np.float32)
    return soft_limit(samples * 10 ** ((target_db - level) / 20))


def volume_gain(percent: float) -> float:
    """Громкость в процентах -> множитель: 100 % — 1, 50 % — −6 дБ, 0 — тишина."""
    percent = max(0.0, min(100.0, float(percent)))
    return percent / 100.0


def apply_volume(samples: np.ndarray, percent: float) -> np.ndarray:
    return soft_limit(np.asarray(samples, dtype=np.float32) * volume_gain(percent))


def fade(samples: np.ndarray, rate: int, ms: float = 8) -> np.ndarray:
    """Короткое нарастание и затухание на краях: без щелчков на стыках."""
    x = np.array(samples, dtype=np.float32)
    n = min(len(x) // 2, int(rate * ms / 1000))
    if n > 1:
        ramp = np.linspace(0, 1, n, dtype=np.float32)
        x[:n] *= ramp
        x[-n:] *= ramp[::-1]
    return x


def trim(samples: np.ndarray, rate: int, threshold_db: float = -45, keep_ms: float = 40) -> np.ndarray:
    """Срезает тишину по краям, оставляя keep_ms."""
    levels = frame_levels(samples, rate, 10)
    loud = np.where(levels > threshold_db)[0]
    if len(loud) == 0:
        return np.zeros(0, dtype=np.float32)
    size = int(rate * 0.01)
    keep = int(rate * keep_ms / 1000)
    start = max(0, loud[0] * size - keep)
    end = min(len(samples), (loud[-1] + 1) * size + keep)
    return np.asarray(samples[start:end], dtype=np.float32)


# --- темп и высота ---------------------------------------------------------------------------

def wsola(samples: np.ndarray, rate: int, factor: float, frame_ms: float = 40,
          tolerance_ms: float = 10) -> np.ndarray:
    """Темп без изменения высоты: factor > 1 — быстрее (короче), < 1 — медленнее."""
    x = np.asarray(samples, dtype=np.float64)
    if abs(factor - 1.0) < 1e-3 or len(x) < rate * 0.05:
        return x.astype(np.float32)
    size = int(rate * frame_ms / 1000) // 2 * 2
    hop_out = size // 2
    hop_in = hop_out * factor
    tolerance = int(rate * tolerance_ms / 1000)
    window = np.hanning(size)
    padded = np.concatenate([np.zeros(size + tolerance), x, np.zeros(2 * size + tolerance)])
    out_length = int(len(x) / factor)
    out = np.zeros(out_length + 2 * size)
    weight = np.zeros_like(out)
    position_in = 0.0
    position_out = 0
    previous = None
    offset = size + tolerance
    while position_out < out_length + size:
        center = int(round(position_in)) + offset
        if previous is None:
            best = center
        else:
            # естественное продолжение предыдущего окна — сдвиг на hop_out в исходной записи
            template = padded[previous + hop_out: previous + hop_out + hop_out]
            start = max(0, center - tolerance)
            region = padded[start: center + tolerance + hop_out]
            if len(region) >= len(template) and template.any():
                scores = np.correlate(region, template, mode="valid")
                best = start + int(np.argmax(scores))
            else:
                best = center
        chunk = padded[best: best + size]
        if len(chunk) < size:
            break
        out[position_out: position_out + size] += chunk * window
        weight[position_out: position_out + size] += window
        previous = best
        position_in += hop_in
        position_out += hop_out
    weight[weight < 1e-3] = 1.0
    result = out / weight
    return result[hop_out // 2: hop_out // 2 + out_length].astype(np.float32) if out_length else np.zeros(0, np.float32)


def stretch(samples: np.ndarray, rate: int, tempo: float) -> np.ndarray:
    """Темп: 1,5 — в полтора раза быстрее."""
    return wsola(samples, rate, tempo)


def pitch_shift(samples: np.ndarray, rate: int, semitones: float) -> np.ndarray:
    """Высота на semitones полутонов при той же длительности."""
    if abs(semitones) < 0.05 or len(samples) == 0:
        return np.asarray(samples, dtype=np.float32)
    ratio = 2 ** (semitones / 12)
    longer = wsola(samples, rate, 1 / ratio)
    # передискретизация обратно к исходной длине поднимает тон в ratio раз
    up, down = _ratio(ratio)
    shifted = resample_poly(longer, down, up)
    target = len(samples)
    if len(shifted) > target:
        shifted = shifted[:target]
    elif len(shifted) < target:
        shifted = np.concatenate([shifted, np.zeros(target - len(shifted))])
    return shifted.astype(np.float32)


def _ratio(value: float, limit: int = 200) -> tuple[int, int]:
    """Дробь up/down, близкая к value, с небольшими числами — для resample_poly."""
    best = (1, 1)
    error = abs(value - 1)
    for down in range(1, limit + 1):
        up = round(value * down)
        if up < 1:
            continue
        candidate = abs(value - up / down)
        if candidate < error - 1e-9:
            best, error = (up, down), candidate
        if error < 1e-4:
            break
    return best


def concatenate(parts: list[np.ndarray]) -> np.ndarray:
    parts = [np.asarray(p, dtype=np.float32) for p in parts if p is not None and len(p)]
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)


# --- анализ ------------------------------------------------------------------------------------

def envelope(samples: np.ndarray, rate: int, frame_ms: float = 20) -> list[float]:
    """Огибающая 0…1 по кадрам — по ней Пафнутий открывает рот."""
    levels = frame_levels(samples, rate, frame_ms)
    opened = np.clip((levels + 50) / 35, 0, 1)
    return [round(float(v), 3) for v in opened]


def estimate_f0(samples: np.ndarray, rate: int, low: float = 60, high: float = 600) -> float | None:
    """Медиана основного тона по звонким кадрам (автокорреляция). Для проверок."""
    x = np.asarray(samples, dtype=np.float64)
    size = int(rate * 0.04)
    hop = size // 2
    values = []
    levels_cut = speech_level(x, rate) - 12
    for start in range(0, len(x) - size, hop):
        frame = x[start: start + size]
        frame = frame - frame.mean()
        rms = math.sqrt(float(np.mean(frame ** 2))) + 1e-12
        if 20 * math.log10(rms) < levels_cut:
            continue
        corr = np.correlate(frame, frame, mode="full")[size - 1:]
        lo, hi = int(rate / high), min(len(corr) - 1, int(rate / low))
        if hi <= lo:
            continue
        lag = lo + int(np.argmax(corr[lo:hi]))
        if corr[lag] / (corr[0] + 1e-12) > 0.45:
            # уточнение параболой
            if 0 < lag < len(corr) - 1:
                a, b, c = corr[lag - 1], corr[lag], corr[lag + 1]
                curve = a - 2 * b + c
                shift = 0.5 * (a - c) / curve if curve < 0 else 0.0
                lag = lag + max(-0.5, min(0.5, shift))
            values.append(rate / lag)
    return float(np.median(values)) if values else None


def lpc(frame: np.ndarray, order: int) -> tuple[np.ndarray, float]:
    """Коэффициенты линейного предсказания (Левинсон — Дарбин) и ошибка."""
    x = np.asarray(frame, dtype=np.float64)
    r = np.correlate(x, x, mode="full")[len(x) - 1: len(x) + order]
    if r[0] <= 0:
        # тишина: фильтр, который ничего не меняет
        flat = np.zeros(order + 1)
        flat[0] = 1.0
        return flat, 0.0
    a = np.zeros(order + 1)
    a[0] = 1.0
    error = r[0] * (1 + 1e-9)
    for i in range(1, order + 1):
        acc = r[i] + np.dot(a[1:i], r[i - 1:0:-1])
        k = -acc / error
        a[1:i] = a[1:i] + k * a[i - 1:0:-1]
        a[i] = k
        error *= 1 - k * k
        if error <= 0:
            break
    return a, max(error, 0.0)


def preemphasis(samples: np.ndarray, coefficient: float = 0.95) -> np.ndarray:
    return lfilter([1, -coefficient], [1], samples)


def deemphasis(samples: np.ndarray, coefficient: float = 0.95) -> np.ndarray:
    return lfilter([1], [1, -coefficient], samples)
