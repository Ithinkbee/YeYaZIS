"""Запуск системы синтеза речи «Глашатай».

    python run.py                  — запустить систему и открыть браузер
    python run.py --no-browser     — только сервер
    python run.py --port 8080      — другой порт
    python run.py --voice formant:karl   — голос по умолчанию
    python run.py --no-desktop     — без буфера обмена и горячих клавиш
"""

from __future__ import annotations

import argparse
import os
import threading
import webbrowser

from glashatai import APP_NAME, VARIANT, config, console

console.setup()


def describe() -> None:
    from glashatai.articles import Collection
    from glashatai.speaker import Speaker

    speaker = Speaker()
    voices = speaker.voices()
    neural = [v for v in voices if v.engine == "piper"]
    ready = [v for v in neural if v.available]
    print(f"Система «{APP_NAME}» — синтез немецкой речи, вариант {VARIANT}")
    print(f"  язык:         {config.LANGUAGE_NAME}; область — научные статьи по computer science "
          f"({len(Collection())} статей)")
    if ready:
        models = sorted({v.id.split(':', 1)[1].split('#')[0] for v in ready})
        print(f"  Piper:        {len(models)} голос(а) — {', '.join(models)}")
    elif neural:
        print(f"  Piper:        {neural[0].note}")
    print("  собственный:  формантный синтезатор — Карл, Клара, Пафнутий")
    sapi = [v for v in voices if v.engine == "sapi"]
    if sapi and sapi[0].available:
        print(f"  Windows:      {', '.join(v.title for v in sapi)}")
    elif sapi:
        print(f"  Windows:      {sapi[0].note}")
    print(f"  по умолчанию: {speaker.default_voice()}")
    if config.DESKTOP_ENABLED:
        print(f"  другие программы: буфер обмена и {config.HOTKEY_READ} — включаются на странице «Из других программ»")
    else:
        print("  другие программы: выключено ключом --no-desktop")


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Система «{APP_NAME}», вариант {VARIANT}")
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--voice", help="голос по умолчанию, например piper:de_DE-thorsten-medium или formant:karl")
    parser.add_argument("--no-desktop", action="store_true", help="без буфера обмена и горячих клавиш")
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер")
    parser.add_argument("--reload", action="store_true", help="режим разработки")
    arguments = parser.parse_args()

    if arguments.voice:
        os.environ["GLASHATAI_VOICE"] = arguments.voice
        config.DEFAULT_VOICE = arguments.voice
    if arguments.no_desktop:
        os.environ["GLASHATAI_DESKTOP"] = "0"
        config.DESKTOP_ENABLED = False
    os.environ["GLASHATAI_PORT"] = str(arguments.port)
    config.PORT = arguments.port

    config.ensure_dirs()
    describe()

    url = f"http://{arguments.host}:{arguments.port}/"
    print(f"\n  интерфейс:    {url}")
    if arguments.host not in {"127.0.0.1", "localhost"}:
        print("                микрофон («Мой говорящий Пафнутий») браузер даёт только адресам 127.0.0.1 и localhost")
    print()
    if not arguments.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    import uvicorn

    uvicorn.run("glashatai.web.app:app", host=arguments.host, port=arguments.port, reload=arguments.reload,
                log_level="info")


if __name__ == "__main__":
    main()
