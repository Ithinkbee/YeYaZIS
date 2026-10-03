"""Сборка русской части обучающего корпуса из текстов лабораторной работы №1.

Тексты первой работы разрешено использовать повторно, поэтому русский корпус
собирается из её коллекции документов. Каталог Lab1 открывается только на
чтение: сценарий ничего в нём не создаёт, не меняет и не удаляет.

    python tools/build_corpus.py              — собрать корпус
    python tools/build_corpus.py --dry-run    — только показать, что будет взято
    python tools/build_corpus.py --clean      — сначала убрать прежний импорт

Немецкая часть корпуса набрана отдельно и этим сценарием не затрагивается:
удаляются только файлы с префиксом `lab1-`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tolmach import config, console, preprocess  # noqa: E402

console.setup()

#: каталог первой лабораторной работы относительно корня проекта
LAB1_DIR = config.BASE_DIR.parent / "Lab1"

#: откуда берутся тексты
LAB1_COLLECTION = LAB1_DIR / "data" / "collection"

#: расширения, которые забираем: только обычный текст, без разметки
SOURCE_EXTENSIONS = {".txt", ".md"}

#: префикс импортированных файлов — по нему же работает --clean
IMPORT_PREFIX = "lab1-"

#: файл короче этого числа символов статистику не улучшает
MIN_LETTERS = 300


def find_sources() -> list[Path]:
    """Находит русские тексты первой работы в устойчивом порядке."""
    if not LAB1_COLLECTION.exists():
        raise FileNotFoundError(
            f"коллекция первой работы не найдена: {LAB1_COLLECTION}\n"
            f"Укажите верный путь в tools/build_corpus.py или наполните "
            f"{config.TRAIN_DIR / 'ru'} вручную."
        )
    return sorted(
        path
        for path in LAB1_COLLECTION.rglob("*")
        if path.is_file() and path.suffix.lower() in SOURCE_EXTENSIONS
    )


def target_name(path: Path) -> str:
    """Имя файла в корпусе: префикс, узел коллекции, рубрика и имя документа.

    Такое имя позволяет проследить происхождение каждого куска корпуса, что
    требуется в отчёте при описании тестовой коллекции.
    """
    parts = path.relative_to(LAB1_COLLECTION).parts
    stem = "-".join(parts[:-1] + (path.stem,))
    return f"{IMPORT_PREFIX}{stem.lower()}.txt"


def cyrillic_share(text: str) -> float:
    """Доля кириллицы среди букв — отсев файлов не на русском языке."""
    letters = [char for char in text if char != " "]
    if not letters:
        return 0.0
    cyrillic = sum(1 for char in letters if "Ѐ" <= char <= "ӿ")
    return cyrillic / len(letters)


def clean_previous() -> int:
    """Удаляет прежде импортированные файлы (только в каталоге Lab2)."""
    directory = config.TRAIN_DIR / "ru"
    removed = 0
    for path in directory.glob(f"{IMPORT_PREFIX}*.txt"):
        path.unlink()
        removed += 1
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="ничего не записывать")
    parser.add_argument("--clean", action="store_true", help="убрать прежний импорт")
    arguments = parser.parse_args()

    config.ensure_dirs()
    destination = config.TRAIN_DIR / "ru"

    if arguments.clean and not arguments.dry_run:
        print(f"убрано прежних файлов: {clean_previous()}")

    sources = find_sources()
    print(f"источник: {LAB1_COLLECTION}")
    print(f"найдено файлов: {len(sources)}\n")

    taken = skipped = 0
    total_bytes = total_letters = 0

    for path in sources:
        raw = path.read_text(encoding="utf-8", errors="replace")
        normalized = preprocess.normalize(raw)
        letters = preprocess.count_letters(normalized)
        share = cyrillic_share(normalized)

        if letters < MIN_LETTERS:
            skipped += 1
            print(f"  пропуск {path.name}: всего {letters} букв")
            continue
        if share < 0.5:
            skipped += 1
            print(f"  пропуск {path.name}: кириллицы {share:.0%}")
            continue

        target = destination / target_name(path)
        if not arguments.dry_run:
            target.write_text(raw, encoding="utf-8")
        taken += 1
        total_bytes += len(raw.encode("utf-8"))
        total_letters += letters

    print(f"\nвзято файлов:  {taken}")
    print(f"пропущено:     {skipped}")
    print(f"объём:         {total_bytes} байт ({total_bytes / 1024:.1f} Кб)")
    print(f"букв:          {total_letters}")

    if arguments.dry_run:
        print("\n(пробный запуск: ничего не записано)")
        return 0

    limit_low = config.TRAIN_MIN_BYTES
    limit_high = config.TRAIN_MAX_BYTES
    own = sum(
        path.stat().st_size
        for path in destination.glob("*.txt")
        if not path.name.startswith(IMPORT_PREFIX)
    )
    corpus_bytes = total_bytes + own
    print(f"\nвсего в русском корпусе: {corpus_bytes / 1024:.1f} Кб "
          f"(требование методички — от {limit_low / 1024:.0f} до {limit_high / 1024:.0f} Кб)")
    if not limit_low <= corpus_bytes <= limit_high:
        print("ВНИМАНИЕ: объём корпуса вне требуемых границ")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
