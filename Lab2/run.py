"""Запуск системы распознавания языка текста «Толмач».

    python run.py                — запустить систему и открыть браузер
    python run.py --no-browser   — только сервер
    python run.py --port 8080    — другой порт
    python run.py --retrain      — построить профили заново перед запуском
"""

from __future__ import annotations

import argparse
import threading
import webbrowser

from tolmach import APP_NAME, VARIANT, config, console, corpus
from tolmach.methods import METHOD_REGISTRY
from tolmach.recognizer import Recognizer

console.setup()


def prepare(retrain: bool) -> None:
    """Готовит каталоги и профили языков до старта сервера."""
    config.ensure_dirs()

    print(f"Система «{APP_NAME}» — распознавание языка текста, вариант {VARIANT}")
    print(f"  языки:    {', '.join(config.language_name(code) for code in config.LANGUAGE_CODES)}")
    print(f"  методы:   {', '.join(cls.title for cls in METHOD_REGISTRY.values())}")

    try:
        stats = corpus.corpus_stats()
    except OSError as problem:
        print(f"  корпус:   не прочитан ({problem})")
        return

    print("  корпус:")
    for code, item in stats.items():
        print(
            f"    {config.language_name(code):10} {item.files:3} файлов, "
            f"{item.kilobytes:6.1f} Кб, {item.letters:6} букв — {item.verdict}"
        )

    recognizer = Recognizer()
    try:
        if retrain:
            timings = recognizer.fit()
            recognizer.save()
            source = "построены заново"
        else:
            from_disk = recognizer.load_or_fit()
            timings = recognizer.training.get("fit_ms", {}) if not from_disk else {}
            source = "прочитаны с диска" if from_disk else "построены заново"
    except (FileNotFoundError, ValueError) as problem:
        print(f"\n  ВНИМАНИЕ: профили не построены — {problem}")
        return

    print(f"  профили:  {source} ({config.MODELS_DIR})")
    if timings:
        for code, value in timings.items():
            print(f"    {METHOD_REGISTRY[code].title:24} {value:8.1f} мс")

    documents = corpus.collection_files()
    labelled = len(corpus.load_labels())
    print(f"  коллекция: {len(documents)} документов, размечено {labelled}")


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Система «{APP_NAME}», вариант {VARIANT}")
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер")
    parser.add_argument("--retrain", action="store_true", help="построить профили заново")
    parser.add_argument("--reload", action="store_true", help="режим разработки")
    arguments = parser.parse_args()

    prepare(arguments.retrain)

    url = f"http://{arguments.host}:{arguments.port}/"
    print(f"\n  интерфейс: {url}\n")

    if not arguments.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    import uvicorn

    uvicorn.run(
        "tolmach.web.app:app",
        host=arguments.host,
        port=arguments.port,
        reload=arguments.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
