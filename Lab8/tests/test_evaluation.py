"""Проверочные наборы и меры."""

from __future__ import annotations

import pytest

from glashatai import evaluation as ev
from glashatai.articles import Collection


def test_measures():
    assert ev.words("Der Über-Setzer, 12 Mal!") == ["der", "über", "setzer", "12", "mal"]
    assert ev.edit_distance(list("kitten"), list("sitting")) == 3
    assert ev.wer("eins zwei drei", "eins drei") == (1, 3)
    assert ev.wer("eins zwei", "eins zwei") == (0, 2)
    assert ev.simplify_phonemes("ˈtaːk ɾ ʔ") == ["t", "a", "ː", "k", "r"]


def test_gold_set_is_well_formed():
    cases = ev.load_gold()
    assert len(cases) >= 120
    assert set(c.category for c in cases) == set(ev.CATEGORY_NAMES)
    assert all(c.expected for c in cases)


def test_normalization_report(reader):
    report = ev.normalization(reader)
    assert report["summary"]["accuracy"] == 1.0 and report["failures"] == []
    assert report["categories"]["satz"]["cases"] == 12


def test_leftovers_on_articles(reader):
    found = ev.leftovers(reader, Collection())
    assert found["tokens"] > 10000 and found["changed"] > 500
    assert found["left"] == 0 and found["dropped"] <= 3


def test_sentence_sets_are_disjoint(reader):
    collection = Collection()
    dev = {s.text for s in ev.dev_sentences(reader, collection)}
    test = ev.test_sentences(reader, collection, per_article=10)
    assert len(dev) == 24 and len(test) >= 45
    assert not dev & {s.text for s in test}
    assert all(not any(t.kind in ev.NOT_FOR_ASR for t in s.tokens) for s in test)
    # тот же набор при повторном запуске
    assert [s.text for s in test] == [s.text for s in ev.test_sentences(reader, collection, per_article=10)]


def test_article_words_exclude_lexicon_terms(reader):
    found = ev.article_words(Collection(), reader)
    assert len(found) > 1000
    assert "Software" not in found and "RDF" not in found and "bzw" not in found
    assert "Compiler" not in found


def test_g2p_against_espeak(piper, reader):
    report = ev.g2p(Collection(), reader, piper)
    assert report["words"] > 1000
    assert report["per_plain"] < 0.12 and report["stress"] > 0.75


def test_evaluation_voices(speaker):
    voices = ev.evaluation_voices(speaker)
    assert "formant:karl" in voices and not any("#" in v and not v.endswith("#neutral") for v in voices)
    assert not any(v.startswith("browser:") for v in voices)


@pytest.fixture(scope="module")
def recognizer():
    from glashatai.asr import Recognizer

    found = Recognizer()
    if not found.available():
        pytest.skip("нет модели Vosk: python tools/get_voices.py --vosk")
    return found


def test_neural_voice_is_intelligible(piper, recognizer, speaker, reader):
    sentences = ev.test_sentences(reader, Collection(), per_article=1)
    result = ev.intelligibility(speaker, recognizer, ["piper:de_DE-thorsten-medium"], sentences)
    assert result["piper:de_DE-thorsten-medium"]["wer"] < 0.35
