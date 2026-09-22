"""Проверка транслитерации и викторины при взятии фигуры."""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tolmach import config, pafnuty, quiz, translit  # noqa: E402
from tolmach.recognizer import Recognizer  # noqa: E402


# --- транслитерация -----------------------------------------------------------


@pytest.mark.parametrize(
    "word,expected",
    [
        ("работа", "rabota"),
        ("язык", "yazyk"),
        ("щука", "shchuka"),
        ("ёжик", "yozhik"),
        ("человек", "chelovek"),
        ("объезд", "obezd"),
    ],
)
def test_russian_is_transliterated(word, expected):
    assert translit.latinize(word, "ru") == expected


@pytest.mark.parametrize(
    "word,expected",
    [("wärme", "waerme"), ("straße", "strasse"), ("über", "ueber"), ("größe", "groesse")],
)
def test_german_diacritics_are_folded(word, expected):
    assert translit.latinize(word, "de") == expected


def test_multi_letter_sequences_win_over_single():
    """«щ» должна давать shch целиком, а не sh + ch по частям."""
    assert translit.latinize("щ", "ru") == "shch"


def test_latinized_words_contain_only_latin():
    for word in ("работа", "щавель", "ёлка", "въезд"):
        assert translit.looks_latin(translit.latinize(word, "ru"))
    for word in ("wärme", "straße", "über"):
        assert translit.looks_latin(translit.latinize(word, "de"))


def test_looks_latin_rejects_other_scripts():
    assert not translit.looks_latin("работа")
    assert not translit.looks_latin("wärme")
    assert not translit.looks_latin("")


def test_german_without_diacritics_is_unchanged():
    assert translit.latinize("bienenvolk", "de") == "bienenvolk"


# --- банк слов ----------------------------------------------------------------


@pytest.fixture(scope="module")
def bank() -> quiz.WordBank:
    return quiz.build_bank()


def test_bank_covers_both_languages(bank):
    assert bank.ready
    for code in config.LANGUAGE_CODES:
        assert bank.size(code) > 50


def test_every_shown_word_is_latin(bank):
    for pool in bank.words.values():
        for word in pool:
            assert translit.looks_latin(word.shown), word.shown


def test_shown_words_do_not_collide_between_languages(bank):
    """Одна и та же латинская запись не должна значить два разных языка.

    Иначе у вопроса не было бы однозначного ответа, и игрок терял бы фигуру
    без своей вины.
    """
    russian = {word.shown for word in bank.words["ru"]}
    german = {word.shown for word in bank.words["de"]}
    assert not russian & german


def test_words_come_from_the_training_corpus(bank):
    """Викторина обязана опираться на те же данные, что и методы."""
    from tolmach import corpus

    training = corpus.load_training_corpus()
    for code, pool in bank.words.items():
        vocabulary = set(training[code].split())
        for word in pool[:40]:
            assert word.original in vocabulary


def test_pick_returns_both_languages(bank):
    rng = random.Random(4)
    seen = {bank.pick(rng).language for _ in range(60)}
    assert seen == set(config.LANGUAGE_CODES)


def test_pick_honours_requested_language(bank):
    rng = random.Random(4)
    for _ in range(10):
        assert bank.pick(rng, language="de").language == "de"


def test_find_locates_a_word(bank):
    word = bank.words["ru"][0]
    assert bank.find(word.shown) is word
    assert bank.find(word.shown.upper()) is word
    assert bank.find("такогослованет") is None


def test_empty_bank_picks_nothing():
    assert quiz.WordBank({}).pick() is None


# --- мнение системы -----------------------------------------------------------


@pytest.fixture(scope="module")
def recognizer() -> Recognizer:
    instance = Recognizer()
    instance.load_or_fit()
    return instance


def test_system_fails_on_transliterated_russian(bank, recognizer):
    """Профили русского построены по кириллице, и латиница их обманывает.

    Это не дефект, а следствие устройства методов: ровно поэтому викторина и
    интересна — человек здесь оказывается точнее системы.
    """
    rng = random.Random(11)
    words = [bank.pick(rng, language="ru") for _ in range(12)]
    wrong = 0
    for word in words:
        opinions = quiz.system_opinion(recognizer, word)
        assert opinions, "методы должны дать ответ"
        if all(answer == "de" for answer in opinions.values()):
            wrong += 1
    assert wrong >= 10, "ожидалось, что транслитерация собьёт методы почти всегда"


def test_system_still_recognises_german(bank, recognizer):
    rng = random.Random(12)
    words = [bank.pick(rng, language="de") for _ in range(12)]
    right = sum(
        1 for word in words
        if all(answer == "de" for answer in quiz.system_opinion(recognizer, word).values())
    )
    assert right >= 10


def test_opinion_summary_explains_total_failure(bank, recognizer):
    word = bank.words["ru"][0]
    summary = quiz.opinion_summary({"ngram": "de", "alphabet": "de", "neural": "de"}, word)
    assert "кириллице" in summary


def test_opinion_summary_without_recognizer():
    assert quiz.system_opinion(None, quiz.QuizWord("а", "a", "ru")) == {}


# --- реплики Пафнутия ---------------------------------------------------------


def test_every_occasion_has_lines():
    for occasion, variants in pafnuty.LINES.items():
        assert variants, occasion
        assert all(line.strip() for line in variants)


def test_unknown_occasion_falls_back():
    assert pafnuty.line("такого-повода-нет") in pafnuty.LINES["idle"]


def test_greeting_differs_by_page():
    rng = random.Random(0)
    assert pafnuty.greeting("check", rng) in pafnuty.LINES["gate"]
    assert pafnuty.greeting("compare", rng) in pafnuty.LINES["compare"]


def test_name_forms_are_spelled_out():
    """Падежи заданы целиком: склейка имени с окончанием даёт «Пафнутийем»."""
    assert pafnuty.NAME_INSTRUMENTAL == "Пафнутием"
    assert not pafnuty.NAME_INSTRUMENTAL.startswith(pafnuty.NAME)
