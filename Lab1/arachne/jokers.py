"""Джокеры — временные модификаторы поискового запроса (механика №15).

Каждый джокер меняет ровно один параметр векторной модели: вес расширений,
схему взвешивания, набор допустимых терминов. Поэтому все шесть реализованы
как поля датакласса Search, а не как правки внутри его методов, — и те же
самые коды можно скормить сравнению конфигураций на /metrics/compare, получив
таблицу «влияние параметров модели на MAP» без отдельного кода.

По умолчанию в оценке качества не активен ни один джокер: метрики считаются
по чистой конфигурации.
"""

from __future__ import annotations

import json
import random
import sqlite3

from . import config, db, economy

DECK: dict[str, dict] = {
    "no-stop": {
        "title": "Ничего лишнего",
        "effect": "стоп-слова остаются в поисковом образе запроса",
        "note": "служебные слова входят в ПОЗ с весом 1,0",
        "price": 120,
    },
    "sq-weights": {
        "title": "Квадратура веса",
        "effect": "вес термина в документе возводится в квадрат",
        "note": "усиливает разрыв между частыми и редкими попаданиями",
        "price": 150,
    },
    "ban-node": {
        "title": "Узел в опале",
        "effect": "документы одного узла ЛВС исключаются из выдачи",
        "note": "узел выбирается случайно при взятии джокера",
        "price": 90,
    },
    "syn-x2": {
        "title": "Синонимы в полный голос",
        "effect": "вес расширений поднимается с 0,5 до 1,0",
        "note": "синоним становится равноправным словом запроса",
        "price": 140,
    },
    "idf-flat": {
        "title": "Плоская частота",
        "effect": "B_i = 1 для всех терминов, остаётся чистая частота Q_ij",
        "note": "наглядно показывает, что даёт формула (1.5)",
        "price": 160,
    },
    "short-doc": {
        "title": "Краткость — сестра",
        "effect": "ранг делится на логарифм длины документа",
        "note": "короткие документы поднимаются наверх",
        "price": 110,
    },
}

_OFFER_KEY = "jokers:offer"
_ACTIVE_KEY = "jokers:active"
_FREE_KEY = "jokers:free_taken"


def enabled() -> bool:
    return config.COMPANION_ENABLED and config.ECONOMY_ENABLED


def _read(conn: sqlite3.Connection, key: str, default):
    raw = db.get_setting(conn, key, "")
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _write(conn: sqlite3.Connection, key: str, value) -> None:
    db.set_setting(conn, key, json.dumps(value, ensure_ascii=False))


# --- Колода -----------------------------------------------------------------

def offer(conn: sqlite3.Connection) -> list[dict]:
    """Три случайных джокера, предлагаемых перед поиском."""
    if not enabled():
        return []
    codes = _read(conn, _OFFER_KEY, [])
    if not codes or any(code not in DECK for code in codes):
        codes = random.sample(list(DECK), 3)
        _write(conn, _OFFER_KEY, codes)
        db.set_setting(conn, _FREE_KEY, "0")
    free_taken = db.get_setting(conn, _FREE_KEY, "0") == "1"
    active = active_jokers(conn)
    return [
        {
            "code": code,
            **DECK[code],
            "free": not free_taken,
            "active": code in active,
        }
        for code in codes
    ]


def reshuffle(conn: sqlite3.Connection) -> None:
    """Новая раздача: следующий вызов offer() соберёт другую тройку."""
    db.set_setting(conn, _OFFER_KEY, "")
    db.set_setting(conn, _FREE_KEY, "0")


def active_jokers(conn: sqlite3.Connection) -> dict[str, int]:
    """Активные джокеры: {код: сколько запросов ещё действует}."""
    if not enabled():
        return {}
    state = _read(conn, _ACTIVE_KEY, {})
    return {
        code: int(left)
        for code, left in state.items()
        if code in DECK and int(left) > 0
    }


def active_list(conn: sqlite3.Connection) -> list[dict]:
    return [
        {"code": code, "left": left, **DECK[code]}
        for code, left in active_jokers(conn).items()
    ]


def take(conn: sqlite3.Connection, code: str) -> tuple[bool, str]:
    """Берёт джокер: первый из раздачи бесплатно, остальные за слова."""
    if not enabled() or code not in DECK:
        return False, "такого джокера в колоде нет"
    codes = _read(conn, _OFFER_KEY, [])
    if code not in codes:
        return False, "этот джокер сейчас не предлагается"

    free_taken = db.get_setting(conn, _FREE_KEY, "0") == "1"
    if free_taken:
        cost = DECK[code]["price"]
        if not economy.spend(conn, cost, f"joker:{code}"):
            return False, f"не хватает слов: нужно {cost}"
    else:
        db.set_setting(conn, _FREE_KEY, "1")

    state = active_jokers(conn)
    state[code] = config.JOKER_QUERIES
    _write(conn, _ACTIVE_KEY, state)
    if code == "ban-node":
        _write(conn, "jokers:ban-node:host", _random_host(conn))
    return True, f"джокер «{DECK[code]['title']}» взят на {config.JOKER_QUERIES} запросов"


def _random_host(conn: sqlite3.Connection) -> str:
    rows = conn.execute("SELECT DISTINCT host FROM documents").fetchall()
    return random.choice([row["host"] for row in rows]) if rows else ""


def consume(conn: sqlite3.Connection) -> None:
    """Уменьшает счётчик оставшихся запросов у всех активных джокеров."""
    if not enabled():
        return
    state = {code: left - 1 for code, left in active_jokers(conn).items()}
    state = {code: left for code, left in state.items() if left > 0}
    _write(conn, _ACTIVE_KEY, state)
    if not state:
        reshuffle(conn)


def clear(conn: sqlite3.Connection) -> None:
    _write(conn, _ACTIVE_KEY, {})


# --- Применение к поисковому механизму --------------------------------------

def apply_to(search, codes, conn: sqlite3.Connection | None = None) -> None:
    """Выставляет поля Search по списку кодов джокеров."""
    codes = set(codes or ())
    if "no-stop" in codes:
        search.keep_stopwords = True
    if "sq-weights" in codes:
        search.square_weights = True
    if "syn-x2" in codes:
        search.expanded_weight = 1.0
    if "idf-flat" in codes:
        search.flat_idf = True
    if "short-doc" in codes:
        search.short_doc_bonus = True
    if "ban-node" in codes:
        host = ""
        if conn is not None:
            host = db.get_setting(conn, "jokers:ban-node:host", "") or _random_host(conn)
        search.banned_host = host
