"""Слова, термины, морфология, стоп-слова."""

from __future__ import annotations

from izbornik.text import morphology
from izbornik.text.analysis import analyze


def counted(doc):
    return [t.term for tokens in doc.sentence_tokens for t in tokens if t.counted]


def test_russian_excludes_latin_numbers_and_stopwords():
    doc = analyze("Нейронные сети в Python 3 обучаются за 10 эпох и быстро.", "ru")
    terms = counted(doc)
    assert "нейронный" in terms and "сеть" in terms
    assert "python" not in terms            # латиница в русском тексте не учитывается
    assert "в" not in terms and "и" not in terms
    assert not any(ch.isdigit() for term in terms for ch in term)


def test_german_excludes_cyrillic_and_stopwords():
    doc = analyze("Die Datenbanken speichern Daten, auch бд und der Index.", "de")
    terms = counted(doc)
    assert "datenbank" in terms and "dat" in terms and "index" in terms    # Daten → dat (Snowball)
    assert "die" not in terms and "der" not in terms and "und" not in terms
    assert not any("Ѐ" <= ch <= "ӿ" for term in terms for ch in term)


def test_russian_forms_share_one_term():
    doc = analyze("Сеть работает. Сети работают. Сетей много.", "ru")
    assert doc.tf["сеть"] == 3


def test_german_forms_share_one_stem():
    doc = analyze("Die Datenbank wächst. Viele Datenbanken wachsen.", "de")
    assert doc.tf["datenbank"] == 2


def test_stop_phrases_are_not_counted():
    doc = analyze("Это, в свою очередь, влияет на систему. Очередь в магазине длинная.", "ru")
    # «очередь» в обороте не учитывается, в прямом значении — учитывается
    assert doc.tf["очередь"] == 1


def test_abbreviation_is_a_noun_shown_in_capitals():
    doc = analyze("БЗ содержит знания. Структура БЗ сложна.", "ru")
    assert "бз" in doc.noun_terms
    assert doc.show("бз") == "БЗ"


def test_german_noun_detection_by_capitalization():
    doc = analyze("Das künstliche Netz lernt. Ein neuronales Netz lernt schnell. Netze lernen.", "de")
    assert "netz" in doc.noun_terms
    assert "kunstlich" not in doc.noun_terms


def test_proper_name_resolved_by_document():
    text = ("Евгений скучает в деревне. Евгений уезжает. Письмо Евгения к Татьяне. "
            "Евгения Онегина читают все.")
    doc = analyze(text, "ru")
    assert doc.tf["евгений"] == 4
    assert "евгения" not in doc.tf
    assert doc.show("евгений") == "Евгений"


def test_german_genitive_of_names_merges():
    doc = analyze("Effi heiratet früh. Effis Mutter ist streng. Effi leidet.", "de")
    assert doc.tf["effi"] == 3


def test_script_check():
    assert morphology.script_ok("какой-то", "ru")
    assert not morphology.script_ok("Python", "ru")
    assert morphology.script_ok("Straße", "de")
    assert not morphology.script_ok("сеть", "de")


def test_russian_phrase_form_agrees():
    morph = morphology.for_language("ru")
    assert morph.phrase_form(("нейронных",), "сетей") == "нейронная сеть"
    assert morph.phrase_form(("искусственной", "нейронной"), "сети") == "искусственная нейронная сеть"
    assert morph.person_form(("Татьяны", "Лариной")) == "Татьяна Ларина"


def test_german_adjective_base():
    assert morphology.for_language("de").adjective_base("künstlichen") == "künstliche"
