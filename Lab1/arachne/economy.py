"""Экономика слов: кошелёк, цены терминов, лавка.

Валюта системы — не абстрактные очки, а сами термины индекса. Цена термина
равна его информативности, то есть инверсной частоте из формулы (1.5):

    price(lemma) = round(100 * B_i) = round(100 * log(N / P_i))

«Сеть» встречается почти везде и стоит копейки, «коаксиальный» — в одном
документе и стоит состояние. Кошелёк — такой же разреженный вектор, как
вектор документа: {лемма: количество}, а капитал — скалярное произведение
этого вектора на вектор цен.

Ни одна функция этого модуля не вызывается из evaluation/*: метрики качества
считаются по чистой конфигурации, и никакая покупка на них не влияет.
"""

from __future__ import annotations

import math
import random
import sqlite3
from datetime import datetime

from . import config, db
from .indexer import inverse_frequency

#: минимальная цена термина — чтобы в кошельке не заводились пустые позиции
MIN_PRICE = 1

#: во сколько раз дешевеет лемма за каждое её появление в истории запросов
INFLATION_STEP = 0.97

#: ниже этой доли базовой цены личная инфляция не опускается
INFLATION_FLOOR = 0.2


def enabled() -> bool:
    """Экономика подчинена общему рубильнику геймификации."""
    return config.COMPANION_ENABLED and config.ECONOMY_ENABLED


def _now() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")


# --- Цены -------------------------------------------------------------------

def document_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()
    return int(row["n"]) if row else 0


def price(conn: sqlite3.Connection, lemma: str) -> int:
    """Базовая цена термина: сто его инверсных частот B_i."""
    row = conn.execute("SELECT df FROM terms WHERE lemma = ?", (lemma,)).fetchone()
    if not row:
        return MIN_PRICE
    value = round(100 * inverse_frequency(document_count(conn), row["df"]))
    return max(MIN_PRICE, int(value))


def query_hits(conn: sqlite3.Connection, lemma: str) -> int:
    """Сколько раз лемма встречалась в нормализованных запросах пользователя."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM query_log "
        "WHERE ' ' || normalized || ' ' LIKE ?",
        (f"% {lemma} %",),
    ).fetchone()
    return int(row["n"]) if row else 0


def personal_price(conn: sqlite3.Connection, lemma: str) -> int:
    """Цена с учётом личной инфляции: что часто ищешь — то для тебя дешевле.

    Побочный эффект, который и делает из этого игру: выгодно скупать то, что
    никогда не ищешь.
    """
    base = price(conn, lemma)
    factor = max(INFLATION_FLOOR, INFLATION_STEP ** query_hits(conn, lemma))
    return max(MIN_PRICE, int(round(base * factor)))


def discount_percent(conn: sqlite3.Connection, lemma: str) -> int:
    """На сколько процентов личная цена ниже базовой (для колонки в лавке)."""
    base = price(conn, lemma)
    if base <= 0:
        return 0
    return int(round(100 * (1 - personal_price(conn, lemma) / base)))


# --- Кошелёк ----------------------------------------------------------------

def wallet(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        row["lemma"]: int(row["amount"])
        for row in conn.execute("SELECT lemma, amount FROM wallet WHERE amount > 0")
    }


def positions(conn: sqlite3.Connection) -> list[dict]:
    """Позиции кошелька с ценами — от самых дешёвых к дорогим."""
    items = [
        {
            "lemma": lemma,
            "amount": amount,
            "price": price(conn, lemma),
            "total": amount * price(conn, lemma),
        }
        for lemma, amount in wallet(conn).items()
    ]
    items.sort(key=lambda item: (item["price"], item["lemma"]))
    return items


def balance(conn: sqlite3.Connection) -> int:
    """Капитал в «словах»: сумма по позициям кошелька."""
    return sum(item["total"] for item in positions(conn))


def _grant(conn: sqlite3.Connection, lemma: str, amount: int) -> None:
    conn.execute(
        "INSERT INTO wallet(lemma, amount) VALUES(?, ?) "
        "ON CONFLICT(lemma) DO UPDATE SET amount = amount + excluded.amount",
        (lemma, int(amount)),
    )
    conn.commit()


def _log(conn: sqlite3.Connection, reason: str, delta: int) -> None:
    conn.execute(
        "INSERT INTO ledger(ts, reason, delta) VALUES(?,?,?)", (_now(), reason, int(delta))
    )
    conn.commit()


def ledger(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT ts, reason, delta FROM ledger ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()


def affordable_lemma(conn: sqlite3.Connection, amount: int) -> str:
    """Случайный термин, которым удобно выдать ровно `amount` слов.

    Берётся редкий термин — но из тех, чья цена укладывается в начисление:
    иначе кэшбэк в десять слов выдавался бы одной монетой за двести и
    экономика разъехалась бы на первом же запросе.
    """
    rows = conn.execute("SELECT lemma, df FROM terms").fetchall()
    if not rows:
        return ""
    total = document_count(conn)
    priced = [
        (row["lemma"], max(MIN_PRICE, int(round(100 * inverse_frequency(total, row["df"])))))
        for row in rows
    ]
    fitting = [lemma for lemma, value in priced if value <= max(amount, MIN_PRICE)]
    if not fitting:
        # всё дороже начисления — берём самый дешёвый термин словаря
        return min(priced, key=lambda item: item[1])[0]
    # из подходящих предпочитаем редкие: сортируем по убыванию цены и берём
    # случайный из верхней трети
    fitting.sort(key=lambda lemma: -price(conn, lemma))
    head = fitting[: max(1, len(fitting) // 3)]
    return random.choice(head)


def earn(
    conn: sqlite3.Connection, amount: int, reason: str, lemma: str | None = None
) -> int:
    """Начисление. Возвращает, сколько слов реально зачислено."""
    if not enabled() or amount <= 0:
        return 0
    target = lemma or affordable_lemma(conn, amount)
    if not target:
        return 0
    unit = price(conn, target)
    units = max(1, round(amount / unit))
    _grant(conn, target, units)
    credited = units * unit
    _log(conn, reason, credited)
    return credited


def spend(conn: sqlite3.Connection, amount: int, reason: str) -> bool:
    """Списание. False, если капитала не хватает — кошелёк при этом не тронут.

    Списывается всегда с самых дешёвых позиций: дорогие редкие термины
    остаются в кошельке как «сбережения».
    """
    if not enabled():
        return False
    if amount <= 0:
        return True
    items = positions(conn)
    if sum(item["total"] for item in items) < amount:
        return False

    remaining = amount
    for item in items:
        if remaining <= 0:
            break
        take = min(item["amount"], math.ceil(remaining / item["price"]))
        if take <= 0:
            continue
        conn.execute(
            "UPDATE wallet SET amount = amount - ? WHERE lemma = ?",
            (take, item["lemma"]),
        )
        remaining -= take * item["price"]
    conn.execute("DELETE FROM wallet WHERE amount <= 0")
    conn.commit()
    _log(conn, reason, -amount)
    return True


def ensure_start_capital(conn: sqlite3.Connection) -> int:
    """Стартовые 300 слов тремя случайными средними леммами — один раз."""
    if not enabled() or db.get_setting(conn, "economy:seeded") == "1":
        return 0
    rows = conn.execute("SELECT lemma FROM terms ORDER BY df DESC").fetchall()
    if not rows:
        return 0
    db.set_setting(conn, "economy:seeded", "1")

    middle = [row["lemma"] for row in rows[len(rows) // 3 : 2 * len(rows) // 3 + 1]]
    chosen = random.sample(middle, min(3, len(middle))) if middle else [rows[0]["lemma"]]
    share = config.START_CAPITAL // len(chosen)
    granted = 0
    for lemma in chosen:
        granted += earn(conn, share, "start", lemma=lemma)
    return granted


# --- Покупки ----------------------------------------------------------------

def owns(conn: sqlite3.Connection, code: str) -> bool:
    """Куплено ли. Намеренно не смотрит на ARACHNE_ECONOMY.

    Отключение кошелька не должно отбирать у пользователя уже купленные
    отключения издевательств и выпавшие темы оформления — иначе выключенная
    экономика превратилась бы в способ включить все шутки разом без единого
    способа их снять. Тратить и начислять при этом нельзя: гейт стоит в
    earn/spend/buy.
    """
    return (
        conn.execute("SELECT 1 FROM purchases WHERE code = ?", (code,)).fetchone()
        is not None
    )


def purchase_meta(conn: sqlite3.Connection, code: str) -> str:
    row = conn.execute("SELECT meta FROM purchases WHERE code = ?", (code,)).fetchone()
    return row["meta"] if row else ""


def record_purchase(conn: sqlite3.Connection, code: str, meta: str = "") -> None:
    conn.execute(
        "INSERT INTO purchases(code, bought_at, meta) VALUES(?,?,?) "
        "ON CONFLICT(code) DO UPDATE SET bought_at = excluded.bought_at, "
        "meta = excluded.meta",
        (code, _now(), meta),
    )
    conn.commit()


def drop_purchase(conn: sqlite3.Connection, code: str) -> None:
    conn.execute("DELETE FROM purchases WHERE code = ?", (code,))
    conn.commit()


def coupon_value(conn: sqlite3.Connection, amount: int) -> int:
    """Цена с учётом купона «скидка за грубость», если он есть."""
    if not owns(conn, "coupon"):
        return amount
    return max(MIN_PRICE, int(round(amount * 0.9)))


def buy(conn: sqlite3.Connection, code: str, amount: int, meta: str = "") -> bool:
    """Покупка позиции лавки. Купон −10% тратится на первую же покупку."""
    if not enabled():
        return False
    final = coupon_value(conn, amount)
    used_coupon = final != amount
    if not spend(conn, final, f"purchase:{code}"):
        return False
    if used_coupon:
        drop_purchase(conn, "coupon")
    record_purchase(conn, code, meta)
    return True


# --- Ассортимент лавки ------------------------------------------------------

#: отключения издевательств: код -> (цена, название, что именно отключает)
RELIEFS: list[dict] = [
    {
        "code": "fix-pagination",
        "price": 300,
        "title": "Честная пагинация",
        "note": "страница 2 перестанет иногда оказываться перемешанной страницей 1",
    },
    {
        "code": "no-cobweb",
        "price": 250,
        "title": "Средство от паутины",
        "note": "выдача не зарастает паутиной, пока вы читаете",
    },
    {
        "code": "normal-scroll",
        "price": 250,
        "title": "Прямой скролл на разметке",
        "note": "колесо мыши на /qrels снова крутится в ту сторону",
    },
    {
        "code": "honest-modals",
        "price": 400,
        "title": "Честные подтверждения",
        "note": "кнопки «Да» и «Нет» перестанут меняться местами",
    },
    {
        "code": "calm-ranking",
        "price": 350,
        "title": "Ровное настроение",
        "note": "выдача никогда не переходит на сортировку по алфавиту",
    },
    {
        "code": "sober-index",
        "price": 300,
        "title": "Трезвый индекс",
        "note": "буквы в сниппетах не пляшут, сколько бы вы ни искали подряд",
    },
    {
        "code": "no-curse",
        "price": 450,
        "title": "Оберег от проклятий",
        "note": "ни одна лемма запроса не подменяется синонимом втихую",
    },
]

#: чёрный рынок стоп-слов: цена фиксированная, товар одноразовый
STOPWORDS_FOR_SALE = ["и", "в", "на", "не", "что"]
STOPWORD_PRICE = 500


def stopword_code(word: str) -> str:
    return f"stopword:{word}"


def bought_stopwords(conn: sqlite3.Connection) -> set[str]:
    """Стоп-слова, купленные и ещё не сгоревшие."""
    if not enabled():
        return set()
    return {
        row["code"].split(":", 1)[1]
        for row in conn.execute("SELECT code FROM purchases WHERE code LIKE 'stopword:%'")
    }


def burn_stopwords(conn: sqlite3.Connection, words: set[str]) -> None:
    """Купленное стоп-слово действует на один запрос и сгорает."""
    for word in words:
        drop_purchase(conn, stopword_code(word))


def relief_state(conn: sqlite3.Connection) -> list[dict]:
    return [{**item, "owned": owns(conn, item["code"])} for item in RELIEFS]
