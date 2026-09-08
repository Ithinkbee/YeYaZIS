"""Прогон эталонных запросов и расчёт метрик качества.

Здесь же собран эксперимент по сравнению конфигураций системы — материал для
раздела отчёта «анализ полученных данных и предложения по улучшению СИП».
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..ai import suggest
from ..indexer import build_index
from ..search import Search
from . import metrics, qrels


@dataclass
class RunConfig:
    """Настройки прогона поиска при оценке качества."""

    name: str = "Базовая конфигурация"
    use_lemmas: bool = True
    use_synonyms: bool = False
    all_words_together: bool = False
    top_k: int = 20
    description: str = ""


def run_query(conn: sqlite3.Connection, query_text: str, run: RunConfig) -> list[int]:
    """Возвращает ранжированный список id документов для одного запроса."""
    expansions = {}
    if run.use_synonyms:
        analysis = suggest.analyze(conn, query_text)
        expansions = suggest.expansion_lemmas(analysis, use_synonyms=True)

    search = Search(
        conn=conn,
        search_query=query_text,
        all_words_together=run.all_words_together,
        expansions=expansions,
        use_lemmas=run.use_lemmas,
        limit=run.top_k,
    )
    return [result.document_id for result in search.get_search_result()]


def evaluate(conn: sqlite3.Connection, run: RunConfig | None = None) -> dict:
    """Оценивает качество поиска по всем эталонным запросам."""
    run = run or RunConfig()
    queries = qrels.list_queries(conn)
    if not queries:
        return {"error": "эталонные запросы не заданы", "per_query": [], "summary": {}}

    per_query = []
    for row in queries:
        rel = qrels.rel_map(conn, row["id"])
        ranked = run_query(conn, row["text"], run)
        result = metrics.evaluate_query(ranked, rel)
        result["query_id"] = row["id"]
        result["query"] = row["text"]
        result["note"] = row["note"]
        per_query.append(result)

    return {
        "config": run,
        "per_query": per_query,
        "summary": metrics.macro_average(per_query),
    }


def compare_configurations(conn: sqlite3.Connection, top_k: int = 20) -> list[dict]:
    """Сравнивает несколько конфигураций системы на одном эталонном наборе.

    Конфигурация без лемматизации требует перестройки индекса, поэтому в конце
    индекс возвращается в обычное (лемматизированное) состояние.
    """
    configurations = [
        RunConfig(
            name="Базовая: леммы, бинарный ПОЗ",
            description="морфологический анализ включён, запрос без расширения",
            top_k=top_k,
        ),
        RunConfig(
            name="С расширением синонимами",
            use_synonyms=True,
            description="в ПОЗ добавлены синонимы из тезауруса с весом 0,5",
            top_k=top_k,
        ),
        RunConfig(
            name="Строгий режим (все слова)",
            all_words_together=True,
            description="документ обязан содержать все слова запроса",
            top_k=top_k,
        ),
        RunConfig(
            name="Без морфологии (словоформы)",
            use_lemmas=False,
            description="индекс построен по словоформам, лемматизация отключена",
            top_k=top_k,
        ),
    ]

    results = []
    for run in configurations:
        if not run.use_lemmas:
            build_index(conn, use_lemmas=False)
        outcome = evaluate(conn, run)
        results.append(
            {
                "name": run.name,
                "description": run.description,
                "summary": outcome["summary"],
            }
        )
        if not run.use_lemmas:
            build_index(conn, use_lemmas=True)

    return results
