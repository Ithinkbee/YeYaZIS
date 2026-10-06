"""Сопоставление распознанной фразы с операциями: точные команды, ошибки
распознавателя, параметры — и фразы, которые командами не являются."""

from __future__ import annotations

import pytest

from sluhach import config, evaluation, matcher
from sluhach.operations import DEFAULTS


def found(text: str, language: str, operations):
    result = matcher.match(text, language, operations)
    return result.operation.id if result else None


@pytest.mark.parametrize("operation", DEFAULTS, ids=lambda operation: operation.id)
@pytest.mark.parametrize("language", config.LANGUAGE_CODES)
def test_every_default_phrase_calls_its_operation(operations, operation, language):
    for template in operation.phrases[language]:
        phrase = template.replace("{" + operation.slot + "}", operation.sample(language)) if operation.slot else template
        result = matcher.match(phrase, language, operations, dictation=operation.dictation)
        assert result is not None and result.operation.id == operation.id, phrase
        assert result.score == pytest.approx(1.0)
        assert bool(result.slot) == bool(operation.slot)
        # операции диктовки вне её не действуют, остальные — не действуют во время неё
        other = matcher.match(phrase, language, operations, dictation=not operation.dictation)
        assert other is None or other.operation.id != operation.id


@pytest.mark.parametrize("heard, language, operation", [
    # так фразы слышит Vosk (см. страницу «Проверка»)
    ("ließ vor", "de", "read"),
    ("ließ den absatz", "de", "read"),
    ("wieviele wörter hat der aufsatz", "de", "count"),
    ("wieviel uhr ist es", "de", "time"),
    ("nächste aufsatz", "de", "next_essay"),
    ("vorherige aufsatz", "de", "prev_essay"),
    ("höhe nicht zu", "de", "sleep"),
    ("spricht deutsch", "de", "language"),
    ("öffne den aufsatz über werte", "de", "open"),
    ("открой сочинении про онегина", "ru", "open"),
    ("закрой сочинении", "ru", "close"),
    ("о чем сочинении", "ru", "info"),
    ("предыдущая сочинении", "ru", "prev_essay"),
    ("говорит по-немецки", "ru", "language"),
    ("первые абзац", "ru", "start"),
    ("сначала", "ru", "start"),
    ("найди слова романа", "ru", "find"),
    ("перейди к абзаца двенадцать", "ru", "goto"),
])
def test_recognizer_mistakes_still_call_the_operation(operations, heard, language, operation):
    assert found(heard, language, operations) == operation


@pytest.mark.parametrize("phrase, language, operation", [
    ("Пафнутий, читай, пожалуйста!", "ru", "read"),
    ("Ну-ка, читай дальше", "ru", "next"),
    ("Bitte lies vor", "de", "read"),
    ("Hey Pafnuti, weiter bitte", "de", "next"),
    ("ладно, открой сочинение три", "ru", "open"),          # лишнее слово в начале
    ("also gut öffne aufsatz zwei", "de", "open"),
    ("LIES VOR!", "de", "read"),
    ("oeffne aufsatz zwei", "de", "open"),                   # без умлаутов
])
def test_politeness_and_noise_words(operations, phrase, language, operation):
    assert found(phrase, language, operations) == operation


def test_slot_is_what_follows_the_command(operations):
    result = matcher.match("Suche das Wort Räuber", "de", operations)
    assert result.operation.id == "find" and result.template.text == "suche das wort {word}"
    assert result.slot == ("raeuber",) and result.raw == ("räuber",)

    result = matcher.match("открой сочинение про Евгения Онегина", "ru", operations)
    assert result.operation.id == "open" and result.slot == ("про", "евгения", "онегина")

    result = matcher.match("перейди к абзацу двадцать три", "ru", operations)
    assert result.operation.id == "goto" and result.slot == ("двадцать", "три")


def test_slot_survives_a_glued_command(operations):
    """Распознаватель склеил или разорвал слова команды — граница параметра сдвигается."""
    result = matcher.match("gehezu absatz fünf", "de", operations)
    assert result.operation.id == "goto" and result.raw == ("fünf",)
    result = matcher.match("пере иди к абзацу пять", "ru", operations)
    assert result.operation.id == "goto" and result.raw == ("пять",)


def test_more_specific_phrase_wins(operations):
    assert matcher.match("найди слово дуэль", "ru", operations).template.text == "найди слово {word}"
    assert matcher.match("найди дуэль", "ru", operations).template.text == "найди {word}"
    assert found("открой игру", "ru", operations) == "game"            # а не «открой {target}»
    assert found("öffne das spiel", "de", operations) == "game"
    assert found("читай дальше", "ru", operations) == "next"           # а не «читай»
    assert found("zurück zur liste", "de", operations) == "close"      # а не „zurück“


def test_command_without_parameter_is_not_matched(operations):
    assert found("открой сочинение", "ru", operations) != "open" or matcher.match(
        "открой сочинение", "ru", operations).slot                     # параметр не бывает пустым
    assert found("gehe zu absatz", "de", operations) is None


@pytest.mark.parametrize("phrase, language", [
    ("kalt", "de"), ("hals", "de"), ("ruhr", "de"),                    # не „halt“ и не „ruhe“
    ("стол", "ru"), ("тиха", "ru"),                                    # не «стоп»
])
def test_short_commands_must_be_exact(operations, phrase, language):
    assert found(phrase, language, operations) is None


def test_short_commands_work(operations):
    assert found("halt", "de", operations) == "stop" and found("стоп", "ru", operations) == "stop"
    assert found("weiter", "de", operations) == "next" and found("назад", "ru", operations) == "back"


@pytest.mark.parametrize("phrase, language", [
    ("сегодня хорошая погода", "ru"),
    ("сколько стоит слон", "ru"),
    ("heute ist schönes wetter", "de"),
    ("ich habe hunger", "de"),
    ("", "ru"), ("?!", "de"), ("пожалуйста", "ru"),
    # длинное предложение, которое начинается похоже на команду „sprich …“
    ("Er spricht davon, sich ihr zu Füßen werfen und ihr Sklave werden zu wollen", "de"),
    ("найди в себе силы признать что ты был совершенно не прав", "ru"),
])
def test_ordinary_phrases_are_not_commands(operations, phrase, language):
    assert found(phrase, language, operations) is None


def test_sentences_from_essays_are_not_commands(collection, operations):
    """Речь предметной области не должна вызывать операции — её система только повторяет."""
    sentences = evaluation.sentence_phrases(collection, per_language=60)
    assert len(sentences) >= 60
    alarms = [(s.text, found(s.text, s.language, operations)) for s in sentences
              if found(s.text, s.language, operations)]
    assert alarms == []


def test_language_of_the_phrases_matters(operations):
    assert found("lies vor", "ru", operations) is None
    assert found("читай", "de", operations) is None


def test_candidates_are_sorted_and_explain_a_miss(operations):
    ranked = matcher.candidates("читать дальше будем", "ru", operations)
    assert [m.score for m in ranked] == sorted((m.score for m in ranked), reverse=True)
    assert len({m.operation.id for m in ranked}) == len(ranked)        # по одному совпадению на операцию
    assert ranked[0].operation.id == "next" and not ranked[0].accepted


def test_threshold():
    from sluhach.operations import BY_ID, parse_template

    short = parse_template("halt", BY_ID["stop"])
    long = parse_template("wie viele wörter", BY_ID["count"])
    assert matcher.threshold(short) == matcher.SHORT_THRESHOLD > config.MATCH_THRESHOLD
    assert matcher.threshold(long) == config.MATCH_THRESHOLD


def test_split_keeps_original_spelling():
    words, raws = matcher.split("Пафнутий, найди слово «Ёлка»!", "ru")
    assert words == ["найди", "слово", "елка"] and raws == ["найди", "слово", "ёлка"]
    assert matcher.clean("Bitte, öffne mal Kafka", "de") == ["oeffne", "kafka"]
