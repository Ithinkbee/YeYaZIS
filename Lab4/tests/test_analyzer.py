"""Анализ английского текста: теггер, лемматизатор, синтаксический анализатор, деревья.

Модели обучены на корпусах Universal Dependencies (tools/train.py) и лежат в
models/. Здесь — проверки на простых предложениях, где ошибка означает
поломку, а не обычную неточность статистической модели; точность на
тестовых частях корпусов меряет tools/train.py --check.
"""

from __future__ import annotations

import pytest

from dragoman import trees
from dragoman.english import analyzer, tags


@pytest.fixture(scope="module")
def nlp():
    return analyzer.get()


def sentence(nlp, text):
    return nlp.analyze(text).sentences[0]


def test_tags_lemmas_and_tree(nlp):
    s = sentence(nlp, "The compiler translated the programs quickly.")
    assert [w.tag for w in s.words] == ["DT", "NN", "VBD", "DT", "NNS", "RB", "."]
    assert [w.lemma for w in s.words][:5] == ["the", "compiler", "translate", "the", "program"]
    root = s.words[s.root]
    assert root.text == "translated"
    assert {(w.text, w.deprel) for w in s.words if w.head == root.index} >= {
        ("compiler", "nsubj"), ("programs", "obj"), ("quickly", "advmod"), (".", "punct")}


def test_every_sentence_is_a_tree(nlp):
    doc = nlp.analyze("Hamlet is a tragedy written by William Shakespeare. It is his longest play, "
                      "and it remains one of the most performed plays in the world.")
    for s in doc.sentences:
        roots = [w for w in s.words if w.head < 0]
        assert len(roots) == 1
        for w in s.words:                       # от каждого слова путь ведёт к корню, без циклов
            seen, k = set(), w.index
            while k >= 0:
                assert k not in seen
                seen.add(k)
                k = s.words[k].head


def test_passive_and_auxiliaries(nlp):
    s = sentence(nlp, "The program was compiled by the compiler.")
    labels = {w.text: w.deprel for w in s.words}
    assert labels["was"] == "aux:pass" and labels["program"] == "nsubj:pass"
    assert s.words[s.root].text == "compiled"


def test_irregular_lemmas(nlp):
    s = sentence(nlp, "Children wrote better books and went home.")
    lemmas = {w.text: w.lemma for w in s.words}
    assert lemmas["Children"].lower() == "child" and lemmas["wrote"] == "write" and lemmas["went"] == "go"


def test_question_tags_after_do_support(nlp):
    s = sentence(nlp, "What does the parser produce?")
    assert s.words[4].tag == "VB"


def test_clitics_are_not_counted_as_words(nlp):
    s = sentence(nlp, "Shakespeare's play isn't short.")
    assert [w.text for w in s.words if w.counts] == ["Shakespeare", "play", "is", "short"]


def test_segmentation_keeps_layout(nlp):
    doc = nlp.analyze("# Plot\n\nThe prince returns. He meets a ghost.\n\nThe end.")
    assert [s.heading for s in doc.sentences] == [True, False, False, False]
    assert [s.paragraph for s in doc.sentences] == [0, 1, 1, 2]


def test_tag_descriptions_cover_the_tagset():
    for tag in ["NN", "NNS", "NNP", "VB", "VBD", "VBG", "VBN", "VBZ", "JJ", "JJR", "RB", "IN", "DT", "PRP", "MD"]:
        assert tags.describe(tag) and tags.describe(tag) != tag
    assert "мн" in tags.describe("NNS").lower()
    assert tags.describe_deprel("nsubj")


def test_dependency_and_phrase_tree_svg(nlp):
    s = sentence(nlp, "The model learns complex patterns.")
    svg = trees.dependency_svg(s)
    assert svg.startswith("<svg") and "nsubj" in svg and "learns" in svg
    phrases = trees.constituency_svg(s)
    assert phrases.startswith("<svg") and ">S<" in phrases and ">NP<" in phrases and ">VP<" in phrases
