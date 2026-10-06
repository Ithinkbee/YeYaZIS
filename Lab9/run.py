"""Запуск системы распознавания речи «Слухач».

    python run.py                 — запустить систему и открыть браузер
    python run.py --no-browser    — только сервер
    python run.py --port 8080     — другой порт
    python run.py --language ru   — язык речи при запуске (по умолчанию немецкий)
    python run.py --admin-password секрет   — свой пароль администратора
"""

from __future__ import annotations

import argparse
import os
import threading
import webbrowser

from sluhach import APP_NAME, VARIANT, config, console

console.setup()


def describe() -> None:
    from sluhach.essays import Collection
    from sluhach.operations import DEFAULTS
    from sluhach.recognizer import STATES, VoskEngine

    collection = Collection()
    engine = VoskEngine()
    print(f"Система «{APP_NAME}» — распознавание речи и голосовое управление, вариант {VARIANT}")
    print(f"  языки:        {', '.join(config.language_name(c) for c in config.LANGUAGE_CODES)}; "
          f"при запуске — {config.language_name(config.DEFAULT_LANGUAGE)}")
    print(f"  область:      сочинения по литературе — {len(collection)} текстов")
    print(f"  операций:     {len(DEFAULTS)}; список задаётся на странице «Операции»")
    for language in config.LANGUAGE_CODES:
        state = engine.state(language)
        note = "" if engine.available(language) else " — скачайте: python tools/get_models.py"
        if state == "idle":
            state_text = "на месте"
        else:
            state_text = STATES[state]
        print(f"  Vosk, {config.language_name(language) + ':':10} {config.VOSK_MODELS[language]} — {state_text}{note}")
    if not all(engine.available(language) for language in config.LANGUAGE_CODES):
        print("                без модели Vosk язык распознаётся только браузером (Chrome, Edge; нужен интернет)")
    # имя и пароль администратора видит только тот, кто запустил систему, — в этой консоли
    if config.ADMIN_PASSWORD == config.DEFAULT_ADMIN_PASSWORD:
        print(f"  администратор: имя {config.ADMIN_LOGIN}, пароль {config.ADMIN_PASSWORD} — пароль по умолчанию; "
              "свой задаётся ключом --admin-password")
    else:
        print(f"  администратор: имя {config.ADMIN_LOGIN}, пароль задан при запуске")
    print("                вход — ссылка «Вход администратора» внизу страницы или адрес /admin")


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Система «{APP_NAME}», вариант {VARIANT}")
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--language", choices=config.LANGUAGE_CODES, help="язык речи при запуске")
    parser.add_argument("--admin-password", metavar="ПАРОЛЬ",
                        help="пароль администратора (иначе — из SLUHACH_ADMIN_PASSWORD или пароль по умолчанию)")
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер")
    parser.add_argument("--reload", action="store_true", help="режим разработки")
    arguments = parser.parse_args()

    if arguments.language:
        os.environ["SLUHACH_LANGUAGE"] = arguments.language
        config.DEFAULT_LANGUAGE = arguments.language
    if arguments.admin_password:
        # переменная окружения — для дочернего процесса в режиме --reload
        os.environ["SLUHACH_ADMIN_PASSWORD"] = arguments.admin_password
        config.ADMIN_PASSWORD = arguments.admin_password

    config.ensure_dirs()
    describe()

    url = f"http://{arguments.host}:{arguments.port}/"
    print(f"\n  интерфейс:    {url}")
    if arguments.host not in {"127.0.0.1", "localhost"}:
        print("                микрофон браузер даёт только адресам 127.0.0.1 и localhost (или по HTTPS)")
    print()
    if not arguments.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    import uvicorn

    uvicorn.run(
        "sluhach.web.app:app",
        host=arguments.host,
        port=arguments.port,
        reload=arguments.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
