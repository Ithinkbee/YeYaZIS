"""Голоса Пафнутия: как он передразнивает сказанное в микрофон.

Кот из «Говорящего Тома» повторяет за игроком писклявым голосом: запись
ускорена, и тон от этого выше. Пафнутий умеет так же и ещё по-разному:

* **писк** — тон на 7 полутонов выше и чуть быстрее: классический «Том»;
* **бас** — тон на 5 полутонов ниже: паук-великан;
* **робот** — речь раскладывается моделью «источник — фильтр»: по каждому
  кадру 25 мс линейное предсказание (LPC, 18 коэффициентов) находит фильтр
  речевого тракта, а вместо голосовых связок его возбуждает ровный поток
  импульсов 120 Гц. Слова остаются, интонация исчезает — голос машины;
* **шёпот** — тот же фильтр, но возбуждается шумом: связки «не звучат»;
* **эхо** — тон чуть выше и три затухающих повтора, как в пещере.

Робот и шёпот — тот же принцип, на котором строится формантный синтез
(engines/formant.py), только фильтр не задан правилами, а вычислен по
живому голосу.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import lfilter

from glashatai import dsp

#: множитель расширения полос формант при LPC-синтезе
EXPANSION = 0.985

EFFECTS = {
    "squeak": "писк",
    "bass": "бас",
    "robot": "робот",
    "whisper": "шёпот",
    "echo": "эхо",
}


def _lpc_resynthesis(samples: np.ndarray, rate: int, excitation: str, order: int = 18) -> np.ndarray:
    """Анализ LPC по кадрам и синтез с новым возбуждением (импульсы или шум)."""
    x = dsp.preemphasis(np.asarray(samples, dtype=np.float64), 0.95)
    size = int(rate * 0.025)
    hop = size // 2
    window = np.hanning(size)
    out = np.zeros(len(x) + size)
    rng = np.random.default_rng(7)
    period = int(rate / 120)
    phase = 0
    state = np.zeros(order)
    for start in range(0, len(x) - size, hop):
        frame = x[start: start + size] * window
        a, error = dsp.lpc(frame, order)
        # расширение полос: полюса чуть отодвигаются от единичной окружности, и фильтр
        # не «звенит» на резонансах сильнее, чем звучат импульсы
        a = a * EXPANSION ** np.arange(order + 1)
        gain = np.sqrt(max(error, 1e-12) / size)
        if excitation == "pulse":
            source = np.zeros(hop)
            positions = np.arange((period - phase) % period, hop, period)
            source[positions] = np.sqrt(period)
            phase = (phase + hop) % period
        else:
            source = rng.standard_normal(hop)
        if not np.all(np.isfinite(a)) or abs(a).max() > 1e4:
            a = np.zeros(order + 1)
            a[0] = 1
        y, state = lfilter([gain], a, source, zi=state * 0 if state.shape[0] != order else state)
        out[start: start + hop] += y
    result = dsp.deemphasis(out[: len(x)], 0.95)
    return result.astype(np.float32)


def apply(samples: np.ndarray, rate: int, effect: str) -> np.ndarray:
    """Эффект к записи; на выходе — уровень, приведённый к общему."""
    x = dsp.trim(np.asarray(samples, dtype=np.float32), rate, threshold_db=-50, keep_ms=60)
    if len(x) == 0:
        return x
    if effect == "squeak":
        y = dsp.stretch(dsp.pitch_shift(x, rate, 7), rate, 1.12)
    elif effect == "bass":
        y = dsp.stretch(dsp.pitch_shift(x, rate, -5), rate, 0.95)
    elif effect == "robot":
        y = _lpc_resynthesis(x, rate, "pulse")
        carrier = np.sin(2 * np.pi * 30 * np.arange(len(y)) / rate)
        y = y * (0.75 + 0.25 * carrier)
    elif effect == "whisper":
        y = _lpc_resynthesis(x, rate, "noise")
    elif effect == "echo":
        y = dsp.pitch_shift(x, rate, 3)
        delay = int(rate * 0.19)
        tail = np.zeros(len(y) + 3 * delay, dtype=np.float32)
        for repeat, gain in enumerate((1.0, 0.45, 0.22, 0.1)):
            tail[repeat * delay: repeat * delay + len(y)] += gain * y
        y = tail
    else:
        y = x
    return dsp.fade(dsp.normalize(y, rate, -16), rate, 10)
