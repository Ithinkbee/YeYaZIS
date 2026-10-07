"""Диктовка: слова-знаки, сборка текста, заглавные буквы, хранение надиктованного, ход диктовки."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from sluhach import config, dictation
from sluhach.dictation import DictationError, Dictations, Lexicon, Mark
from sluhach.essays import Collection
from sluhach.reactions import Draft, Reaction, Reactor, Session

NOW = datetime(2026, 10, 6, 14, 5)


@pytest.fixture(scope="module")
def lexicon(collection):
    return Lexicon(collection)


def write(text, phrase, language="ru", lexicon=None, period=True):
    return dictation.write(text, phrase, language, lexicon, period)


# --- слова-знаки ---------------------------------------------------------------------

@pytest.mark.parametrize("language", config.LANGUAGE_CODES)
def test_every_spoken_mark_is_understood(language):
    """Подсказка страницы не обещает лишнего: каждое её слово действительно даёт знак."""
    for words, sign in dictation.SPOKEN[language]:
        parsed = dictation.parse(words, language)
        assert len(parsed) == 1 and isinstance(parsed[0], Mark), words
        assert parsed[0].text == (dictation.PARAGRAPH if sign == "¶" else sign), words


@pytest.mark.parametrize("phrase, language, expected", [
    # так знаки слышит распознаватель (проверено на озвученных фразах)
    ("он задумался многоточие новые абзац татьяна", "ru", "Он задумался…\n\nТатьяна."),
    ("с красные строки чацкий приезжает", "ru", "Чацкий приезжает."),
    ("werther liebt lotte komme aber lotte ist verlobt punkt", "de", "Werther liebt lotte, aber lotte ist verlobt."),
    ("er dachte nach drei punkte neue absatz effi", "de", "Er dachte nach…\n\nEffi."),
    ("zitat anfangen ich komme wieder zitat ende", "de", "„Ich komme wieder“."),
    ("erstens strichpunkt zweitens semikolon drittens", "de", "Erstens; zweitens; drittens."),
])
def test_marks_as_the_recognizer_hears_them(phrase, language, expected):
    assert write("", phrase, language) == expected


@pytest.mark.parametrize("phrase, language, expected", [
    ("его точка зрения ясна", "ru", "Его точка зрения ясна."),               # «точка зрения» — не знак
    ("это точка опоры точка", "ru", "Это точка опоры."),
    ("das ist der punkt", "de", "Das ist der punkt."),                       # „der Punkt“ — слово
    ("kommen wir zum punkt punkt", "de", "Kommen wir zum punkt."),
    ("ich komme wieder komma sagte er", "de", "Ich komme wieder, sagte er."),  # „ich komme“ — глагол
])
def test_mark_words_in_their_own_meaning(phrase, language, expected):
    assert write("", phrase, language) == expected


def test_marks_of_another_language_are_plain_words():
    assert write("", "punkt komma", "ru") == "Punkt komma."
    assert write("", "точка запятая", "de") == "Точка запятая."


# --- сборка текста ----------------------------------------------------------------------

def test_sentence_starts_with_a_capital_and_ends_with_a_period():
    text = write("", "татьяна любит онегина")
    assert text == "Татьяна любит онегина."
    assert write(text, "онегин уехал") == "Татьяна любит онегина. Онегин уехал."


def test_named_mark_replaces_the_period_put_after_the_last_phrase():
    """Пауза оказалась не концом предложения: фразу начинают со слова «запятая»."""
    text = write("Онегин уехал.", "запятая и татьяна осталась одна")
    assert text == "Онегин уехал, и татьяна осталась одна."
    assert write("Кто виноват.", "вопросительный знак") == "Кто виноват?"
    assert write("Он ушёл.", "точка") == "Он ушёл."                           # вторая точка не ставится


def test_period_is_not_added_where_the_sentence_goes_on():
    assert write("", "онегин запятая") == "Онегин,"
    assert write("Онегин,", "добрый мой приятель") == "Онегин, добрый мой приятель."
    assert write("", "роман тире") == "Роман —"
    assert write("", "он сказал двоеточие") == "Он сказал:"
    assert write("", "что это вопросительный знак") == "Что это?"


def test_without_the_automatic_period():
    text = write("", "татьяна любит онегина", period=False)
    assert text == "Татьяна любит онегина"
    assert write(text, "и пишет ему письмо точка", period=False) == "Татьяна любит онегина и пишет ему письмо."
    assert write("Первый", "новый абзац второй", period=False) == "Первый\n\nВторой"


def test_quotes_and_direct_speech():
    assert write("", "он сказал двоеточие открыть кавычки я вернусь закрыть кавычки") == "Он сказал: «Я вернусь»."
    assert write("", "роман открыть кавычки мёртвые души закрыть кавычки написан гоголем") == \
        "Роман «мёртвые души» написан гоголем."
    assert write("", "открыть кавычки горе от ума закрыть кавычки точка") == "«Горе от ума»."
    assert write("«Быть или не быть?»", "спросил он") == "«Быть или не быть?» Спросил он."
    assert write("", "er sagte doppelpunkt anführungszeichen auf ich komme wieder anführungszeichen zu", "de") == \
        "Er sagte: „Ich komme wieder“."


def test_paragraphs():
    text = write("Первый абзац", "новый абзац второй")
    assert text == "Первый абзац.\n\nВторой."                                # незаконченное предложение закрыто точкой
    assert write(text, "новый абзац") == text + "\n\n"
    assert write(text + "\n\n", "третий") == text + "\n\nТретий."
    assert write("", "новый абзац начало") == "Начало."                      # в пустом тексте абзац и так новый


def test_dash_is_spaced_and_differs_by_language():
    assert write("", "роман тире это зеркало") == "Роман — это зеркало."
    assert write("", "der roman gedankenstrich ein spiegel", "de") == "Der roman – ein spiegel."


def test_text_with_real_punctuation_is_kept():
    """Распознаватель браузера ставит знаки сам — они остаются как есть."""
    assert write("", "Онегин, добрый мой приятель.") == "Онегин, добрый мой приятель."
    assert write("Начало.", "И что дальше?") == "Начало. И что дальше?"


def test_marks_without_a_word_to_attach_to_are_dropped():
    assert write("", "запятая") == ""
    assert write("", "точка точка") == ""
    assert write("Абзац.\n\n", "запятая дальше") == "Абзац.\n\nДальше."


def test_hand_edited_text_is_continued_as_is():
    assert write("Написано руками   ", "и дописано голосом") == "Написано руками и дописано голосом."
    assert write("Заголовок\n", "текст") == "Заголовок\nТекст."


def test_difference_restores_the_previous_text():
    for old, phrase in [("", "первая фраза"), ("Первая фраза.", "вторая"), ("Онегин уехал.", "запятая и не вернулся"),
                        ("Абзац.", "новый абзац другой")]:
        new = write(old, phrase)
        common, removed = dictation.difference(old, new)
        assert new[:common] + removed == old
    assert dictation.difference("Онегин уехал.", "Онегин уехал, и не вернулся.") == (12, ".")


def test_clean_and_title():
    assert dictation.clean("  Первый. \r\n\n\n\n  Второй.  \n") == "Первый.\n\nВторой."
    assert len(dictation.clean("а" * (config.MAX_DRAFT_CHARS + 50))) == config.MAX_DRAFT_CHARS
    assert dictation.title_of("Онегин, добрый мой приятель, родился на брегах Невы.\n\nВторой.") == \
        "Онегин, добрый мой приятель, родился…"
    assert dictation.title_of("Коротко.") == "Коротко"
    assert dictation.title_of("# Раздел\n\nТекст") == "Раздел"
    assert len(dictation.title_of("слово " * 3 + "ж" * 200)) <= config.MAX_TITLE_CHARS + 1


# --- заглавные буквы ------------------------------------------------------------------------

def test_lexicon_knows_names_from_the_essays(lexicon):
    russian = lexicon.capitals("ru")
    assert {"онегин", "онегина", "татьяна", "пушкин", "чацкий", "чацкого", "раскольников"} <= russian
    # обычные слова именами не становятся, даже если встречаются в названиях: «Большого театра»
    assert not {"роман", "автор", "любовь", "большого", "великого", "души"} & russian
    german = lexicon.capitals("de")
    assert {"roman", "werther", "lotte", "leben", "autor", "raeuber", "vater", "krieg"} <= german   # существительные
    assert not {"gut", "liebt", "aber", "und", "schoen"} & german


def test_lexicon_restores_capitals(lexicon):
    assert write("", "татьяна любит онегина запятая а онегин любит свободу", "ru", lexicon) == \
        "Татьяна любит Онегина, а Онегин любит свободу."
    assert write("", "werther liebt lotte komma aber lotte ist verlobt", "de", lexicon) == \
        "Werther liebt Lotte, aber Lotte ist verlobt."
    assert lexicon.restore("räuber", "de") == "Räuber" and lexicon.restore("räuber,", "de") == "Räuber,"
    assert lexicon.restore("неведомоеслово", "ru") == "неведомоеслово"
    assert lexicon.restore("ОНЕГИН", "ru") == "ОНЕГИН" and lexicon.restore("iPhone", "de") == "iPhone"
    assert lexicon.restore("онегин", "de") == "онегин"                       # словарь у каждого языка свой


def test_lexicon_ignores_dictated_essays(tmp_path):
    """Надиктованное само написано по словарю и на него влиять не должно."""
    collection = Collection()
    Dictations(collection, tmp_path / "dictated.json").save("ru", "", "Пишу про Табуретку и ещё про Табуретку.")
    assert "табуретку" not in Lexicon(collection).capitals("ru")


# --- хранение надиктованного -----------------------------------------------------------------

@pytest.fixture()
def shelf(tmp_path):
    """Отдельная коллекция и хранилище: общая коллекция тестов не меняется."""
    collection = Collection()
    return collection, Dictations(collection, tmp_path / "dictated.json")


def test_saved_dictation_is_an_essay_like_the_others(shelf):
    collection, store = shelf
    essay = store.save("ru", "", "Татьяна любит Онегина.\n\nОнегин её не любит. Он уезжает.", now=NOW)
    assert essay.dictated and essay.id.startswith("dict-") and essay.created == "06.10.2026 14:05"
    assert essay.title == "Татьяна любит Онегина" and essay.about == "надиктованное сочинение"
    assert [p.text for p in essay.paragraphs] == ["Татьяна любит Онегина.", "Онегин её не любит. Он уезжает."]
    assert (essay.stats.words, essay.stats.sentences, essay.stats.paragraphs) == (9, 3, 2)
    assert collection.get(essay.id) is essay and collection.by_language("ru")[-1] is essay
    assert collection.number(essay) == 6 and collection.by_number("ru", 6) is essay
    assert collection.lookup(["татьяна", "онегина"], "ru") is not None
    assert essay.summary()["dictated"] and not collection.by_language("ru")[0].summary()["dictated"]
    assert essay.find("онегин").count == 2
    german = store.save("de", "Mein Aufsatz", "Werther liebt Lotte.")
    assert german.about == "diktierter Aufsatz" and german.about_ru == "надиктованное сочинение"
    assert collection.by_language("de")[-1] is german and len(collection.by_language("ru")) == 6


def test_dictations_survive_a_restart(shelf, tmp_path):
    _collection, store = shelf
    first = store.save("ru", "Первое", "Текст первого.")
    store.save("de", "", "Zweiter Text.")
    data = json.loads((tmp_path / "dictated.json").read_text(encoding="utf-8"))
    assert [item["title"] for item in data["essays"]] == ["Первое", "Zweiter Text"]

    again = Collection()
    reopened = Dictations(again, tmp_path / "dictated.json")
    assert [essay.title for essay in reopened.all()] == ["Первое", "Zweiter Text"]
    assert again.get(first.id).paragraphs[0].text == "Текст первого." and len(again) == 12


def test_editing_replaces_the_essay_in_place(shelf):
    collection, store = shelf
    first = store.save("ru", "Первое", "Старый текст.", now=NOW)
    second = store.save("ru", "Второе", "Другой текст.")
    edited = store.save("ru", "Первое, исправленное", "Новый текст. Ещё предложение.", first.id)
    assert edited.id == first.id and edited.created == first.created
    assert [essay.title for essay in collection.by_language("ru")[-2:]] == ["Первое, исправленное", "Второе"]
    assert collection.get(first.id).stats.sentences == 2 and len(store.all()) == 2
    # чужой или несуществующий идентификатор — это новое сочинение, а не правка
    assert store.save("ru", "", "Третье.", "ru-lit-onegin").id not in {first.id, second.id, "ru-lit-onegin"}
    assert collection.get("ru-lit-onegin").title == "Евгений Онегин"


def test_removing(shelf):
    collection, store = shelf
    essay = store.save("ru", "", "Текст.")
    assert store.remove("ru-lit-onegin") is None and collection.get("ru-lit-onegin") is not None   # каталог не трогается
    assert store.remove(essay.id) is essay and collection.get(essay.id) is None and store.all() == []
    assert store.remove(essay.id) is None


def test_what_cannot_be_saved(shelf, monkeypatch):
    _collection, store = shelf
    for text in ("", "   \n\n ", "# Только заголовок"):
        with pytest.raises(DictationError) as problem:
            store.save("ru", "Название", text)
        assert problem.value.code == "empty"
    with pytest.raises(DictationError):
        store.save("fr", "", "Texte.")
    monkeypatch.setattr(config, "MAX_DICTATED", 2)
    store.save("ru", "", "Раз.")
    kept = store.save("ru", "", "Два.")
    with pytest.raises(DictationError) as problem:
        store.save("ru", "", "Три.")
    assert problem.value.code == "limit" and problem.value.fields == {"count": 2}
    assert store.save("ru", "", "Два с половиной.", kept.id).id == kept.id          # правка места не требует


def test_spoiled_file_is_ignored(tmp_path):
    path = tmp_path / "dictated.json"
    path.write_text("{ не JSON", encoding="utf-8")
    assert Dictations(Collection(), path).all() == []
    path.write_text(json.dumps({"essays": [{"id": "dict-1", "language": "ru", "title": "Годное", "text": "Текст."},
                                           {"id": "dict-2", "language": "fr", "title": "Чужой язык", "text": "T."},
                                           {"id": "dict-3", "language": "ru", "title": "Пустое", "text": " "},
                                           "мусор"]}), encoding="utf-8")
    assert [essay.title for essay in Dictations(Collection(), path).all()] == ["Годное"]


# --- ход диктовки ---------------------------------------------------------------------------

class Talk:
    """Разговор с системой, у которой есть хранилище диктовок и словарь заглавных букв."""

    def __init__(self, tmp_path, operations, eggs, language: str) -> None:
        self.collection = Collection()
        self.store = Dictations(self.collection, tmp_path / "dictated.json")
        self.reactor = Reactor(self.collection, operations, eggs, self.store, Lexicon(Collection()))
        self.session = Session(language=language)

    def say(self, phrase: str = "", action: str = "") -> Reaction:
        reaction = self.reactor.react(phrase, self.session, NOW, action=action)
        self.session = Session.from_dict(json.loads(json.dumps(reaction.session)), self.collection)   # как со страницы
        return reaction

    @property
    def text(self) -> str | None:
        return self.session.draft.text if self.session.draft else None


@pytest.fixture()
def russian(tmp_path, operations, eggs):
    return Talk(tmp_path, operations, eggs, "ru")


@pytest.fixture()
def german(tmp_path, operations, eggs):
    return Talk(tmp_path, operations, eggs, "de")


def test_dictation_from_start_to_saved_essay(russian):
    russian.say("открой сочинение два")
    start = russian.say("начни диктовку")
    assert start.operation == "dictate" and start.speech == "Диктуйте."      # голосом — коротко: диктовать начнут сразу
    assert "запятая, точка, новый абзац" in start.display and "«конец диктовки»" in start.display
    assert russian.text == "" and russian.session.essay == ""

    written = russian.say("татьяна любит онегина")
    assert written.kind == "dictation" and written.speech == "" and written.display == "Татьяна любит Онегина."
    assert russian.say("запятая но онегин её не любит").display == ", но Онегин её не любит."
    russian.say("новый абзац онегин уезжает вопросительный знак")
    assert russian.text == "Татьяна любит Онегина, но Онегин её не любит.\n\nОнегин уезжает?"

    end = russian.say("конец диктовки")
    assert end.kind == "operation" and end.operation == "dictate_end" and russian.text is None
    essay = russian.collection.get(russian.session.essay)
    assert essay.dictated and essay.title == "Татьяна любит Онегина, но Онегин…"
    assert end.speech == "Сохранил сочинение «Татьяна любит Онегина, но Онегин…»: 10 слов. Оно открыто."
    listed = next(effect for effect in end.effects if effect["type"] == "essays")
    assert listed["language"] == "ru" and [item["id"] for item in listed["items"]][-1] == essay.id
    # с надиктованным работают обычные операции
    assert russian.say("сколько слов").speech == "В сочинении 10 слов, 2 предложения и 2 абзаца."
    assert russian.say("прочитай").speech == "Татьяна любит Онегина, но Онегин её не любит."
    assert russian.say("найди слово онегин").speech.startswith("Слово «Онегин» встречается 3 раза.")
    assert "Номер 6: Татьяна любит Онегина, но Онегин…" in russian.say("список сочинений").speech
    assert russian.say("открой сочинение шесть").operation == "open" and russian.session.essay == essay.id


def test_during_dictation_everything_else_is_text(russian):
    russian.say("начни диктовку")
    for phrase in ("список сочинений", "сколько стоит слон", "который час", "стоп", "начни диктовку"):
        assert russian.say(phrase).kind == "dictation", phrase
    assert russian.text == "Список сочинений. Сколько стоит слон. Который час. Стоп. Начни диктовку."
    assert russian.say("э").kind == "noise" and russian.say("").kind == "silence"
    assert russian.text.endswith("Начни диктовку.")


def test_dictation_commands_do_nothing_outside_it(russian, german):
    assert russian.say("конец диктовки").kind == "echo"
    assert russian.say("удали последнюю фразу").kind == "echo"
    # «закончи диктовку» на три четверти совпадает с «начни диктовку», но диктовку не начинает
    assert russian.say("закончи диктовку").kind == "echo" and russian.text is None
    assert russian.say("закончить диктовку").kind == "echo" and russian.text is None
    assert german.say("diktat beenden").kind == "echo" and german.text is None
    assert russian.say(action="dictate_end").speech == "Диктовка не идёт."
    assert russian.say(action="dictate_undo").speech == "Диктовка не идёт."


def test_erasing_the_last_phrase(russian):
    russian.say(action="dictate")
    russian.say("онегин уехал")
    russian.say("запятая и не вернулся")
    russian.say("это лишнее")
    erased = russian.say("удали последнюю фразу")
    assert erased.operation == "dictate_undo" and erased.speech == "" and erased.display == "Стёр: Это лишнее."
    assert russian.text == "Онегин уехал, и не вернулся."
    russian.say("сотри последнюю фразу")
    assert russian.text == "Онегин уехал."                                   # вернулась и точка, заменённая запятой
    russian.say(action="dictate_undo")
    assert russian.text == ""
    assert russian.say(action="dictate_undo").display == "Стирать нечего." and russian.text == ""


def test_recognizer_mistakes_in_dictation_commands(russian, german):
    """Так команды диктовки слышит Vosk."""
    russian.say("начать диктовку")
    russian.say("первая фраза")
    russian.say("вторая фраза")
    assert russian.say("смотри последнюю фразу").operation == "dictate_undo"         # «сотри последнюю фразу»
    assert russian.say("конец диктовку").operation == "dictate_end"                  # «конец диктовки»
    german.say("ich möchte diktieren")
    german.say("erster satz")
    assert german.say("ende des diktat").operation == "dictate_end"                  # „Ende des Diktats“
    assert german.collection.get(german.session.essay).title == "Erster Satz"


def test_german_dictation(german):
    assert german.say("diktat starten").speech == "Diktieren Sie."
    german.say("werther liebt lotte komma aber lotte ist verlobt")
    german.say("neuer absatz er schreibt briefe doppelpunkt anführungszeichen auf ich leide anführungszeichen zu")
    assert german.text == "Werther liebt Lotte, aber Lotte ist verlobt.\n\nEr schreibt Briefe: „Ich leide“."
    end = german.say("diktat beenden")
    assert end.speech == "Gespeichert: Aufsatz „Werther liebt Lotte, aber Lotte…“, 12 Wörter. Er ist jetzt geöffnet."
    assert end.gloss == "Сохранил сочинение «Werther liebt Lotte, aber Lotte…»: 12 слов. Оно открыто."
    assert german.say("wie viele wörter").speech == "Der Aufsatz hat 12 Wörter, 2 Sätze und 2 Absätze."


def test_title_and_hand_edits_come_from_the_page(russian):
    russian.say(action="dictate")
    russian.say("первая фраза")
    # страница прислала название и поправленный руками текст; шаги стирания к нему уже не подходят
    russian.session.draft.title = "  Моё   сочинение "
    russian.session.draft.text = "Первая фраза, исправленная."
    russian.session.draft.undo = []
    russian.say("вторая фраза")
    assert russian.text == "Первая фраза, исправленная. Вторая фраза."
    russian.say(action="dictate_end")
    assert russian.collection.get(russian.session.essay).title == "Моё сочинение"


def test_empty_dictation_saves_nothing(russian):
    russian.say("начни диктовку")
    before = len(russian.collection)
    end = russian.say("конец диктовки")
    assert end.speech == "Диктовка окончена. Сохранять нечего." and russian.text is None
    assert len(russian.collection) == before and not end.effects


def test_editing_a_dictated_essay(russian):
    russian.say(action="dictate")
    russian.say("первая версия")
    russian.say(action="dictate_end")
    essay = russian.session.essay
    # страница открывает сочинение для правки: текст и идентификатор — в черновике
    russian.session.draft = Draft(text="Первая версия.", title="Заново", essay=essay)
    russian.session.essay = ""
    russian.say("и продолжение")
    russian.say(action="dictate_end")
    assert russian.session.essay == essay and len(russian.store.all()) == 1
    assert russian.collection.get(essay).title == "Заново"
    assert russian.collection.get(essay).paragraphs[0].text == "Первая версия. И продолжение."


def test_full_shelf_keeps_the_draft(russian, monkeypatch):
    monkeypatch.setattr(config, "MAX_DICTATED", 1)
    russian.store.save("ru", "", "Уже есть.")
    russian.say(action="dictate")
    russian.say("ещё одно")
    refused = russian.say(action="dictate_end")
    assert refused.speech == "Надиктованных сочинений уже 1. Удалите лишнее — и я сохраню."
    assert russian.text == "Ещё одно."                                       # текст не пропал


def test_draft_limit(russian, monkeypatch):
    monkeypatch.setattr(config, "MAX_DRAFT_CHARS", 30)
    russian.say(action="dictate")
    russian.say("десять букв текста")
    full = russian.say("и ещё столько же сверху")
    assert full.speech == "Черновик заполнен. Закончите диктовку." and russian.text == "Десять букв текста."


def test_long_sentence_is_not_cut_during_dictation(russian):
    russian.say(action="dictate")
    phrase = " ".join(["слово"] * 120)                                       # длиннее MAX_PHRASE_CHARS
    assert len(phrase) > config.MAX_PHRASE_CHARS
    russian.say(phrase)
    assert russian.text.count("лово") == 120


def test_without_a_store_dictation_just_ends(reactor, collection):
    """Так устроена проверка на озвученных фразах: диктовка в ней сочинений не оставляет."""
    session = Session(language="ru")
    reactor.react("начни диктовку", session, NOW)
    reactor.react("какой-то текст", session, NOW)
    before = len(collection)
    end = reactor.react("конец диктовки", session, NOW)
    assert end.speech == "Диктовка окончена." and session.draft is None and len(collection) == before


def test_no_lexicon_no_capitals(reactor):
    session = Session(language="ru")
    reactor.react("начни диктовку", session, NOW)
    assert reactor.react("татьяна любит онегина", session, NOW).display == "Татьяна любит онегина."


# --- состояние со страницы ---------------------------------------------------------------------

def test_draft_from_the_page_is_checked(collection):
    assert Session.from_dict({"language": "ru"}, collection).draft is None
    assert Session.from_dict({"language": "ru", "draft": "текст"}, collection).draft is None
    draft = Session.from_dict({"language": "ru", "draft": {
        "text": "я" * (config.MAX_DRAFT_CHARS + 10), "title": " Длинное   название " + "ж" * 200,
        "essay": "ru-lit-onegin", "period": 0, "undo": [[5, ""], "мусор", [3, "."], [10 ** 9, ""], [2, "."]]}},
        collection).draft
    assert len(draft.text) == config.MAX_DRAFT_CHARS and len(draft.title) == config.MAX_TITLE_CHARS
    assert draft.title.startswith("Длинное название ж") and draft.period is False
    assert draft.essay == ""                          # сочинение каталога диктовкой не правится
    assert draft.undo == [[2, "."]]                   # негодный шаг отбрасывается вместе с прежними
    empty = Session.from_dict({"language": "de", "draft": {}}, collection).draft
    assert empty == Draft() and empty.period is True


def test_session_with_a_draft_round_trips(collection):
    session = Session(language="de", last_language="de", draft=Draft(text="Text.", title="Titel", undo=[[0, ""]]))
    again = Session.from_dict(json.loads(json.dumps(session.to_dict())), collection)
    assert again == session
