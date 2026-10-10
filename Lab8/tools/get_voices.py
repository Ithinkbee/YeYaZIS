"""Загрузка нейросетевых голосов Piper и модели распознавания для проверки.

    python tools/get_voices.py                 скачать четыре немецких голоса Piper (≈ 225 МБ)
    python tools/get_voices.py thorsten        только голоса, в имени которых есть «thorsten»
    python tools/get_voices.py --vosk          ещё и модель Vosk (45 МБ) — она нужна только tools/evaluate.py
    python tools/get_voices.py --check         ничего не скачивать, показать, что есть

Голоса лежат в voices/ (модель .onnx и её описание .onnx.json) и в
репозиторий не входят. Источник — https://huggingface.co/rhasspy/piper-voices
(лицензии моделей указаны в их карточках). Без голосов система работает на
собственном синтезаторе.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from glashatai import config, console  # noqa: E402

console.setup()


def download(url: str, target: Path) -> None:
    """Скачивает файл во временный и переименовывает: оборванная загрузка не оставит половину модели."""
    partial = target.with_suffix(target.suffix + ".part")
    with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done, shown = 0, -25
        while True:
            block = response.read(1 << 16)
            if not block:
                break
            out.write(block)
            done += len(block)
            percent = 100 * done // total if total else 0
            if percent >= shown + 25:
                shown = percent - percent % 25
                print(f"    {done / 1048576:5.1f} МБ" + (f" из {total / 1048576:.1f} ({shown} %)" if total else ""),
                      flush=True)
    partial.replace(target)


def voice(name: str, info: dict, check: bool) -> bool:
    model = config.VOICES_DIR / f"{name}.onnx"
    described = config.VOICES_DIR / f"{name}.onnx.json"
    if model.exists() and described.exists():
        print(f"  {info['title']:20} {name} — уже на месте")
        return True
    if check:
        print(f"  {info['title']:20} {name} — нет")
        return False
    config.VOICES_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  {info['title']:20} {name} — скачиваю")
    for extension, target in ((".onnx.json", described), (".onnx", model)):
        url = config.PIPER_URL.format(path=info["path"], name=name, extension=extension)
        try:
            download(url, target)
        except OSError as problem:
            print(f"    не скачано: {problem}")
            return False
    return True


def vosk(check: bool) -> bool:
    target = config.MODELS_DIR / config.VOSK_MODEL
    if (target / "am").exists() or (target / "conf").exists():
        print(f"  Vosk                 {config.VOSK_MODEL} — уже на месте")
        return True
    if check:
        print(f"  Vosk                 {config.VOSK_MODEL} — нет")
        return False
    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    url = config.VOSK_MODEL_URL.format(name=config.VOSK_MODEL)
    print(f"  Vosk                 {config.VOSK_MODEL} — скачиваю {url}")
    with tempfile.TemporaryDirectory(prefix="glashatai-vosk-") as folder:
        archive = Path(folder) / "model.zip"
        try:
            download(url, archive)
            with zipfile.ZipFile(archive) as packed:
                packed.extractall(config.MODELS_DIR)
        except (OSError, zipfile.BadZipFile) as problem:
            print(f"    не скачано: {problem}")
            return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Голоса Piper и модель Vosk для «Глашатая»")
    parser.add_argument("names", nargs="*", help="часть имени голоса: thorsten, kerstin, eva")
    parser.add_argument("--vosk", action="store_true", help="скачать и модель распознавания для проверки")
    parser.add_argument("--check", action="store_true", help="только показать, что скачано")
    arguments = parser.parse_args()

    try:
        import piper  # noqa: F401
    except ImportError:
        print("Пакет piper-tts не установлен: pip install piper-tts — без него голоса скачать можно, но не услышать.")
    print(f"Каталог голосов: {config.VOICES_DIR}")
    ok = True
    for name, info in config.PIPER_VOICES.items():
        if arguments.names and not any(part.lower() in name.lower() for part in arguments.names):
            continue
        ok = voice(name, info, arguments.check) and ok
    if arguments.vosk:
        ok = vosk(arguments.check) and ok
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
