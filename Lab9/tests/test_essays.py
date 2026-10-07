"""Сочинения: состав коллекции, абзацы, счёт предложений, поиск слова, поиск по названию."""

from __future__ import annotations

import pytest

from sluhach import config
from sluhach.essays import sentences, stem
from sluhach.text import tokens


def test_collection_has_five_essays_per_language(collection):
    assert len(collection) == 10
    for language in config.LANGUAGE_CODES:
        essays = collection.by_language(language)
        assert len(essays) == 5
        assert all(essay.language == language and essay.title and essay.about for essay in essays)


def test_essays_are_about_literature(collection):
    titles = {essay.title for essay in collection}
    assert {"Die Räuber", "Die Verwandlung", "Евгений Онегин", "Мастер и Маргарита"} <= titles
    assert all(essay.source.get("url", "").startswith("https://") and essay.source.get("license") for essay in collection)


def test_paragraphs_and_sections(collection):
    essay = collection.get("de-lit-raeuber")
    paragraphs = essay.paragraphs
    assert len(paragraphs) == essay.stats.paragraphs == 28
    assert [p.index for p in paragraphs] == list(range(28))
    assert paragraphs[0].section == "Inhalt" and paragraphs[0].opens_section
    assert paragraphs[2].section == "Zusammenfassung der Handlung" and paragraphs[2].opens_section
    assert not paragraphs[3].opens_section and paragraphs[3].section == paragraphs[2].section
    assert not any(p.text.startswith("#") or "\n" in p.text for p in paragraphs)
    assert essay.stats.sections == sum(p.opens_section for p in paragraphs) == 10


def test_stats_are_plausible(collection):
    for essay in collection:
        stats = essay.stats
        assert 20 <= stats.paragraphs <= 60
        assert 2000 <= stats.words <= 3200
        assert stats.paragraphs <= stats.sentences <= stats.words / 8, essay.id


@pytest.mark.parametrize("paragraph, language, count", [
    ("Пушкин начал роман в 1823 г. в Кишинёве. Закончил в 1831 году.", "ru", 2),
    ("Роман высоко оценил В. Г. Белинский. Он назвал его энциклопедией.", "ru", 2),
    ("В книге есть и др. Герои. Их много.", "ru", 2),
    ("Он спросил: «Кто там?» Никто не ответил.", "ru", 2),
    ("Одно предложение без точки", "ru", 1),
    ("Die Handlung beginnt am 4. Mai 1771. Sie endet 1772.", "de", 2),
    ("Im 19. Jahrhundert war das Werk beliebt. Heute gilt es als Klassiker.", "de", 2),
    ("Der Amtmann S. hat neun Kinder. Werther besucht ihn.", "de", 2),
    ("Vgl. Kapitel drei. Dort steht mehr.", "de", 2),
    ("Was ist das? Niemand weiß es! Wirklich niemand.", "de", 3),
])
def test_sentences(paragraph, language, count):
    assert len(sentences(paragraph, language)) == count


def test_sentences_keep_text():
    paragraph = "Первое предложение. Второе, подлиннее! Третье?"
    assert sentences(paragraph, "ru") == ["Первое предложение.", "Второе, подлиннее!", "Третье?"]


def test_stem():
    assert stem("дуэль") == "дуэл" and stem("raeuber") == "raeub" and stem("кот") == "кот"


def test_find_word_in_all_its_forms(collection):
    found = collection.get("ru-lit-onegin").find("дуэль")
    assert found.count == 3 and "дуэли" in found.forms
    assert list(found.paragraphs) == sorted(set(found.paragraphs))

    found = collection.get("de-lit-raeuber").find("räuber")
    assert found.count >= 20 and {"Räuber", "Räubern", "Räuberbande"} <= set(found.forms)
    assert collection.get("de-lit-raeuber").find("raeuber").count == found.count        # умлаут или «ae» — одно слово


def test_find_missing_word(collection):
    found = collection.get("de-lit-raeuber").find("Elefant")
    assert found.count == 0 and found.paragraphs == () and found.nearest(3) is None
    assert collection.get("de-lit-raeuber").find("").count == 0


def test_find_nearest_goes_forward_and_wraps(collection):
    found = collection.get("ru-lit-onegin").find("дуэль")
    first, last = found.paragraphs[0], found.paragraphs[-1]
    assert found.nearest(0) == first
    assert found.nearest(first) == first
    assert found.nearest(last + 1) == first              # после последнего вхождения — снова первое


def test_numbers_and_neighbours(collection):
    first = collection.by_number("de", 1)
    assert first.id == "de-lit-raeuber" and collection.number(first) == 1
    assert collection.by_number("de", 6) is None and collection.by_number("de", 0) is None
    assert collection.neighbour(first, -1) is None
    assert collection.neighbour(first, +1).id == collection.by_number("de", 2).id
    assert collection.neighbour(collection.by_number("ru", 5), +1) is None
    assert collection.get("нет такого") is None and collection.get(None) is None


@pytest.mark.parametrize("phrase, language, essay_id", [
    ("über die räuber", "de", "de-lit-raeuber"),
    ("räuber", "de", "de-lit-raeuber"),
    ("schiller", "de", "de-lit-raeuber"),
    ("den aufsatz über kafka", "de", "de-lit-verwandlung"),
    ("die leiden des jungen werthers", "de", "de-lit-werther"),
    ("über goethe", "de", "de-lit-werther"),
    ("effi briest", "de", "de-lit-effi"),
    ("im westen nichts neues", "de", "de-lit-westen"),
    ("про евгения онегина", "ru", "ru-lit-onegin"),
    ("онегина", "ru", "ru-lit-onegin"),
    ("сочинение о мастере и маргарите", "ru", "ru-lit-master"),
    ("мёртвые души", "ru", "ru-lit-souls"),
    ("про раскольникова", "ru", "ru-lit-crime"),
    ("горе от ума", "ru", "ru-lit-woe"),
    ("про чацкого", "ru", "ru-lit-woe"),
])
def test_lookup_by_title_hero_or_author(collection, phrase, language, essay_id):
    assert collection.lookup(tokens(phrase), language).id == essay_id


@pytest.mark.parametrize("phrase, language", [
    ("про слона", "ru"), ("сочинение", "ru"), ("", "ru"), ("über den elefanten", "de"), ("drei", "de"),
    ("про онегина", "de"),                     # русское сочинение в немецком списке не ищется
])
def test_lookup_finds_nothing(collection, phrase, language):
    assert collection.lookup(tokens(phrase), language) is None


def test_content_for_the_page(collection):
    content = collection.get("ru-lit-woe").content()
    assert content["title"] == "Горе от ума" and len(content["items"]) == content["paragraphs"]
    assert content["items"][0]["section"] and content["items"][1]["section"] == ""
    assert all(item["index"] == i for i, item in enumerate(content["items"]))
