"""Оценка качества: BLEU, chrF и эталонные переводы. Меры — в процентах (0…100), как их принято
приводить в работах по машинному переводу."""

from __future__ import annotations

import pytest

from dragoman import evaluation
from dragoman.collection import Collection


def test_bleu_of_identical_text_is_100():
    text = ["Der Compiler übersetzt den Quellcode in Maschinencode ."]
    result = evaluation.bleu(text, text)
    assert result["bleu"] == pytest.approx(100.0) and result["bp"] == pytest.approx(1.0)


def test_bleu_known_value():
    # 7 слов гипотезы, совпадения: 1-грамм 5/7, 2-грамм 3/6, 3-грамм 1/5, 4-грамм 0/4 → без сглаживания 0
    hyp = ["Der Compiler übersetzt die Programm schnell heute"]
    ref = ["Der Compiler übersetzt das Programm schnell ."]
    result = evaluation.bleu(hyp, ref)
    assert result["precisions"][0] == pytest.approx(100 * 5 / 7)
    assert result["precisions"][1] == pytest.approx(100 * 3 / 6)
    assert result["bleu"] == 0.0


def test_bleu_brevity_penalty():
    ref = ["Der Compiler übersetzt den gesamten Quellcode sehr schnell ."]
    short = evaluation.bleu(["Der Compiler übersetzt ."], ref)
    assert short["bp"] < 1 and short["ratio"] < 1


def test_bleu_is_case_sensitive():
    assert evaluation.bleu(["der compiler"], ["Der Compiler"])["precisions"][0] == 0


def test_sentence_bleu_is_smoothed():
    value = evaluation.sentence_bleu("Der Compiler übersetzt Code", "Der Compiler übersetzt den Code")
    assert 0 < value < 100


def test_chrf_rewards_shared_stems():
    ref = "mit neuronalen Netzen"
    close = evaluation.chrf("mit neuronales Netz", ref)
    far = evaluation.chrf("durch künstliche Systeme", ref)
    assert evaluation.chrf(ref, ref) == pytest.approx(100.0)
    assert close > 60 > far


def test_references_are_aligned_with_the_collection(translator):
    """Эталон i-го предложения документа — перевод именно i-го предложения после сегментации."""
    rows = evaluation.load_references()
    assert len(rows) == 120
    collection = Collection()
    assert {r["doc"] for r in rows} == {e.id for e in collection}
    for entry in collection:
        doc = translator.analyzer.analyze(collection.text(entry.id))
        for row in (r for r in rows if r["doc"] == entry.id):
            assert doc.sentences[row["index"]].text == row["en"], (entry.id, row["index"])


def test_run_compares_modes(translator):
    collection = Collection()
    collection.entries = [collection.get("cs-compiler"), collection.get("lit-gatsby")]
    result = evaluation.run(translator, collection)
    assert result["references"] == 20
    for group in ("all", "cs", "lit"):
        for mode in ("transfer", "direct"):
            scores = result["groups"][group][mode]
            assert 0 < scores["bleu"] < 100 and 0 < scores["chrf"] < 100
    overall = result["groups"]["all"]
    # перевод с трансфером лучше пословного
    assert overall["transfer"]["bleu"] > overall["direct"]["bleu"]
    assert overall["transfer"]["chrf"] > overall["direct"]["chrf"]
    assert overall["wins"]["transfer"] > overall["wins"]["direct"]
    # правила словообразования повышают долю переведённых слов
    assert result["coverage"]["transfer"] >= result["coverage"]["no_rules"]
