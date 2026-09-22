"""Тесты игровой надстройки: экономика слов, джокеры, издевательства, режимы.

Главное, что здесь проверяется, — инвариант: геймификация не протекает в
измерения. Метрики качества должны совпадать до последнего знака независимо
от того, что пользователь накупил, какие джокеры активировал и сколько
запросов задал подряд.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arachne import companion, crawler, db, economy, indexer, jokers, mischief  # noqa: E402
from arachne import search as search_module  # noqa: E402
from arachne.evaluation import qrels, runner  # noqa: E402
from arachne.search import Search  # noqa: E402
from arachne.text import snippets  # noqa: E402


@pytest.fixture()
def conn(tmp_path: Path):
    """Коллекция с заметным разбросом df: есть и частые, и уникальные термины."""
    node = tmp_path / "NODE-GAME"
    node.mkdir()
    (node / "a.txt").write_text(
        "Сеть сеть сеть коммутатор коаксиальный кабель", encoding="utf-8"
    )
    (node / "b.txt").write_text("Сеть маршрутизатор кабель", encoding="utf-8")
    (node / "c.txt").write_text("Сеть сервер", encoding="utf-8")
    (node / "d.txt").write_text("Борщ рецепт свёкла", encoding="utf-8")

    connection = db.connect(tmp_path / "game.db")
    db.init_db(connection)
    crawler.add_source(connection, str(node), "NODE-GAME")
    crawler.crawl(connection)
    indexer.build_index(connection)
    yield connection
    connection.close()


# --- Цены: валюта — это информативность термина ------------------------------

def test_price_follows_inverse_frequency(conn):
    # «сеть» есть в трёх документах из четырёх, «коаксиальный» — в одном
    assert economy.price(conn, "коаксиальный") > economy.price(conn, "сеть")
    assert economy.price(conn, "сеть") >= economy.MIN_PRICE


def test_price_matches_formula(conn):
    expected = round(100 * indexer.get_lemma_inverse_frequency(conn, "коаксиальный"))
    assert economy.price(conn, "коаксиальный") == expected


def test_unknown_lemma_costs_minimum(conn):
    assert economy.price(conn, "такого-термина-нет") == economy.MIN_PRICE


def test_personal_price_falls_with_repeated_queries(conn):
    base = economy.price(conn, "коаксиальный")
    for _ in range(12):
        conn.execute(
            "INSERT INTO query_log(raw_query, normalized, ts) VALUES(?,?,?)",
            ("коаксиальный кабель", "коаксиальный кабель", "01.01.2026 00:00:00"),
        )
    conn.commit()
    personal = economy.personal_price(conn, "коаксиальный")
    assert personal < base
    assert personal >= base * economy.INFLATION_FLOOR
    assert economy.discount_percent(conn, "коаксиальный") > 0


# --- Кошелёк ----------------------------------------------------------------

def test_balance_is_scalar_product_of_wallet_and_prices(conn):
    economy.earn(conn, 300, "test", lemma="сеть")
    expected = sum(
        amount * economy.price(conn, lemma)
        for lemma, amount in economy.wallet(conn).items()
    )
    assert economy.balance(conn) == expected


def test_earn_credits_requested_amount(conn):
    credited = economy.earn(conn, 200, "test")
    assert credited > 0
    assert economy.balance(conn) == credited


def test_spend_takes_from_cheapest_positions(conn):
    economy.earn(conn, 400, "test", lemma="коаксиальный")   # дорогая позиция
    economy.earn(conn, 120, "test", lemma="сеть")           # дешёвая позиция
    before = economy.wallet(conn)["коаксиальный"]

    assert economy.spend(conn, 60, "test") is True
    after = economy.wallet(conn)
    assert after.get("коаксиальный") == before, "дорогое остаётся в сбережениях"
    assert after.get("сеть", 0) < 999


def test_spend_refuses_when_capital_is_short(conn):
    economy.earn(conn, 50, "test", lemma="сеть")
    balance_before = economy.balance(conn)
    assert economy.spend(conn, 100_000, "test") is False
    assert economy.balance(conn) == balance_before


def test_ledger_records_both_directions(conn):
    economy.earn(conn, 300, "cashback")
    economy.spend(conn, 100, "purchase:test")
    reasons = [row["reason"] for row in economy.ledger(conn)]
    assert "cashback" in reasons and "purchase:test" in reasons


def test_start_capital_is_granted_once(conn):
    first = economy.ensure_start_capital(conn)
    assert first > 0
    assert economy.ensure_start_capital(conn) == 0


# --- Покупки ----------------------------------------------------------------

def test_buy_requires_capital(conn):
    assert economy.buy(conn, "fix-pagination", 300) is False
    assert economy.owns(conn, "fix-pagination") is False

    economy.earn(conn, 600, "test", lemma="сеть")
    assert economy.buy(conn, "fix-pagination", 300) is True
    assert economy.owns(conn, "fix-pagination") is True


def test_coupon_gives_ten_percent_and_burns(conn):
    economy.earn(conn, 900, "test", lemma="сеть")
    economy.record_purchase(conn, "coupon", "01.01.2026")
    assert economy.coupon_value(conn, 300) == 270

    economy.buy(conn, "no-cobweb", 300)
    assert economy.owns(conn, "coupon") is False
    assert economy.coupon_value(conn, 300) == 300


def test_bought_stopword_burns_after_one_query(conn):
    economy.record_purchase(conn, economy.stopword_code("и"))
    assert "и" in economy.bought_stopwords(conn)
    economy.burn_stopwords(conn, {"и"})
    assert "и" not in economy.bought_stopwords(conn)


# --- Джокеры как параметры модели -------------------------------------------

def test_jokers_map_onto_search_fields(conn):
    engine = Search(conn=conn, search_query="сеть")
    jokers.apply_to(engine, ["no-stop", "syn-x2", "idf-flat", "short-doc", "sq-weights"], conn)
    assert engine.keep_stopwords and engine.flat_idf
    assert engine.short_doc_bonus and engine.square_weights
    assert engine.expanded_weight == 1.0


def test_flat_idf_still_ranks_and_normalizes(conn):
    engine = Search(conn=conn, search_query="сеть кабель", flat_idf=True)
    results = engine.get_search_result()
    assert results
    assert all(0 < item.rank <= 1.0000001 for item in results)


def test_ban_node_excludes_host(conn):
    engine = Search(conn=conn, search_query="сеть", banned_host="NODE-GAME")
    assert engine.get_search_result() == []


def test_taking_joker_costs_words_after_the_free_one(conn):
    offer = jokers.offer(conn)
    assert len(offer) == 3
    taken, _ = jokers.take(conn, offer[0]["code"])
    assert taken is True                       # первый — бесплатно

    ok, message = jokers.take(conn, offer[1]["code"])
    assert ok is False and "не хватает" in message.lower()


def test_active_joker_expires(conn):
    code = jokers.offer(conn)[0]["code"]
    jokers.take(conn, code)
    for _ in range(10):
        jokers.consume(conn)
    assert jokers.active_jokers(conn) == {}


# --- Купленные стоп-слова в поисковом образе --------------------------------

def test_bought_stopword_enters_query_vector(conn):
    plain = Search(conn=conn, search_query="и сеть")
    plain.get_search_query_vector()
    assert "и" not in plain.user_lemmas

    bought = Search(conn=conn, search_query="и сеть", allowed_stopwords={"и"})
    vector = bought.get_search_query_vector()
    assert vector["и"] == search_module.BOUGHT_STOPWORD_WEIGHT
    assert bought.kept_stopwords == ["и"]
    assert "и" in bought.user_lemmas


def test_bought_stopword_lifts_wordy_documents(tmp_path: Path):
    """Наверх всплывают просто длинные документы — в этом и абсурд механики."""
    node = tmp_path / "NODE-STOP"
    node.mkdir()
    (node / "short.txt").write_text("Сеть предприятия.", encoding="utf-8")
    (node / "wordy.txt").write_text(
        "Сеть и сервер и кабель и розетка и патч-панель и шлюз и подсеть и домен.",
        encoding="utf-8",
    )
    # третий документ без «сети»: иначе B_i = log(N / P_i) обнуляет её вес
    (node / "other.txt").write_text("Борщ и рецепт.", encoding="utf-8")

    connection = db.connect(tmp_path / "stop.db")
    db.init_db(connection)
    crawler.add_source(connection, str(node), "NODE-STOP")
    crawler.crawl(connection)
    indexer.build_index(connection)

    plain = Search(conn=connection, search_query="сеть").get_search_result()
    assert plain[0].path.endswith("short.txt"), "без покупки короткий документ точнее"

    bought = Search(
        conn=connection, search_query="и сеть", allowed_stopwords={"и"}
    ).get_search_result()
    assert bought[0].path.endswith("wordy.txt")
    connection.close()


# --- Издевательства ---------------------------------------------------------

def test_mood_sulks_after_queries_without_opening(conn):
    for _ in range(mischief.SULK_AFTER):
        mischief.note_search(conn)
    assert mischief.mood(conn) == "sulking"

    mischief.note_document_open(conn)
    assert mischief.mood(conn) == "normal"


def test_calm_ranking_purchase_stops_sulking(conn):
    for _ in range(mischief.SULK_AFTER + 5):
        mischief.note_search(conn)
    economy.record_purchase(conn, "calm-ranking")
    assert mischief.mood(conn) == "normal"


def test_alphabetical_ranking_keeps_real_ranks(conn):
    results = Search(conn=conn, search_query="сеть кабель", alphabetical=True).get_search_result()
    titles = [item.title.lower() for item in results]
    assert titles == sorted(titles)
    assert all(item.rank > 0 for item in results), "ранги настоящие, а не подделанные"


def test_slur_keeps_markup_intact(conn):
    source = "<mark>сеть</mark> и коммутатор &amp; кабель"
    noisy = snippets.slur(source, 0.9, seed=1)
    assert "<mark>" in noisy and "</mark>" in noisy and "&amp;" in noisy
    assert noisy != source


def test_pagination_betrayal_is_off_after_purchase(conn):
    economy.record_purchase(conn, "fix-pagination")
    assert mischief.betrays_page(conn, 2) is False


def test_streak_resets_search_noise_without_purchase(conn):
    assert mischief.snippet_noise(conn, streak=3) == 0.0
    assert mischief.snippet_noise(conn, streak=mischief.DRUNK_AFTER + 1) > 0
    economy.record_purchase(conn, "sober-index")
    assert mischief.snippet_noise(conn, streak=mischief.DRUNK_AFTER + 1) == 0.0


# --- Ломбард ----------------------------------------------------------------

def test_pawn_pays_share_and_redeem_costs_full(conn):
    companion.unlock(conn, "first-web")
    ok, _ = companion.pawn(conn, "first-web")
    assert ok is True
    assert economy.balance(conn) > 0

    # выкуп дороже, чем выдали: в этом и смысл ломбарда
    assert companion.redeem(conn, "first-web")[0] is False
    economy.earn(conn, 500, "test", lemma="сеть")
    assert companion.redeem(conn, "first-web")[0] is True


def test_pawn_refuses_unopened_achievement(conn):
    ok, message = companion.pawn(conn, "sniper")
    assert ok is False and "не открыто" in message


# --- Контроль качества разметки ---------------------------------------------

def test_few_judgements_are_not_suspicious(conn):
    """Порог в восемь оценок: четыре положительные — ещё не перекос."""
    query_id = qrels.ensure_query(conn, "сеть")
    for doc_id in [row["id"] for row in conn.execute("SELECT id FROM documents")]:
        qrels.set_judgement(conn, query_id, doc_id, 2)
    assert qrels.check_suspect(conn, query_id) is False
    assert qrels.is_suspect(conn, query_id) is False


def test_suspect_requires_all_positive(tmp_path: Path):
    connection = db.connect(tmp_path / "suspect.db")
    db.init_db(connection)
    connection.executemany(
        """INSERT INTO documents(path, uri, host, title, text, ext, date_added, time_added)
           VALUES(?,?,?,?,?,?,?,?)""",
        [
            (f"/d{index}.txt", f"file:///d{index}.txt", "NODE", f"Документ {index}",
             "текст", ".txt", "01.01.2026", "00:00:00")
            for index in range(8)
        ],
    )
    connection.commit()
    doc_ids = [row["id"] for row in connection.execute("SELECT id FROM documents")]

    query_id = qrels.ensure_query(connection, "тест")
    for doc_id in doc_ids:
        qrels.set_judgement(connection, query_id, doc_id, 2)
    assert qrels.check_suspect(connection, query_id) is True
    assert qrels.is_suspect(connection, query_id) is True

    # одна нерелевантная оценка — и метка снимается сама
    qrels.set_judgement(connection, query_id, doc_ids[0], 0)
    qrels.check_suspect(connection, query_id)
    assert qrels.is_suspect(connection, query_id) is False
    connection.close()


# --- Инвариант: геймификация не влияет на измерения -------------------------

def _map_of(connection) -> float:
    return runner.evaluate(connection, runner.RunConfig(top_k=20))["summary"]["map"]


def test_metrics_are_immune_to_gamification(conn):
    query_id = qrels.ensure_query(conn, "сеть кабель")
    for doc_id in [row["id"] for row in conn.execute("SELECT id FROM documents")][:2]:
        qrels.set_judgement(conn, query_id, doc_id, 2)

    baseline = _map_of(conn)

    # покупаем всё подряд, берём джокер, доводим паука до обиды, напиваемся
    economy.earn(conn, 5000, "test", lemma="сеть")
    for item in economy.RELIEFS:
        economy.record_purchase(conn, item["code"])
    for word in economy.STOPWORDS_FOR_SALE:
        economy.record_purchase(conn, economy.stopword_code(word))
    jokers.take(conn, jokers.offer(conn)[0]["code"])
    for _ in range(mischief.SULK_AFTER + 10):
        mischief.note_search(conn)
        mischief.bump_streak(conn)
    companion.feed(conn, "judge", 30)

    assert _map_of(conn) == pytest.approx(baseline, abs=1e-12)


def test_evaluation_ignores_active_jokers(conn):
    """Активный у пользователя джокер не должен попадать в прогон метрик."""
    clean = runner.run_query(conn, "сеть кабель", runner.RunConfig(top_k=20))

    offered = [item["code"] for item in jokers.offer(conn)]
    jokers.take(conn, offered[0])
    assert jokers.active_jokers(conn), "джокер действительно активен"

    assert runner.run_query(conn, "сеть кабель", runner.RunConfig(top_k=20)) == clean


def test_joker_config_applies_only_when_named(conn):
    """На /metrics/compare те же коды работают — но лишь по явному указанию."""
    plain = runner.run_query(conn, "сеть кабель", runner.RunConfig(top_k=20))
    short = runner.run_query(
        conn, "сеть кабель", runner.RunConfig(top_k=20, joker="short-doc")
    )
    assert short, "конфигурация-джокер даёт свою выдачу"
    # а прогон без указания кода остаётся прежним
    assert runner.run_query(conn, "сеть кабель", runner.RunConfig(top_k=20)) == plain
