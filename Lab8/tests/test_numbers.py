"""Немецкие числительные."""

from __future__ import annotations

import pytest

from glashatai.text import numbers


@pytest.mark.parametrize("n, words", [
    (0, "null"), (1, "eins"), (7, "sieben"), (11, "elf"), (12, "zwölf"), (16, "sechzehn"), (17, "siebzehn"),
    (21, "einundzwanzig"), (30, "dreißig"), (99, "neunundneunzig"), (100, "hundert"), (101, "hunderteins"),
    (256, "zweihundertsechsundfünfzig"), (1000, "tausend"), (1024, "tausendvierundzwanzig"),
    (2009, "zweitausendneun"), (101000, "hunderteintausend"), (1_000_000, "eine Million"),
    (2_500_000, "zwei Millionen fünfhunderttausend"), (3_000_000_000, "drei Milliarden"),
])
def test_cardinal(n, words):
    assert numbers.cardinal(n) == words


def test_cardinal_negative_and_spaced():
    assert numbers.cardinal(-5) == "minus fünf"
    assert numbers.cardinal(1954, spaced=True) == "tausend neunhundert vierundfünfzig"


@pytest.mark.parametrize("n, words", [
    (1954, "neunzehnhundertvierundfünfzig"), (1100, "elfhundert"), (1900, "neunzehnhundert"),
    (1843, "achtzehnhundertdreiundvierzig"), (2021, "zweitausendeinundzwanzig"), (999, "neunhundertneunundneunzig"),
])
def test_year(n, words):
    assert numbers.year(n) == words


@pytest.mark.parametrize("n, ending, words", [
    (1, "e", "erste"), (3, "en", "dritten"), (7, "er", "siebter"), (8, "e", "achte"), (19, "en", "neunzehnten"),
    (20, "e", "zwanzigste"), (21, "en", "einundzwanzigsten"), (100, "e", "hundertste"), (101, "e", "hundertersten"[:-1]),
    (1000, "es", "tausendstes"),
])
def test_ordinal(n, ending, words):
    assert numbers.ordinal(n, ending) == words


def test_ordinal_unknown_ending_falls_back():
    assert numbers.ordinal(2, "xyz") == "zweite"


@pytest.mark.parametrize("n, words", [
    (1950, "neunzehnhundertfünfziger"), (80, "achtziger"), (2010, "zweitausendzehner"), (1900, "neunzehnhunderter"),
])
def test_decade(n, words):
    assert numbers.decade(n) == words


def test_decimal_and_digits():
    assert numbers.decimal("3", "14") == "drei Komma eins vier"
    assert numbers.decimal("0", "25") == "null Komma zwei fünf"
    assert numbers.digits("0815") == "null acht eins fünf"


@pytest.mark.parametrize("a, b, words", [
    (1, 2, "ein halb"), (3, 2, "drei halbe"), (3, 4, "drei Viertel"), (1, 3, "ein Drittel"),
    (5, 12, "fünf Zwölftel"), (7, 20, "sieben Zwanzigstel"), (2, 1000, "zwei Tausendstel"),
])
def test_fraction(a, b, words):
    assert numbers.fraction(a, b) == words


def test_fraction_without_word():
    assert numbers.fraction(882, 2019) is None


def test_article_form_agrees_with_gender():
    assert numbers.article_form(1, "f") == "eine"
    assert numbers.article_form(1, "n") == "ein"
    assert numbers.article_form(21, "f") == "einundzwanzig"


def test_month_and_time():
    assert numbers.month(3) == "März" and numbers.month(13) is None
    assert numbers.time_of_day(12, 30) == "zwölf Uhr dreißig"
    assert numbers.time_of_day(1, 5) == "ein Uhr fünf"
    assert numbers.time_of_day(9, 0) == "neun Uhr"
