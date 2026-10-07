"""Проверочный набор фраз и подсчёт показателей.

Сам прогон (озвучивание и распознавание сотен записей) идёт минуты и
запускается отдельно: python tools/evaluate.py. Здесь проверяется, что набор
составлен верно — иначе числа проверки ничего бы не значили — и что
показатели считаются правильно.
"""

from __future__ import annotations

import json

import pytest

from sluhach import config, evaluation as ev
from sluhach.operations import DEFAULTS


@pytest.fixture(scope="module")
def phrases(collection):
    return ev.build_phrases(collection, per_language=40)


@pytest.fixture(scope="module")
def reference(collection):
    return ev.default_reactor(collection)


def test_set_has_three_kinds_in_both_languages(phrases):
    for language in config.LANGUAGE_CODES:
        kinds = {kind: [p for p in phrases if p.language == language and p.kind == kind]
                 for kind in ("command", "sentence", "egg")}
        assert len(kinds["command"]) >= 70 and 30 <= len(kinds["sentence"]) <= 40 and len(kinds["egg"]) == 1
    assert len({phrase.id for phrase in phrases}) == len(phrases)
    assert len({(phrase.language, phrase.text) for phrase in phrases}) == len(phrases)       # без повторов


def test_commands_cover_every_phrase_of_every_operation(phrases):
    for operation in DEFAULTS:
        for language in config.LANGUAGE_CODES:
            mine = [p.text for p in phrases if p.operation == operation.id and p.language == language]
            for template in operation.phrases[language]:
                head = template.split("{")[0].strip()
                assert any(text.startswith(head) for text in mine), f"{operation.id}: «{template}»"


def test_every_command_is_understood_as_written(phrases, reference, collection):
    """Эталонный текст команды вызывает именно её операцию — иначе мерить распознавание было бы не по чему."""
    for phrase in phrases:
        if phrase.kind != "command":
            continue
        signature = ev.reaction_signature(reference, collection, phrase.text, phrase.language, ev.dictating(phrase))
        assert signature[0] == "operation" and signature[1] == phrase.operation, phrase.text


def test_open_commands_open_all_essays_by_number_and_by_name(phrases, reference, collection):
    for language in config.LANGUAGE_CODES:
        opened = {ev.reaction_signature(reference, collection, p.text, language)[2]
                  for p in phrases if p.operation == "open" and p.language == language}
        assert opened == {essay.id for essay in collection.by_language(language)}


def test_sentences_come_from_the_essays_and_are_not_commands(phrases, reference, collection):
    sentences = [p for p in phrases if p.kind == "sentence"]
    for phrase in sentences:
        essay = collection.get(phrase.essay)
        assert essay.language == phrase.language and any(phrase.text in p.text for p in essay.paragraphs)
        words = phrase.text.rstrip(".!?").replace(",", " ").split()
        assert ev.SENTENCE_WORDS[0] <= len(words) <= ev.SENTENCE_WORDS[1] and all(word.isalpha() for word in words)
        assert ev.reaction_signature(reference, collection, phrase.text, phrase.language)[0] == "echo"
    assert len({p.essay for p in sentences}) == 10                           # из каждого сочинения


def test_eggs_are_the_default_ones(phrases, reference, collection):
    for phrase in (p for p in phrases if p.kind == "egg"):
        assert ev.reaction_signature(reference, collection, phrase.text, phrase.language)[0] == "egg"


def test_set_is_reproducible(collection, phrases):
    assert ev.build_phrases(collection, per_language=40) == phrases


def test_default_reactor_ignores_user_settings(collection):
    from sluhach.operations import OperationSet

    OperationSet().update({"time": {"enabled": False}})                      # пользователь выключил операцию
    try:
        reactor = ev.default_reactor(collection)
        assert ev.reaction_signature(reactor, collection, "wie spät ist es", "de")[1] == "time"
        assert ev.reaction_signature(reactor, collection, "öffne das spiel", "de")[1] == "game"
    finally:
        OperationSet().reset()
        config.OPERATIONS_PATH.unlink(missing_ok=True)


def test_signature_ignores_wording(reference, collection):
    """Суть реакции — операция и её итог, а не слова ответа."""
    a = ev.reaction_signature(reference, collection, "öffne aufsatz zwei", "de")
    b = ev.reaction_signature(reference, collection, "zeige den aufsatz über werther", "de")
    assert a == b == ("operation", "open", "de-lit-werther", 0, "de", (), None)
    assert ev.reaction_signature(reference, collection, "öffne aufsatz drei", "de") != a
    found = ev.reaction_signature(reference, collection, "suche das wort räuber", "de")
    assert found[1] == "find" and "Räuber" in found[5]
    assert ev.reaction_signature(reference, collection, "wie spät ist es", "de")[:2] == ("operation", "time")


def test_start_session_lets_every_operation_run(collection):
    session = ev.start_session(collection, "ru")
    assert session.essay == "ru-lit-onegin" and session.paragraph == 5 and session.last_reply
    assert session.draft is None


def test_dictation_commands_are_checked_during_dictation(phrases, reference, collection):
    """Фразы, управляющие диктовкой, вне её — просто слова; проверяются они с черновиком."""
    controls = [p for p in phrases if ev.dictating(p)]
    assert {p.operation for p in controls} == {"dictate_undo", "dictate_end"}
    assert not ev.dictating(next(p for p in phrases if p.operation == "dictate"))
    assert not any(ev.dictating(p) for p in phrases if p.kind != "command")
    first, second = ev.DRAFT_PHRASES["ru"]
    assert ev.start_session(collection, "ru", dictation=True).draft.text == f"{first} {second}"

    erased = ev.reaction_signature(reference, collection, "удали последнюю фразу", "ru", dictation=True)
    assert erased[:2] == ("operation", "dictate_undo") and erased[6] == first          # вторая фраза стёрта
    ended = ev.reaction_signature(reference, collection, "конец диктовки", "ru", dictation=True)
    assert ended[:2] == ("operation", "dictate_end") and ended[6] is None              # диктовка закончена
    # та же фраза, расслышанная неверно, уходит в текст — и это видно по сути реакции
    missed = ev.reaction_signature(reference, collection, "конец декабря", "ru", dictation=True)
    assert missed[0] == "dictation" and missed[6].endswith("Конец декабря.") and missed != ended
    assert ev.reaction_signature(reference, collection, "конец диктовки", "ru")[0] == "echo"


def test_evaluation_does_not_keep_dictated_essays(reference, collection):
    """Проверка не оставляет следов: диктовка в ней заканчивается без сохранения сочинения."""
    before = len(collection)
    assert reference.dictations is None
    ev.reaction_signature(reference, collection, "diktat beenden", "de", dictation=True)
    assert len(collection) == before


def trial(phrase, **values) -> ev.Trial:
    return ev.Trial(phrase, "Hedda", "clean", **values)


def test_tally(phrases):
    command = next(p for p in phrases if p.kind == "command")
    tally = ev.Tally()
    tally.add(trial(command, heard="x", detected=True, pieces=1, errors=0, words=3, exact=True, reaction_ok=True,
                    confidence=1.0, audio_ms=2000, recognition_ms=300))
    tally.add(trial(command, heard="y", detected=True, pieces=2, errors=2, words=3, exact=False, reaction_ok=True,
                    confidence=0.6, audio_ms=2000, recognition_ms=500))
    tally.add(trial(command, heard="", detected=False, pieces=0, errors=4, words=4, exact=False, reaction_ok=False))
    data = tally.to_dict()
    assert data["trials"] == 3
    assert data["wer"] == pytest.approx(6 / 10)                              # ошибки и слова складываются по всем фразам
    assert data["exact"] == pytest.approx(1 / 3) and data["reaction"] == pytest.approx(2 / 3)
    assert data["detected"] == pytest.approx(2 / 3) and data["split"] == pytest.approx(1 / 3)
    assert data["confidence"] == pytest.approx(0.8)                          # среднее по замеченным фразам
    assert data["rtf"] == pytest.approx(800 / 4000)


def test_empty_tally():
    data = ev.Tally().to_dict()
    assert data["trials"] == 0 and data["wer"] is None and data["rtf"] is None and data["reaction"] == 0


def test_run_trial_on_a_recording(engine, recordings, collection, reference):
    item = next(r for r in recordings if r["file"] == "ru-egg.wav")
    phrase = ev.TestPhrase("egg", "ru", "egg", item["text"])
    expected = ev.reaction_signature(reference, collection, item["text"], "ru")
    clean = ev.run_trial(engine, reference, collection, phrase, "Pavel", item["path"], "clean", None, expected)
    assert clean.detected and clean.pieces == 1 and clean.exact and clean.errors == 0 and clean.words == 3
    assert clean.reaction_ok and not clean.false_alarm and clean.recognition_ms > 0 and clean.audio_ms > 1000
    again = ev.run_trial(engine, reference, collection, phrase, "Pavel", item["path"], "snr10", 10.0, expected)
    repeat = ev.run_trial(engine, reference, collection, phrase, "Pavel", item["path"], "snr10", 10.0, expected)
    assert again.heard == repeat.heard                                       # шум у записи всегда один и тот же


def test_command_must_run_its_own_operation(engine, recordings, collection, reference):
    """Если бы эталон команды не понимался, совпадение с ним не считалось бы верной реакцией."""
    item = next(r for r in recordings if r["file"] == "ru-egg.wav")
    wrong = ev.TestPhrase("x", "ru", "command", item["text"], operation="read")
    expected = ev.reaction_signature(reference, collection, item["text"], "ru")
    assert not ev.run_trial(engine, reference, collection, wrong, "Pavel", item["path"], "clean", None, expected).reaction_ok


def test_load(tmp_path):
    assert ev.load(tmp_path / "нет.json") is None
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    assert ev.load(tmp_path / "bad.json") is None
    (tmp_path / "empty.json").write_text("{}", encoding="utf-8")
    assert ev.load(tmp_path / "empty.json") is None
    (tmp_path / "ok.json").write_text(json.dumps({"groups": {"all": {}}, "created": "сегодня"}), encoding="utf-8")
    assert ev.load(tmp_path / "ok.json")["created"] == "сегодня"


def test_saved_results_match_the_current_set(collection, phrases):
    """Числа на странице «Проверка» посчитаны по нынешнему набору фраз, а не по устаревшему."""
    data = ev.load(config.REPORT_DIR / "evaluation.json")
    if data is None:
        pytest.skip("проверка ещё не запускалась: python tools/evaluate.py")
    for language in config.LANGUAGE_CODES:
        for kind in ("command", "sentence", "egg"):
            expected = sum(1 for p in phrases if p.language == language and p.kind == kind)
            assert data["phrases"][language][kind] == expected, f"{language}, {kind}: перезапустите tools/evaluate.py"
