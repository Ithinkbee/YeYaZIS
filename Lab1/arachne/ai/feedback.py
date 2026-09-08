"""Обратная связь по релевантности и подбор похожих документов.

Метод Рокчио сдвигает вектор запроса в сторону документов, отмеченных
пользователем как удачные, и от документов, отмеченных как неудачные:

    Q' = alpha * Q + beta / |Dr| * sum(Dr) - gamma / |Dnr| * sum(Dnr)
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from .. import config
from ..indexer import get_document_vector_by_lemma


def _normalized_vector(conn: sqlite3.Connection, doc_id: int) -> dict[str, float]:
    """Вектор документа, приведённый к единичной длине."""
    row = conn.execute(
        "SELECT vector_norm FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    if not row or not row["vector_norm"]:
        return {}
    norm = float(row["vector_norm"])
    return {
        lemma: weight / norm
        for lemma, weight in get_document_vector_by_lemma(conn, doc_id).items()
    }


def record(conn: sqlite3.Connection, query: str, doc_id: int, mark: int) -> None:
    """Сохраняет отметку пользователя: +1 «больше таких», -1 «не то»."""
    conn.execute(
        "INSERT INTO feedback(query, doc_id, mark, ts) VALUES(?,?,?,?)",
        (query.strip(), doc_id, 1 if mark > 0 else -1,
         datetime.now().strftime("%d.%m.%Y %H:%M:%S")),
    )
    conn.commit()


def marks_for_query(conn: sqlite3.Connection, query: str) -> dict[int, int]:
    """Текущие отметки пользователя по данному запросу: {doc_id: +1/-1}."""
    rows = conn.execute(
        """SELECT doc_id, mark FROM feedback
           WHERE query = ? AND id IN (
               SELECT MAX(id) FROM feedback WHERE query = ? GROUP BY doc_id
           )""",
        (query.strip(), query.strip()),
    ).fetchall()
    return {row["doc_id"]: row["mark"] for row in rows}


def clear(conn: sqlite3.Connection, query: str) -> None:
    conn.execute("DELETE FROM feedback WHERE query = ?", (query.strip(),))
    conn.commit()


def rocchio_vector(
    conn: sqlite3.Connection,
    base_vector: dict[str, float],
    positive_ids: list[int],
    negative_ids: list[int],
    top_terms: int = 40,
) -> dict[str, float]:
    """Модифицированный вектор запроса по методу Рокчио.

    Отрицательные компоненты обнуляются, вектор усекается до `top_terms`
    наиболее весомых терминов — иначе запрос «расползается» по всей коллекции.
    """
    if not positive_ids and not negative_ids:
        return dict(base_vector)

    vector: dict[str, float] = {
        lemma: weight * config.ROCCHIO_ALPHA for lemma, weight in base_vector.items()
    }

    if positive_ids:
        factor = config.ROCCHIO_BETA / len(positive_ids)
        for doc_id in positive_ids:
            for lemma, weight in _normalized_vector(conn, doc_id).items():
                vector[lemma] = vector.get(lemma, 0.0) + factor * weight

    if negative_ids:
        factor = config.ROCCHIO_GAMMA / len(negative_ids)
        for doc_id in negative_ids:
            for lemma, weight in _normalized_vector(conn, doc_id).items():
                vector[lemma] = vector.get(lemma, 0.0) - factor * weight

    positive_part = {
        lemma: weight for lemma, weight in vector.items() if weight > 1e-6
    }
    if len(positive_part) <= top_terms:
        return positive_part
    best = sorted(positive_part.items(), key=lambda item: -item[1])[:top_terms]
    return dict(best)


def similar_documents(
    conn: sqlite3.Connection, doc_id: int, limit: int = 5
) -> list[sqlite3.Row]:
    """Документы, наиболее близкие к данному по косинусной мере."""
    source = _normalized_vector(conn, doc_id)
    if not source:
        return []
    # для скорости берём только наиболее весомые термины документа-образца
    top = sorted(source.items(), key=lambda item: -item[1])[:25]
    lemmas = [lemma for lemma, _ in top]
    weights = dict(top)

    placeholders = ",".join("?" * len(lemmas))
    rows = conn.execute(
        f"""SELECT p.doc_id AS doc_id, t.lemma AS lemma, p.weight AS weight
            FROM postings p JOIN terms t ON t.id = p.term_id
            WHERE t.lemma IN ({placeholders}) AND p.doc_id <> ?""",
        (*lemmas, doc_id),
    ).fetchall()

    products: dict[int, float] = {}
    for row in rows:
        products[row["doc_id"]] = (
            products.get(row["doc_id"], 0.0) + row["weight"] * weights[row["lemma"]]
        )
    if not products:
        return []

    norms = {
        row["id"]: float(row["vector_norm"])
        for row in conn.execute(
            "SELECT id, vector_norm FROM documents WHERE vector_norm > 0"
        )
    }
    query_norm = sum(weight * weight for weight in weights.values()) ** 0.5
    ranked = sorted(
        (
            (product / (norms.get(other, 1.0) * query_norm), other)
            for other, product in products.items()
            if other in norms
        ),
        key=lambda item: -item[0],
    )[:limit]

    results = []
    for score, other in ranked:
        row = conn.execute(
            "SELECT id, title, host, date_added, uri, path FROM documents WHERE id = ?",
            (other,),
        ).fetchone()
        if row:
            results.append({"score": round(score, 4), **dict(row)})
    return results
