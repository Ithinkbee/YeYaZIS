"""Проверка своим голосом: набор фраз для чтения, выравнивание слов, оценка прочитанного."""

from __future__ import annotations

import pytest

from sluhach import config, evaluation as ev, selftest
from sluhach.text import Aligned, align, spelled, tokens, word_errors


@pytest.fixture(scope="module")
def phrases(collection):
    return selftest.table(collection)


@pytest.fixture(scope="module")
def reference(collection):
    return ev.default_reactor(collection)


def ops(reference_text: str, heard: str) -> list[tuple[str, str, str]]:
    return [(item.op, item.said, item.heard) for item in align(reference_text, heard)]


# --- выравнивание слов -------------------------------------------------------------------

def test_spelled_keeps_the_writing_and_matches_tokens(collection):
    assert spelled("Die Räuber, по-немецки!") == [("Die", "die"), ("Räuber", "raeuber"), ("по", "по"),
                                                   ("немецки", "немецки")]
    assert spelled("") == [] and spelled("…—") == []
    for essay in collection:
        for paragraph in essay.paragraphs[:5]:
            assert [normalized for _, normalized in spelled(paragraph.text)] == tokens(paragraph.text)


def test_align_marks_every_kind_of_error():
    assert ops("открой сочинение три", "открой сочинение три") == [
        ("ok", "открой", "открой"), ("ok", "сочинение", "сочинение"), ("ok", "три", "три")]
    assert ops("открой сочинение три", "открой сочинении") == [
        ("ok", "открой", "открой"), ("sub", "сочинение", "сочинении"), ("del", "три", "")]
    assert ops("читай", "ну читай же") == [("ins", "", "ну"), ("ok", "читай", "читай"), ("ins", "", "же")]
    assert ops("читай", "") == [("del", "читай", "")] and ops("", "читай") == [("ins", "", "читай")]
    assert ops("", "") == []


def test_align_compares_normalized_but_shows_as_written():
    """«Räuber» и «räuber» — одно слово; в разборе оно остаётся таким, каким написано в эталоне."""
    assert ops("Die Räuber, ein Drama.", "die raeuber ein trauma") == [
        ("ok", "Die", "die"), ("ok", "Räuber", "raeuber"), ("ok", "ein", "ein"), ("sub", "Drama", "trauma")]
    assert ops("Ёлка", "елка") == [("ok", "Ёлка", "елка")]


@pytest.mark.parametrize("said, heard", [
    ("öffne den aufsatz zwei", "öffne den aufsatz"), ("wie viele wörter", "wieviele wörter"),
    ("а б в г", "б в г д"), ("один", "два три"), ("", "лишнее"), ("слово", ""),
])
def test_word_errors_agree_with_the_alignment(said, heard):
    errors, aligned = word_errors(said, heard), align(said, heard)
    count = {kind: sum(1 for item in aligned if item.op == kind) for kind in ("ok", "sub", "del", "ins")}
    assert (errors.substitutions, errors.deletions, errors.insertions) == (count["sub"], count["del"], count["ins"])
    assert errors.reference == count["ok"] + count["sub"] + count["del"] == len(tokens(said))
    assert all(isinstance(item, Aligned) for item in aligned)


# --- набор фраз ---------------------------------------------------------------------------

@pytest.mark.parametrize("language", config.LANGUAGE_CODES)
def test_set_has_commands_of_different_operations_and_short_sentences(phrases, language):
    picked = selftest.pick(phrases, language, seed=1)
    commands = [p for p in picked if p.kind == "command"]
    sentences = [p for p in picked if p.kind == "sentence"]
    assert len(picked) == selftest.COMMANDS + selftest.SENTENCES and picked == commands + sentences
    assert len(commands) == selftest.COMMANDS and len({p.operation for p in commands}) == selftest.COMMANDS
    assert all(p.language == language for p in picked)
    assert all(len(p.text.split()) <= selftest.SENTENCE_WORDS for p in sentences)
    assert len({p.id for p in picked}) == len(picked)


def test_set_is_the_same_for_a_seed_and_new_without_it(phrases):
    assert selftest.pick(phrases, "ru", seed=5) == selftest.pick(phrases, "ru", seed=5)
    assert selftest.pick(phrases, "ru", seed=5) != selftest.pick(phrases, "ru", seed=6)
    variants = {tuple(p.id for p in selftest.pick(phrases, "de")) for _ in range(6)}
    assert len(variants) > 1


def test_table_is_a_part_of_the_evaluation_set(phrases, collection):
    whole = {phrase.id: phrase for phrase in ev.build_phrases(collection)}
    assert phrases and all(whole[key] == phrase for key, phrase in phrases.items())
    assert not any(phrase.kind == "egg" for phrase in phrases.values())


def test_describe():
    command = ev.TestPhrase("ru-read-0", "ru", "command", "читай", "read")
    assert selftest.describe(command) == {"id": "ru-read-0", "text": "читай", "kind": "command", "operation": "read",
                                          "title": "Читать абзац"}
    assert selftest.describe(ev.TestPhrase("s", "ru", "sentence", "Текст."))["title"] == ""


# --- оценка прочитанного --------------------------------------------------------------------

def judge(reference, collection, phrase, heard):
    return selftest.judge(reference, collection, phrase, heard)


def test_command_read_right(reference, collection):
    phrase = ev.TestPhrase("x", "ru", "command", "открой сочинение три", "open")
    exact = judge(reference, collection, phrase, "открой сочинение три")
    assert exact["exact"] and exact["errors"] == 0 and exact["words"] == 3 and exact["reaction_ok"]
    assert exact["did"] == "операция «Открыть сочинение»"
    # ошибка в слове, но система всё равно открыла то же сочинение: реакция верная
    close = judge(reference, collection, phrase, "открой сочинении три")
    assert not close["exact"] and close["errors"] == close["substitutions"] == 1 and close["reaction_ok"]
    assert [item["op"] for item in close["alignment"]] == ["ok", "sub", "ok"]


def test_command_read_wrong(reference, collection):
    phrase = ev.TestPhrase("x", "ru", "command", "открой сочинение три", "open")
    other = judge(reference, collection, phrase, "открой сочинение два")           # операция та, сочинение не то
    assert not other["reaction_ok"] and other["did"] == "операция «Открыть сочинение»" and other["errors"] == 1
    lost = judge(reference, collection, phrase, "какие-то слова")
    assert not lost["reaction_ok"] and lost["did"] == "фраза повторена"
    silent = judge(reference, collection, phrase, "")
    assert not silent["reaction_ok"] and silent["did"] == "нет реакции" and silent["heard"] == ""
    assert silent["errors"] == silent["deletions"] == 3 and not silent["exact"]


def test_sentence_must_not_become_a_command(reference, collection, phrases):
    sentence = next(p for p in phrases.values() if p.kind == "sentence" and p.language == "ru")
    read = judge(reference, collection, sentence, sentence.text.lower())
    assert read["exact"] and read["reaction_ok"] and read["did"] == "фраза повторена"
    alarm = judge(reference, collection, sentence, "который час")                   # расслышано как команда
    assert not alarm["reaction_ok"] and alarm["did"] == "операция «Который час»"
    assert judge(reference, collection, sentence, "")["reaction_ok"]                 # молчание — не ложная команда


def test_dictation_commands_are_judged_during_dictation(reference, collection):
    phrase = ev.TestPhrase("x", "ru", "command", "конец диктовки", "dictate_end")
    assert judge(reference, collection, phrase, "конец диктовку")["reaction_ok"]
    missed = judge(reference, collection, phrase, "конец декабря")
    assert not missed["reaction_ok"] and missed["did"] == "фраза записана в текст"


def test_score_sums_up(reference, collection, phrases):
    picked = selftest.pick(phrases, "ru", seed=3)
    commands = [p for p in picked if p.kind == "command"]
    sentences = [p for p in picked if p.kind == "sentence"]
    items = [{"id": commands[0].id, "heard": commands[0].text}, {"id": commands[1].id, "heard": ""},
             {"id": sentences[0].id, "heard": sentences[0].text}, {"id": "нет такой", "heard": "x"}, "мусор"]
    result = selftest.score(reference, collection, phrases, items)
    assert result["language"] == "ru" and [entry["id"] for entry in result["items"]] == [
        commands[0].id, commands[1].id, sentences[0].id]
    totals = result["totals"]
    words = [len(tokens(p.text)) for p in (commands[0], commands[1], sentences[0])]
    assert totals["all"] == {"phrases": 3, "words": sum(words), "errors": words[1],
                             "wer": pytest.approx(words[1] / sum(words)), "exact": 2, "reaction_ok": 2}
    assert totals["command"]["phrases"] == 2 and totals["command"]["reaction_ok"] == 1
    assert totals["sentence"] == {"phrases": 1, "words": words[2], "errors": 0, "wer": 0, "exact": 1, "reaction_ok": 1}
    assert result["synthetic"] is None

    empty = selftest.score(reference, collection, phrases, [])
    assert empty["items"] == [] and empty["totals"]["all"]["wer"] is None and empty["language"] == ""


def test_reference_numbers_come_from_the_evaluation():
    data = {"groups": {"ru": {"command": {"clean": {"wer": 0.1, "exact": 0.7, "reaction": 0.98}},
                              "sentence": {"clean": {"wer": 0.2, "exact": 0.4, "false_alarm": 0.05}}}}}
    assert selftest.reference(data, "ru") == {"command": {"wer": 0.1, "exact": 0.7, "reaction": 0.98},
                                              "sentence": {"wer": 0.2, "exact": 0.4, "reaction": 0.95}}
    assert selftest.reference(data, "de") is None and selftest.reference(None, "ru") is None
    assert selftest.reference({"groups": {"ru": {"command": {"clean": {}}}}}, "ru") is None
