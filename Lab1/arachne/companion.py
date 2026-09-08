"""Паук-компаньон Пафнутий и достижения — необязательная «живая» часть интерфейса.

Отключается флагом ARACHNE_COMPANION=0 в .env, на работу поиска не влияет.
"""

from __future__ import annotations

import random
import sqlite3
from datetime import datetime

from . import config, db

# --- Реплики ----------------------------------------------------------------

LINES: dict[str, list[str]] = {
    "welcome": [
        "Паутина натянута, жду запрос.",
        "Восемь лап, один индекс. Спрашивайте.",
        "Сижу в углу, наблюдаю за документами.",
    ],
    "results": [
        "Поймал в сеть кое-что подходящее.",
        "Держите улов — сверху самое релевантное.",
        "Косинус посчитан, документы разложены.",
    ],
    "few_results": [
        "Улов скромный. Попробуйте слово попроще.",
        "Мало ниток в этой паутине. Расширим запрос?",
    ],
    "empty": [
        "Пусто. Даже мухи не пролетали.",
        "Ничего не нашлось — может, опечатка?",
        "Такого слова в моей паутине нет.",
    ],
    "typo": [
        "Похоже, палец соскользнул. Я поправил.",
        "Восемь глаз заметили опечатку.",
    ],
    "long_query": [
        "Внушительный запрос. Разберу по словам.",
        "Целое предложение! Люблю такие.",
    ],
    "short_query": [
        "Одно слово — широкий улов.",
        "Кратко. Уточните, если найдётся лишнее.",
    ],
    "repeat": [
        "Этот запрос уже был. Ничего не изменилось.",
        "Дежавю: спрашивали недавно.",
    ],
    "night": [
        "Полночь — лучшее время для плетения индекса.",
        "Ночная смена? Я тоже не сплю.",
    ],
    "crawl": [
        "Обошёл узлы, притащил документы.",
        "Лапы в пыли: сеть большая.",
    ],
    "index": [
        "Паутина сплетена заново, веса пересчитаны.",
        "Индекс готов — можно ловить.",
    ],
    "metrics": [
        "Проверяем, хорошо ли я ловлю? Справедливо.",
        "Метрики — это как взвешивание улова.",
    ],
    "document": [
        "Хороший документ. Я его помню.",
        "Этот попался в сеть одним из первых.",
    ],
    "food": [
        "Запросы о еде вызывают у меня аппетит. К мухам.",
    ],
    "sport": [
        "Спорт? Я сегодня уже пробежал по всей паутине.",
    ],
}


def line(event: str, seed: str = "") -> str:
    """Реплика на событие; при одинаковом seed фраза не скачет при перерисовке."""
    variants = LINES.get(event) or LINES["welcome"]
    if seed:
        return variants[hash((event, seed)) % len(variants)]
    return random.choice(variants)


def react_to_search(query: str, found: int, corrected: bool, repeated: bool) -> str:
    """Комментарий к поисковому запросу пользователя."""
    words = query.split()
    hour = datetime.now().hour
    if found == 0:
        event = "empty"
    elif corrected:
        event = "typo"
    elif repeated:
        event = "repeat"
    elif any(word in query.lower() for word in ("борщ", "рецепт", "блин", "суп", "кофе")):
        event = "food"
    elif any(word in query.lower() for word in ("бег", "спорт", "шахмат", "футбол", "трениров")):
        event = "sport"
    elif 0 <= hour < 5:
        event = "night"
    elif found <= 2:
        event = "few_results"
    elif len(words) >= 6:
        event = "long_query"
    elif len(words) == 1:
        event = "short_query"
    else:
        event = "results"
    return line(event, seed=query)


# --- Достижения -------------------------------------------------------------

ACHIEVEMENTS: dict[str, dict] = {
    "first-web": {
        "title": "Первая паутина",
        "description": "В индексе появились первые документы",
        "icon": "🕸️",
    },
    "big-web": {
        "title": "Большая паутина",
        "description": "Проиндексировано не менее 50 документов",
        "icon": "🏗️",
    },
    "archivist": {
        "title": "Архивариус",
        "description": "Задано 25 поисковых запросов",
        "icon": "📚",
    },
    "typo-master": {
        "title": "Опечаточник",
        "description": "Система пять раз исправила опечатку в запросе",
        "icon": "⌨️",
    },
    "explorer": {
        "title": "Исследователь",
        "description": "Открыто 10 документов из выдачи",
        "icon": "🔍",
    },
    "evaluator": {
        "title": "Метролог",
        "description": "Выполнена оценка качества работы системы",
        "icon": "📊",
    },
    "sniper": {
        "title": "Снайпер",
        "description": "По одному из запросов точность P@5 достигла 1,0",
        "icon": "🎯",
    },
    "night-owl": {
        "title": "Полуночник",
        "description": "Поиск между полуночью и пятью утра",
        "icon": "🌙",
    },
    "gourmet": {
        "title": "Гурман",
        "description": "Нашли рецепт вместо технической документации",
        "icon": "🍲",
    },
}


def unlock(conn: sqlite3.Connection, code: str) -> bool:
    """Открывает достижение. True — если оно открыто впервые."""
    if code not in ACHIEVEMENTS:
        return False
    existing = conn.execute(
        "SELECT 1 FROM achievements WHERE code = ?", (code,)
    ).fetchone()
    if existing:
        return False
    conn.execute(
        "INSERT INTO achievements(code, unlocked_at) VALUES(?, ?)",
        (code, datetime.now().strftime("%d.%m.%Y %H:%M:%S")),
    )
    conn.commit()
    return True


def bump(conn: sqlite3.Connection, counter: str, amount: int = 1) -> int:
    """Увеличивает счётчик в таблице настроек и возвращает новое значение."""
    key = f"counter:{counter}"
    value = int(db.get_setting(conn, key, "0") or 0) + amount
    db.set_setting(conn, key, str(value))
    return value


def unlocked(conn: sqlite3.Connection) -> list[dict]:
    """Список достижений с отметкой, какие уже открыты."""
    opened = {
        row["code"]: row["unlocked_at"]
        for row in conn.execute("SELECT code, unlocked_at FROM achievements")
    }
    return [
        {
            "code": code,
            "opened": code in opened,
            "at": opened.get(code, ""),
            **data,
        }
        for code, data in ACHIEVEMENTS.items()
    ]


def check_after_search(
    conn: sqlite3.Connection, query: str, found: int, corrected: bool
) -> list[dict]:
    """Проверяет достижения, связанные с поиском. Возвращает новые."""
    if not config.COMPANION_ENABLED:
        return []
    new_codes: list[str] = []

    queries = bump(conn, "queries")
    if queries >= 25 and unlock(conn, "archivist"):
        new_codes.append("archivist")
    if corrected:
        typos = bump(conn, "typos")
        if typos >= 5 and unlock(conn, "typo-master"):
            new_codes.append("typo-master")
    if 0 <= datetime.now().hour < 5 and unlock(conn, "night-owl"):
        new_codes.append("night-owl")
    if found and any(
        word in query.lower() for word in ("борщ", "рецепт", "блин", "суп", "паста")
    ) and unlock(conn, "gourmet"):
        new_codes.append("gourmet")

    return [{"code": code, **ACHIEVEMENTS[code]} for code in new_codes]


def check_after_index(conn: sqlite3.Connection, documents: int) -> list[dict]:
    if not config.COMPANION_ENABLED:
        return []
    new_codes = []
    if documents > 0 and unlock(conn, "first-web"):
        new_codes.append("first-web")
    if documents >= 50 and unlock(conn, "big-web"):
        new_codes.append("big-web")
    return [{"code": code, **ACHIEVEMENTS[code]} for code in new_codes]


def check_after_evaluation(conn: sqlite3.Connection, per_query: list[dict]) -> list[dict]:
    if not config.COMPANION_ENABLED:
        return []
    new_codes = []
    if unlock(conn, "evaluator"):
        new_codes.append("evaluator")
    if any(item.get("p@5", 0) >= 1.0 for item in per_query) and unlock(conn, "sniper"):
        new_codes.append("sniper")
    return [{"code": code, **ACHIEVEMENTS[code]} for code in new_codes]


def check_after_open_document(conn: sqlite3.Connection) -> list[dict]:
    if not config.COMPANION_ENABLED:
        return []
    if bump(conn, "opened") >= 10 and unlock(conn, "explorer"):
        return [{"code": "explorer", **ACHIEVEMENTS["explorer"]}]
    return []
