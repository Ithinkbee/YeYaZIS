"""Эталонная коллекция запросов и разметка релевантности (qrels).

Разметка хранится в БД, а её текстовое представление — в data/qrels.csv,
чтобы результат ручной оценки не терялся при пересборке базы.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from .. import config

EVAL_QUERIES_PATH = config.DATA_DIR / "eval_queries.csv"


def slug_to_id(conn: sqlite3.Connection) -> dict[str, int]:
    """Сопоставление «имя файла без расширения -> id документа»."""
    return {
        Path(row["path"]).stem: row["id"]
        for row in conn.execute("SELECT id, path FROM documents")
    }


def ensure_query(conn: sqlite3.Connection, text: str, note: str = "") -> int:
    text = text.strip()
    conn.execute(
        "INSERT INTO eval_queries(text, note) VALUES(?, ?) "
        "ON CONFLICT(text) DO UPDATE SET note = excluded.note",
        (text, note),
    )
    conn.commit()
    return int(
        conn.execute("SELECT id FROM eval_queries WHERE text = ?", (text,)).fetchone()["id"]
    )


def set_judgement(conn: sqlite3.Connection, query_id: int, doc_id: int, rel: int) -> None:
    """Ставит оценку релевантности документа запросу (0, 1 или 2)."""
    conn.execute(
        "INSERT INTO qrels(query_id, doc_id, rel) VALUES(?,?,?) "
        "ON CONFLICT(query_id, doc_id) DO UPDATE SET rel = excluded.rel",
        (query_id, doc_id, int(rel)),
    )
    conn.commit()


def remove_judgement(conn: sqlite3.Connection, query_id: int, doc_id: int) -> None:
    conn.execute(
        "DELETE FROM qrels WHERE query_id = ? AND doc_id = ?", (query_id, doc_id)
    )
    conn.commit()


def rel_map(conn: sqlite3.Connection, query_id: int) -> dict[int, int]:
    return {
        row["doc_id"]: row["rel"]
        for row in conn.execute(
            "SELECT doc_id, rel FROM qrels WHERE query_id = ?", (query_id,)
        )
    }


def list_queries(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT q.id, q.text, q.note,
                  (SELECT COUNT(*) FROM qrels r WHERE r.query_id = q.id AND r.rel > 0)
                      AS relevant_count,
                  (SELECT COUNT(*) FROM qrels r WHERE r.query_id = q.id) AS judged_count
           FROM eval_queries q ORDER BY q.id"""
    ).fetchall()


def load_from_csv(conn: sqlite3.Connection) -> dict:
    """Загружает эталонные запросы и разметку из CSV в базу.

    Документы сопоставляются по имени файла, поэтому разметка переживает
    повторный обход ЛВС и смену идентификаторов.
    """
    if not EVAL_QUERIES_PATH.exists() or not config.QRELS_PATH.exists():
        return {"queries": 0, "judgements": 0, "missing": ["файлы эталона не найдены"]}

    mapping = slug_to_id(conn)
    numbers: dict[str, int] = {}

    with EVAL_QUERIES_PATH.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            query_id = ensure_query(conn, row["text"], row.get("note", ""))
            numbers[row["query_id"]] = query_id

    judgements = 0
    missing: list[str] = []
    with config.QRELS_PATH.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            query_id = numbers.get(row["query_id"])
            doc_id = mapping.get(row["doc_slug"])
            if query_id is None or doc_id is None:
                missing.append(row["doc_slug"])
                continue
            set_judgement(conn, query_id, doc_id, int(row["rel"]))
            judgements += 1

    return {"queries": len(numbers), "judgements": judgements, "missing": missing}


def save_to_csv(conn: sqlite3.Connection) -> dict:
    """Выгружает текущую разметку из базы обратно в CSV."""
    config.ensure_dirs()
    queries = list_queries(conn)
    with EVAL_QUERIES_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["query_id", "text", "note"])
        for row in queries:
            writer.writerow([row["id"], row["text"], row["note"]])

    id_to_slug = {
        row["id"]: Path(row["path"]).stem
        for row in conn.execute("SELECT id, path FROM documents")
    }
    pairs = 0
    with config.QRELS_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["query_id", "doc_slug", "rel"])
        for row in conn.execute(
            "SELECT query_id, doc_id, rel FROM qrels ORDER BY query_id, doc_id"
        ):
            slug = id_to_slug.get(row["doc_id"])
            if slug:
                writer.writerow([row["query_id"], slug, row["rel"]])
                pairs += 1
    return {"queries": len(queries), "judgements": pairs}
