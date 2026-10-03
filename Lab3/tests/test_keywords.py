"""Реферат в виде списка ключевых слов: именные группы и иерархия."""

from __future__ import annotations

from izbornik import keywords, weights as w
from izbornik.keywords import _contains_compound, _derived
from izbornik.text.analysis import analyze

RU = (
    "Нейронная сеть обучается на данных. Искусственная нейронная сеть состоит из слоёв. "
    "Каждая нейронная сеть имеет параметры. Параметры нейронных сетей подбираются автоматически. "
    "Искусственная нейронная сеть решает задачи. Сеть обрабатывает данные. База данных хранит данные. "
    "База данных растёт. Лазерный луч и синий лазер описаны. Лазерный луч опасен. Синий лазер дорог. "
    "Лазер светит."
)
RU_OTHER = "Кошка спит на диване. Собака гуляет во дворе. Погода хорошая."

DE = (
    "Die Datenbank speichert Daten. Ein Datenbanksystem verwaltet die Datenbank. "
    "Das Datenbanksystem ist schnell. Die relationale Datenbank nutzt Tabellen. "
    "Eine relationale Datenbank ist verbreitet. Der Sohn liest. Die Versöhnung gelingt. Die Versöhnung hält."
)
DE_OTHER = "Der Hund bellt. Die Katze schläft. Das Wetter ist schön."


def extract(text, other, language):
    doc = analyze(text, language, "doc")
    stats = w.CorpusStats.from_documents([doc, analyze(other, language, "other")])
    return keywords.extract(doc, w.term_weights(doc, stats), top=6, children=5)


def find(summary, text):
    for top in summary.tree:
        for _, kw in top.walk():
            if kw.text == text:
                return kw
    return None


def test_russian_hierarchy():
    summary = extract(RU, RU_OTHER, "ru")
    network = find(summary, "сеть")
    assert network is not None and network.kind == "word"
    child_texts = [c.text for c in network.children]
    assert "нейронная сеть" in child_texts
    neural = find(summary, "нейронная сеть")
    assert any(c.text == "искусственная нейронная сеть" for c in neural.children)


def test_russian_genitive_group_in_nominative_head():
    summary = extract(RU, RU_OTHER, "ru")
    assert find(summary, "база данных") is not None


def test_derived_adjective_attaches_to_noun():
    summary = extract(RU, RU_OTHER, "ru")
    laser = find(summary, "лазер")
    assert laser is not None
    texts = {c.text for c in laser.children}
    assert {"лазерный луч", "синий лазер"} <= texts


def test_german_compounds_and_adjective_groups():
    summary = extract(DE, DE_OTHER, "de")
    database = find(summary, "Datenbank")
    assert database is not None
    texts = {c.text for c in database.children}
    assert "Datenbanksystem" in texts
    assert "relationale Datenbank" in texts


def test_compound_rules():
    assert _contains_compound("datenbanksystem", "datenbank")
    assert _contains_compound("lieblingssohn", "sohn")
    assert not _contains_compound("versohn", "sohn")          # Versöhnung — не «Sohn»
    assert _derived("лазерный", "лазер")
    assert not _derived("сетевой", "сеть")


def test_roundtrip_to_dict():
    summary = extract(RU, RU_OTHER, "ru")
    again = keywords.KeywordSummary.from_dict(summary.to_dict())
    assert again.texts() == summary.texts()
