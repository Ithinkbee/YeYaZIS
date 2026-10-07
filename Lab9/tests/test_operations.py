"""Список операций: умолчания, задание списка пользователем, проверка фраз, хранение."""

from __future__ import annotations

import json

import pytest

from sluhach import config, matcher
from sluhach.operations import BY_ID, DEFAULTS, GROUPS, OperationSet, parse_template


def test_defaults_are_complete():
    assert len(DEFAULTS) == len(BY_ID) == 24
    for operation in DEFAULTS:
        assert operation.group in GROUPS and operation.title and operation.description
        for language in config.LANGUAGE_CODES:
            phrases = operation.phrases[language]
            assert 1 <= len(phrases) <= config.MAX_TEMPLATES, operation.id
            for phrase in phrases:
                template = parse_template(phrase, operation)             # фраза сама проходит проверку
                assert template.slot == bool(operation.slot)
        if operation.slot:
            assert operation.hint("de") and operation.hint("ru") and operation.sample("de") and operation.sample("ru")


def test_default_phrases_do_not_collide():
    for language in config.LANGUAGE_CODES:
        seen = {}
        for operation in DEFAULTS:
            for phrase in operation.phrases[language]:
                template = parse_template(phrase, operation)
                key = (template.literal, template.slot)
                assert key not in seen, f"«{phrase}»: {operation.id} и {seen.get(key)}"
                seen[key] = operation.id


@pytest.mark.parametrize("text, operation, problem", [
    ("", "read", "пустая"),
    ("   ", "read", "пустая"),
    ("читай {word}", "read", "нет параметра"),
    ("открой сочинение", "open", "заканчиваться параметром"),
    ("открой {target} сочинение", "open", "заканчиваться параметром"),
    ("открой {word}", "open", "заканчиваться параметром"),
    ("открой {target} {target}", "open", "заканчиваться параметром"),
    ("{target}", "open", "нет слов"),
    ("открой {} ", "read", "фигурные скобки"),
    ("?!", "read", "нет слов"),
    ("я" * 61, "read", "длиннее"),
])
def test_bad_phrases_are_refused(text, operation, problem):
    with pytest.raises(ValueError, match=problem):
        parse_template(text, BY_ID[operation])


def test_template_parsing():
    template = parse_template("  Öffne   den Aufsatz {target} ", BY_ID["open"])
    assert template.text == "Öffne den Aufsatz {target}" and template.words == ("oeffne", "den", "aufsatz")
    assert template.slot and template.literal == "oeffne den aufsatz"
    assert template.shown("‹Nummer›") == "Öffne den Aufsatz ‹Nummer›"


def test_everything_is_on_by_default(operations):
    entries = operations.entries()
    assert len(entries) == 24 and all(entry.enabled and not entry.customized for entry in entries)
    for language in config.LANGUAGE_CODES:
        # во время диктовки действуют только две её операции, вне её — все остальные
        assert len(operations.active(language)) == 22
        assert [operation.id for operation, _ in operations.active(language, dictation=True)] == \
            ["dictate_undo", "dictate_end"]
    assert not operations.path.exists()                       # пока ничего не меняли, файла нет


def test_switching_an_operation_off(operations):
    assert matcher.match("который час", "ru", operations) is not None
    assert operations.update({"time": {"enabled": False}}) == []
    assert matcher.match("который час", "ru", operations) is None
    assert matcher.match("wie spät ist es", "de", operations) is None
    assert "time" not in [operation.id for operation, _ in operations.active("ru")]
    assert not operations.entry("time").enabled and operations.entry("read").enabled

    again = OperationSet(operations.path, companion=True)      # настройка пережила перезапуск
    assert not again.entry("time").enabled
    assert json.loads(operations.path.read_text(encoding="utf-8"))["operations"] == {"time": {"enabled": False}}


def test_changing_phrases(operations):
    errors = operations.update({"read": {"phrases": {"ru": ["огласи", "зачитай вслух"]}}})
    assert errors == []
    assert matcher.match("зачитай вслух", "ru", operations).operation.id == "read"
    assert matcher.match("читай", "ru", operations) is None                    # прежняя фраза больше не действует
    assert matcher.match("lies vor", "de", operations).operation.id == "read"  # немецкие фразы не тронуты
    entry = operations.entry("read")
    assert entry.customized and entry.texts("ru") == ["огласи", "зачитай вслух"]

    again = OperationSet(operations.path, companion=True)
    assert again.entry("read").texts("ru") == ["огласи", "зачитай вслух"]


def test_phrases_equal_to_defaults_are_not_stored(operations):
    defaults = list(BY_ID["read"].phrases["ru"])
    assert operations.update({"read": {"phrases": {"ru": defaults}}}) == []
    assert not operations.entry("read").customized
    assert json.loads(operations.path.read_text(encoding="utf-8"))["operations"] == {}


def test_operation_may_lose_all_phrases_of_one_language(operations):
    assert operations.update({"time": {"phrases": {"de": []}}}) == []
    assert "time" not in [operation.id for operation, _ in operations.active("de")]
    assert "time" in [operation.id for operation, _ in operations.active("ru")]


@pytest.mark.parametrize("changes, problem", [
    ({"read": {"phrases": {"ru": ["читай {word}"]}}}, "нет параметра"),
    ({"open": {"phrases": {"de": ["öffne"]}}}, "заканчиваться параметром"),
    ({"read": {"phrases": {"ru": ["дальше"]}}}, "фраза «дальше» уже вызывает операцию «Читать абзац»"),
    ({"read": {"phrases": {"de": [f"lies {i}" for i in range(9)]}}}, "не больше 8"),
])
def test_bad_lists_are_refused_whole(operations, changes, problem):
    errors = operations.update({**changes, "time": {"enabled": False}})
    assert len(errors) == 1 and problem in errors[0]
    assert operations.entry("time").enabled                       # при ошибке не сохранено ничего
    assert not operations.path.exists()


def test_collision_with_a_disabled_operation_is_allowed(operations):
    assert operations.update({"next": {"enabled": False}, "read": {"phrases": {"ru": ["дальше"]}}}) == []
    assert matcher.match("дальше", "ru", operations).operation.id == "read"


def test_reset(operations):
    operations.update({"time": {"enabled": False}, "read": {"phrases": {"ru": ["огласи"]}}})
    operations.reset()
    assert all(entry.enabled and not entry.customized for entry in operations.entries())
    assert matcher.match("читай", "ru", operations).operation.id == "read"


def test_spoiled_settings_file_is_ignored(tmp_path):
    path = tmp_path / "operations.json"
    path.write_text("{ это не JSON", encoding="utf-8")
    assert len(OperationSet(path, companion=True).entries()) == 24

    path.write_text(json.dumps({"operations": {"read": {"phrases": {"ru": ["читай {нет}"]}}, "нет": {},
                                               "time": "выключить"}}), encoding="utf-8")
    loaded = OperationSet(path, companion=True)
    assert loaded.entry("read").texts("ru") == list(BY_ID["read"].phrases["ru"])     # испорченная запись — умолчание
    assert loaded.entry("time").enabled


def test_game_operation_belongs_to_the_spider(tmp_path):
    without = OperationSet(tmp_path / "operations.json", companion=False)
    assert without.entry("game") is None and len(without.entries()) == 23
    assert matcher.match("открой игру", "ru", without).operation.id == "open"     # теперь это «открой {target}»
    # настройки скрытой операции при сохранении не теряются
    with_spider = OperationSet(tmp_path / "operations.json", companion=True)
    with_spider.update({"game": {"enabled": False}})
    without.load()
    without.update({"time": {"enabled": False}})
    with_spider.load()
    assert not with_spider.entry("game").enabled and not with_spider.entry("time").enabled


def test_cheatsheet_and_examples(operations):
    sheet = operations.cheatsheet("de")
    assert [item["id"] for item in sheet] == [operation.id for operation in DEFAULTS]
    opening = next(item for item in sheet if item["id"] == "open")
    assert opening["phrases"][0] == "öffne den aufsatz ‹Nummer oder Titel›" and not opening["needs_essay"]
    assert next(item for item in sheet if item["id"] == "read")["needs_essay"]
    assert operations.example("open", "de") == "öffne den aufsatz zwei"
    assert operations.example("find", "ru") == "найди слово любовь"
    assert operations.example("read", "ru") == "читай"
    operations.update({"read": {"enabled": False}})
    assert operations.example("read", "ru") == "" and operations.example("нет", "ru") == ""
