"""Реакция системы на фразу: операции, пасхалки, повтор, состояние разговора."""

from __future__ import annotations

from datetime import datetime

import pytest

from sluhach import config
from sluhach.reactions import Reaction, Session

NOW = datetime(2026, 10, 6, 14, 5)


class Talk:
    """Разговор: фразы подаются по одной, состояние переходит от фразы к фразе."""

    def __init__(self, reactor, collection, language: str) -> None:
        self.reactor, self.collection = reactor, collection
        self.session = Session(language=language)

    def say(self, phrase: str) -> Reaction:
        reaction = self.reactor.react(phrase, self.session, NOW)
        # состояние возвращается так, как его вернула бы страница
        self.session = Session.from_dict(reaction.session, self.collection)
        return reaction


@pytest.fixture()
def german(reactor, collection):
    return Talk(reactor, collection, "de")


@pytest.fixture()
def russian(reactor, collection):
    return Talk(reactor, collection, "ru")


def effects(reaction: Reaction, kind: str) -> list[dict]:
    return [effect for effect in reaction.effects if effect["type"] == kind]


# --- сочинения -------------------------------------------------------------------

def test_list_names_essays_by_number(german, russian):
    reaction = german.say("Liste der Aufsätze")
    assert reaction.kind == "operation" and reaction.operation == "list" and reaction.title == "Список сочинений"
    assert "Es gibt 5 Aufsätze" in reaction.speech and "Nummer 1: Die Räuber." in reaction.speech
    assert reaction.speech_language == "de" and reaction.gloss.startswith("Сочинений: 5.")
    assert "Номер 1: Евгений Онегин." in russian.say("список сочинений").speech


@pytest.mark.parametrize("phrase, language, essay_id", [
    ("öffne aufsatz vier", "de", "de-lit-verwandlung"),
    ("öffne den dritten aufsatz", "de", "de-lit-effi"),
    ("öffne aufsatz 2", "de", "de-lit-werther"),
    ("öffne den aufsatz über die räuber", "de", "de-lit-raeuber"),
    ("öffne kafka", "de", "de-lit-verwandlung"),
    ("zeige den aufsatz über goethe", "de", "de-lit-werther"),
    ("открой сочинение номер пять", "ru", "ru-lit-master"),
    ("открой третье сочинение", "ru", "ru-lit-souls"),
    ("открой сочинении про евгения онегина", "ru", "ru-lit-onegin"),
    ("открой мёртвые души", "ru", "ru-lit-souls"),
    ("покажи сочинение про раскольникова", "ru", "ru-lit-crime"),
    ("открой сочинение питый", "ru", "ru-lit-master"),          # числительное расслышано с ошибкой
])
def test_open_by_number_title_hero_or_author(reactor, collection, phrase, language, essay_id):
    talk = Talk(reactor, collection, language)
    reaction = talk.say(phrase)
    assert reaction.operation == "open" and talk.session.essay == essay_id and talk.session.paragraph == 0
    assert collection.get(essay_id).title in reaction.speech


def test_open_reply_describes_the_work(german, russian):
    reaction = german.say("öffne aufsatz eins")
    assert reaction.speech == ("Ich öffne den Aufsatz „Die Räuber“: Drama von Friedrich Schiller aus dem Jahr 1781. "
                               "Er hat 28 Absätze.")
    assert reaction.gloss == "Открываю сочинение «Die Räuber»: драма Фридриха Шиллера, 1781 год. В нём 28 абзацев."
    assert reaction.display == reaction.speech
    assert russian.say("открой сочинение один").gloss == ""          # русскому ответу перевод не нужен


def test_open_unknown(german, russian):
    reaction = german.say("öffne aufsatz neun")
    assert reaction.speech == "Aufsatz Nummer 9 gibt es nicht. Es sind nur 5." and german.session.essay == ""
    reaction = russian.say("открой сочинение про слона")
    assert reaction.operation == "open" and "«про слона» в моей паутине нет" in reaction.speech
    assert russian.session.essay == ""


def test_next_and_previous_essay(german):
    german.say("öffne aufsatz eins")
    assert german.say("vorheriger aufsatz").speech == "Das ist der erste Aufsatz der Liste."
    german.say("nächster aufsatz")
    assert german.session.essay == "de-lit-werther"
    german.say("öffne aufsatz fünf")
    assert german.say("nächster aufsatz").speech == "Das ist der letzte Aufsatz der Liste."
    assert german.session.essay == "de-lit-westen"


def test_close(german):
    assert german.say("schließe den aufsatz").speech == "Es ist kein Aufsatz geöffnet."
    german.say("öffne aufsatz zwei")
    assert german.say("zurück zur liste").speech == "Geschlossen. Hier ist wieder die Liste."
    assert german.session.essay == ""


# --- чтение ------------------------------------------------------------------------

def test_reading_speaks_the_paragraph_and_shows_its_beginning(german, collection):
    german.say("öffne aufsatz eins")
    reaction = german.say("lies vor")
    paragraph = collection.get("de-lit-raeuber").paragraphs[0]
    assert reaction.operation == "read"
    assert reaction.speech == "Abschnitt: Inhalt. " + paragraph.text            # раздел называется перед первым абзацем
    assert reaction.display.startswith("Ich lese Absatz 1 von 28: „Das dramatische Schauspiel")
    assert reaction.display.endswith("…“") and len(reaction.display) < 150
    assert reaction.gloss == "читает абзац 1 из 28"
    assert effects(reaction, "read") == [{"type": "read", "index": 0}]


def test_walking_through_paragraphs(russian, collection):
    essay = collection.get("ru-lit-onegin")
    russian.say("открой сочинение один")
    assert russian.say("назад").speech == "Раньше ничего нет: это первый абзац."
    reaction = russian.say("дальше")
    assert russian.session.paragraph == 1 and essay.paragraphs[1].text in reaction.speech
    russian.say("читай дальше")
    assert russian.session.paragraph == 2
    russian.say("назад")
    assert russian.session.paragraph == 1
    russian.say("абзац двадцать три")
    assert russian.session.paragraph == 22
    assert russian.say("читай").speech.endswith(essay.paragraphs[22].text)
    russian.say("в начало")
    assert russian.session.paragraph == 0
    russian.say(f"перейди к абзацу {len(essay.paragraphs)}")
    assert russian.say("дальше").speech == "Дальше ничего нет: это последний абзац."
    assert russian.session.paragraph == len(essay.paragraphs) - 1


def test_section_is_named_only_before_its_first_paragraph(german, collection):
    german.say("öffne aufsatz eins")
    german.say("absatz nummer vier")                    # второй абзац раздела
    paragraph = collection.get("de-lit-raeuber").paragraphs[3]
    assert not paragraph.opens_section and german.say("lies vor").speech == paragraph.text


def test_goto_errors(german):
    german.say("öffne aufsatz eins")
    assert german.say("absatz neunundneunzig").speech == "Absatz 99 gibt es nicht. Der Aufsatz hat nur 28."
    assert german.say("gehe zu absatz kafka").speech == "Die Nummer des Absatzes habe ich nicht verstanden."
    assert german.session.paragraph == 0
    german.say("gehe zu absatz sie bin")                # „sieben“, как его слышит распознаватель
    assert german.session.paragraph == 6


@pytest.mark.parametrize("phrase, language", [
    ("lies vor", "de"), ("weiter", "de"), ("zurück", "de"), ("zum anfang", "de"), ("absatz drei", "de"),
    ("worum geht es", "de"), ("wie viele wörter", "de"), ("suche das wort liebe", "de"), ("nächster aufsatz", "de"),
    ("читай", "ru"), ("дальше", "ru"), ("сколько слов", "ru"), ("найди слово любовь", "ru"),
])
def test_essay_operations_need_an_open_essay(reactor, collection, phrase, language):
    reaction = Talk(reactor, collection, language).say(phrase)
    assert reaction.kind == "operation" and reaction.operation
    assert reaction.speech == ("Öffnen Sie zuerst einen Aufsatz. Sagen Sie: „Liste der Aufsätze“." if language == "de"
                               else "Сначала откройте сочинение. Скажите: «список сочинений».")


# --- разбор сочинения ------------------------------------------------------------------

def test_info_and_count(german, russian):
    german.say("öffne aufsatz eins")
    assert german.say("worum geht es").speech == ("Aufsatz „Die Räuber“: Drama von Friedrich Schiller aus dem Jahr 1781. "
                                                  "Umfang: 2852 Wörter, 149 Sätze und 28 Absätze.")
    assert german.say("wie viele wörter hat der aufsatz").gloss == "В сочинении 2852 слова, 149 предложений и 28 абзацев."
    russian.say("открой сочинение один")
    assert russian.say("сколько слов").speech == "В сочинении 2228 слов, 142 предложения и 45 абзацев."


def test_find_marks_the_word_and_moves_to_it(german, russian):
    german.say("öffne aufsatz eins")
    reaction = german.say("suche das wort räuber")
    assert reaction.operation == "find" and reaction.slot == "räuber"
    assert reaction.speech.startswith("Das Wort „Räuber“ kommt ") and "Die nächste Stelle ist Absatz 5." in reaction.speech
    assert german.session.paragraph == 4
    marks = effects(reaction, "highlight")[0]
    assert {"Räuber", "Räubern", "Räuberbande"} <= set(marks["forms"])

    russian.say("открой сочинение один")
    reaction = russian.say("найди слова дуэль")           # «слово» расслышано как «слова»
    assert reaction.speech == "Слово «дуэль» встречается 3 раза. Ближайшее место — абзац 12."
    assert effects(reaction, "highlight")[0]["forms"] == ["дуэли"]
    russian.say("абзац двадцать два")
    assert "Ближайшее место — абзац 24." in russian.say("найди дуэль").speech      # ищет вперёд от текущего абзаца
    russian.say("абзац сорок")
    assert "Ближайшее место — абзац 12." in russian.say("найди дуэль").speech      # дальше слова нет — снова первое


def test_find_missing_word(german):
    german.say("öffne aufsatz eins")
    german.say("absatz drei")
    reaction = german.say("suche das wort elefant")
    assert reaction.speech == "Das Wort „elefant“ kommt in diesem Aufsatz nicht vor."
    assert effects(reaction, "highlight") == [{"type": "highlight", "forms": []}]
    assert german.session.paragraph == 2                 # с места не ушёл


def test_find_once(german):
    german.say("öffne aufsatz eins")
    assert "kommt einmal vor" in german.say("suche das wort hippokrates").speech


def test_where(german):
    assert german.say("wo bin ich").speech == "Kein Aufsatz ist geöffnet. Sie sehen die Liste."
    german.say("öffne aufsatz zwei")
    german.say("absatz fünf")
    assert german.say("wo sind wir").speech == "Aufsatz „Die Leiden des jungen Werthers“, Absatz 5 von 26."


# --- система ---------------------------------------------------------------------------

def test_help_gives_examples_of_active_operations(german, russian, operations):
    reaction = german.say("was kannst du")
    assert "„liste der aufsätze“, „öffne den aufsatz zwei“, „lies vor“, „weiter“, „suche das wort Liebe“" in reaction.speech
    assert effects(reaction, "cheatsheet")
    operations.update({"find": {"enabled": False}, "read": {"phrases": {"ru": ["огласи"]}}})
    speech = russian.say("что ты умеешь").speech
    assert "«огласи»" in speech and "найди" not in speech         # примеры — из действующего списка


def test_language_switch_answers_in_the_new_language(german):
    german.say("öffne aufsatz eins")
    reaction = german.say("sprich russisch")
    assert reaction.operation == "language" and reaction.speech == "Хорошо, дальше говорю по-русски."
    assert reaction.speech_language == "ru" and reaction.gloss == ""
    assert effects(reaction, "language") == [{"type": "language", "code": "ru"}]
    assert german.session.language == "ru" and german.session.essay == ""     # немецкое сочинение закрыто
    # теперь система понимает русский
    assert german.say("говори по-немецки").speech == "Gut, ab jetzt spreche ich Deutsch."
    assert german.session.language == "de"


def test_language_switch_edge_cases(german, russian):
    assert german.say("sprich deutsch").speech == "Ich spreche schon Deutsch."
    assert german.say("sprich französisch").speech == "Ich kann Deutsch und Russisch. Welche Sprache soll es sein?"
    assert german.session.language == "de"
    assert russian.say("переключи на русский").speech == "Я и так говорю по-русски."
    assert russian.say("язык немецкий").speech_language == "de"


def test_repeat(german):
    assert german.say("wiederhole").speech == "Es gibt noch nichts zu wiederholen."
    said = german.say("öffne aufsatz eins").speech
    assert german.say("noch einmal").speech == said
    assert german.say("wiederhole").speech == said               # «повтори» сам повторяемым не становится


def test_repeat_keeps_the_language_of_the_reply(german):
    german.say("sprich russisch")                                # ответ был по-русски
    german.session.language = "de"
    reaction = german.say("wiederhole")
    assert reaction.speech == "Хорошо, дальше говорю по-русски." and reaction.speech_language == "ru"


def test_time(german, russian):
    assert german.say("wie spät ist es").speech == "Es ist 14 Uhr 5."
    assert russian.say("который час").speech == "Сейчас 14 часов 5 минут."
    assert russian.reactor.react("который час", Session(language="ru"), datetime(2026, 1, 1, 21, 0)).speech == \
        "Сейчас 21 час ровно."
    assert german.reactor.react("wie spät ist es", Session(language="de"), datetime(2026, 1, 1, 9, 0)).speech == \
        "Es ist 9 Uhr."


def test_stop_sleep_and_game_tell_the_page_what_to_do(german, russian):
    assert effects(german.say("halt"), "silence") and effects(russian.say("замолчи"), "silence")
    assert effects(russian.say("не слушай"), "sleep") and effects(german.say("mikrofon aus"), "sleep")
    assert effects(german.say("öffne das spiel"), "navigate") == [{"type": "navigate", "url": "/walk"}]
    assert russian.say("пойдём гулять").speech == "Идём гулять. Только говорите погромче."


def test_service_replies_are_not_repeated(german):
    german.say("öffne aufsatz eins")
    german.say("halt")
    assert german.say("wiederhole").speech.startswith("Ich öffne den Aufsatz")


# --- пасхалки, повтор, шум ------------------------------------------------------------------

def test_easter_egg_replaces_the_echo(russian, german):
    reaction = russian.say("Сколько стоит слон?")
    assert reaction.kind == "egg" and reaction.speech == "Вам тут не рынок и не цирк." == reaction.display
    assert reaction.operation == "" and reaction.speech_language == "ru"
    assert german.say("wie viel kostet ein elefant").speech == "Hier ist weder ein Markt noch ein Zirkus."
    assert russian.say("повтори").speech == "Вам тут не рынок и не цирк."


def test_easter_egg_survives_recognition(russian):
    assert russian.say("пафнутий сколько стоит слон").kind == "egg"
    assert russian.say("сколько стоит слом").kind == "egg"               # ошибка в букве
    assert russian.say("сколько стоит билет").kind == "echo"             # а это уже другая фраза


def test_easter_egg_beats_an_operation(russian, eggs):
    eggs.add("Который час?", "Время собирать мух.")
    reaction = russian.say("который час")
    assert reaction.kind == "egg" and reaction.speech == "Время собирать мух."


def test_easter_egg_answer_may_be_in_another_language(russian, eggs):
    eggs.add("Скажи по-немецки спасибо", "Vielen Dank!")
    assert russian.say("скажи по-немецки спасибо").speech_language == "de"


def test_unknown_phrase_is_repeated(russian, german):
    reaction = russian.say("Сегодня хорошая погода")
    assert reaction.kind == "echo" and reaction.speech == "Повторяю: Сегодня хорошая погода."
    assert reaction.operation == "" and reaction.score is None and reaction.gloss == ""
    assert reaction.near and reaction.near[0]["score"] < config.MATCH_THRESHOLD
    reaction = german.say("heute ist schönes wetter")
    assert reaction.speech == "Ich wiederhole: heute ist schönes wetter." and reaction.gloss.startswith("Повторяю:")


def test_disabled_operation_is_just_a_phrase(russian, operations):
    operations.update({"time": {"enabled": False}})
    assert russian.say("который час").kind == "echo"


@pytest.mark.parametrize("phrase", ["hm", "э", "а", "ну", "и", "ja", "mhm", "да", "э э э"])
def test_sighs_are_not_answered(russian, phrase):
    reaction = russian.say(phrase)
    assert reaction.kind == "noise" and reaction.speech == "" and reaction.display == ""


@pytest.mark.parametrize("phrase", ["", "   ", "?!", "…"])
def test_nothing_heard(russian, phrase):
    reaction = russian.say(phrase)
    assert reaction.kind == "silence" and reaction.speech == ""
    assert russian.session.last_reply == ""


def test_long_phrase_is_cut(russian):
    reaction = russian.say("слово " * 200)
    assert len(reaction.heard) <= config.MAX_PHRASE_CHARS and reaction.kind == "echo"


# --- состояние разговора ----------------------------------------------------------------

def test_session_from_untrusted_data(collection):
    assert Session.from_dict(None, collection) == Session()
    assert Session.from_dict("мусор", collection) == Session()
    assert Session.from_dict({"language": "fr"}, collection).language == config.DEFAULT_LANGUAGE
    assert Session.from_dict({"language": "ru", "essay": "нет такого", "paragraph": 7}, collection) == Session(language="ru")
    # сочинение другого языка открытым не считается
    assert Session.from_dict({"language": "ru", "essay": "de-lit-raeuber"}, collection).essay == ""
    session = Session.from_dict({"language": "de", "essay": "de-lit-raeuber", "paragraph": 999}, collection)
    assert session.essay == "de-lit-raeuber" and session.paragraph == 27
    assert Session.from_dict({"language": "de", "essay": "de-lit-raeuber", "paragraph": "x"}, collection).paragraph == 0
    assert Session.from_dict({"language": "de", "essay": "de-lit-raeuber", "paragraph": -3}, collection).paragraph == 0
    session = Session.from_dict({"language": "de", "last_reply": "x" * 9000, "last_language": "ru"}, collection)
    assert len(session.last_reply) == 4000 and session.last_language == "ru"


def test_reaction_is_serialisable(german):
    data = german.say("öffne aufsatz eins").to_dict()
    assert data["kind"] == "operation" and data["session"]["essay"] == "de-lit-raeuber"
    assert data["score"] == 1.0 and data["phrase"] == "öffne aufsatz {target}" and data["ms"] >= 0
