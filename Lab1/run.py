"""Запуск информационно-поисковой системы «Арахна».

    python run.py                — запустить систему и открыть браузер
    python run.py --no-browser   — только сервер
    python run.py --port 8080    — другой порт
"""

from __future__ import annotations

import argparse
import threading
import webbrowser

from arachne import APP_NAME, config, db
from arachne.ai import llm


def prepare() -> None:
    """Создаёт каталоги и схему базы данных до старта сервера."""
    config.ensure_dirs()
    conn = db.connect()
    try:
        db.init_db(conn)
        statistics = db.stats(conn)
    finally:
        conn.close()

    print(f"ИПС «{APP_NAME}»")
    print(f"  база данных: {config.DB_PATH}")
    print(f"  документов:  {statistics['documents']} (проиндексировано {statistics['indexed']})")
    print(f"  терминов:    {statistics['terms']}")
    status = llm.status()
    print(
        "  помощник:    "
        + (
            f"{status['provider']}, модель {status['model']}"
            if status["enabled"]
            else status["reason"]
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=f"ИПС «{APP_NAME}»")
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер")
    parser.add_argument("--reload", action="store_true", help="режим разработки")
    arguments = parser.parse_args()

    prepare()
    url = f"http://{arguments.host}:{arguments.port}/"
    print(f"\n  интерфейс:   {url}\n")

    if not arguments.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    import uvicorn

    uvicorn.run(
        "arachne.web.app:app",
        host=arguments.host,
        port=arguments.port,
        reload=arguments.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
