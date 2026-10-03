"""Мера ROUGE и способы отбора предложений."""

from __future__ import annotations

import random

import pytest

from izbornik import evaluation as ev


def test_rouge_on_known_example():
    candidate = [["кот", "ловить", "мышь"]]
    reference = [["кот", "ловить", "птица"], ["мышь"]]
    r1 = ev.rouge(candidate, reference, 1)
    assert r1.r == pytest.approx(3 / 4)
    assert r1.p == pytest.approx(3 / 3)
    r2 = ev.rouge(candidate, reference, 2)
    assert r2.r == pytest.approx(1 / 2)       # «кот ловить» совпала, «ловить птица» — нет
    assert r2.p == pytest.approx(1 / 2)


def test_rouge_clips_repeated_ngrams():
    r1 = ev.rouge([["а", "а", "а"]], [["а"]], 1)
    assert r1.r == 1.0 and r1.p == pytest.approx(1 / 3)


def test_empty_inputs():
    assert ev.rouge([], [["а"]], 1).f == 0.0
    assert ev.rouge([["а"]], [], 1).r == 0.0


@pytest.fixture(scope="module")
def result(collection):
    return collection.summarize("ru-cs-crypto", 10)


def test_all_methods_select_n_sentences(result, collection):
    reference = ev.reference_terms(collection.get("ru-cs-crypto").reference_abstract, "ru")
    for method in ev.METHODS:
        chosen = ev.select(method, result, 10, reference, random.Random(1))
        assert len(chosen) == 10 and chosen == sorted(chosen) and len(set(chosen)) == 10, method


def test_oracle_is_an_upper_bound(result, collection):
    entry = collection.get("ru-cs-crypto")
    reference = ev.reference_terms(entry.reference_abstract, "ru")
    sentences = ev.sentence_terms(result.document)
    value = {}
    for method in ("extraction", "lead", "oracle"):
        picked = [sentences[i] for i in ev.select(method, result, 10, reference)]
        value[method] = ev.rouge(picked, reference, 1).r + ev.rouge(picked, reference, 2).r
    assert value["oracle"] >= value["extraction"]
    assert value["oracle"] >= value["lead"]


def test_evaluate_document_record(collection):
    score = ev.evaluate_document(collection, "de-cs-compiler", 10)
    assert set(score.rouge) == set(ev.METHODS)
    assert 0 <= score.rouge["extraction"]["r1"] <= 1
    assert score.keywords["author_recall"] is None          # у статей Википедии нет авторских ключевых слов
    assert score.timings["summarize_total"] > 0
