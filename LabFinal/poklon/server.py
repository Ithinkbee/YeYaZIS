"""Сервер «Поклона»: страница ролика, музыка, слова и метки.

Здесь нет ни FastAPI, ни шаблонов: ролик — одна страница, и ей нужны файлы да
три ответа в JSON. Хватает стандартной библиотеки, поэтому ролик запускается
на любом компьютере, где есть Python, без pip install.

    GET    /                 страница
    GET    /static/…         сценарии и оформление
    GET    /api/show         запись, слова прощания, сохранённые метки
    GET    /track/<имя>      сама запись (с поддержкой Range)
    POST   /api/cues         сохранить метки хора
    DELETE /api/cues         забыть метки
    POST   /api/track?name=  сохранить запись, перетащенную на страницу

Запись и метки сервер принимает только от страницы, открытой на этом же
компьютере: иначе любой сайт в соседней вкладке мог бы писать файлы на диск.
"""

from __future__ import annotations

import ipaddress
import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from . import config, show


class Handler(BaseHTTPRequestHandler):
    server_version = "Poklon/1.0"
    protocol_version = "HTTP/1.1"
    quiet = True
    SKIP_LIMIT = 1024 * 1024    # тело отвергнутого запроса дочитывается, если оно не больше этого

    # --- разбор запросов ---------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 — имя задаёт http.server
        self.route(body=True)

    def do_HEAD(self) -> None:  # noqa: N802
        self.route(body=False)

    def route(self, body: bool) -> None:
        path = unquote(urlsplit(self.path).path)
        if path in ("/", "/index.html"):
            self.send_file(config.WEB_DIR / "index.html", body)
        elif path.startswith("/static/"):
            self.send_file(self.inside(config.STATIC_DIR, path[len("/static/"):]), body)
        elif path == "/api/show":
            self.send_json(show.describe(), body=body)
        elif path.startswith("/track/"):
            self.send_track(path[len("/track/"):], body)
        elif path == "/favicon.ico":
            self.send_bytes(b"", "image/x-icon", HTTPStatus.NO_CONTENT, body)
        else:
            self.send_error_json(HTTPStatus.NOT_FOUND, "такой страницы нет")

    def do_POST(self) -> None:  # noqa: N802
        parts = urlsplit(self.path)
        if not self.writer_is_local():
            self.skip_body()
            self.send_error_json(HTTPStatus.FORBIDDEN, "изменения принимаются только с этого компьютера")
            return
        if parts.path == "/api/cues":
            self.save_cues()
        elif parts.path == "/api/track":
            self.save_track(parse_qs(parts.query).get("name", [""])[0])
        else:
            self.skip_body()
            self.send_error_json(HTTPStatus.NOT_FOUND, "такой страницы нет")

    def do_DELETE(self) -> None:  # noqa: N802
        self.skip_body()
        if not self.writer_is_local():
            self.send_error_json(HTTPStatus.FORBIDDEN, "изменения принимаются только с этого компьютера")
        elif urlsplit(self.path).path == "/api/cues":
            show.forget_cues()
            self.send_json({"ok": True})
        else:
            self.send_error_json(HTTPStatus.NOT_FOUND, "такой страницы нет")

    # --- запись на диск ------------------------------------------------------------

    def writer_is_local(self) -> bool:
        """Запрос пришёл с этого компьютера и со страницы самого «Поклона»."""
        try:
            if not ipaddress.ip_address(self.client_address[0]).is_loopback:
                return False
        except ValueError:
            return False
        origin = self.headers.get("Origin")
        if origin:
            return urlsplit(origin).netloc == self.headers.get("Host", "")
        return True

    def skip_body(self) -> None:
        """Пропускает тело запроса, на который будет отказ.

        Если ответить, не дочитав, и закрыть соединение, клиент получит обрыв
        вместо ответа: он ещё пишет, а читать уже некому. Поэтому небольшое
        тело дочитывается и отбрасывается. Большое читать незачем — тогда
        соединение после ответа закрывается.
        """
        try:
            left = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            left = -1
        if not 0 <= left <= self.SKIP_LIMIT:
            self.close_connection = True
            return
        while left > 0:
            chunk = self.rfile.read(min(64 * 1024, left))
            if not chunk:
                break
            left -= len(chunk)

    def read_body(self, limit: int) -> bytes | None:
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self.close_connection = True
            self.send_error_json(HTTPStatus.LENGTH_REQUIRED, "не указана длина данных")
            return None
        if length < 0 or length > limit:
            self.skip_body()
            self.send_error_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "слишком много данных")
            return None
        return self.rfile.read(length)

    def save_cues(self) -> None:
        raw = self.read_body(4096)
        if raw is None:
            return
        try:
            cues = show.save_cues(json.loads(raw.decode("utf-8")))
        except (ValueError, UnicodeDecodeError) as error:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
            return
        self.send_json({"ok": True, "cues": cues})

    def save_track(self, name: str) -> None:
        safe = show.safe_track_name(name)
        if safe is None:
            self.skip_body()
            known = ", ".join(sorted(config.AUDIO_TYPES))
            self.send_error_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, f"подходят записи {known}")
            return
        raw = self.read_body(config.MAX_TRACK_BYTES)
        if raw is None:
            return
        if not raw:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "запись пуста")
            return
        folder = config.music_dir()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / safe).write_bytes(raw)
        self.send_json({"ok": True, "name": safe, "playing": getattr(show.find_track(), "name", None)})

    # --- ответы -----------------------------------------------------------------

    @staticmethod
    def inside(folder: Path, relative: str) -> Path | None:
        """Файл внутри папки; None, если путь выводит за её пределы."""
        try:
            path = (folder / relative).resolve()
            path.relative_to(folder.resolve())
        except (OSError, ValueError):
            return None
        return path

    def send_file(self, path: Path | None, body: bool) -> None:
        if path is None or not path.is_file():
            self.send_error_json(HTTPStatus.NOT_FOUND, "файл не найден")
            return
        kind = config.STATIC_TYPES.get(path.suffix.lower(), "application/octet-stream")
        self.send_bytes(path.read_bytes(), kind, HTTPStatus.OK, body)

    def send_track(self, name: str, body: bool) -> None:
        track = show.find_track()
        if track is None or track.name != name:
            self.send_error_json(HTTPStatus.NOT_FOUND, "такой записи нет")
            return
        size = track.stat().st_size
        first, last = 0, size - 1
        status = HTTPStatus.OK
        span = self.headers.get("Range", "")
        if span.startswith("bytes=") and "," not in span:
            # перемотка: браузер просит кусок записи
            begin, _, end = span[len("bytes="):].partition("-")
            try:
                if begin:
                    first = int(begin)
                    last = min(int(end), size - 1) if end else size - 1
                else:
                    first = max(0, size - int(end))
            except ValueError:
                first, last = 0, size - 1
            else:
                if first > last or first >= size:
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                status = HTTPStatus.PARTIAL_CONTENT
        self.send_response(status)
        self.send_header("Content-Type", config.AUDIO_TYPES[track.suffix.lower()])
        self.send_header("Content-Length", str(last - first + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {first}-{last}/{size}")
        self.end_headers()
        if not body:
            return
        with track.open("rb") as stream:
            stream.seek(first)
            left = last - first + 1
            while left > 0:
                chunk = stream.read(min(256 * 1024, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (ConnectionError, OSError):
                    return      # вкладку закрыли посреди передачи
                left -= len(chunk)

    def send_json(self, data: object, status: HTTPStatus = HTTPStatus.OK, body: bool = True) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_bytes(raw, "application/json; charset=utf-8", status, body)

    def send_error_json(self, status: HTTPStatus, message: str) -> None:
        self.send_json({"ok": False, "error": message}, status)

    def send_bytes(self, raw: bytes, kind: str, status: HTTPStatus, body: bool = True) -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(raw)))
        # страницу правят и перезагружают: старые сценарии из кэша не нужны
        self.send_header("Cache-Control", "no-cache")
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        if body and raw:
            try:
                self.wfile.write(raw)
            except (ConnectionError, OSError):
                pass

    def log_message(self, format: str, *args) -> None:  # noqa: A002 — имя задаёт http.server
        if not self.quiet:
            super().log_message(format, *args)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        # вкладку закрыли или перезагрузили — соединение оборвалось; это не ошибка сервера
        if isinstance(sys.exc_info()[1], ConnectionError):
            return
        super().handle_error(request, client_address)


def make_server(host: str | None = None, port: int | None = None, quiet: bool = True) -> Server:
    Handler.quiet = quiet
    return Server((host or config.HOST, config.PORT if port is None else port), Handler)
