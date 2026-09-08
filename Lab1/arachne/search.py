"""Поисковый механизм: векторная модель поиска.

Класс Search соответствует диаграмме из методички (рис. 2): он строит
поисковый образ запроса (ПОЗ), вычисляет скалярное произведение и евклидовы
нормы и выдаёт упорядоченный по релевантности список SearchResult.

Мера близости документа d и запроса q — косинус угла между их векторами:

        sim(D, Q) = (D, Q) / (||D|| * ||Q||)
"""

from __future__ import annotations

import math
import sqlite3
import time
from dataclasses import dataclass, field

from . import config
from .models import SearchResult
from .text import snippets
from .text.morphology import lemmatize, tokenize


def _date_key(value: str) -> str:
    """ДД.ММ.ГГГГ -> ГГГГММДД для сравнения дат в SQL/Python."""
    value = (value or "").strip()
    if not value:
        return ""
    if "-" in value:  # формат из <input type="date">: ГГГГ-ММ-ДД
        parts = value.split("-")
        if len(parts) == 3:
            return f"{parts[0]}{parts[1]:0>2}{parts[2]:0>2}"
        return ""
    parts = value.split(".")
    if len(parts) == 3:
        return f"{parts[2]}{parts[1]:0>2}{parts[0]:0>2}"
    return ""


@dataclass
class Search:
    """Поисковый запрос и параметры отбора."""

    conn: sqlite3.Connection
    search_query: str = ""
    #: требовать присутствия всех слов запроса в документе
    all_words_together: bool = False
    date_start_string: str = ""
    date_end_string: str = ""
    #: расширения запроса: {исходная лемма: [дополнительные леммы]}
    expansions: dict[str, list[str]] = field(default_factory=dict)
    #: вектор после обратной связи по релевантности (метод Рокчио): {лемма: вес}
    rocchio_vector: dict[str, float] | None = None
    limit: int = 50
    #: минимальный ранг, ниже которого документ не попадает в выдачу
    min_rank: float = 1e-9
    #: строить ПОЗ по леммам (False — по словоформам, для сравнения конфигураций)
    use_lemmas: bool = True

    # служебное
    took_ms: float = 0.0
    query_lemmas: list[str] = field(default_factory=list)
    expanded_lemmas: list[str] = field(default_factory=list)
    lemma_to_word: dict[str, str] = field(default_factory=dict)
    total_found: int = 0

    # --- Построение поискового образа запроса (ПОЗ) -------------------------

    def get_search_query_vector(self) -> dict[str, float]:
        """Вектор запроса {лемма: w_qj}.

        По методичке w_qj = 1, если слово присутствует в запросе, и 0 иначе.
        Термины, добавленные системой (синонимы, исправления опечаток), входят
        с пониженным весом, чтобы не перебивать то, что пользователь ввёл сам.
        """
        if self.rocchio_vector:
            self.query_lemmas = [
                lemma for lemma, weight in self.rocchio_vector.items() if weight > 0
            ]
            return dict(self.rocchio_vector)

        vector: dict[str, float] = {}
        self.query_lemmas = []
        self.lemma_to_word = {}
        for word, norm in lemmatize(tokenize(self.search_query)):
            term = norm if self.use_lemmas else word
            if term not in vector:
                self.query_lemmas.append(term)
                self.lemma_to_word[term] = word
            vector[term] = 1.0

        self.expanded_lemmas = []
        for source_lemma, extras in self.expansions.items():
            for extra in extras:
                if extra in vector:
                    continue
                vector[extra] = config.EXPANDED_TERM_WEIGHT
                self.expanded_lemmas.append(extra)
                self.lemma_to_word.setdefault(extra, extra)
        return vector

    # --- Векторная арифметика (рис. 2) --------------------------------------

    @staticmethod
    def scalar_product(a: dict, b: dict) -> float:
        """Скалярное произведение (D, Q)."""
        if len(a) > len(b):
            a, b = b, a
        return sum(value * b.get(key, 0.0) for key, value in a.items())

    @staticmethod
    def euclidean_norm(a: dict) -> float:
        """Евклидова норма ||a||."""
        return math.sqrt(sum(value * value for value in a.values()))

    # --- Поисковая выдача ---------------------------------------------------

    def get_search_result(self) -> list[SearchResult]:
        """Возвращает список результатов, упорядоченный по убыванию релевантности."""
        started = time.perf_counter()
        query_vector = self.get_search_query_vector()
        if not query_vector:
            self.took_ms = (time.perf_counter() - started) * 1000
            self.total_found = 0
            return []

        lemmas = list(query_vector)
        placeholders = ",".join("?" * len(lemmas))
        rows = self.conn.execute(
            f"""SELECT p.doc_id AS doc_id, t.lemma AS lemma, p.weight AS weight
                FROM postings p JOIN terms t ON t.id = p.term_id
                WHERE t.lemma IN ({placeholders})""",
            lemmas,
        ).fetchall()
        if not rows:
            self.took_ms = (time.perf_counter() - started) * 1000
            self.total_found = 0
            return []

        # скалярное произведение (D, Q) и вклад каждого термина
        products: dict[int, float] = {}
        matched: dict[int, dict[str, float]] = {}
        for row in rows:
            doc_id = row["doc_id"]
            contribution = row["weight"] * query_vector[row["lemma"]]
            products[doc_id] = products.get(doc_id, 0.0) + contribution
            matched.setdefault(doc_id, {})[row["lemma"]] = contribution

        # фильтр «все слова вместе» — по словам, которые ввёл пользователь
        required = set(self.query_lemmas) if self.all_words_together else set()

        norm_q = self.euclidean_norm(query_vector)
        start_key, end_key = _date_key(self.date_start_string), _date_key(self.date_end_string)

        doc_ids = list(products)
        docs: dict[int, sqlite3.Row] = {}
        for chunk_start in range(0, len(doc_ids), 500):
            chunk = doc_ids[chunk_start : chunk_start + 500]
            chunk_placeholders = ",".join("?" * len(chunk))
            for row in self.conn.execute(
                f"""SELECT id, title, uri, path, host, date_added, vector_norm, text
                    FROM documents WHERE id IN ({chunk_placeholders})""",
                chunk,
            ):
                docs[row["id"]] = row

        ranked: list[tuple[float, int]] = []
        for doc_id, product in products.items():
            row = docs.get(doc_id)
            if row is None or not row["vector_norm"]:
                continue
            if required and not required.issubset(matched.get(doc_id, {}).keys()):
                continue
            if start_key or end_key:
                key = _date_key(row["date_added"])
                if start_key and key < start_key:
                    continue
                if end_key and key > end_key:
                    continue
            rank = product / (row["vector_norm"] * norm_q) if norm_q else 0.0
            if rank > self.min_rank:
                ranked.append((rank, doc_id))

        ranked.sort(key=lambda item: (-item[0], item[1]))
        self.total_found = len(ranked)

        results: list[SearchResult] = []
        query_lemma_set = set(query_vector)
        for rank, doc_id in ranked[: self.limit]:
            row = docs[doc_id]
            contributions = matched.get(doc_id, {})
            words = [
                self.lemma_to_word.get(lemma, lemma)
                for lemma in sorted(contributions, key=lambda l: -contributions[l])
            ]
            fragment = snippets.make_snippet(row["text"], query_lemma_set)
            results.append(
                SearchResult(
                    document_id=doc_id,
                    title=row["title"],
                    snippet=snippets.highlight(fragment, query_lemma_set),
                    rank=round(rank, 6),
                    date=row["date_added"],
                    matched_words=words,
                    uri=row["uri"],
                    path=row["path"],
                    host=row["host"],
                    explanation=[
                        (lemma, round(value / (row["vector_norm"] * norm_q), 6))
                        for lemma, value in sorted(
                            contributions.items(), key=lambda item: -item[1]
                        )[:5]
                    ],
                )
            )

        self.took_ms = (time.perf_counter() - started) * 1000
        return results
