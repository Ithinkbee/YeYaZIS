"""Издевательства над интерфейсом: настроение, пагинация, проклятия, усталость.

Всё, что здесь есть, живёт исключительно в пользовательской выдаче /search и
снимается либо покупкой в лавке, либо флагом ARACHNE_CRUELTY=0, либо общим
рубильником ARACHNE_COMPANION=0. В evaluation/runner.evaluate() ни одна из
этих функций не вызывается — метрики считаются по чистой конфигурации.
"""

from __future__ import annotations

import json
import random
import sqlite3
from datetime import datetime, timedelta
from functools import lru_cache

from . import config, db, economy
from .ai.suggest import thesaurus
from .text.morphology import is_significant, lemma, tokenize

#: сколько запросов без единого открытого документа доводят паука до обиды
SULK_AFTER = 15

#: вероятность подсунуть на второй странице перемешанную первую
PAGE_BETRAYAL_CHANCE = 0.25

#: после какого запроса подряд индекс начинает «пьянеть»
DRUNK_AFTER = 20

#: вероятность перестановки соседних букв в сниппете
DRUNK_NOISE = 0.04

#: пауза, которая сбрасывает счётчик запросов подряд
STREAK_PAUSE = timedelta(minutes=10)

_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def cruelty_enabled() -> bool:
    return config.COMPANION_ENABLED and config.CRUELTY_ENABLED


def _now() -> datetime:
    return datetime.now()


def _read_time(conn: sqlite3.Connection, key: str) -> datetime | None:
    raw = db.get_setting(conn, key, "")
    if not raw:
        return None
    try:
        return datetime.strptime(raw, _TIME_FORMAT)
    except ValueError:
        return None


# --- №25. Ранжирование по настроению ----------------------------------------

def note_search(conn: sqlite3.Connection) -> None:
    """Запрос задан — счётчик «сколько ищу, ничего не открывая» подрос."""
    value = int(db.get_setting(conn, "counter:since_open", "0") or 0) + 1
    db.set_setting(conn, "counter:since_open", str(value))


def note_document_open(conn: sqlite3.Connection) -> None:
    """Документ открыт — паук успокоился."""
    db.set_setting(conn, "counter:since_open", "0")


def mood(conn: sqlite3.Connection) -> str:
    """Настроение паука: 'sulking' — обижен, 'normal' — в порядке."""
    if not cruelty_enabled() or economy.owns(conn, "calm-ranking"):
        return "normal"
    since = int(db.get_setting(conn, "counter:since_open", "0") or 0)
    return "sulking" if since >= SULK_AFTER else "normal"


# --- №28. Пагинация-предатель -----------------------------------------------

def betrays_page(conn: sqlite3.Connection, page: int) -> bool:
    """Подменить ли запрошенную страницу перемешанной первой.

    Зерно берётся от текущей минуты: обновление страницы в пределах минуты
    даёт тот же результат, и человек начинает сомневаться в себе, а не в
    системе. Ровно в этом и шутка.
    """
    if not cruelty_enabled() or page < 2 or economy.owns(conn, "fix-pagination"):
        return False
    seed = int(_now().timestamp() // 60)
    return random.Random(seed).random() < PAGE_BETRAYAL_CHANCE


def shuffled_first_page(results: list, per_page: int) -> list:
    """Первая страница выдачи в перемешанном порядке."""
    page = list(results[:per_page])
    random.Random(int(_now().timestamp() // 60)).shuffle(page)
    return page


# --- №23. Пьяный индекс -----------------------------------------------------

def bump_streak(conn: sqlite3.Connection) -> int:
    """Счётчик запросов подряд; пауза дольше десяти минут его обнуляет."""
    now = _now()
    previous = _read_time(conn, "streak:last")
    count = int(db.get_setting(conn, "streak:count", "0") or 0)
    count = count + 1 if previous and now - previous < STREAK_PAUSE else 1
    db.set_setting(conn, "streak:count", str(count))
    db.set_setting(conn, "streak:last", now.strftime(_TIME_FORMAT))
    return count


def snippet_noise(conn: sqlite3.Connection, streak: int) -> float:
    """Насколько сильно пляшут буквы в сниппетах."""
    if not cruelty_enabled() or economy.owns(conn, "sober-index"):
        return 0.0
    return DRUNK_NOISE if streak > DRUNK_AFTER else 0.0


# --- №18. Проклятый запрос --------------------------------------------------

def _curse_candidates(query: str) -> list[tuple[str, str]]:
    """Пары (словоформа, синоним-подмена) для слов запроса."""
    synonyms = thesaurus()
    pairs = []
    for token in tokenize(query):
        if not is_significant(token):
            continue
        variants = synonyms.get(lemma(token), [])
        if variants:
            pairs.append((token, random.choice(variants)))
    return pairs


def maybe_curse(conn: sqlite3.Connection, query: str) -> tuple[str, dict]:
    """С вероятностью ARACHNE_CURSE_CHANCE молча подменяет одну лемму синонимом.

    Возвращает (текст запроса для поиска, описание подмены). Описание пустое,
    если проклятия не случилось.
    """
    db.set_setting(conn, "curse:active", "")
    if not cruelty_enabled() or economy.owns(conn, "no-curse"):
        return query, {}
    if random.random() >= config.CURSE_CHANCE:
        return query, {}

    candidates = _curse_candidates(query)
    if not candidates:
        return query, {}

    word, replacement = random.choice(candidates)
    cursed = query.replace(word, replacement, 1)
    state = {"original": query, "cursed": cursed, "word": word, "replacement": replacement}
    db.set_setting(conn, "curse:active", json.dumps(state, ensure_ascii=False))
    return cursed, state


def active_curse(conn: sqlite3.Connection) -> dict:
    raw = db.get_setting(conn, "curse:active", "")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def lift_curse(conn: sqlite3.Connection) -> dict:
    """«Снять проклятие»: угадал — награда, не угадал — плата за подозрительность."""
    state = active_curse(conn)
    db.set_setting(conn, "curse:active", "")
    if state:
        earned = economy.earn(conn, 80, "curse:lifted")
        return {
            "found": True,
            "amount": earned,
            "query": state.get("original", ""),
            "message": (
                f"Проклятие снято: «{state['word']}» было подменено на "
                f"«{state['replacement']}». +{earned} сл."
            ),
        }
    economy.spend(conn, 20, "curse:paranoia")
    return {
        "found": False,
        "amount": -20,
        "query": "",
        "message": "Проклятия не было. За подозрительность — 20 сл.",
    }


# --- №36. Скидка за грубость ------------------------------------------------

@lru_cache(maxsize=1)
def _rude_words() -> set[str]:
    """Короткий список из data/rude_words.txt. Сами слова в интерфейс не попадают."""
    path = config.RUDE_WORDS_PATH
    if not path.exists():
        return set()
    return {
        line.strip().lower()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


def is_rude(query: str) -> bool:
    words = _rude_words()
    if not words:
        return False
    return any(lemma(token) in words or token in words for token in tokenize(query))


def react_to_rudeness(conn: sqlite3.Connection, query: str) -> bool:
    """Выдаёт купон −10%, но не чаще раза в сутки. True — паук оскорбился."""
    if not config.COMPANION_ENABLED or not is_rude(query):
        return False
    today = _now().strftime("%d.%m.%Y")
    if db.get_setting(conn, "rude:last_day", "") == today:
        return True  # оскорбиться можно снова, а купон — раз в сутки
    db.set_setting(conn, "rude:last_day", today)
    economy.record_purchase(conn, "coupon", today)
    return True
