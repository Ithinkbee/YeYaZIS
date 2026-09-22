"""Игровые режимы: слепая выдача, блиц и «мне повезёт».

Все три опираются на то, что в системе уже есть: слепая выдача — на эталонную
разметку, блиц — на индекс и на обычный поиск, «мне повезёт» — на историю
запросов. Собственного ранжирования здесь нет, метрики качества эти режимы не
трогают.
"""

from __future__ import annotations

import json
import random
import re
import sqlite3
from datetime import datetime, timedelta

from . import config, db, economy
from .ai import llm
from .evaluation import qrels
from .search import Search
from .text import snippets

_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# --- Слепая выдача (№13) ----------------------------------------------------

BLIND_OPTIONS = 4
BLIND_REWARD = 50
BLIND_STREAK_STEP = 1.2
BLIND_STREAK_CAP = 3.0

HINTS = {
    "half": {"title": "50/50", "price": 30, "note": "убирает два заведомо неверных"},
    "call": {"title": "Звонок Пафнутию", "price": 60, "note": "паук назовёт решающий термин"},
    "hall": {"title": "Помощь зала", "price": 40, "note": "как голосовали открытия документов"},
}


def enabled() -> bool:
    return config.COMPANION_ENABLED


def _now() -> datetime:
    return datetime.now()


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


def blind_round(conn: sqlite3.Connection) -> dict:
    """Текущий вопрос слепой выдачи; при отсутствии — новый."""
    state = _read(conn, "blind:round", {})
    if state.get("options"):
        return state
    return new_blind_round(conn)


def new_blind_round(conn: sqlite3.Connection) -> dict:
    """Собирает вопрос: четыре сниппета, ровно один из них размечен как rel = 2.

    Режим целиком держится на эталонной разметке — чем больше размечено на
    /qrels, тем больше вопросов. Это и есть его побочная польза.
    """
    candidates = conn.execute(
        """SELECT q.id AS query_id, q.text AS text
           FROM eval_queries q
           WHERE EXISTS (SELECT 1 FROM qrels r
                         WHERE r.query_id = q.id AND r.rel = 2)"""
    ).fetchall()
    if not candidates:
        _write(conn, "blind:round", {})
        return {}

    row = random.choice(candidates)
    judgements = qrels.rel_map(conn, row["query_id"])
    good = [doc_id for doc_id, rel in judgements.items() if rel == 2]
    bad = [doc_id for doc_id, rel in judgements.items() if rel == 0]
    answer = random.choice(good)

    distractors = random.sample(bad, min(BLIND_OPTIONS - 1, len(bad)))
    if len(distractors) < BLIND_OPTIONS - 1:
        # разметки не хватает — добираем документы, не отмеченные релевантными
        extra = conn.execute(
            "SELECT id FROM documents WHERE vector_norm > 0 ORDER BY RANDOM() LIMIT 40"
        ).fetchall()
        for item in extra:
            if len(distractors) >= BLIND_OPTIONS - 1:
                break
            if item["id"] in judgements or item["id"] in distractors:
                continue
            distractors.append(item["id"])

    options = distractors + [answer]
    random.shuffle(options)

    state = {
        "query_id": row["query_id"],
        "query": row["text"],
        "answer": answer,
        "options": options,
        "removed": [],
        "hints": [],
        "hint_text": "",
    }
    _write(conn, "blind:round", state)
    return state


def blind_options(conn: sqlite3.Connection, state: dict) -> list[dict]:
    """Сниппеты вариантов — без заголовков, путей и узлов."""
    result = []
    lemmas: set[str] = set()  # сниппет без подсветки: подсказывать нельзя
    for doc_id in state.get("options", []):
        if doc_id in state.get("removed", []):
            continue
        row = conn.execute(
            "SELECT id, text FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        if row is None:
            continue
        fragment = snippets.make_snippet(row["text"], lemmas, length=260)
        result.append({"doc_id": doc_id, "snippet": fragment})
    return result


def blind_streak(conn: sqlite3.Connection) -> int:
    return int(db.get_setting(conn, "blind:streak", "0") or 0)


def blind_answer(conn: sqlite3.Connection, doc_id: int) -> dict:
    """Проверка ответа. Серия верных ответов умножает награду, но не выше ×3."""
    state = _read(conn, "blind:round", {})
    if not state:
        return {"correct": False, "message": "Вопрос не задан.", "amount": 0}

    correct = doc_id == state.get("answer")
    if correct:
        streak = blind_streak(conn) + 1
        factor = min(BLIND_STREAK_CAP, BLIND_STREAK_STEP ** (streak - 1))
        earned = economy.earn(conn, int(round(BLIND_REWARD * factor)), "blind:win")
        db.set_setting(conn, "blind:streak", str(streak))
        message = f"Верно. Серия {streak}, начислено {earned} сл."
    else:
        db.set_setting(conn, "blind:streak", "0")
        earned = 0
        message = "Мимо. Серия сброшена."

    result = {
        "correct": correct,
        "amount": earned,
        "message": message,
        "query": state.get("query", ""),
        "answer": state.get("answer"),
    }
    new_blind_round(conn)
    return result


def blind_hint(conn: sqlite3.Connection, kind: str) -> dict:
    """Покупка подсказки."""
    state = _read(conn, "blind:round", {})
    if not state or kind not in HINTS:
        return {"ok": False, "message": "Подсказка недоступна."}
    if kind in state.get("hints", []):
        return {"ok": False, "message": "Эта подсказка уже куплена."}
    price = HINTS[kind]["price"]
    if not economy.spend(conn, price, f"blind:hint:{kind}"):
        return {"ok": False, "message": f"Не хватает слов: нужно {price}."}

    state.setdefault("hints", []).append(kind)
    if kind == "half":
        wrong = [item for item in state["options"] if item != state["answer"]]
        random.shuffle(wrong)
        state["removed"] = list(state.get("removed", [])) + wrong[:2]
        state["hint_text"] = "Два варианта убраны."
    elif kind == "call":
        state["hint_text"] = _call_paphnuty(conn, state)
    else:
        state["hint_text"] = _hall_vote(conn, state)
    _write(conn, "blind:round", state)
    return {"ok": True, "message": state["hint_text"]}


def _call_paphnuty(conn: sqlite3.Connection, state: dict) -> str:
    """Подсказка от языковой модели, а без неё — из блока «Почему найден».

    Языковой помощник по умолчанию выключен, поэтому заготовка обязательна:
    иначе механика была бы мертва на любой машине без ключа.
    """
    engine = Search(conn=conn, search_query=state.get("query", ""), limit=50)
    results = engine.get_search_result()
    for result in results:
        if result.document_id == state.get("answer") and result.explanation:
            term, value = result.explanation[0]
            return (
                f"Ищите документ, в котором тяжелее всего весит «{term}» "
                f"(вклад {value:.4f})."
            )
    if llm.available():
        try:
            row = conn.execute(
                "SELECT title, text FROM documents WHERE id = ?", (state["answer"],)
            ).fetchone()
            if row:
                return llm.explain_relevance(
                    state.get("query", ""), row["title"], row["text"][:1200]
                )
        except llm.LLMUnavailable:
            pass
    return "Паук молчит: у верного варианта нет заметного перевеса по терминам."


def _hall_vote(conn: sqlite3.Connection, state: dict) -> str:
    """Распределение «голосов»: чем выше документ в обычной выдаче, тем больше.

    Зал — это сама система: голоса пропорциональны рангу документа по тому же
    запросу. Зал, как и положено, ошибается — верный вариант получает лишь
    небольшую прибавку, а не готовый ответ.
    """
    engine = Search(conn=conn, search_query=state.get("query", ""), limit=200)
    ranks = {item.document_id: item.rank for item in engine.get_search_result()}

    votes = []
    for doc_id in state.get("options", []):
        if doc_id in state.get("removed", []):
            continue
        weight = 100 * ranks.get(doc_id, 0.0)
        if doc_id == state.get("answer"):
            weight += 12
        votes.append(max(1.0, weight + random.uniform(0, 8)))

    total = sum(votes) or 1.0
    parts = [
        f"вариант {index}: {round(100 * value / total)}%"
        for index, value in enumerate(votes, 1)
    ]
    return "Зал разделился — " + ", ".join(parts)


# --- Блиц (№17) -------------------------------------------------------------

BLITZ_SECONDS = 30
BLITZ_TICK_COST = 2
BLITZ_REWARD = 100
BLITZ_COMBO_STEP = 1.2

_SENTENCE_RE = re.compile(r"[^.!?…]+[.!?…]")


def _middle_sentences(text: str, count: int = 2) -> str:
    """Два предложения из середины текста — чтобы не совпало со сниппетом."""
    clean = re.sub(r"\s+", " ", text or "").strip()
    sentences = [s.strip() for s in _SENTENCE_RE.findall(clean) if len(s.strip()) > 40]
    if len(sentences) < count:
        return clean[config.SNIPPET_LENGTH : config.SNIPPET_LENGTH + 320] or clean[:320]
    start = max(0, len(sentences) // 2 - count // 2)
    return " ".join(sentences[start : start + count])


def blitz_round(conn: sqlite3.Connection, restart: bool = False) -> dict:
    """Текущий или новый раунд блица."""
    state = _read(conn, "blitz:round", {})
    if state and not restart and not blitz_expired(state):
        return state

    row = conn.execute(
        "SELECT id, text FROM documents WHERE vector_norm > 0 ORDER BY RANDOM() LIMIT 1"
    ).fetchone()
    if row is None:
        _write(conn, "blitz:round", {})
        return {}
    state = {
        "doc_id": row["id"],
        "fragment": _middle_sentences(row["text"]),
        "started_at": _now().strftime(_TIME_FORMAT),
    }
    _write(conn, "blitz:round", state)
    return state


def blitz_elapsed(state: dict) -> int:
    if not state.get("started_at"):
        return 0
    try:
        started = datetime.strptime(state["started_at"], _TIME_FORMAT)
    except ValueError:
        return 0
    return max(0, int((_now() - started).total_seconds()))


def blitz_expired(state: dict) -> bool:
    return bool(state) and blitz_elapsed(state) > BLITZ_SECONDS


def blitz_combo(conn: sqlite3.Connection) -> int:
    return int(db.get_setting(conn, "blitz:combo", "0") or 0)


def blitz_check(conn: sqlite3.Connection, doc_id: int) -> dict:
    """Вызывается при открытии документа: тот ли документ нашёл игрок."""
    state = _read(conn, "blitz:round", {})
    if not enabled() or not state or state.get("doc_id") != doc_id:
        return {}

    elapsed = blitz_elapsed(state)
    economy.spend(conn, elapsed * BLITZ_TICK_COST, "blitz:timer")
    _write(conn, "blitz:round", {})

    if elapsed > BLITZ_SECONDS:
        db.set_setting(conn, "blitz:combo", "0")
        return {
            "won": False,
            "elapsed": elapsed,
            "message": f"Документ тот самый, но {elapsed} с — время вышло. "
                       f"Потрачено {elapsed * BLITZ_TICK_COST} сл.",
        }

    combo = blitz_combo(conn) + 1
    factor = min(BLITZ_COMBO_STEP ** (combo - 1), 3.0)
    earned = economy.earn(conn, int(round(BLITZ_REWARD * factor)), "blitz:win")
    db.set_setting(conn, "blitz:combo", str(combo))
    return {
        "won": True,
        "elapsed": elapsed,
        "message": f"Есть! {elapsed} с, комбо {combo}, начислено {earned} сл. "
                   f"(таймер съел {elapsed * BLITZ_TICK_COST} сл.)",
    }


# --- «Мне повезёт» (№21) ----------------------------------------------------

LUCKY_JACKPOT = 200
LUCKY_COOLDOWN = timedelta(minutes=10)


def lucky_ready(conn: sqlite3.Connection) -> bool:
    raw = db.get_setting(conn, "lucky:last", "")
    if not raw:
        return True
    try:
        last = datetime.strptime(raw, _TIME_FORMAT)
    except ValueError:
        return True
    return _now() - last >= LUCKY_COOLDOWN


def lucky_document(conn: sqlite3.Connection) -> dict:
    """Случайный документ индекса; джекпот — если он в top-10 последнего запроса."""
    row = conn.execute(
        "SELECT id, title FROM documents WHERE vector_norm > 0 ORDER BY RANDOM() LIMIT 1"
    ).fetchone()
    if row is None:
        return {}
    if not lucky_ready(conn):
        return {"doc_id": row["id"], "title": row["title"], "jackpot": False,
                "message": "Ещё не повезёт: удача перезаряжается десять минут."}

    db.set_setting(conn, "lucky:last", _now().strftime(_TIME_FORMAT))
    last_query = conn.execute(
        "SELECT raw_query FROM query_log ORDER BY id DESC LIMIT 1"
    ).fetchone()

    jackpot = False
    if last_query:
        engine = Search(conn=conn, search_query=last_query["raw_query"], limit=10)
        top = [item.document_id for item in engine.get_search_result()]
        jackpot = row["id"] in top

    amount = economy.earn(conn, LUCKY_JACKPOT, "lucky:jackpot") if jackpot else 0
    return {
        "doc_id": row["id"],
        "title": row["title"],
        "jackpot": jackpot,
        "amount": amount,
        "message": (
            f"Восемь глаз, и все везучие. Документ был в top-10 последнего запроса: "
            f"+{amount} сл."
            if jackpot
            else "Не повезло. Бывает."
        ),
    }
