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
    """Настройки прогона поиска при оценке качества.

    Поле `joker` — тот же код модификатора, что и в игровой колоде: джокеры
    это буквально конфигурации векторной модели, поэтому их можно прогнать
    через оценку качества и получить таблицу «влияние параметров модели на
    MAP». По умолчанию пусто: измерения идут по чистой конфигурации, и ни
    одна покупка, отметка или активный джокер пользователя сюда не попадает.
    """

    name: str = "Базовая конфигурация"
    use_lemmas: bool = True
    use_synonyms: bool = False
    all_words_together: bool = False
    top_k: int = 20
    description: str = ""
    joker: str = ""


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
    if run.joker:
        from ..jokers import apply_to

        apply_to(search, [run.joker], conn)
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


def evaluate_single(
    conn: sqlite3.Connection, query_id: int, top_k: int = 20
) -> dict:
    """Метрики одного эталонного запроса по чистой конфигурации.

    Нужно странице разметки: после каждой оценки видно, что именно изменилось
    у этого запроса, — общий MAP на одну оценку сдвигается на тысячные доли и
    глазом не читается.
    """
    row = conn.execute(
        "SELECT id, text FROM eval_queries WHERE id = ?", (query_id,)
    ).fetchone()
    if row is None:
        return {}
    run = RunConfig(top_k=top_k)
    rel = qrels.rel_map(conn, query_id)
    ranked = run_query(conn, row["text"], run)
    result = metrics.evaluate_query(ranked, rel)
    result["query_id"] = query_id
    result["query"] = row["text"]
    return result


def compare_configurations(
    conn: sqlite3.Connection, top_k: int = 20, jokers: bool = False
) -> list[dict]:
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

    if jokers:
        # Те же коды, что и в игровой колоде: каждый меняет ровно один
        # параметр модели, поэтому получается готовая таблица «влияние
        # параметров модели на MAP». Включается только явным выбором на
        # странице сравнения конфигураций.
        from ..jokers import DECK

        configurations += [
            RunConfig(
                name=f"Джокер «{data['title']}»",
                description=data["effect"],
                joker=code,
                top_k=top_k,
            )
            for code, data in DECK.items()
            if code != "ban-node"  # исключение случайного узла не параметр модели
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
