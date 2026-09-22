"""Паук-компаньон Пафнутий и достижения — необязательная «живая» часть интерфейса.

Отключается флагом ARACHNE_COMPANION=0 в .env, на работу поиска не влияет.

Здесь же живут его «характер» и имущество: сытость тамагочи, линька со сменой
оформления, патчноуты по реальным значениям config.py и ломбард достижений.
"""

from __future__ import annotations

import json
import math
import random
import sqlite3
from datetime import datetime, timedelta

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
    "offended": [
        "Я, между прочим, всю ночь плёл этот индекс.",
        "Восемь глаз, и все сейчас смотрят на вас с укором.",
        "Ну знаете. Вот вам купон, и давайте больше об этом не будем.",
    ],
    "shop": [
        "Я ничего не продавал. Вы ничего не покупали.",
        "Лавка? Какая лавка. Это склад терминов.",
    ],
    "solitaire": [
        "Пасьянс назван в мою честь. Играйте, я посмотрю.",
        "Восемь последовательностей, восемь лап. Совпадение?",
        "Карты тоже складываются в сеть, только сверху вниз.",
        "Здесь я ничего не начисляю. Просто раскладывайте.",
        "Король сверху, туз снизу. Как в приличной паутине.",
    ],
    "hungry": [
        "Лапы дрожат. В индексе ничего нового не появлялось.",
        "Я бы поел. Хоть один новый документ.",
    ],
    "full": [
        "Сыт, доволен, готов расширить ваш запрос синонимом.",
        "После сытного обхода косинус считается веселее.",
    ],
    "moult": [
        "Линька. Не смотрите, это неприлично.",
        "Сбросил панцирь — заодно и оформление.",
    ],
    "tax": [
        "Одно слово — широкий улов, плати за широту.",
        "За краткость нынче берут отдельно.",
    ],
    "cashback": [
        "Вот это запрос! Держите сдачу словами.",
        "Целое предложение — и кэшбэк к нему.",
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
    "lucky": {
        "title": "Везунчик",
        "description": "Случайный документ оказался в top-10 последнего запроса",
        "icon": "🎲",
    },
    "sorry": {
        "title": "Извинения приняты",
        "description": "Паука обидели, а потом попросили прощения",
        "icon": "🤝",
    },
    "paperwork": {
        "title": "Бюрократ",
        "description": "Подано заявление об отказе от паука в трёх экземплярах",
        "icon": "📄",
    },
    "fake-expert": {
        "title": "Липовый эксперт",
        "description": "Восемь оценок подряд и ни одной нерелевантной",
        "icon": "🎓",
    },
    "moulted": {
        "title": "Новая шкура",
        "description": "Пережита первая линька и смена оформления",
        "icon": "🪳",
    },
    "shopper": {
        "title": "Постоянный покупатель",
        "description": "В лавке Пафнутия куплено три позиции",
        "icon": "🛒",
    },
    "blind-eye": {
        "title": "Слепой метод",
        "description": "Пять верных ответов подряд в слепой выдаче",
        "icon": "🙈",
    },
}

#: оценка достижения в ломбарде (механика №7): за сколько слов Пафнутий его берёт
PAWN_VALUE: dict[str, int] = {
    "first-web": 200,
    "big-web": 400,
    "archivist": 350,
    "typo-master": 300,
    "explorer": 300,
    "evaluator": 500,
    "sniper": 900,
    "night-owl": 250,
    "gourmet": 250,
    "lucky": 400,
    "sorry": 200,
    "paperwork": 300,
    "fake-expert": 350,
    "moulted": 300,
    "shopper": 350,
    "blind-eye": 700,
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
    """Список достижений с отметкой, какие открыты, заложены или потеряны."""
    opened = {
        row["code"]: row["unlocked_at"]
        for row in conn.execute("SELECT code, unlocked_at FROM achievements")
    }
    in_pawn = {
        row["code"]: row for row in conn.execute("SELECT * FROM pawned")
    }
    lost = _collection(conn)
    return [
        {
            "code": code,
            "opened": code in opened,
            "at": opened.get(code, ""),
            "value": PAWN_VALUE.get(code, 200),
            "pawned": code in in_pawn,
            "due_at": in_pawn[code]["due_at"] if code in in_pawn else "",
            "lost_at": lost.get(code, ""),
            **data,
        }
        for code, data in ACHIEVEMENTS.items()
    ]


def _announce(conn: sqlite3.Connection, codes: list[str]) -> list[dict]:
    """Уведомления о новых достижениях — только при включённом компаньоне.

    Сами достижения к этому моменту уже записаны в базу: в режиме отказа от
    паука они копятся молча.
    """
    if not config.COMPANION_ENABLED:
        return []
    return [{"code": code, **ACHIEVEMENTS[code]} for code in codes]


def check_after_search(
    conn: sqlite3.Connection, query: str, found: int, corrected: bool
) -> list[dict]:
    """Проверяет достижения, связанные с поиском. Возвращает новые.

    При выключенном компаньоне достижения всё равно пишутся в базу — просто
    молча, без всплывающих уведомлений: вернув паука, пользователь увидит всё,
    что успел заработать в режиме отказа.
    """
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

    lowered = query.lower()
    if "прост" in lowered and "пафнут" in lowered and unlock(conn, "sorry"):
        new_codes.append("sorry")

    return _announce(conn, new_codes)


def check_after_index(conn: sqlite3.Connection, documents: int) -> list[dict]:
    new_codes = []
    if documents > 0 and unlock(conn, "first-web"):
        new_codes.append("first-web")
    if documents >= 50 and unlock(conn, "big-web"):
        new_codes.append("big-web")
    return _announce(conn, new_codes)


def check_after_evaluation(conn: sqlite3.Connection, per_query: list[dict]) -> list[dict]:
    new_codes = []
    if unlock(conn, "evaluator"):
        new_codes.append("evaluator")
    if any(item.get("p@5", 0) >= 1.0 for item in per_query) and unlock(conn, "sniper"):
        new_codes.append("sniper")
    return _announce(conn, new_codes)


def check_after_open_document(conn: sqlite3.Connection) -> list[dict]:
    if bump(conn, "opened") >= 10 and unlock(conn, "explorer"):
        return _announce(conn, ["explorer"])
    return []


# --- Тамагочи (№37) ---------------------------------------------------------
#
# Коллекция статична — 108 документов, новые появляются редко. Поэтому
# основной корм — обычная работа с системой, а новый документ в индексе даёт
# жирный разовый бонус. Иначе паук был бы вечно голодным и механика
# превратилась бы в укор вместо шутки.

FEED: dict[str, int] = {
    "new_document": 3,     # за каждый новый документ после обхода
    "reindex": 1,          # переиндексация без новых документов
    "open": 1,             # открытие документа из выдачи
    "judge": 2,            # оценка релевантности на /qrels
}

#: сколько сытости теряется за сутки без еды
HUNGER_PER_DAY = 5

#: через сколько дней голода паук уходит искать мух
STARVED_DAYS = 7

_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def _read_time(conn: sqlite3.Connection, key: str) -> datetime | None:
    raw = db.get_setting(conn, key, "")
    if not raw:
        return None
    try:
        return datetime.strptime(raw, _TIME_FORMAT)
    except ValueError:
        return None


def feed(conn: sqlite3.Connection, event: str, times: int = 1) -> None:
    """Кормление паука. Сытость хранится в settings как spider:hunger (0–100)."""
    if not config.COMPANION_ENABLED:
        return
    gain = FEED.get(event, 0) * max(1, times)
    if gain <= 0:
        return
    state = spider_state(conn)
    value = min(100, state["satiety"] + gain)
    db.set_setting(conn, "spider:hunger", str(int(value)))
    db.set_setting(conn, "spider:fed_at", datetime.now().strftime(_TIME_FORMAT))


def spider_state(conn: sqlite3.Connection) -> dict:
    """Сытость, размер и настроение паука с поправкой на прошедшее время."""
    if not config.COMPANION_ENABLED:
        return {"satiety": 100, "size": 1.0, "level": "normal", "gone": False, "days": 0}

    stored = db.get_setting(conn, "spider:hunger", "")
    satiety = int(stored) if stored.isdigit() else 60
    fed_at = _read_time(conn, "spider:fed_at")
    days = (datetime.now() - fed_at).total_seconds() / 86400 if fed_at else 0.0
    satiety = max(0, int(round(satiety - HUNGER_PER_DAY * days)))

    if satiety > 70:
        level = "full"
    elif satiety >= 30:
        level = "normal"
    elif satiety >= 10:
        level = "hungry"
    else:
        level = "starved"

    size = round(min(1.6, max(0.8, 0.8 + 0.8 * satiety / 100)), 2)
    gone = level == "starved" and days >= STARVED_DAYS
    return {
        "satiety": satiety,
        "size": size,
        "level": level,
        "gone": gone,
        "days": round(days, 1),
    }


def spider_line(conn: sqlite3.Connection, event: str, seed: str = "") -> str:
    """Реплика с поправкой на сытость: голодный ворчит и отвечает реже."""
    state = spider_state(conn)
    if state["gone"]:
        return "Ушёл искать мух. Вернусь, когда в индексе появится что-нибудь новое."
    if state["level"] == "hungry":
        return line("hungry") if random.random() < 0.5 else line(event, seed)
    if state["level"] == "full" and random.random() < 0.25:
        return line("full")
    return line(event, seed)


def suggest_synonym(conn: sqlite3.Connection, analysis) -> str:
    """Сытый паук иногда сам подсказывает синоним к запросу."""
    if not config.COMPANION_ENABLED or spider_state(conn)["level"] != "full":
        return ""
    for source, extras in (analysis.synonyms or {}).items():
        if extras:
            return f"Сытый и добрый: попробуйте ещё «{extras[0]}» вместо «{source}»."
    return ""


# --- Линька и темы оформления (№41) -----------------------------------------

SKINS: dict[str, str] = {
    "classic": "Классическая",
    "web": "Паутина, светлая",
    "night": "Ночная, готическая",
    "office": "Канцелярия",
    "terminal": "Зелёный на чёрном",
    "notepad": "Жёлтый блокнот в линейку",
}

#: каждые столько запросов паук линяет и роняет случайную тему
MOULT_EVERY = 25

#: во что превращается дубль темы
DUPLICATE_PRICE = 50


def owned_skins(conn: sqlite3.Connection) -> list[str]:
    codes = [
        row["code"].split(":", 1)[1]
        for row in conn.execute("SELECT code FROM purchases WHERE code LIKE 'skin:%'")
    ]
    return ["classic"] + [code for code in codes if code in SKINS and code != "classic"]


def active_skin(conn: sqlite3.Connection) -> str:
    """Выбранная тема. При выключенном компаньоне — всегда канцелярия (№34)."""
    if not config.COMPANION_ENABLED:
        return "office"
    skin = db.get_setting(conn, "skin:active", "classic")
    return skin if skin in owned_skins(conn) else "classic"


def choose_skin(conn: sqlite3.Connection, skin: str) -> bool:
    if skin not in owned_skins(conn):
        return False
    db.set_setting(conn, "skin:active", skin)
    return True


def maybe_moult(conn: sqlite3.Connection) -> dict:
    """Каждые MOULT_EVERY запросов — линька с выпадением случайной темы."""
    from . import economy  # локальный импорт: экономика знает про компаньона

    if not config.COMPANION_ENABLED:
        return {}
    queries = int(db.get_setting(conn, "counter:queries", "0") or 0)
    last = int(db.get_setting(conn, "moult:at", "0") or 0)
    if queries < last + MOULT_EVERY:
        return {}
    db.set_setting(conn, "moult:at", str(queries))

    skin = random.choice(list(SKINS))
    code = f"skin:{skin}"
    if skin == "classic" or economy.owns(conn, code):
        earned = economy.earn(conn, DUPLICATE_PRICE, "moult:duplicate")
        return {
            "skin": skin,
            "title": SKINS[skin],
            "duplicate": True,
            "amount": earned,
            "line": line("moult"),
        }
    economy.record_purchase(conn, code, "выпало при линьке")
    unlock(conn, "moulted")
    return {
        "skin": skin,
        "title": SKINS[skin],
        "duplicate": False,
        "amount": 0,
        "line": line("moult"),
    }


# --- Патчноуты (№44) --------------------------------------------------------

BALANCE_JOKES = [
    "Баланс не трогали. Косинус по-прежнему считает честно.",
    "Исправлена опечатка в реплике про мух. Мухи не пострадали.",
    "Пауку выдана новая паутина того же размера.",
    "Улучшена читаемость логарифма. Логарифм не заметил.",
]

#: какие значения config.py попадают в патчноут
TRACKED = (
    "ROCCHIO_ALPHA", "ROCCHIO_BETA", "ROCCHIO_GAMMA",
    "EXPANDED_TERM_WEIGHT", "RESULTS_PER_PAGE", "SNIPPET_LENGTH",
)


def _snapshot(conn: sqlite3.Connection) -> dict:
    values = {name: getattr(config, name) for name in TRACKED}
    statistics = db.stats(conn)
    values["documents"] = statistics["documents"]
    values["terms"] = statistics["terms"]
    return values


def patch_notes(conn: sqlite3.Connection, advance: bool = False) -> dict:
    """Патчноут по реальным значениям config.py и состоянию индекса.

    Побочная польза, ради которой это и стоит показывать: если кто-то крутил
    конфигурацию между прогонами метрик, патчноут скажет об этом прямым
    текстом.
    """
    current = _snapshot(conn)
    raw = db.get_setting(conn, "patch:snapshot", "")
    try:
        previous = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        previous = {}

    runs = int(db.get_setting(conn, "runs", "0") or 0)
    if advance:
        runs += 1
        db.set_setting(conn, "runs", str(runs))
        db.set_setting(conn, "patch:snapshot", json.dumps(current, ensure_ascii=False))

    changes = []
    for name, value in current.items():
        if name in previous and previous[name] != value:
            changes.append(
                f"{name} изменён с {previous[name]} на {value}".replace(".", ",")
            )
    if not changes:
        seed = runs or 1
        changes = [BALANCE_JOKES[seed % len(BALANCE_JOKES)]]

    return {
        "version": f"1.0.{max(runs, 1)}",
        "changes": changes,
        "config": current,
    }


# --- Ломбард Пафнутия (№7) --------------------------------------------------

PAWN_DAYS = 7
PAWN_SHARE = 0.6


def _collection(conn: sqlite3.Connection) -> dict[str, str]:
    """Достижения, ушедшие в коллекцию Пафнутия за долги: {код: дата}."""
    raw = db.get_setting(conn, "pawn:collection", "")
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}


def expire_pawned(conn: sqlite3.Connection) -> list[str]:
    """Просроченные залоги уходят в коллекцию Пафнутия."""
    if not config.COMPANION_ENABLED:
        return []
    today = datetime.now()
    lost = []
    for row in conn.execute("SELECT code, due_at FROM pawned").fetchall():
        try:
            due = datetime.strptime(row["due_at"], "%d.%m.%Y")
        except ValueError:
            continue
        if today <= due:
            continue
        conn.execute("DELETE FROM pawned WHERE code = ?", (row["code"],))
        conn.execute("DELETE FROM achievements WHERE code = ?", (row["code"],))
        lost.append(row["code"])
    if lost:
        collection = _collection(conn)
        for code in lost:
            collection[code] = today.strftime("%d.%m.%Y")
        db.set_setting(conn, "pawn:collection", json.dumps(collection, ensure_ascii=False))
        conn.commit()
    return lost


def pawn(conn: sqlite3.Connection, code: str) -> tuple[bool, str]:
    """Заложить достижение: 60% оценки сразу, выкуп по 100% в течение недели."""
    from . import economy

    if code not in ACHIEVEMENTS:
        return False, "нет такого достижения"
    if conn.execute("SELECT 1 FROM achievements WHERE code = ?", (code,)).fetchone() is None:
        return False, "это достижение ещё не открыто"
    if conn.execute("SELECT 1 FROM pawned WHERE code = ?", (code,)).fetchone():
        return False, "уже в залоге"

    value = PAWN_VALUE.get(code, 200)
    payout = int(round(value * PAWN_SHARE))
    due = datetime.now() + timedelta(days=PAWN_DAYS)
    conn.execute(
        "INSERT INTO pawned(code, taken_at, due_at, price) VALUES(?,?,?,?)",
        (code, datetime.now().strftime("%d.%m.%Y"), due.strftime("%d.%m.%Y"), value),
    )
    conn.commit()
    earned = economy.earn(conn, payout, f"pawn:{code}")
    return True, (
        f"«{ACHIEVEMENTS[code]['title']}» в залоге. Получено {earned} сл., "
        f"выкуп до {due.strftime('%d.%m.%Y')} за {value} сл."
    )


def redeem(conn: sqlite3.Connection, code: str) -> tuple[bool, str]:
    """Выкуп заложенного достижения по полной оценке."""
    from . import economy

    row = conn.execute("SELECT price FROM pawned WHERE code = ?", (code,)).fetchone()
    if row is None:
        return False, "это достижение не в залоге"
    price = int(row["price"])
    if not economy.spend(conn, price, f"redeem:{code}"):
        return False, f"не хватает слов: нужно {price}"
    conn.execute("DELETE FROM pawned WHERE code = ?", (code,))
    conn.commit()
    return True, f"«{ACHIEVEMENTS[code]['title']}» выкуплено за {price} сл."


def pawn_price(conn: sqlite3.Connection, code: str) -> int:
    """Цена повторного получения: за ушедшее в коллекцию платят вдвое."""
    return PAWN_VALUE.get(code, 200) * (2 if code in _collection(conn) else 1)


def pawn_list(conn: sqlite3.Connection) -> list[dict]:
    """Что сейчас можно заложить и что уже заложено."""
    if not config.COMPANION_ENABLED:
        return []
    expire_pawned(conn)
    in_pawn = {row["code"]: row for row in conn.execute("SELECT * FROM pawned")}
    opened = {row["code"] for row in conn.execute("SELECT code FROM achievements")}
    items = []
    for code, data in ACHIEVEMENTS.items():
        if code not in opened and code not in in_pawn:
            continue
        value = PAWN_VALUE.get(code, 200)
        items.append(
            {
                "code": code,
                "title": data["title"],
                "icon": data["icon"],
                "value": value,
                "payout": int(round(value * PAWN_SHARE)),
                "pawned": code in in_pawn,
                "due_at": in_pawn[code]["due_at"] if code in in_pawn else "",
            }
        )
    return items


# --- Экономика поиска (№4) --------------------------------------------------

#: налог за односложный запрос
LAZY_TAX = 15

#: части речи, за которые полагается повышенный кэшбэк
VERB_TAGS = {"глагол", "инфинитив", "причастие", "кр. причастие"}


def reward_for_query(conn: sqlite3.Connection, analysis, repeated: bool) -> dict:
    """Налог на лень и кэшбэк за человеческий запрос.

    Механика прямо толкает пользователя к естественно-языковым запросам — к
    тому самому, что требует вариант 3 задания.
    """
    from . import economy

    if not economy.enabled():
        return {}

    count = len(analysis.lemmas)
    if repeated:
        return {"kind": "repeat", "amount": 0, "line": line("repeat")}
    if count <= 1:
        economy.spend(conn, LAZY_TAX, "tax:lazy")
        return {"kind": "tax", "amount": -LAZY_TAX, "line": line("tax")}
    if count >= 4:
        has_verb = any(
            item.get("pos") in VERB_TAGS for item in (analysis.morphology or [])
        )
        amount = (5 if has_verb else 2) * count
        earned = economy.earn(conn, amount, "cashback")
        return {
            "kind": "cashback",
            "amount": earned,
            "verb": has_verb,
            "line": line("cashback"),
        }
    return {}


def score_delta(previous: float, current: float) -> str:
    """Подпись дельты метрики для интерфейса разметки."""
    difference = current - previous
    if math.isclose(difference, 0.0, abs_tol=5e-4):
        return ""
    return f"{difference:+.3f}".replace(".", ",")
