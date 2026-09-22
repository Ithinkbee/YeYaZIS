"""Тесты метрик качества поиска на примерах с известным ответом."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arachne import config, db  # noqa: E402
from arachne.evaluation import metrics, qrels  # noqa: E402

# выдача: релевантны документы 1, 2 и 5; документы 3, 4 оценены как нерелевантные
RANKED = [1, 3, 2, 4, 5]
REL_MAP = {1: 2, 2: 1, 5: 1, 3: 0, 4: 0}


def test_precision_and_recall():
    assert metrics.precision(RANKED, REL_MAP) == pytest.approx(3 / 5)
    assert metrics.recall(RANKED, REL_MAP) == pytest.approx(1.0)


def test_precision_at_k():
    assert metrics.precision_at_k(RANKED, REL_MAP, 1) == pytest.approx(1.0)
    assert metrics.precision_at_k(RANKED, REL_MAP, 2) == pytest.approx(0.5)
    assert metrics.precision_at_k(RANKED, REL_MAP, 3) == pytest.approx(2 / 3)


def test_r_precision():
    # релевантных три, среди первых трёх документов их два
    assert metrics.r_precision(RANKED, REL_MAP) == pytest.approx(2 / 3)


def test_f_measure():
    assert metrics.f_measure(0.5, 0.5) == pytest.approx(0.5)
    assert metrics.f_measure(1.0, 0.0) == 0.0


def test_average_precision_manual():
    # попадания на позициях 1, 3, 5: (1/1 + 2/3 + 3/5) / 3
    expected = (1 / 1 + 2 / 3 + 3 / 5) / 3
    assert metrics.average_precision(RANKED, REL_MAP) == pytest.approx(expected)


def test_interpolated_curve_is_monotonic():
    curve = metrics.interpolated_precision(RANKED, REL_MAP)
    assert len(curve) == 11
    values = [value for _, value in curve]
    assert all(values[i] >= values[i + 1] for i in range(len(values) - 1))
    assert values[0] == pytest.approx(1.0)


def test_ndcg_of_ideal_order_is_one():
    ideal = [1, 2, 5, 3, 4]
    assert metrics.ndcg(ideal, REL_MAP) == pytest.approx(1.0)
    assert metrics.ndcg(RANKED, REL_MAP) < 1.0


def test_dcg_manual():
    # только первый документ, релевантность 2: (2^2 - 1) / log2(2) = 3
    assert metrics.dcg([1], REL_MAP) == pytest.approx(3.0)
    # два документа: 3 + (2^1 - 1)/log2(3)
    assert metrics.dcg([1, 2], REL_MAP) == pytest.approx(3 + 1 / math.log2(3))


def test_bpref_penalizes_irrelevant_above_relevant():
    perfect = metrics.bpref([1, 2, 5, 3, 4], REL_MAP)
    shuffled = metrics.bpref(RANKED, REL_MAP)
    assert perfect == pytest.approx(1.0)
    assert shuffled < perfect


def test_empty_result_gives_zeroes():
    result = metrics.evaluate_query([], REL_MAP)
    assert result["precision"] == 0.0
    assert result["ap"] == 0.0
    assert result["ndcg"] == 0.0


def test_macro_average_computes_map():
    first = metrics.evaluate_query([1, 2], {1: 1, 2: 1})
    second = metrics.evaluate_query([3, 1], {1: 1})
    summary = metrics.macro_average([first, second])
    assert summary["map"] == pytest.approx((first["ap"] + second["ap"]) / 2)
    assert summary["queries"] == 2
    assert len(summary["curve"]) == 11


# --- Эталонная разметка -----------------------------------------------------

def test_qrels_load_keeps_numbering_from_csv(tmp_path: Path, monkeypatch):
    """Номера эталонных запросов в базе должны совпадать с номерами в CSV.

    Иначе при повторной загрузке эталона нумерация в таблицах и на графиках
    отчёта уезжает относительно data/eval_queries.csv.
    """
    queries_csv = tmp_path / "eval_queries.csv"
    judgements_csv = tmp_path / "qrels.csv"
    queries_csv.write_text(
        "query_id;text;note\n7;локальная сеть;первый\n9;резервное копирование;второй\n",
        encoding="utf-8",
    )
    judgements_csv.write_text(
        "query_id;doc_slug;rel\n7;lan;2\n9;backup;1\n", encoding="utf-8"
    )
    monkeypatch.setattr(qrels, "EVAL_QUERIES_PATH", queries_csv)
    monkeypatch.setattr(config, "QRELS_PATH", judgements_csv)

    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    try:
        for slug in ("lan", "backup"):
            conn.execute(
                """INSERT INTO documents(path, uri, host, title, text, ext,
                                         date_added, time_added)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (f"C:\\\\node\\\\{slug}.txt", "file:///", "NODE", slug, "текст",
                 ".txt", "01.01.2026", "00:00:00"),
            )
        conn.commit()

        # запрос, добавленный из интерфейса: сдвигает счётчик AUTOINCREMENT
        qrels.ensure_query(conn, "посторонний запрос")

        first = qrels.load_from_csv(conn)
        assert first["judgements"] == 2
        assert [row["id"] for row in qrels.list_queries(conn)] == [7, 9]

        # повторная загрузка не должна менять номера
        qrels.load_from_csv(conn)
        assert [row["id"] for row in qrels.list_queries(conn)] == [7, 9]
        assert qrels.rel_map(conn, 7) and qrels.rel_map(conn, 9)

        # следующий запрос из интерфейса продолжает нумерацию эталона
        assert qrels.ensure_query(conn, "ещё один запрос") == 10
    finally:
        conn.close()
