"""Загрузка моделей распознавания Vosk.

    python tools/get_models.py            скачать модели обоих языков, если их ещё нет
    python tools/get_models.py de         только немецкую
    python tools/get_models.py --check    ничего не скачивать, показать, что есть

Малые модели — около 45 МБ на язык в архиве, 90 МБ на диске. Они лежат в
models/ и в репозиторий не входят: их нужно скачать один раз на каждом
компьютере. Источник — https://alphacephei.com/vosk/models (лицензия Apache 2.0).
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sluhach import config, console  # noqa: E402
from sluhach.recognizer import VoskEngine  # noqa: E402

console.setup()


def download(url: str, target: Path) -> None:
    """Скачивает файл, показывая ход загрузки."""
    with urllib.request.urlopen(url, timeout=60) as response, target.open("wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done, shown = 0, -10
        while True:
            block = response.read(1 << 16)
            if not block:
                break
            out.write(block)
            done += len(block)
            percent = 100 * done // total if total else 0
            if percent >= shown + 10:
                shown = percent - percent % 10
                print(f"    {done / 1048576:5.1f} МБ" + (f" из {total / 1048576:.1f} ({shown} %)" if total else ""),
                      flush=True)


def install(language: str, engine: VoskEngine) -> bool:
    name = config.VOSK_MODELS[language]
    if engine.installed(language):
        print(f"  {config.language_name(language):9} {name} — уже на месте")
        return True
    url = config.VOSK_MODEL_URL.format(name=name)
    print(f"  {config.language_name(language):9} {name} — скачиваю {url}")
    engine.models_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sluhach-model-") as folder:
        archive = Path(folder) / f"{name}.zip"
        try:
            download(url, archive)
            with zipfile.ZipFile(archive) as packed:
                packed.extractall(folder)
        except (OSError, zipfile.BadZipFile) as problem:
            print(f"    не получилось: {problem}")
            return False
        unpacked = Path(folder) / name
        if not (unpacked / "am" / "final.mdl").exists():
            print("    в архиве нет модели — возможно, изменился её адрес")
            return False
        target = engine.model_path(language)
        if target.exists():
            shutil.rmtree(target)                  # недокачанный остаток прошлой попытки
        shutil.move(str(unpacked), str(target))
    print(f"    готово: {engine.model_path(language)}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Загрузка моделей Vosk")
    parser.add_argument("languages", nargs="*", metavar="язык",
                        help="языки: " + ", ".join(config.LANGUAGE_CODES) + " (по умолчанию все)")
    parser.add_argument("--check", action="store_true", help="только показать, какие модели есть")
    parser.add_argument("--dir", help="каталог моделей (по умолчанию models/)")
    arguments = parser.parse_args()
    unknown = [code for code in arguments.languages if code not in config.LANGUAGE_CODES]
    if unknown:
        parser.error("нет такого языка: " + ", ".join(unknown))

    engine = VoskEngine(models_dir=Path(arguments.dir) if arguments.dir else None)
    languages = arguments.languages or list(config.LANGUAGE_CODES)
    print(f"Модели Vosk в {engine.models_dir}:")
    if arguments.check:
        for language in languages:
            state = "на месте" if engine.installed(language) else "нет"
            print(f"  {config.language_name(language):9} {config.VOSK_MODELS[language]} — {state}")
        if not engine.package():
            print("  пакет vosk не установлен: pip install -r requirements.txt")
        return 0 if all(engine.installed(language) for language in languages) else 1

    ok = all([install(language, engine) for language in languages])
    if not engine.package():
        print("Пакет vosk не установлен: pip install -r requirements.txt")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
