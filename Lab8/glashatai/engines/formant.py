"""Собственный синтезатор системы: формантный, по схеме Клатта.

Так работали первые синтезаторы речи — MITalk, DECtalk, в котором говорил
Стивен Хокинг, — и так до сих пор устроен eSpeak. Речь строится не из
записанных кусков, а из модели речевого тракта (модель «источник —
фильтр»):

* **источник голоса** — импульсы голосовой щели с частотой основного тона;
  форма импульса — по Розенбергу: щель плавно открывается, быстрее
  закрывается, потом закрыта;
* **источник шума** — белый шум: придыхание («h», «p» в начале слога) и
  шум узкой щели («s», «ʃ», «f»);
* **каскад резонаторов** — пять формант, через которые проходит голос:
  положение первых двух формант и отличает «а» от «и»; для носовых в каскад
  добавлены носовой полюс и нуль;
* **параллельная ветвь** — шум проходит через резонаторы с собственными
  усилителями: так задаётся спектр шумных согласных («s» — высокий,
  «ʃ» — средний, «x» — низкий).

Параметры (форманты, полосы, громкость голоса, шума и придыхания, тон)
меняются каждые 5 мс. Для каждой фонемы задана цель; между целями параметры
сглаживаются — так получаются переходы формант между звуками, по которым
слух и узнаёт согласные (коартикуляция). Партитуру — длительности и
мелодию — строит prosody.py.

Звук получается узнаваемо «машинным» — и это голос Пафнутия.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import lfilter

from glashatai.phonetics.g2p import DIPHTHONGS, VOWELS
from glashatai.phonetics.prosody import Score, score

SAMPLE_RATE = 22050
HOP = 110                       # отсчётов на кадр параметров (≈ 5 мс)
FRAME_MS = 1000 * HOP / SAMPLE_RATE

#: усиление шумовой ветви и придыхания относительно голоса. Подобраны так, чтобы
#: шумные согласные были тише гласных, как в живой речи: «s» — примерно на 12 дБ,
#: «ʃ» — на 10, «f» — на 22, «h» — на 20 (см. tests/test_formant.py)
FRICATION_GAIN = 16.0
ASPIRATION_GAIN = 1.1


@dataclass(frozen=True)
class FormantVoice:
    id: str
    title: str
    gender: str
    f0: float                   # средний основной тон, Гц
    scale: float                # множитель формант: короче речевой тракт — выше форманты
    open_quotient: float        # доля периода, когда голосовая щель открыта
    rate: float = 1.0           # собственный темп голоса
    breath: float = 0.04        # придыхание в голосе
    note: str = ""


VOICES = {
    "karl": FormantVoice("karl", "Карл", "мужской", 112, 1.0, 0.6, note="ровный голос диктора-робота"),
    "klara": FormantVoice("klara", "Клара", "женский", 205, 1.14, 0.55, 1.03, 0.07, "голос выше, тракт короче"),
    "pafnuty": FormantVoice("pafnuty", "Пафнутий", "паучий", 255, 1.24, 0.5, 1.08, 0.05,
                            "маленький тракт, высокий тон — голос паука"),
}

# --- цели фонем ---------------------------------------------------------------------------
#
# Форманты гласных — средние значения для немецкого мужского голоса (по формантным
# картам немецких гласных); согласные — по таблицам Клатта (1980), приведённым к
# немецкому набору. Громкости — в дБ: 60 дБ — единичная амплитуда.

VOWEL_TARGETS: dict[str, tuple[int, int, int]] = {
    "iː": (270, 2250, 3000), "i": (300, 2150, 2900), "ɪ": (380, 1950, 2650),
    "yː": (270, 1750, 2150), "y": (300, 1700, 2200), "ʏ": (370, 1550, 2200),
    "eː": (360, 2150, 2700), "e": (400, 2000, 2650), "ɛ": (530, 1750, 2500), "ɛː": (480, 1950, 2550),
    "øː": (370, 1500, 2200), "ø": (400, 1500, 2250), "œ": (510, 1400, 2300),
    "ə": (480, 1450, 2450), "ɐ": (620, 1300, 2450), "ɐ̯": (560, 1350, 2450),
    "aː": (750, 1250, 2550), "a": (700, 1300, 2550),
    "oː": (380, 750, 2400), "o": (420, 850, 2450), "ɔ": (560, 900, 2450),
    "uː": (300, 650, 2250), "u": (330, 750, 2300), "ʊ": (390, 950, 2300),
}
DIPHTHONG_PARTS = {"aɪ": ("a", "ɪ"), "aʊ": ("a", "ʊ"), "ɔʏ": ("ɔ", "ʏ"), "ɛɪ": ("ɛ", "ɪ"), "oʊ": ("o", "ʊ")}

#: места образования согласных: «локус» — куда тянутся форманты соседних гласных
LOCI = {
    "labial": (250, 900, 2200), "dental": (280, 1700, 2600), "postalveolar": (280, 1850, 2700),
    "palatal": (260, 2100, 2950), "velar_front": (280, 2050, 2550), "velar_back": (300, 1250, 2350),
    "uvular": (500, 1250, 2300), "glottal": (None, None, None),
}

#: согласные: вид, место, голос AV, шум AF, придыхание AH, спектр шума (дБ резонаторов 2–6 и обхода)
CONSONANTS: dict[str, dict] = {
    "p": {"type": "stop", "place": "labial", "voiced": False, "burst": {"AB": 52, "A2": 42}},
    "b": {"type": "stop", "place": "labial", "voiced": True, "burst": {"AB": 48, "A2": 40}},
    "t": {"type": "stop", "place": "dental", "voiced": False, "burst": {"A5": 50, "A6": 54, "A4": 44}},
    "d": {"type": "stop", "place": "dental", "voiced": True, "burst": {"A5": 46, "A6": 50, "A4": 40}},
    "k": {"type": "stop", "place": "velar", "voiced": False, "burst": {"A3": 54, "A2": 48, "A4": 44}},
    "ɡ": {"type": "stop", "place": "velar", "voiced": True, "burst": {"A3": 50, "A2": 44, "A4": 40}},
    "f": {"type": "fric", "place": "labial", "voiced": False, "AF": 50, "spec": {"AB": 52, "A5": 40, "A6": 42}},
    "v": {"type": "fric", "place": "labial", "voiced": True, "AF": 50, "spec": {"AB": 48, "A6": 38}},
    "s": {"type": "fric", "place": "dental", "voiced": False, "AF": 60, "spec": {"A6": 56, "A5": 46}},
    "z": {"type": "fric", "place": "dental", "voiced": True, "AF": 54, "spec": {"A6": 52, "A5": 42}},
    "ʃ": {"type": "fric", "place": "postalveolar", "voiced": False, "AF": 65,
          "spec": {"A3": 56, "A4": 52, "A5": 46, "A6": 40}},
    "ʒ": {"type": "fric", "place": "postalveolar", "voiced": True, "AF": 54,
          "spec": {"A3": 52, "A4": 48, "A5": 42}},
    "ç": {"type": "fric", "place": "palatal", "voiced": False, "AF": 63, "spec": {"A4": 54, "A5": 50, "A3": 42}},
    "x": {"type": "fric", "place": "velar_back", "voiced": False, "AF": 63, "spec": {"A2": 54, "A3": 48}},
    "h": {"type": "aspirate", "place": "glottal", "voiced": False, "AH": 56},
    "ʔ": {"type": "glottal", "place": "glottal", "voiced": False},
    "m": {"type": "nasal", "place": "labial", "voiced": True, "FNZ": 750},
    "n": {"type": "nasal", "place": "dental", "voiced": True, "FNZ": 1450},
    "ŋ": {"type": "nasal", "place": "velar", "voiced": True, "FNZ": 2300},
    "l": {"type": "liquid", "place": "dental", "voiced": True, "F": (360, 1300, 2800)},
    "ʁ": {"type": "rhotic", "place": "uvular", "voiced": True, "F": (520, 1250, 2300), "AF": 38,
          "spec": {"A3": 40, "A2": 38}},
    "j": {"type": "glide", "place": "palatal", "voiced": True, "F": (260, 2100, 3000)},
}
AFFRICATES = {"ts": ("t", "s"), "pf": ("p", "f"), "tʃ": ("t", "ʃ"), "dʒ": ("d", "ʒ")}

#: имена параметров кадра
FIELDS = ("F1", "F2", "F3", "F4", "F5", "B1", "B2", "B3", "B4", "B5", "AV", "AH", "AF",
          "A2", "A3", "A4", "A5", "A6", "AB", "FNZ", "F0")


def _db(value: np.ndarray) -> np.ndarray:
    """дБ -> линейная амплитуда; 0 дБ и ниже — тишина."""
    return np.where(value > 1, 10 ** ((value - 60) / 20), 0.0)


class _Track:
    """Параметры по кадрам: цели фонем, потом сглаживание."""

    def __init__(self, frames: int) -> None:
        self.n = frames
        self.values = {name: np.full(frames, np.nan) for name in FIELDS}
        for name in ("AV", "AH", "AF", "A2", "A3", "A4", "A5", "A6", "AB"):
            self.values[name][:] = 0.0
        self.values["FNZ"][:] = 270.0

    def set(self, start: int, end: int, **params) -> None:
        end = max(start + 1, min(end, self.n))
        for name, value in params.items():
            if value is None:
                continue
            if isinstance(value, tuple):           # линейный ход внутри отрезка
                self.values[name][start:end] = np.linspace(value[0], value[1], end - start)
            else:
                self.values[name][start:end] = value


def _smooth(values: np.ndarray, width: int) -> np.ndarray:
    if width <= 1 or len(values) < 3:
        return values
    kernel = np.hanning(width + 2)[1:-1]
    kernel /= kernel.sum()
    padded = np.pad(values, (width // 2, width - 1 - width // 2), mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def _fill(values: np.ndarray, default: float) -> np.ndarray:
    """Пустые кадры (паузы, смычки) — интерполяцией от соседей: форманты не прыгают."""
    mask = np.isnan(values)
    if mask.all():
        return np.full_like(values, default)
    if mask.any():
        index = np.arange(len(values))
        values = values.copy()
        values[mask] = np.interp(index[mask], index[~mask], values[~mask])
    return values


def _next_vowel(phones, position: int) -> str | None:
    for phone in phones[position + 1:]:
        if phone.symbol in VOWELS:
            return phone.symbol
        if phone.symbol == "_" and phone.duration > 40:
            return None
    return None


def _vowel_formants(symbol: str, which: int = 0) -> tuple[int, int, int]:
    if symbol in DIPHTHONG_PARTS:
        symbol = DIPHTHONG_PARTS[symbol][which]
    return VOWEL_TARGETS.get(symbol, VOWEL_TARGETS["ə"])


def _locus(place: str, next_vowel: str | None) -> tuple[int, int, int]:
    if place == "velar":
        front = next_vowel is not None and _vowel_formants(next_vowel)[1] > 1600
        return LOCI["velar_front" if front else "velar_back"]
    return LOCI.get(place, LOCI["dental"])


def build_track(sc: Score, voice: FormantVoice) -> _Track:
    """Партитура -> параметры по кадрам."""
    frame_ms = FRAME_MS
    counts = [max(1, int(round(phone.duration / frame_ms))) for phone in sc.phones]
    total = sum(counts)
    track = _Track(total)
    f0 = np.full(total, np.nan)
    position = 0
    for index, (phone, n) in enumerate(zip(sc.phones, counts)):
        start, end = position, position + n
        symbol = phone.symbol
        nv = _next_vowel(sc.phones, index)
        stress_gain = 2.5 if phone.stress == 1 else 0 if phone.stress == 2 else -2.5
        if symbol in VOWELS:
            av = 60 + stress_gain - (3 if symbol in {"ə", "ɐ", "ɐ̯"} else 0)
            if symbol in DIPHTHONG_PARTS:
                a, b = _vowel_formants(symbol, 0), _vowel_formants(symbol, 1)
                hold = start + max(1, int(n * 0.35))
                track.set(start, hold, F1=a[0], F2=a[1], F3=a[2])
                track.set(hold, end, F1=(a[0], b[0]), F2=(a[1], b[1]), F3=(a[2], b[2]))
            else:
                f = _vowel_formants(symbol)
                track.set(start, end, F1=f[0], F2=f[1], F3=f[2])
            track.set(start, end, AV=av, B1=70 if symbol not in {"iː", "uː", "yː", "i", "u", "y"} else 55)
        elif symbol == "_":
            track.set(start, end, AV=0)
        elif symbol in AFFRICATES:
            first, second = AFFRICATES[symbol]
            cut = start + max(1, int(n * 0.4))
            _consonant(track, first, start, cut, nv, closure_only=True)
            _consonant(track, second, cut, end, nv)
        else:
            _consonant(track, symbol, start, end, nv)
        # мелодия
        if phone.f0:
            for k in range(start, end):
                t = (k - start + 0.5) / n
                multiplier = np.interp(t, [p[0] for p in phone.f0], [p[1] for p in phone.f0])
                f0[k] = voice.f0 * multiplier
        position = end

    values = track.values
    for name, default in (("F1", 500), ("F2", 1500), ("F3", 2500)):
        values[name] = _smooth(_fill(values[name], default), 7)
    values["F4"] = np.full(total, 3500.0)
    values["F5"] = np.full(total, 4300.0)
    values["B1"] = _smooth(_fill(values["B1"], 80), 3)
    values["B2"] = np.full(total, 100.0)
    values["B3"] = np.full(total, 150.0)
    values["B4"] = np.full(total, 250.0)
    values["B5"] = np.full(total, 300.0)
    for name in ("AV", "AH", "AF", "A2", "A3", "A4", "A5", "A6", "AB"):
        values[name] = _smooth(values[name], 3)
    values["FNZ"] = _smooth(values["FNZ"], 3)
    # тон: паузы заполняются соседями, кадры слегка дрожат — живой голос не бывает ровным
    rng = np.random.default_rng(len(sc.phones))
    tone = _smooth(_fill(f0, voice.f0), 9)
    tone *= 1 + 0.006 * _smooth(rng.standard_normal(total), 5)
    values["F0"] = tone
    # форманты — по размеру тракта голоса
    for name in ("F1", "F2", "F3", "F4", "F5"):
        values[name] = values[name] * voice.scale
    return track


def _consonant(track: _Track, symbol: str, start: int, end: int, next_vowel: str | None,
               closure_only: bool = False) -> None:
    spec = CONSONANTS.get(symbol)
    if spec is None:
        track.set(start, end, AV=0)
        return
    kind = spec["type"]
    place = spec.get("place", "dental")
    locus = spec.get("F") or _locus(place, next_vowel)
    n = end - start
    if kind == "stop":
        closure = start + max(1, int(n * (1.0 if closure_only else 0.55)))
        burst = min(end, closure + 2)
        track.set(start, closure, F1=locus[0], F2=locus[1], F3=locus[2],
                  AV=40 if spec["voiced"] else 0, AF=0, AH=0)
        if closure_only:
            return
        track.set(closure, burst, AF=60, AV=42 if spec["voiced"] else 0,
                  F1=locus[0], F2=locus[1], F3=locus[2], **spec["burst"])
        if not spec["voiced"] and burst < end and next_vowel is not None:
            # придыхание: шум идёт через форманты следующей гласной
            target = _vowel_formants(next_vowel)
            track.set(burst, end, AH=54, AV=0, F1=target[0], F2=target[1], F3=target[2])
        elif burst < end:
            track.set(burst, end, AV=48 if spec["voiced"] else 0)
    elif kind == "fric":
        track.set(start, end, AF=spec["AF"], AV=46 if spec["voiced"] else 0,
                  F1=locus[0] if locus[0] else None, F2=locus[1], F3=locus[2], **spec["spec"])
    elif kind == "aspirate":
        target = _vowel_formants(next_vowel) if next_vowel else (500, 1500, 2500)
        track.set(start, end, AH=spec["AH"], AV=0, F1=target[0], F2=target[1], F3=target[2])
    elif kind == "glottal":
        track.set(start, end, AV=0)
    elif kind == "nasal":
        track.set(start, end, AV=52, F1=270, F2=locus[1], F3=locus[2], FNZ=spec["FNZ"], B1=110)
    elif kind in {"liquid", "glide"}:
        track.set(start, end, AV=54 if kind == "liquid" else 55, F1=locus[0], F2=locus[1], F3=locus[2])
    elif kind == "rhotic":
        track.set(start, end, AV=50, AF=spec["AF"], F1=locus[0], F2=locus[1], F3=locus[2], **spec["spec"])


# --- звук -------------------------------------------------------------------------------------

def _coefficients(freq: np.ndarray, bandwidth: np.ndarray, rate: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Резонатор второго порядка Клатта: y = A x + B y[-1] + C y[-2]."""
    t = 1.0 / rate
    c = -np.exp(-2 * np.pi * bandwidth * t)
    b = 2 * np.exp(-np.pi * bandwidth * t) * np.cos(2 * np.pi * freq * t)
    a = 1 - b - c
    return a, b, c


def _glottal(f0_samples: np.ndarray, open_quotient: float) -> tuple[np.ndarray, np.ndarray]:
    """Производная импульса Розенберга (с излучением губ) и признак «щель открыта»."""
    phase = np.cumsum(f0_samples) / SAMPLE_RATE
    frac = phase - np.floor(phase)
    rise = open_quotient * 0.66
    flow = np.where(frac < rise, 0.5 * (1 - np.cos(np.pi * frac / rise)),
                    np.where(frac < open_quotient, np.cos(0.5 * np.pi * (frac - rise) / (open_quotient - rise)), 0.0))
    derivative = np.diff(flow, prepend=0.0)
    derivative /= np.max(np.abs(derivative)) + 1e-9
    return derivative, (frac < open_quotient).astype(float)


def render(track: _Track, voice: FormantVoice, seed: int = 1) -> np.ndarray:
    """Параметры по кадрам -> звук."""
    values = track.values
    frames = track.n
    samples = frames * HOP
    grid = (np.arange(samples) + 0.5) / HOP - 0.5
    frame_index = np.arange(frames)

    def per_sample(name: str) -> np.ndarray:
        return np.interp(grid, frame_index, values[name])

    f0 = per_sample("F0")
    source, open_phase = _glottal(f0, voice.open_quotient)
    rng = np.random.default_rng(seed)
    noise = rng.uniform(-1, 1, samples)
    av = _db(per_sample("AV"))
    ah = _db(per_sample("AH"))
    af = _db(per_sample("AF"))
    # голос: импульсы + немного придыхания в открытой фазе; затем лёгкий спад высоких
    voiced = source * av * 6.0 + noise * av * voice.breath * open_phase
    voiced = lfilter([1.0], [1.0, -0.35], voiced)
    cascade_in = voiced + noise * ah * ASPIRATION_GAIN
    # шум для параллельной ветви; у звонких щелевых он «пульсирует» с голосом
    fric_noise = noise * af * (1 - 0.5 * (av > 0.05) * (1 - open_phase))

    out_cascade = np.zeros(samples)
    out_parallel = np.zeros(samples)
    state = {name: np.zeros(2) for name in ("NP", "NZ", "R1", "R2", "R3", "R4", "R5")}
    pstate = {name: np.zeros(2) for name in ("P2", "P3", "P4", "P5", "P6")}

    F = {name: values[name] for name in ("F1", "F2", "F3", "F4", "F5")}
    B = {name: values[name] for name in ("B1", "B2", "B3", "B4", "B5")}
    coeff = {k: _coefficients(F["F" + k[1]], B["B" + k[1]], SAMPLE_RATE) for k in ("R1", "R2", "R3", "R4", "R5")}
    np_coeff = _coefficients(np.full(frames, 270.0), np.full(frames, 100.0), SAMPLE_RATE)
    nz_coeff = _coefficients(values["FNZ"], np.full(frames, 100.0), SAMPLE_RATE)
    # параллельные резонаторы шума: 2–5 — по формантам, 6 — около 6 кГц
    p_freq = {"P2": F["F2"], "P3": F["F3"], "P4": F["F4"], "P5": F["F5"], "P6": np.full(frames, 6000.0 * voice.scale ** 0.3)}
    p_band = {"P2": np.full(frames, 200.0), "P3": np.full(frames, 300.0), "P4": np.full(frames, 400.0),
              "P5": np.full(frames, 600.0), "P6": np.full(frames, 1200.0)}
    p_coeff = {k: _coefficients(p_freq[k], p_band[k], SAMPLE_RATE) for k in p_freq}
    p_gain = {k: _db(values["A" + k[1]]) for k in p_freq}
    bypass = _db(values["AB"])

    for frame in range(frames):
        lo, hi = frame * HOP, (frame + 1) * HOP
        x = cascade_in[lo:hi]
        # носовой нуль и полюс: у не-носовых они на одной частоте и гасят друг друга
        a, b, c = nz_coeff[0][frame], nz_coeff[1][frame], nz_coeff[2][frame]
        x, state["NZ"] = lfilter([1 / a, -b / a, -c / a], [1.0], x, zi=state["NZ"])
        a, b, c = np_coeff[0][frame], np_coeff[1][frame], np_coeff[2][frame]
        x, state["NP"] = lfilter([a], [1.0, -b, -c], x, zi=state["NP"])
        for name in ("R5", "R4", "R3", "R2", "R1"):
            a, b, c = coeff[name][0][frame], coeff[name][1][frame], coeff[name][2][frame]
            x, state[name] = lfilter([a], [1.0, -b, -c], x, zi=state[name])
        out_cascade[lo:hi] = x

        y = fric_noise[lo:hi]
        if y.any() or any(s.any() for s in pstate.values()):
            total = y * bypass[frame] * 0.5
            sign = 1.0
            for name in ("P2", "P3", "P4", "P5", "P6"):
                gain = p_gain[name][frame]
                a, b, c = p_coeff[name][0][frame], p_coeff[name][1][frame], p_coeff[name][2][frame]
                # усиление резонатора на его частоте — к единице: спектр задают только A2–A6
                w = 2 * np.pi * p_freq[name][frame] / SAMPLE_RATE
                peak = abs(a / (1 - b * np.exp(-1j * w) - c * np.exp(-2j * w)))
                filtered, pstate[name] = lfilter([a / peak], [1.0, -b, -c], y, zi=pstate[name])
                total = total + sign * gain * filtered
                sign = -sign
            out_parallel[lo:hi] = total

    signal = out_cascade + out_parallel * FRICATION_GAIN
    # срез постоянной составляющей и самых низких частот
    signal = lfilter([1, -1], [1, -0.995], signal)
    peak = np.max(np.abs(signal)) or 1.0
    return (signal / peak * 0.9).astype(np.float32)


def synthesize(text: str, voice_id: str = "karl", kind: str = "statement", rate: float = 1.0,
               pitch: float = 0.0, intonation: float = 1.0, seed: int = 0) -> tuple[np.ndarray, int]:
    """Произношение («Mä'schien 'Lörning …») -> звук и частота дискретизации.

    pitch — сдвиг тона в полутонах (форманты при этом не меняются: голос
    тот же, только выше или ниже).
    """
    voice = VOICES.get(voice_id, VOICES["karl"])
    sc = score(text, kind, rate * voice.rate, intonation, seed)
    shifted = FormantVoice(voice.id, voice.title, voice.gender, voice.f0 * 2 ** (pitch / 12), voice.scale,
                           voice.open_quotient, voice.rate, voice.breath)
    track = build_track(sc, shifted)
    return render(track, shifted, seed + 1), SAMPLE_RATE


def describe(text: str, rate: float = 1.0) -> list[dict]:
    """Партитура для страницы «Транскрипция»: звук, длительность, тон."""
    sc = score(text, rate=rate)
    return [{"symbol": p.symbol, "ms": round(p.duration), "stress": p.stress,
             "f0": [round(v, 3) for _, v in p.f0]} for p in sc.phones]

