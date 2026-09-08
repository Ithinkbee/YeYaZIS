"""Паук (агент) — первый компонент ИПС.

Обходит указанные ресурсы локальной вычислительной сети: обычные каталоги и
сетевые шары вида \\\\host\\share, извлекает текст документов и складывает их
в базу данных. Поддерживает инкрементальный обход: неизменившиеся файлы
повторно не разбираются.
"""

from __future__ import annotations

import hashlib
import os
import socket
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from . import config
from .models import CrawlReport
from .text import extract


# --- Источники (узлы ЛВС) ---------------------------------------------------

def detect_kind(root_path: str) -> str:
    return "unc" if root_path.startswith("\\\\") or root_path.startswith("//") else "local"


def host_of(root_path: str, label: str = "") -> str:
    """Имя узла ЛВС, которому принадлежит ресурс."""
    if label:
        return label
    if detect_kind(root_path) == "unc":
        parts = root_path.replace("/", "\\").strip("\\").split("\\")
        return parts[0].upper() if parts else "UNKNOWN"
    return socket.gethostname().upper()


def add_source(conn: sqlite3.Connection, root_path: str, label: str = "") -> int:
    """Регистрирует ресурс ЛВС. Возвращает id источника."""
    path = str(Path(root_path).expanduser())
    if not label:
        label = host_of(path)
    conn.execute(
        "INSERT INTO sources(root_path, kind, label, enabled) VALUES(?,?,?,1) "
        "ON CONFLICT(root_path) DO UPDATE SET label = excluded.label, enabled = 1",
        (path, detect_kind(path), label),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM sources WHERE root_path = ?", (path,)).fetchone()
    return int(row["id"])


def list_sources(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM sources ORDER BY id").fetchall()


def remove_source(conn: sqlite3.Connection, source_id: int, drop_documents: bool = True) -> None:
    row = conn.execute("SELECT root_path FROM sources WHERE id = ?", (source_id,)).fetchone()
    if row and drop_documents:
        conn.execute("DELETE FROM documents WHERE path LIKE ?", (row["root_path"] + "%",))
    conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    conn.commit()


def discover_shares(host: str) -> list[str]:
    """Список доступных сетевых шар узла (Windows, `net view`).

    Используется как удобство интерфейса: пользователь видит, какие ресурсы
    ЛВС можно добавить в обход. При ошибке возвращает пустой список.
    """
    import subprocess

    host = host.strip().strip("\\")
    if not host:
        return []
    try:
        completed = subprocess.run(
            ["net", "view", f"\\\\{host}"],
            capture_output=True, timeout=15, check=False,
        )
    except Exception:
        return []
    output = completed.stdout.decode("cp866", errors="ignore")
    shares = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].lower() in {"disk", "диск"}:
            shares.append(f"\\\\{host}\\{parts[0]}")
    return shares


# --- Обход ------------------------------------------------------------------

def _file_uri(path: str) -> str:
    """file:// ссылка для активной ссылки в поисковой выдаче."""
    return Path(path).as_uri() if not path.startswith("\\\\") else "file:" + path.replace("\\", "/")


def _iter_files(root: Path) -> list[Path]:
    """Рекурсивный обход каталога с пропуском служебных папок."""
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
        dirnames[:] = [d for d in dirnames if d not in config.SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            path = Path(dirpath) / name
            if path.suffix.lower() in config.ALLOWED_EXTENSIONS:
                files.append(path)
    return files


def _read_file(path: Path) -> tuple[Path, str, str, str, int, float] | tuple[Path, None, str]:
    """Читает и разбирает один файл (выполняется в пуле потоков)."""
    try:
        stat = path.stat()
        if stat.st_size > config.MAX_FILE_SIZE:
            return (path, None, "файл больше допустимого размера")
        raw = path.read_bytes()
        digest = hashlib.sha1(raw).hexdigest()
        title, text = extract.extract(path)
        return (path, title, text, digest, stat.st_size, stat.st_mtime)
    except extract.ExtractionError as exc:
        return (path, None, str(exc))
    except (PermissionError, OSError) as exc:
        return (path, None, f"нет доступа: {exc}")
    except Exception as exc:  # noqa: BLE001 - паук не должен падать из-за одного файла
        return (path, None, f"{type(exc).__name__}: {exc}")


def crawl(
    conn: sqlite3.Connection,
    source_ids: list[int] | None = None,
    progress=None,
) -> CrawlReport:
    """Обходит включённые источники и обновляет таблицу documents.

    `progress` — необязательный callback(done, total, message) для интерфейса.
    """
    started = time.perf_counter()
    report = CrawlReport()

    query = "SELECT * FROM sources WHERE enabled = 1"
    params: tuple = ()
    if source_ids:
        placeholders = ",".join("?" * len(source_ids))
        query += f" AND id IN ({placeholders})"
        params = tuple(source_ids)
    sources = conn.execute(query, params).fetchall()

    if not sources:
        report.messages.append("Нет включённых источников для обхода.")
        return report

    log_id = conn.execute(
        "INSERT INTO crawl_log(started_at) VALUES(?)",
        (datetime.now().strftime("%d.%m.%Y %H:%M:%S"),),
    ).lastrowid
    conn.commit()

    known = {
        row["path"]: (row["mtime"], row["size_bytes"], row["content_hash"])
        for row in conn.execute("SELECT path, mtime, size_bytes, content_hash FROM documents")
    }
    seen_paths: set[str] = set()

    for source in sources:
        root = Path(source["root_path"])
        host = host_of(source["root_path"], source["label"])
        if not root.exists():
            report.errors += 1
            report.messages.append(f"Ресурс недоступен: {root}")
            continue

        files = _iter_files(root)
        report.files_seen += len(files)

        # файлы, которые не менялись, пропускаем не читая
        to_read: list[Path] = []
        for path in files:
            spath = str(path)
            seen_paths.add(spath)
            try:
                stat = path.stat()
            except OSError as exc:
                report.errors += 1
                report.messages.append(f"{path}: {exc}")
                continue
            previous = known.get(spath)
            if previous and abs(previous[0] - stat.st_mtime) < 1e-6 and previous[1] == stat.st_size:
                report.skipped += 1
                continue
            to_read.append(path)

        total = len(to_read)
        done = 0
        if total:
            with ThreadPoolExecutor(max_workers=config.CRAWLER_THREADS) as pool:
                for result in pool.map(_read_file, to_read):
                    done += 1
                    path = result[0]
                    if result[1] is None:
                        report.errors += 1
                        report.messages.append(f"{path.name}: {result[2]}")
                    else:
                        _, title, text, digest, size, mtime = result
                        spath = str(path)
                        previous = known.get(spath)
                        if previous and previous[2] == digest:
                            conn.execute(
                                "UPDATE documents SET mtime = ?, size_bytes = ? WHERE path = ?",
                                (mtime, size, spath),
                            )
                            report.skipped += 1
                        else:
                            now = datetime.now()
                            conn.execute(
                                """
                                INSERT INTO documents(path, uri, host, title, text, ext,
                                                      size_bytes, mtime, date_added, time_added,
                                                      content_hash)
                                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                                ON CONFLICT(path) DO UPDATE SET
                                    title = excluded.title, text = excluded.text,
                                    size_bytes = excluded.size_bytes, mtime = excluded.mtime,
                                    content_hash = excluded.content_hash, host = excluded.host,
                                    vector_norm = 0
                                """,
                                (
                                    spath, _file_uri(spath), host, title, text,
                                    path.suffix.lower(), size, mtime,
                                    now.strftime("%d.%m.%Y"), now.strftime("%H:%M:%S"),
                                    digest,
                                ),
                            )
                            if previous:
                                report.updated += 1
                            else:
                                report.added += 1
                    if progress:
                        progress(done, total, f"{host}: {path.name}")
            conn.commit()

        conn.execute(
            "UPDATE sources SET last_crawl = ? WHERE id = ?",
            (datetime.now().strftime("%d.%m.%Y %H:%M:%S"), source["id"]),
        )

    # документы, файлы которых исчезли из ЛВС
    if seen_paths:
        for row in conn.execute("SELECT id, path FROM documents").fetchall():
            if row["path"] in seen_paths:
                continue
            still_there = any(
                row["path"].startswith(str(Path(s["root_path"]))) for s in sources
            )
            if still_there and not Path(row["path"]).exists():
                conn.execute("DELETE FROM documents WHERE id = ?", (row["id"],))
                report.removed += 1

    report.took_ms = (time.perf_counter() - started) * 1000
    conn.execute(
        """UPDATE crawl_log SET finished_at = ?, added = ?, updated = ?, skipped = ?,
                                removed = ?, errors = ?, details = ? WHERE id = ?""",
        (
            datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
            report.added, report.updated, report.skipped, report.removed,
            report.errors, "\n".join(report.messages[:100]), log_id,
        ),
    )
    conn.commit()
    return report
