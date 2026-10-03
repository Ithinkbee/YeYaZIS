"""Запуск системы автоматического реферирования «Изборник».

    python run.py                 — запустить систему и открыть браузер
    python run.py --no-browser    — только сервер
    python run.py --port 8080     — другой порт
    python run.py --offline       — без OSTIS, только локальный расчёт
"""

from __future__ import annotations

import argparse
import os
import threading
import webbrowser

from izbornik import APP_NAME, VARIANT, config, console

console.setup()


def describe() -> None:
    from izbornik.collection import Collection

    collection = Collection()
    print(f"Система «{APP_NAME}» — автоматическое реферирование документов, вариант {VARIANT}")
    print(f"  языки:      {', '.join(config.language_name(c) for c in config.LANGUAGE_CODES)}")
    print(f"  области:    {'; '.join(config.domain_name(c) for c in config.DOMAIN_CODES)}")
    print(f"  метод:      sentence extraction + OSTIS, реферат из {config.SUMMARY_SENTENCES} предложений")
    if not len(collection):
        print("  коллекция:  не найдена — соберите её: python tools/build_collection.py --offline")
        return
    sizes = [e.chars for e in collection]
    print(f"  коллекция:  {len(collection)} документов, {min(sizes)}–{max(sizes)} знаков")
    mode = {"off": "выключен", "on": "только OSTIS", "auto": "OSTIS, если доступна"}.get(config.OSTIS_MODE,
                                                                                          config.OSTIS_MODE)
    print(f"  OSTIS:      {mode}; sc-сервер {config.OSTIS_URL}, агент: {config.AGENT_MODE}")


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Система «{APP_NAME}», вариант {VARIANT}")
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер")
    parser.add_argument("--offline", action="store_true", help="не подключаться к OSTIS")
    parser.add_argument("--reload", action="store_true", help="режим разработки")
    arguments = parser.parse_args()

    if arguments.offline:
        os.environ["IZBORNIK_OSTIS"] = "off"
        config.OSTIS_MODE = "off"

    config.ensure_dirs()
    describe()

    url = f"http://{arguments.host}:{arguments.port}/"
    print(f"\n  интерфейс:  {url}\n")
    if not arguments.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    import uvicorn

    uvicorn.run(
        "izbornik.web.app:app",
        host=arguments.host,
        port=arguments.port,
        reload=arguments.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
