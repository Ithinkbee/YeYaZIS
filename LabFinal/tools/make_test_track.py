"""Проверочная дорожка: не музыка, а размеченный звук для репетиции без записи.

    python tools/make_test_track.py                     data/test_track.wav, 100 секунд
    python tools/make_test_track.py --out путь.wav --choir 35 --leave 70 --length 95

Настоящую запись этот файл не заменяет: в нём случайные ноты. Зато устроен он
так же, как ожидает ролик: сначала тихий одинокий высокий голос, потом громкая
часть — аккорды в середине и бас, — потом снова тихо. По такой дорожке
проверяется, что страница находит большой хор, что паучата поют на верхах, а
Большой паук — на басах.

    python run.py --music data/test_track.wav
"""

from __future__ import annotations

import argparse
import math
import random
import struct
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from poklon import console  # noqa: E402

RATE = 22050
SCALE = [0, 2, 4, 7, 9, 12, 14, 16]     # пентатоника, в полутонах от основного тона


def tone(samples: list[float], start: float, length: float, frequency: float, volume: float,
         vibrato: float = 0.0) -> None:
    """Добавляет ноту: синус с парой обертонов, плавные начало и конец."""
    first = int(start * RATE)
    count = int(length * RATE)
    attack = max(1, int(0.04 * RATE))
    release = max(1, int(0.16 * RATE))
    phase = 0.0
    for i in range(count):
        at = first + i
        if at >= len(samples):
            break
        shape = min(1.0, i / attack, (count - i) / release)
        wobble = 1 + vibrato * math.sin(2 * math.pi * 5.5 * i / RATE)
        phase += 2 * math.pi * frequency * wobble / RATE
        samples[at] += volume * shape * (math.sin(phase) + 0.3 * math.sin(2 * phase) + 0.12 * math.sin(3 * phase))


def build(length: float, choir: float, leave: float, seed: int = 7) -> list[float]:
    rng = random.Random(seed)
    samples = [0.0] * int(length * RATE)

    # одинокий высокий голос: фразы по несколько нот, между фразами вдох
    t = 0.3
    while t < length - 1.5:
        inside = choir <= t < leave
        for _ in range(rng.randint(3, 6)):
            note = 0.35 + rng.random() * 0.55
            step = rng.choice(SCALE)
            fade = min(1.0, (length - t) / 8)
            tone(samples, t, note, 880 * 2 ** (step / 12), (0.11 if inside else 0.16) * fade, vibrato=0.012)
            t += note
        t += 0.5 + rng.random() * 0.6

    # большой хор: аккорды в середине и бас
    t = choir
    while t < leave - 0.5:
        note = min(1.6 + rng.random() * 1.2, leave - t)
        root = rng.choice([0, 5, 7, 3])
        for step in (0, 4, 7):
            tone(samples, t, note, 261.6 * 2 ** ((root + step) / 12), 0.2, vibrato=0.006)
        tone(samples, t, note * 0.92, 65.4 * 2 ** (root / 12), 0.42)
        t += note

    peak = max(1e-9, max(abs(value) for value in samples))
    return [value / peak * 0.89 for value in samples]


def main() -> None:
    console.setup()
    parser = argparse.ArgumentParser(description="Проверочная дорожка для репетиции без записи")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "test_track.wav")
    parser.add_argument("--length", type=float, default=100, help="длина, секунды")
    parser.add_argument("--choir", type=float, default=42, help="с какой секунды громкая часть")
    parser.add_argument("--leave", type=float, default=78, help="на какой секунде она кончается")
    arguments = parser.parse_args()
    if not 5 < arguments.choir < arguments.leave < arguments.length:
        parser.error("нужно 5 < choir < leave < length")

    samples = build(arguments.length, arguments.choir, arguments.leave)
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(arguments.out), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(RATE)
        output.writeframes(struct.pack(f"<{len(samples)}h", *(int(value * 32767) for value in samples)))
    print(f"{arguments.out} — {arguments.length:.0f} с, громкая часть {arguments.choir:.0f}–{arguments.leave:.0f} с")
    print(f"запуск: python run.py --music {arguments.out}")


if __name__ == "__main__":
    main()
