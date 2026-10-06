"""Запуск системы машинного перевода «Драгоман».

    python run.py                 — запустить систему и открыть браузер
    python run.py --no-browser    — только сервер
    python run.py --port 8080     — другой порт
"""

from __future__ import annotations

import argparse
import threading
import webbrowser

from dragoman import APP_NAME, VARIANT, config, console

console.setup()


def describe() -> None:
    from dragoman.collection import Collection
    from dragoman.lexicon import db

    print(f"Система «{APP_NAME}» — автоматический машинный перевод, вариант {VARIANT}")
    print("  направление: английский → немецкий")
    print(f"  области:     {'; '.join(config.domain_name(c) for c in config.DOMAIN_CODES)}")
    missing = [name for name in ("tagger.json.gz", "parser.json.gz", "lemmatizer.json")
               if not (config.MODELS_DIR / name).exists()]
    if missing:
        print(f"  модели:      нет {', '.join(missing)} — обучите их: python tools/train.py")
    else:
        size = sum((config.MODELS_DIR / n).stat().st_size for n in ("tagger.json.gz", "parser.json.gz",
                                                                    "lemmatizer.json"))
        print(f"  модели:      теггер, лемматизатор, анализатор зависимостей ({size / 1e6:.1f} МБ)")
    lexicon = db.get()
    stats = lexicon.stats()
    print(f"  словарь:     {stats['total']} записей ({stats['phrases']} оборотов) в {config.DICTIONARY_DB.name}")
    collection = Collection()
    print(f"  коллекция:   {len(collection)} текстов")
    print(f"  Пафнутий:    {'в углу страницы, тир открыт' if config.COMPANION_ENABLED else 'выключен'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Система «{APP_NAME}», вариант {VARIANT}")
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер")
    parser.add_argument("--reload", action="store_true", help="режим разработки")
    arguments = parser.parse_args()

    config.ensure_dirs()
    describe()
    url = f"http://{arguments.host}:{arguments.port}/"
    print(f"\n  интерфейс:   {url}\n")
    if not arguments.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    import uvicorn

    uvicorn.run("dragoman.web.app:app", host=arguments.host, port=arguments.port, reload=arguments.reload,
                log_level="info")


if __name__ == "__main__":
    main()
