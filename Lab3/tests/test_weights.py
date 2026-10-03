"""Формулы методички на примере, посчитанном вручную.

Коллекция из трёх документов:
    A: «Кот ловит мышь. Кот спит.»
    B: «Собака ловит кота.»
    C: «Мышь ест сыр.»          («ест» → «есть» — стоп-слово)

Для A: tf(кот) = 2 = tf_max; df(кот) = df(ловить) = df(мышь) = 2, df(спать) = 1; |DB| = 3.
    w(кот)    = 0,5 · (1 + 2/2) · ln(3/2) = 0,405465
    w(ловить) = w(мышь) = 0,5 · (1 + 1/2) · ln(3/2) = 0,304099
    w(спать)  = 0,5 · (1 + 1/2) · ln 3 = 0,823959
    Score(S₁) = 0,405465 + 2 · 0,304099 = 1,013663; Posd = Posp = 1
    Score(S₂) = 0,405465 + 0,823959 = 1,229424;  BD = BP = 16, |D| = |P| = 25
    Posd(S₂) = Posp(S₂) = 1 − 16/25 = 0,36;  вес S₂ = 1,229424 · 0,36² = 0,159333
"""

from __future__ import annotations

import math

import pytest

from izbornik import weights as w
from izbornik.summary import build
from izbornik.text.analysis import analyze


@pytest.fixture(scope="module")
def toy():
    a = analyze("Кот ловит мышь. Кот спит.", "ru", "A")
    b = analyze("Собака ловит кота.", "ru", "B")
    c = analyze("Мышь ест сыр.", "ru", "C")
    return a, w.CorpusStats.from_documents([a, b, c])


def test_term_frequencies(toy):
    a, stats = toy
    assert a.tf == {"кот": 2, "ловить": 1, "мышь": 1, "спать": 1}
    assert a.tf_max == 2
    assert stats.n_docs == 3
    assert stats.df["кот"] == 2 and stats.df["мышь"] == 2 and stats.df["спать"] == 1
    assert "есть" not in stats.df


def test_term_weights(toy):
    a, stats = toy
    weights = w.term_weights(a, stats)
    assert weights["кот"].weight == pytest.approx(0.5 * 2 * math.log(1.5))
    assert weights["ловить"].weight == pytest.approx(0.304099, abs=1e-6)
    assert weights["мышь"].weight == pytest.approx(0.304099, abs=1e-6)
    assert weights["спать"].weight == pytest.approx(0.823959, abs=1e-6)


def test_sentence_scores_and_positions(toy):
    a, stats = toy
    scores = w.sentence_scores(a, w.term_weights(a, stats))
    s1, s2 = scores
    assert s1.score == pytest.approx(1.013663, abs=1e-6)
    assert (s1.posd, s1.posp) == (1.0, 1.0)
    assert s2.score == pytest.approx(1.229424, abs=1e-6)
    assert s2.posd == pytest.approx(0.36) and s2.posp == pytest.approx(0.36)
    assert s2.weight == pytest.approx(0.159333, abs=1e-6)
    assert s1.contributions["кот"] == pytest.approx(0.405465, abs=1e-6)


def test_term_in_every_document_has_zero_weight():
    a = analyze("Модель данных. Модель строится.", "ru", "A")
    b = analyze("Модель проста.", "ru", "B")
    weights = w.term_weights(a, w.CorpusStats.from_documents([a, b]))
    assert weights["модель"].weight == 0.0


def test_selection_keeps_text_order_and_breaks_ties_by_position():
    scores = [w.SentenceScore(i, 0, 1, 1, weight, 1) for i, weight in enumerate([1.0, 5.0, 3.0, 5.0, 0.5])]
    assert w.select(scores, 2) == [1, 3]
    assert w.select(scores, 3) == [1, 2, 3]
    assert w.select(scores, 10) == [0, 1, 2, 3, 4]
    assert w.ranks(scores) == {1: 1, 3: 2, 2: 3, 0: 4, 4: 5}


def test_new_document_is_added_to_collection(toy):
    _, stats = toy
    new = analyze("Кот и сыр.", "ru", "")
    extended = stats.including(new)
    assert extended.n_docs == 4
    assert extended.df["сыр"] == 2
    assert stats.including(analyze("Кот.", "ru", "A")) is stats   # документ коллекции не добавляется


def test_build_returns_both_sections(toy):
    a, stats = toy
    result = build(a, stats, 1)
    summary = result.summary
    assert [s.index for s in summary.sentences] == [0]
    assert summary.stats["db_docs"] == 3
    assert summary.sentences[0].rank == 1
    assert summary.keywords.tree, "реферат в виде ключевых слов пуст"
