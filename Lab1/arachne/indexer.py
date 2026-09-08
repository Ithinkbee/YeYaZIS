"""Модуль индексирования: построение поисковых образов документов (ПОД).

Реализует формулы методички:

    (1.5)  B_i = log(N / P_i)        — инверсная частота термина i;
    (1.6)  A_ij = Q_ij * B_i         — вес термина i в документе j,

где N — число документов в базе, P_i — число документов с термином i,
Q_ij — частота термина i в документе j. Веса A_ij складываются в
инвертированный индекс (таблица postings), а евклидова норма ||D|| вектора
документа сохраняется в documents.vector_norm — она нужна для косинусной меры.
"""

from __future__ import annotations

import math
import sqlite3
import time
from collections import Counter
from datetime import datetime

from .models import Document
from .text.morphology import analyze_text

#: основание логарифма в формуле (1.5); на порядок выдачи не влияет —
#: смена основания умножает все веса на общий множитель
LOG_BASE = 10.0


def inverse_frequency(doc_count: int, df: int) -> float:
    """Инверсная частота термина B_i по формуле (1.5)."""
    if df <= 0 or doc_count <= 0:
        return 0.0
    return math.log(doc_count / df, LOG_BASE)


def build_index(conn: sqlite3.Connection, progress=None, use_lemmas: bool = True) -> dict:
    """Полностью перестраивает индекс по документам из базы.

    Полная перестройка (а не досборка) выбрана потому, что при добавлении
    документов меняется N и все инверсные частоты B_i, а значит и все веса A_ij.

    `use_lemmas=False` строит индекс по словоформам — режим для сравнения
    качества поиска с морфологическим анализом и без него.
    """
    started = time.perf_counter()

    rows = conn.execute("SELECT id, text FROM documents").fetchall()
    doc_count = len(rows)
    if doc_count == 0:
        conn.executescript("DELETE FROM postings; DELETE FROM forms; DELETE FROM terms;")
        conn.commit()
        return {"documents": 0, "terms": 0, "postings": 0, "took_ms": 0.0}

    # 1. Поисковые образы документов: частоты лемм Q_ij и словоформы
    doc_terms: dict[int, Counter] = {}
    form_freq: dict[str, Counter] = {}   # лемма -> {словоформа: частота}
    df: Counter = Counter()              # P_i — число документов с термином

    for position, row in enumerate(rows, 1):
        counts, forms = analyze_text(row["text"], use_lemmas=use_lemmas)
        doc_terms[row["id"]] = counts
        for lemma_str in counts:
            df[lemma_str] += 1
        for lemma_str, variants in forms.items():
            form_freq.setdefault(lemma_str, Counter()).update(variants)
        if progress:
            progress(position, doc_count, "анализ документов")

    # 2. Словарь системы
    conn.executescript("DELETE FROM postings; DELETE FROM forms; DELETE FROM terms;")
    conn.executemany(
        "INSERT INTO terms(lemma, df) VALUES(?, ?)",
        [(lemma_str, count) for lemma_str, count in df.items()],
    )
    term_id = {
        row["lemma"]: row["id"]
        for row in conn.execute("SELECT id, lemma FROM terms")
    }

    # 3. Веса A_ij и нормы векторов документов
    postings: list[tuple[int, int, int, float]] = []
    norms: list[tuple[float, int, int]] = []
    idf_cache = {
        lemma_str: inverse_frequency(doc_count, count) for lemma_str, count in df.items()
    }

    for doc_id, counts in doc_terms.items():
        norm_sq = 0.0
        total = 0
        for lemma_str, tf in counts.items():
            weight = tf * idf_cache[lemma_str]          # формула (1.6)
            postings.append((term_id[lemma_str], doc_id, tf, weight))
            norm_sq += weight * weight
            total += tf
        norms.append((math.sqrt(norm_sq), total, doc_id))

    conn.executemany(
        "INSERT INTO postings(term_id, doc_id, tf, weight) VALUES(?,?,?,?)", postings
    )
    conn.executemany(
        "UPDATE documents SET vector_norm = ?, term_count = ? WHERE id = ?", norms
    )

    # 4. Словоформы — для автодополнения и исправления опечаток
    conn.executemany(
        "INSERT INTO forms(form, term_id, freq) VALUES(?,?,?)",
        [
            (form, term_id[lemma_str], freq)
            for lemma_str, variants in form_freq.items()
            for form, freq in variants.items()
        ],
    )
    conn.commit()

    return {
        "documents": doc_count,
        "terms": len(term_id),
        "postings": len(postings),
        "took_ms": (time.perf_counter() - started) * 1000,
    }


# --- Сервисные функции (соответствуют диаграмме класса Document, рис. 1) -----

def add_document_to_base(conn: sqlite3.Connection, document: Document) -> int:
    """Добавляет документ в базу и возвращает его идентификатор.

    Соответствует операции AddDocumentToBase (рис. 1). Повторное добавление того
    же пути обновляет запись: путь в ЛВС однозначно определяет документ. Веса
    терминов при этом сбрасываются — документ нужно переиндексировать, поскольку
    появление нового документа меняет N, а значит и все инверсные частоты B_i.
    """
    now = datetime.now()
    conn.execute(
        """
        INSERT INTO documents(path, uri, host, title, text, ext, size_bytes, mtime,
                              date_added, time_added, content_hash)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(path) DO UPDATE SET
            title = excluded.title, text = excluded.text, host = excluded.host,
            size_bytes = excluded.size_bytes, mtime = excluded.mtime,
            content_hash = excluded.content_hash, vector_norm = 0
        """,
        (
            document.path, document.uri, document.host, document.title, document.text,
            document.ext, document.size_bytes, document.mtime,
            document.date_added or now.strftime("%d.%m.%Y"),
            document.time_added or now.strftime("%H:%M:%S"),
            document.content_hash,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM documents WHERE path = ?", (document.path,)).fetchone()
    document.document_id = int(row["id"])
    return document.document_id


def delete_document_from_base(conn: sqlite3.Connection, doc_id: int) -> bool:
    """Удаляет документ из базы вместе с его вхождениями в индекс.

    Соответствует операции DeleteDocumentFromBase (рис. 1). Возвращает False,
    если документа с таким идентификатором нет. Счётчики df затронутых терминов
    после удаления становятся завышенными, поэтому для точных весов индекс
    следует перестроить (build_index).
    """
    row = conn.execute("SELECT id FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if row is None:
        return False
    # postings удалятся каскадом, но qrels и feedback ссылаются на документ тоже
    conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    conn.commit()
    return True


def get_lemma_inverse_frequency(conn: sqlite3.Connection, lemma_str: str) -> float:
    """B_i для термина по его лемме."""
    row = conn.execute("SELECT df FROM terms WHERE lemma = ?", (lemma_str,)).fetchone()
    if not row:
        return 0.0
    total = conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"]
    return inverse_frequency(total, row["df"])


def get_lemma_inverse_frequency_by_id(conn: sqlite3.Connection, term_id: int) -> float:
    """B_i для термина по его идентификатору (вторая форма операции на рис. 1)."""
    row = conn.execute("SELECT df FROM terms WHERE id = ?", (term_id,)).fetchone()
    if not row:
        return 0.0
    total = conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"]
    return inverse_frequency(total, row["df"])


def get_lemma_weight_in_document(
    conn: sqlite3.Connection, term_id: int, doc_id: int
) -> float:
    """A_ij по идентификатору термина (GetLemmWeightInDocument, рис. 1)."""
    row = conn.execute(
        "SELECT weight FROM postings WHERE term_id = ? AND doc_id = ?",
        (term_id, doc_id),
    ).fetchone()
    return float(row["weight"]) if row else 0.0


def get_word_weight_in_document(
    conn: sqlite3.Connection, lemma_str: str, doc_id: int
) -> float:
    """A_ij — вес термина в конкретном документе."""
    row = conn.execute(
        """SELECT p.weight FROM postings p
           JOIN terms t ON t.id = p.term_id
           WHERE t.lemma = ? AND p.doc_id = ?""",
        (lemma_str, doc_id),
    ).fetchone()
    return float(row["weight"]) if row else 0.0


def get_document_vector(conn: sqlite3.Connection, doc_id: int) -> dict[int, float]:
    """Вектор документа: {term_id: A_ij}."""
    return {
        row["term_id"]: float(row["weight"])
        for row in conn.execute(
            "SELECT term_id, weight FROM postings WHERE doc_id = ?", (doc_id,)
        )
    }


def get_document_vector_by_lemma(conn: sqlite3.Connection, doc_id: int) -> dict[str, float]:
    """Вектор документа в виде {лемма: A_ij} — удобно для объяснения выдачи."""
    return {
        row["lemma"]: float(row["weight"])
        for row in conn.execute(
            """SELECT t.lemma AS lemma, p.weight AS weight
               FROM postings p JOIN terms t ON t.id = p.term_id
               WHERE p.doc_id = ?""",
            (doc_id,),
        )
    }


def top_terms(conn: sqlite3.Connection, limit: int = 30) -> list[sqlite3.Row]:
    """Наиболее «весомые» термины словаря — для страницы статистики."""
    return conn.execute(
        """SELECT t.lemma AS lemma, t.df AS df, SUM(p.tf) AS tf_total,
                  MAX(p.weight) AS max_weight
           FROM terms t JOIN postings p ON p.term_id = t.id
           GROUP BY t.id ORDER BY tf_total DESC LIMIT ?""",
        (limit,),
    ).fetchall()
