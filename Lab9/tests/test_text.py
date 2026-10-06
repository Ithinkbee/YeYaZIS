"""Нормализация фраз, расстояние Левенштейна, ошибки по словам, числительные."""

from __future__ import annotations

import pytest

from sluhach import text


@pytest.mark.parametrize("raw, expected", [
    ("Сколько стоит слон?", "сколько стоит слон"),
    ("  Öffne   den Aufsatz!  ", "oeffne den aufsatz"),
    ("oeffne den aufsatz", "oeffne den aufsatz"),          # набрано без умлаутов — та же фраза
    ("Straße, Füße", "strasse fuesse"),
    ("Ещё раз — ёлка", "еще раз елка"),
    ("по-немецки", "по немецки"),
    ("Café „Müller“", "cafe mueller"),                    # диакритика снимается, «й» при этом цел
    ("Йошкар-Ола", "йошкар ола"),
    ("абзац № 12.", "абзац 12"),
    ("", ""),
    ("?!…", ""),
])
def test_normalize(raw, expected):
    assert text.normalize(raw) == expected


def test_tokens():
    assert text.tokens("Wie viele Wörter hat der Aufsatz?") == ["wie", "viele", "woerter", "hat", "der", "aufsatz"]


@pytest.mark.parametrize("phrase, language", [
    ("Сколько стоит слон?", "ru"),
    ("Wie viel kostet ein Elefant?", "de"),
    ("Größe", "de"),
    ("Мастер и Маргарита (Master)", "ru"),        # решает большинство букв
    ("12345", "de"),
])
def test_script_language(phrase, language):
    assert text.script_language(phrase) == language


def test_script_language_default():
    assert text.script_language("…", default="ru") == "ru"


@pytest.mark.parametrize("a, b, distance", [
    ("", "", 0), ("кот", "кот", 0), ("кот", "кит", 1), ("кот", "", 3), ("lies", "liess", 1),
    ("сочинение", "сочинении", 1), ("wie viele", "wieviele", 1),
])
def test_levenshtein(a, b, distance):
    assert text.levenshtein(a, b) == distance
    assert text.levenshtein(b, a) == distance


def test_levenshtein_on_word_lists():
    assert text.levenshtein(["открой", "сочинение", "три"], ["открой", "сочинении", "три"]) == 1


def test_similarity():
    assert text.similarity("lies vor", "lies vor") == 1.0
    assert text.similarity("liess vor", "lies vor") == pytest.approx(1 - 1 / 9)
    assert text.similarity("", "") == 1.0
    assert text.similarity("абв", "") == 0.0
    assert text.phrase_similarity("Ließ vor!", "lies vor") == pytest.approx(1 - 1 / 9)


def test_word_errors_counts_each_kind():
    errors = text.word_errors("открой сочинение про евгения онегина", "открой сочинении евгения онегина сейчас")
    assert (errors.reference, errors.substitutions, errors.deletions, errors.insertions) == (5, 1, 1, 1)
    assert errors.errors == 3 and errors.rate == pytest.approx(0.6)


def test_word_errors_glued_words():
    """Склейка «wie viele» -> «wieviele» — замена и пропуск: два слова эталона испорчены."""
    errors = text.word_errors("wie viele wörter hat der aufsatz", "wieviele wörter hat der aufsatz")
    assert errors.errors == 2 and errors.reference == 6


def test_word_errors_edge_cases():
    assert text.word_errors("читай", "читай").rate == 0
    assert text.word_errors("читай дальше", "").rate == 1
    assert text.word_errors("", "").rate == 0
    assert text.word_errors("", "лишнее слово").rate == 1         # эталон пуст, а слова есть
    assert text.word_errors("Lies vor!", "lies   VOR").errors == 0


@pytest.mark.parametrize("phrase, value", [
    ("три", 3), ("третье", 3), ("третьего", 3), ("первый", 1), ("вторую", 2), ("седьмой", 7),
    ("двадцать три", 23), ("тридцать первый", 31), ("сороковой", 40), ("пятнадцатый", 15),
    ("номер семь", 7), ("42", 42), ("абзац номер двенадцать", 12), ("пятьдесят", 50),
    ("пятно", None), ("слон", None), ("", None), ("вторник", None),
])
def test_parse_number_russian(phrase, value):
    assert text.parse_number(text.tokens(phrase), "ru") == value


@pytest.mark.parametrize("phrase, value", [
    ("drei", 3), ("dritten", 3), ("erste", 1), ("ersten", 1), ("zweiter", 2), ("siebte", 7), ("achte", 8),
    ("zwölf", 12), ("zwölfte", 12), ("dreizehnte", 13), ("zwanzigste", 20), ("dreiundzwanzig", 23),
    ("einunddreißigste", 31), ("Nummer sieben", 7), ("42", 42), ("fünfzehn", 15),
    ("vierer", None), ("aufsatz", None), ("erstens", None),
])
def test_parse_number_german(phrase, value):
    assert text.parse_number(text.tokens(phrase), "de") == value


def test_parse_number_takes_first_number():
    assert text.parse_number(text.tokens("абзац три из десяти"), "ru") == 3
    assert text.parse_number(["99999"], "ru") is None             # это не номер абзаца


@pytest.mark.parametrize("phrase, language, value", [
    ("sie bin", "de", 7),              # так Vosk слышит „sieben“
    ("siebin", "de", 7),
    ("zwolf", "de", 12),
    ("sieben", "de", 7),
    ("двинадцать", "ru", 12),
    ("питнадцать", "ru", 15),
    ("слон", "ru", None),
    ("f e", "de", None),               # обрывки имени — не число
    ("über die räuber", "de", None),
    ("", "de", None),
])
def test_guess_number(phrase, language, value):
    assert text.guess_number(text.tokens(phrase), language) == value


@pytest.mark.parametrize("number, form", [
    (1, "абзац"), (2, "абзаца"), (4, "абзаца"), (5, "абзацев"), (11, "абзацев"), (12, "абзацев"),
    (21, "абзац"), (22, "абзаца"), (25, "абзацев"), (101, "абзац"), (111, "абзацев"), (0, "абзацев"),
])
def test_plural_ru(number, form):
    assert text.plural_ru(number, "абзац", "абзаца", "абзацев") == form


def test_plural_de():
    assert text.plural_de(1, "Absatz", "Absätze") == "Absatz"
    assert text.plural_de(28, "Absatz", "Absätze") == "Absätze"
