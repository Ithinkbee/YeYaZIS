"""Поисковый механизм: векторная модель поиска.

Класс Search соответствует диаграмме из методички (рис. 2): он строит
поисковый образ запроса (ПОЗ), вычисляет скалярное произведение и евклидовы
нормы и выдаёт упорядоченный по релевантности список SearchResult.

Мера близости документа d и запроса q — косинус угла между их векторами:

        sim(D, Q) = (D, Q) / (||D|| * ||Q||)

Часть полей датакласса — параметры игровых модификаторов («джокеры»). Они
собраны здесь намеренно: каждый из них меняет ровно один множитель формулы, а
не переписывает метод, поэтому поисковый механизм остаётся одним и тем же.
Значения по умолчанию соответствуют чистой конфигурации, на которой считаются
метрики качества.
"""

from __future__ import annotations

import math
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass, field

from . import config
from .models import SearchResult
from .text import snippets
from .text.morphology import is_significant, is_stopword, lemma, tokenize

#: вес купленного в лавке стоп-слова в ПОЗ (механика «чёрный рынок стоп-слов»)
BOUGHT_STOPWORD_WEIGHT = 3.0

#: вес стоп-слова, оставленного в запросе джокером `no-stop`
JOKER_STOPWORD_WEIGHT = 1.0


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

    # --- Игровые модификаторы (по умолчанию выключены) ----------------------
    #: стоп-слова, купленные в лавке: входят в ПОЗ с весом 3,0
    allowed_stopwords: set[str] = field(default_factory=set)
    #: джокер `no-stop`: в ПОЗ остаются все стоп-слова запроса
    keep_stopwords: bool = False
    #: джокер `sq-weights`: вес термина в документе возводится в квадрат
    square_weights: bool = False
    #: джокер `ban-node`: документы этого узла ЛВС исключаются из выдачи
    banned_host: str = ""
    #: джокер `syn-x2`: вес расширений (None — берётся config.EXPANDED_TERM_WEIGHT)
    expanded_weight: float | None = None
    #: джокер `idf-flat`: B_i = 1 для всех терминов, остаётся чистая частота Q_ij
    flat_idf: bool = False
    #: джокер `short-doc`: ранг делится на логарифм длины документа
    short_doc_bonus: bool = False
    #: «ранжирование по настроению»: выдача сортируется по алфавиту заголовков
    alphabetical: bool = False
    #: «пьяный индекс»: вероятность перестановки соседних букв в сниппете
    snippet_noise: float = 0.0

    # служебное
    took_ms: float = 0.0
    #: леммы, которые пользователь ввёл сам (без Рокчио и без расширений)
    user_lemmas: list[str] = field(default_factory=list)
    #: всё, что реально лежит в векторе запроса — для подсветки и объяснений
    query_lemmas: list[str] = field(default_factory=list)
    expanded_lemmas: list[str] = field(default_factory=list)
    #: термины, добавленные методом Рокчио по отметкам пользователя
    feedback_lemmas: list[str] = field(default_factory=list)
    #: стоп-слова запроса, попавшие в ПОЗ вопреки обычным правилам
    kept_stopwords: list[str] = field(default_factory=list)
    lemma_to_word: dict[str, str] = field(default_factory=dict)
    total_found: int = 0

    # --- Построение поискового образа запроса (ПОЗ) -------------------------

    def _stopword_weight(self, token: str) -> float:
        """Вес стоп-слова в ПОЗ: 0 — обычное поведение, стоп-слово отброшено."""
        if self.keep_stopwords:
            return JOKER_STOPWORD_WEIGHT
        if token in self.allowed_stopwords:
            return BOUGHT_STOPWORD_WEIGHT
        return 0.0

    def _collect_user_lemmas(self) -> dict[str, float]:
        """Слова, которые пользователь ввёл сам, с их весами w_qj = 1.

        Заполняет user_lemmas и lemma_to_word. Вызывается всегда — в том числе
        когда ПОЗ будет заменён вектором Рокчио: фильтр «все слова вместе» и
        чипсы «слова запроса в документе» строятся именно по этим леммам, а не
        по вектору обратной связи.
        """
        vector: dict[str, float] = {}
        self.user_lemmas = []
        self.kept_stopwords = []
        self.lemma_to_word = {}
        for token in tokenize(self.search_query):
            if not is_significant(token):
                if not is_stopword(token):
                    continue
                weight = self._stopword_weight(token)
                if weight <= 0:
                    continue
                term = lemma(token) if self.use_lemmas else token
                if term not in vector:
                    self.user_lemmas.append(term)
                    self.kept_stopwords.append(token)
                    self.lemma_to_word[term] = token
                vector[term] = weight
                continue
            term = lemma(token) if self.use_lemmas else token
            if term not in vector:
                self.user_lemmas.append(term)
                self.lemma_to_word[term] = token
            vector[term] = 1.0
        return vector

    def get_search_query_vector(self) -> dict[str, float]:
        """Вектор запроса {лемма: w_qj}.

        По методичке w_qj = 1, если слово присутствует в запросе, и 0 иначе.
        Термины, добавленные системой (синонимы, исправления опечаток), входят
        с пониженным весом, чтобы не перебивать то, что пользователь ввёл сам.
        """
        vector = self._collect_user_lemmas()

        self.expanded_lemmas = []
        extra_weight = (
            config.EXPANDED_TERM_WEIGHT
            if self.expanded_weight is None
            else self.expanded_weight
        )
        for source_lemma, extras in self.expansions.items():
            for extra in extras:
                if extra in vector:
                    continue
                vector[extra] = extra_weight
                self.expanded_lemmas.append(extra)
                self.lemma_to_word.setdefault(extra, extra)

        if self.rocchio_vector:
            # Вектор обратной связи заменяет ПОЗ целиком, но user_lemmas и
            # lemma_to_word уже заполнены выше и не теряются.
            self.feedback_lemmas = [
                term
                for term, weight in self.rocchio_vector.items()
                if weight > 0 and term not in vector
            ]
            self.query_lemmas = [
                term for term, weight in self.rocchio_vector.items() if weight > 0
            ]
            return dict(self.rocchio_vector)

        self.feedback_lemmas = []
        self.query_lemmas = list(vector)
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

    def _tf_norms(self) -> dict[int, float]:
        """Нормы векторов документов для режима B_i = 1 (джокер `idf-flat`).

        В индексе хранится норма вектора весов A_ij; если вес термина сводится
        к частоте Q_ij, норму приходится пересчитывать. Один агрегат по всему
        индексу — на коллекции лабораторной это доли секунды.
        """
        return {
            row["doc_id"]: math.sqrt(row["sq"])
            for row in self.conn.execute(
                "SELECT doc_id, SUM(tf * tf) AS sq FROM postings GROUP BY doc_id"
            )
            if row["sq"]
        }

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
            f"""SELECT p.doc_id AS doc_id, t.lemma AS lemma,
                       p.weight AS weight, p.tf AS tf
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
            doc_weight = float(row["tf"]) if self.flat_idf else row["weight"]
            if self.square_weights:
                doc_weight *= doc_weight
            contribution = doc_weight * query_vector[row["lemma"]]
            products[doc_id] = products.get(doc_id, 0.0) + contribution
            matched.setdefault(doc_id, {})[row["lemma"]] = contribution

        # фильтр «все слова вместе» — по словам, которые ввёл пользователь,
        # а не по всему вектору: после Рокчио в нём до сорока терминов, и
        # требование содержать их все обнуляло бы любую выдачу
        required = set(self.user_lemmas) if self.all_words_together else set()

        norm_q = self.euclidean_norm(query_vector)
        start_key, end_key = _date_key(self.date_start_string), _date_key(self.date_end_string)

        doc_ids = list(products)
        docs: dict[int, sqlite3.Row] = {}
        for chunk_start in range(0, len(doc_ids), 500):
            chunk = doc_ids[chunk_start : chunk_start + 500]
            chunk_placeholders = ",".join("?" * len(chunk))
            for row in self.conn.execute(
                f"""SELECT id, title, uri, path, host, date_added, vector_norm,
                           term_count, text
                    FROM documents WHERE id IN ({chunk_placeholders})""",
                chunk,
            ):
                docs[row["id"]] = row

        tf_norms = self._tf_norms() if self.flat_idf else {}

        def norm_of(doc_id: int, row: sqlite3.Row) -> float:
            """Норма ||D||, соответствующая выбранной схеме взвешивания."""
            return tf_norms.get(doc_id, 0.0) if self.flat_idf else row["vector_norm"]

        # Стоп-слова в индекс не попадают вовсе: analyze_text отбрасывает их
        # ещё на этапе построения ПОД. Поэтому их вклад в скалярное
        # произведение считается прямо по тексту документа-кандидата. Норма
        # ||D|| при этом остаётся индексной, то есть заниженной, — и длинные
        # документы, набитые служебными словами, всплывают наверх. Абсурдный
        # эффект здесь и задуман: механика показывает, зачем стоп-слова вообще
        # выбрасывают из поискового образа.
        if self.kept_stopwords:
            wanted = {
                token: (lemma(token) if self.use_lemmas else token)
                for token in self.kept_stopwords
            }
            for doc_id, row in docs.items():
                tokens = Counter(tokenize(row["text"]))
                for token, term in wanted.items():
                    weight = query_vector.get(term, 0.0)
                    hits = tokens.get(token, 0)
                    if not weight or not hits:
                        continue
                    contribution = hits * weight
                    products[doc_id] = products.get(doc_id, 0.0) + contribution
                    matched.setdefault(doc_id, {})[term] = contribution

        ranked: list[tuple[float, int]] = []
        for doc_id, product in products.items():
            row = docs.get(doc_id)
            if row is None:
                continue
            norm_d = norm_of(doc_id, row)
            if not norm_d:
                continue
            if required and not required.issubset(matched.get(doc_id, {}).keys()):
                continue
            if self.banned_host and row["host"] == self.banned_host:
                continue
            if start_key or end_key:
                key = _date_key(row["date_added"])
                if start_key and key < start_key:
                    continue
                if end_key and key > end_key:
                    continue
            rank = product / (norm_d * norm_q) if norm_q else 0.0
            if self.short_doc_bonus:
                rank /= math.log10(max(row["term_count"], 10))
            if rank > self.min_rank:
                ranked.append((rank, doc_id))

        if self.alphabetical:
            # «настроение» паука: порядок по заголовку вместо косинуса.
            # Ранги при этом не подделываются — они остаются настоящими.
            ranked.sort(key=lambda item: (docs[item[1]]["title"].lower(), item[1]))
        else:
            ranked.sort(key=lambda item: (-item[0], item[1]))
        self.total_found = len(ranked)

        results: list[SearchResult] = []
        query_lemma_set = set(query_vector)
        # подсвечиваем и показываем только то, что пользователь ввёл сам,
        # плюс добавленное системой расширение — но не весь вектор Рокчио
        own_lemmas = set(self.user_lemmas) | set(self.expanded_lemmas)
        for rank, doc_id in ranked[: self.limit]:
            row = docs[doc_id]
            norm_d = norm_of(doc_id, row)
            contributions = matched.get(doc_id, {})
            ordered = sorted(contributions, key=lambda item: -contributions[item])
            words = [
                self.lemma_to_word.get(term, term)
                for term in ordered
                if term in own_lemmas
            ]
            feedback_words = [term for term in ordered if term not in own_lemmas]
            fragment = snippets.make_snippet(row["text"], query_lemma_set)
            snippet = snippets.highlight(fragment, query_lemma_set)
            if self.snippet_noise:
                snippet = snippets.slur(snippet, self.snippet_noise)
            results.append(
                SearchResult(
                    document_id=doc_id,
                    title=row["title"],
                    snippet=snippet,
                    rank=round(rank, 6),
                    date=row["date_added"],
                    matched_words=words,
                    feedback_words=feedback_words,
                    uri=row["uri"],
                    path=row["path"],
                    host=row["host"],
                    explanation=[
                        (term, round(value / (norm_d * norm_q), 6))
                        for term, value in sorted(
                            contributions.items(), key=lambda item: -item[1]
                        )[:5]
                    ],
                )
            )

        self.took_ms = (time.perf_counter() - started) * 1000
        return results
