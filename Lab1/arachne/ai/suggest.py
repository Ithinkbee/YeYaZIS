"""«Понимание» естественно-языкового запроса — интеллектуальная часть интерфейса.

Здесь собраны механизмы, которые помогают пользователю сформулировать запрос:
морфологический разбор, автодополнение по словарю системы, исправление опечаток
методом редакционного расстояния и расширение запроса синонимами из тезауруса.
"""

from __future__ import annotations

import json
import sqlite3
from functools import lru_cache

from .. import config
from ..models import QueryAnalysis
from ..text.morphology import (
    is_significant,
    is_stopword,
    lemma,
    parse_word,
    tokenize,
)


# --- Тезаурус ---------------------------------------------------------------

@lru_cache(maxsize=1)
def _thesaurus() -> dict[str, list[str]]:
    """Отображение «термин -> синонимы» из data/synonyms_ru.json."""
    path = config.SYNONYMS_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    mapping: dict[str, list[str]] = {}
    for group in data.get("groups", []):
        normalized = []
        for phrase in group:
            for word in phrase.split():
                normalized.append(lemma(word.lower().replace("ё", "е")))
        for word in normalized:
            others = [other for other in normalized if other != word]
            if others:
                mapping.setdefault(word, [])
                for other in others:
                    if other not in mapping[word]:
                        mapping[word].append(other)
    return mapping


def synonyms_for(lemmas: list[str], known: set[str]) -> dict[str, list[str]]:
    """Синонимы, которые реально присутствуют в словаре системы."""
    result: dict[str, list[str]] = {}
    thesaurus = _thesaurus()
    for word in lemmas:
        candidates = [
            synonym for synonym in thesaurus.get(word, [])
            if synonym in known and synonym not in lemmas
        ]
        if candidates:
            result[word] = candidates
    return result


# --- Словарь системы --------------------------------------------------------

def known_lemmas(conn: sqlite3.Connection) -> set[str]:
    return {row["lemma"] for row in conn.execute("SELECT lemma FROM terms")}


def vocabulary(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """Словоформы словаря с частотами — основа автодополнения и опечаток."""
    return [
        (row["form"], row["freq"])
        for row in conn.execute(
            "SELECT form, SUM(freq) AS freq FROM forms GROUP BY form ORDER BY freq DESC"
        )
    ]


# --- Автодополнение ---------------------------------------------------------

def autocomplete(conn: sqlite3.Connection, prefix: str, limit: int = 8) -> list[str]:
    """Продолжения для последнего слова запроса.

    Сначала предлагаются ранее задававшиеся запросы, затем словоформы из
    индекса, отсортированные по частоте.
    """
    prefix = (prefix or "").strip().lower().replace("ё", "е")
    if len(prefix) < 2:
        return []

    suggestions: list[str] = []
    head, _, tail = prefix.rpartition(" ")

    for row in conn.execute(
        """SELECT raw_query, COUNT(*) AS hits FROM query_log
           WHERE lower(raw_query) LIKE ? GROUP BY lower(raw_query)
           ORDER BY hits DESC, MAX(id) DESC LIMIT ?""",
        (prefix + "%", limit),
    ):
        candidate = row["raw_query"].strip()
        if candidate.lower() != prefix and candidate not in suggestions:
            suggestions.append(candidate)

    if tail:
        for row in conn.execute(
            """SELECT form, SUM(freq) AS freq FROM forms
               WHERE form LIKE ? GROUP BY form ORDER BY freq DESC LIMIT ?""",
            (tail + "%", limit * 2),
        ):
            candidate = (head + " " + row["form"]).strip() if head else row["form"]
            if candidate.lower() != prefix and candidate not in suggestions:
                suggestions.append(candidate)

    return suggestions[:limit]


# --- Исправление опечаток ---------------------------------------------------

def damerau_levenshtein(a: str, b: str, max_distance: int = 2) -> int:
    """Редакционное расстояние с перестановками соседних символов.

    Возвращает max_distance + 1, если расстояние заведомо больше порога.
    """
    if abs(len(a) - len(b)) > max_distance:
        return max_distance + 1
    previous_previous: list[int] = []
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, 1):
        current = [i] + [0] * len(b)
        best_in_row = current[0]
        for j, char_b in enumerate(b, 1):
            cost = 0 if char_a == char_b else 1
            value = min(
                previous[j] + 1,        # удаление
                current[j - 1] + 1,     # вставка
                previous[j - 1] + cost, # замена
            )
            if (
                i > 1 and j > 1
                and char_a == b[j - 2] and a[i - 2] == char_b
            ):
                value = min(value, previous_previous[j - 2] + 1)  # перестановка
            current[j] = value
            best_in_row = min(best_in_row, value)
        if best_in_row > max_distance:
            return max_distance + 1
        previous_previous, previous = previous, current
    return previous[-1]


def correct_word(word: str, vocab: list[tuple[str, int]]) -> str | None:
    """Ближайшее слово словаря для слова, которого в индексе нет."""
    if len(word) < 4:
        return None
    threshold = 1 if len(word) <= 5 else 2
    best: tuple[int, int, str] | None = None
    for form, freq in vocab:
        if abs(len(form) - len(word)) > threshold:
            continue
        # в коротких словах первая буква обычно набирается верно — быстрый отсев
        if len(word) <= 5 and form[:1] != word[:1]:
            continue
        distance = damerau_levenshtein(word, form, threshold)
        if distance > threshold:
            continue
        candidate = (distance, -freq, form)
        if best is None or candidate < best:
            best = candidate
    return best[2] if best else None


def corrections_for(conn: sqlite3.Connection, words: list[str]) -> dict[str, str]:
    """Исправления для слов запроса, отсутствующих в словаре системы."""
    unknown = []
    for word in words:
        row = conn.execute(
            "SELECT 1 FROM forms WHERE form = ? LIMIT 1", (word,)
        ).fetchone()
        if row is None and conn.execute(
            "SELECT 1 FROM terms WHERE lemma = ? LIMIT 1", (lemma(word),)
        ).fetchone() is None:
            unknown.append(word)
    if not unknown:
        return {}

    vocab = vocabulary(conn)
    result: dict[str, str] = {}
    for word in unknown:
        suggestion = correct_word(word, vocab)
        if suggestion and suggestion != word:
            result[word] = suggestion
    return result


# --- Полный разбор запроса --------------------------------------------------

def analyze(conn: sqlite3.Connection, query: str) -> QueryAnalysis:
    """Показывает пользователю, как система поняла его запрос."""
    analysis = QueryAnalysis(raw=query)
    tokens = tokenize(query)
    analysis.tokens = tokens

    known = known_lemmas(conn)
    for token in tokens:
        if is_stopword(token):
            analysis.stopwords.append(token)
            continue
        if not is_significant(token):
            continue
        info = parse_word(token)
        norm = info["lemma"]
        in_index = norm in known
        analysis.morphology.append(
            {
                "word": token,
                "lemma": norm,
                "pos": info["pos_ru"],
                "in_index": in_index,
            }
        )
        if norm not in analysis.lemmas:
            analysis.lemmas.append(norm)
        if not in_index:
            analysis.unknown.append(token)

    analysis.corrections = corrections_for(conn, analysis.unknown)
    analysis.synonyms = synonyms_for(analysis.lemmas, known)
    return analysis


def corrected_query(query: str, corrections: dict[str, str]) -> str:
    """Собирает исправленный вариант запроса для ссылки «искать вместо этого»."""
    if not corrections:
        return query
    result = query
    for wrong, right in corrections.items():
        result = result.replace(wrong, right)
    return result


def expansion_lemmas(analysis: QueryAnalysis, use_synonyms: bool) -> dict[str, list[str]]:
    """Дополнительные термины ПОЗ: синонимы и леммы исправленных слов."""
    expansions: dict[str, list[str]] = {}
    if use_synonyms:
        for source, extras in analysis.synonyms.items():
            expansions.setdefault(source, []).extend(extras)
    for wrong, right in analysis.corrections.items():
        expansions.setdefault(lemma(wrong), []).append(lemma(right))
    return expansions


# --- История запросов -------------------------------------------------------

def log_query(
    conn: sqlite3.Connection, raw: str, normalized: str, count: int, took_ms: float
) -> None:
    from datetime import datetime

    conn.execute(
        "INSERT INTO query_log(raw_query, normalized, ts, results_count, took_ms) "
        "VALUES(?,?,?,?,?)",
        (raw, normalized, datetime.now().strftime("%d.%m.%Y %H:%M:%S"), count, took_ms),
    )
    conn.commit()


def popular_queries(conn: sqlite3.Connection, limit: int = 8) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT raw_query, COUNT(*) AS hits, MAX(results_count) AS found
           FROM query_log WHERE results_count > 0
           GROUP BY lower(raw_query) ORDER BY hits DESC, MAX(id) DESC LIMIT ?""",
        (limit,),
    ).fetchall()


def recent_queries(conn: sqlite3.Connection, limit: int = 10) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT raw_query, ts, results_count FROM query_log ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
