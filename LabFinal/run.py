"""Запуск прощального ролика «Поклон».

    python run.py                      — запустить и открыть браузер
    python run.py --no-browser         — только сервер
    python run.py --port 8080          — другой порт
    python run.py --music запись.mp3   — своя запись (иначе первая из папки music/)

Ничего ставить не нужно: сервер написан на стандартной библиотеке Python.
"""

from __future__ import annotations

import argparse
import threading
import webbrowser
from pathlib import Path

from poklon import APP_NAME, config, console

console.setup()


def describe() -> None:
    from poklon import show

    words, problem = show.load_words()
    track = show.find_track()
    cues = show.load_cues()
    print(f"«{APP_NAME}» — прощальный ролик к курсу ЕЯзИИС")
    if track is not None:
        megabytes = track.stat().st_size / 1024 / 1024
        print(f"  музыка:    {track.name} ({megabytes:.1f} МБ)")
        if cues and cues["track"] == track.name:
            print(f"  метки:     хор с {clock(cues['choir'])} до {clock(cues['leave'])} — сохранены на репетиции")
        else:
            print("  метки:     хор страница найдёт сама; подправить — клавиша R (репетиция)")
    else:
        kinds = ", ".join(sorted(config.AUDIO_TYPES))
        print(f"  музыка:    не найдена — положите запись ({kinds}) в папку")
        print(f"             {config.music_dir()}")
        print("             или перетащите её на страницу; без записи ролик идёт в тишине")
    floors = len(words["floors"])
    print(f"  слова:     {config.words_file().name} — этажей: {floors}, строк прощания: {len(words['lines'])}")
    if problem:
        print(f"             внимание: {problem}")
    if not words["to"]:
        print(f"             обращение («to») пусто — впишите имя и отчество в {config.words_file().name}")


def clock(seconds: float) -> str:
    return f"{int(seconds // 60)}:{seconds % 60:04.1f}"


def main() -> None:
    parser = argparse.ArgumentParser(description=f"«{APP_NAME}» — прощальный ролик")
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--music", metavar="ПУТЬ", help="запись или папка с записью (по умолчанию music/)")
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер")
    parser.add_argument("--verbose", action="store_true", help="печатать запросы")
    arguments = parser.parse_args()

    if arguments.music:
        config.MUSIC = Path(arguments.music).expanduser().resolve()
        if not config.MUSIC.exists():
            parser.error(f"нет такого файла или папки: {config.MUSIC}")

    from poklon.server import make_server

    describe()
    try:
        server = make_server(arguments.host, arguments.port, quiet=not arguments.verbose)
    except OSError as error:
        raise SystemExit(f"\nПорт {arguments.port} занят ({error}). Запустите с другим: python run.py --port 8101")

    url = f"http://{arguments.host}:{arguments.port}/"
    print(f"\n  ролик:     {url}")
    print("             F — во весь экран, пробел — пауза, R — репетиция; остановить сервер — Ctrl+C\n")
    if not arguments.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nЗанавес.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
