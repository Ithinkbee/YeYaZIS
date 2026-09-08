"""База данных системы (SQLite): схема, подключение, служебные операции.

Второй из трёх компонентов ИПС по методичке — «база данных, которая содержит
всю информацию, собираемую пауками».
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from . import config

SCHEMA = """
-- Документы, найденные пауком в ЛВС
CREATE TABLE IF NOT EXISTS documents (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    path          TEXT    NOT NULL UNIQUE,   -- полный путь (локальный или UNC)
    uri           TEXT    NOT NULL,          -- file:// ссылка для интерфейса
    host          TEXT    NOT NULL,          -- узел ЛВС (имя компьютера/шары)
    title         TEXT    NOT NULL,
    text          TEXT    NOT NULL,          -- извлечённый текст документа
    ext           TEXT    NOT NULL,
    size_bytes    INTEGER NOT NULL DEFAULT 0,
    mtime         REAL    NOT NULL DEFAULT 0,-- время изменения файла (для инкрементальности)
    date_added    TEXT    NOT NULL,          -- дата добавления в базу (ДД.ММ.ГГГГ)
    time_added    TEXT    NOT NULL,          -- время добавления (ЧЧ:ММ:СС)
    content_hash  TEXT    NOT NULL DEFAULT '',
    term_count    INTEGER NOT NULL DEFAULT 0,-- число значимых словоупотреблений
    vector_norm   REAL    NOT NULL DEFAULT 0 -- евклидова норма ||D|| вектора документа
);

-- Словарь системы: леммы (термины) и число документов с термином (P_i)
CREATE TABLE IF NOT EXISTS terms (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    lemma  TEXT    NOT NULL UNIQUE,
    df     INTEGER NOT NULL DEFAULT 0
);

-- Инвертированный индекс: вес термина i в документе j
CREATE TABLE IF NOT EXISTS postings (
    term_id  INTEGER NOT NULL REFERENCES terms(id)     ON DELETE CASCADE,
    doc_id   INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    tf       INTEGER NOT NULL,      -- Q_ij, частота термина i в документе j
    weight   REAL    NOT NULL,      -- A_ij = Q_ij * B_i  (формула 1.6)
    PRIMARY KEY (term_id, doc_id)
);

-- Словоформы -> лемма: нужны для автодополнения и исправления опечаток
CREATE TABLE IF NOT EXISTS forms (
    form     TEXT    NOT NULL,
    term_id  INTEGER NOT NULL REFERENCES terms(id) ON DELETE CASCADE,
    freq     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (form, term_id)
);

-- Источники: узлы и каталоги локальной сети, которые обходит паук
CREATE TABLE IF NOT EXISTS sources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    root_path   TEXT    NOT NULL UNIQUE,
    kind        TEXT    NOT NULL DEFAULT 'local',  -- local | unc
    label       TEXT    NOT NULL DEFAULT '',
    enabled     INTEGER NOT NULL DEFAULT 1,
    last_crawl  TEXT    NOT NULL DEFAULT ''
);

-- Журнал обходов паука
CREATE TABLE IF NOT EXISTS crawl_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT '',
    added      INTEGER NOT NULL DEFAULT 0,
    updated    INTEGER NOT NULL DEFAULT 0,
    skipped    INTEGER NOT NULL DEFAULT 0,
    removed    INTEGER NOT NULL DEFAULT 0,
    errors     INTEGER NOT NULL DEFAULT 0,
    details    TEXT NOT NULL DEFAULT ''
);

-- История пользовательских запросов (для подсказок и статистики)
CREATE TABLE IF NOT EXISTS query_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_query      TEXT    NOT NULL,
    normalized     TEXT    NOT NULL DEFAULT '',
    ts             TEXT    NOT NULL,
    results_count  INTEGER NOT NULL DEFAULT 0,
    took_ms        REAL    NOT NULL DEFAULT 0
);

-- Эталонные запросы для оценки качества
CREATE TABLE IF NOT EXISTS eval_queries (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    text  TEXT NOT NULL UNIQUE,
    note  TEXT NOT NULL DEFAULT ''
);

-- Эталонная разметка релевантности (qrels)
CREATE TABLE IF NOT EXISTS qrels (
    query_id  INTEGER NOT NULL REFERENCES eval_queries(id) ON DELETE CASCADE,
    doc_id    INTEGER NOT NULL REFERENCES documents(id)    ON DELETE CASCADE,
    rel       INTEGER NOT NULL DEFAULT 0,   -- 0 - нерелевантен, 1 - релевантен, 2 - высоко релевантен
    PRIMARY KEY (query_id, doc_id)
);

-- Обратная связь пользователя по релевантности (метод Рокчио)
CREATE TABLE IF NOT EXISTS feedback (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    query    TEXT    NOT NULL,
    doc_id   INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    mark     INTEGER NOT NULL,   -- +1 «больше таких», -1 «не то»
    ts       TEXT    NOT NULL
);

-- Достижения (геймификация)
CREATE TABLE IF NOT EXISTS achievements (
    code        TEXT PRIMARY KEY,
    unlocked_at TEXT NOT NULL
);

-- Настройки, изменяемые из интерфейса
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_postings_term ON postings(term_id);
CREATE INDEX IF NOT EXISTS idx_postings_doc  ON postings(doc_id);
CREATE INDEX IF NOT EXISTS idx_terms_lemma   ON terms(lemma);
CREATE INDEX IF NOT EXISTS idx_forms_form    ON forms(form);
CREATE INDEX IF NOT EXISTS idx_documents_host ON documents(host);
"""


def connect(db_path=None) -> sqlite3.Connection:
    """Возвращает подключение к БД с включёнными внешними ключами."""
    path = str(db_path or config.DB_PATH)
    if path != ":memory:":
        config.ensure_dirs()
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Создаёт схему БД (идемпотентно)."""
    conn.executescript(SCHEMA)
    conn.commit()


@contextmanager
def session(db_path=None) -> Iterator[sqlite3.Connection]:
    """Контекстный менеджер: подключение + гарантированное закрытие."""
    conn = connect(db_path)
    try:
        init_db(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


# --- Настройки --------------------------------------------------------------

def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


# --- Статистика -------------------------------------------------------------

def stats(conn: sqlite3.Connection) -> dict:
    """Сводка по базе — используется на странице управления индексом."""

    def scalar(sql: str, default=0):
        row = conn.execute(sql).fetchone()
        value = row[0] if row else None
        return default if value is None else value

    return {
        "documents": scalar("SELECT COUNT(*) FROM documents"),
        "terms": scalar("SELECT COUNT(*) FROM terms"),
        "postings": scalar("SELECT COUNT(*) FROM postings"),
        "forms": scalar("SELECT COUNT(*) FROM forms"),
        "sources": scalar("SELECT COUNT(*) FROM sources"),
        "hosts": scalar("SELECT COUNT(DISTINCT host) FROM documents"),
        "queries": scalar("SELECT COUNT(*) FROM query_log"),
        "avg_terms": round(scalar("SELECT AVG(term_count) FROM documents", 0) or 0, 1),
        "total_size": scalar("SELECT SUM(size_bytes) FROM documents"),
        "indexed": scalar("SELECT COUNT(*) FROM documents WHERE vector_norm > 0"),
    }


def reset_index(conn: sqlite3.Connection) -> None:
    """Очищает индекс (термины/веса), сами документы остаются."""
    conn.executescript(
        "DELETE FROM postings; DELETE FROM forms; DELETE FROM terms; "
        "UPDATE documents SET vector_norm = 0, term_count = 0;"
    )
    conn.commit()


def clear_all(conn: sqlite3.Connection) -> None:
    """Полная очистка базы документов и индекса."""
    conn.executescript(
        "DELETE FROM postings; DELETE FROM forms; DELETE FROM terms; "
        "DELETE FROM qrels; DELETE FROM feedback; DELETE FROM documents;"
    )
    conn.commit()
