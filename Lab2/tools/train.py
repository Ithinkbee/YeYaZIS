"""Построение профилей языков по обучающему корпусу.

    python tools/train.py            — построить и сохранить профили
    python tools/train.py --check    — только проверить объём корпуса
    python tools/train.py --quiet    — без подробностей

Профили сохраняются в каталог `models` и при запуске системы читаются оттуда,
поэтому обучение выполняется один раз после каждого изменения корпуса.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tolmach import config, console, corpus  # noqa: E402
from tolmach.methods import METHOD_REGISTRY  # noqa: E402
from tolmach.recognizer import Recognizer  # noqa: E402

console.setup()


def check_corpus(quiet: bool = False) -> bool:
    """Печатает объём корпуса и сообщает, укладывается ли он в требования."""
    stats = corpus.corpus_stats()
    ok = True
    if not quiet:
        print("Обучающий корпус:")
        print(f"  {'язык':12}{'файлов':>8}{'объём':>10}{'букв':>9}{'слов':>8}  состояние")
    for code, item in stats.items():
        if not quiet:
            print(
                f"  {config.language_name(code):12}{item.files:>8}"
                f"{item.kilobytes:>9.1f}К{item.letters:>9}{item.words:>8}  {item.verdict}"
            )
        ok = ok and item.within_limits

    if not quiet:
        letters = [item.letters for item in stats.values()]
        if letters and min(letters):
            ratio = max(letters) / min(letters)
            print(f"\n  перекос между языками по числу букв: {ratio:.2f}×")
            if ratio > 1.5:
                print("  ВНИМАНИЕ: корпуса заметно разного объёма — "
                      "профили языков окажутся неравноточными")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="только проверить корпус")
    parser.add_argument("--quiet", action="store_true", help="меньше подробностей")
    arguments = parser.parse_args()

    config.ensure_dirs()
    within_limits = check_corpus(arguments.quiet)

    if arguments.check:
        return 0 if within_limits else 1

    if not within_limits:
        print("\nВНИМАНИЕ: объём корпуса вне требуемых границ "
              f"({config.TRAIN_MIN_BYTES // 1024}–{config.TRAIN_MAX_BYTES // 1024} Кб), "
              "профили всё равно будут построены.")

    print("\nПостроение профилей…")
    recognizer = Recognizer()
    started = time.perf_counter()
    try:
        timings = recognizer.fit()
    except (FileNotFoundError, ValueError) as problem:
        print(f"ОШИБКА: {problem}")
        return 1
    total = (time.perf_counter() - started) * 1000.0

    for code, value in timings.items():
        title = METHOD_REGISTRY[code].title
        print(f"  {title:24}{value:9.1f} мс")
    print(f"  {'всего':24}{total:9.1f} мс")

    neural = recognizer.methods.get("neural")
    if neural is not None and not arguments.quiet:
        info = neural.info
        print(
            f"\n  сеть: {info.get('features')} признаков, "
            f"{info.get('hidden')} нейронов скрытого слоя, "
            f"{info.get('train_fragments')} обучающих фрагментов "
            f"и {info.get('valid_fragments')} контрольных"
        )
        print(
            f"        точность на обучении {info.get('train_accuracy')}, "
            f"на контроле {info.get('valid_accuracy')} "
            f"(лучшая эпоха {info.get('best_epoch')} из {info.get('epochs')})"
        )

    paths = recognizer.save()
    print("\nСохранено:")
    for path in paths:
        print(f"  {path}  ({path.stat().st_size / 1024:.0f} Кб)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
