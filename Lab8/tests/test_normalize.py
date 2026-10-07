"""Нормализация: что и как произносится."""

from __future__ import annotations

import pytest

from glashatai.evaluation import load_gold, words
from glashatai.text import ReadingOptions
from glashatai.text.normalize import feminine, tidy

from .conftest import render


@pytest.mark.parametrize("case", [c for c in load_gold() if c.category != "satz"], ids=lambda c: c.text[:40])
def test_gold_reading(reader, case):
    """Эталонный набор читается слово в слово."""
    assert words(render(reader, case.text)) == words(case.expected)


@pytest.mark.parametrize("case", [c for c in load_gold() if c.category == "satz"], ids=lambda c: c.text[:40])
def test_gold_sentences(reader, case):
    assert len(reader.prepare(case.text).sentences) == int(case.expected)


@pytest.mark.parametrize("text, expected", [
    ("Am 1. Mai", "Am ersten Mai"),
    ("die 3. Auflage", "die dritte Auflage"),
    ("in der 2. Version", "in der zweiten Version"),
    ("ein 2. Versuch", "ein zweiter Versuch"),
    ("des 20. Jahrhunderts", "des zwanzigsten Jahrhunderts"),
    ("Berlin, 3. Mai 2021", "Berlin, dritter Mai zweitausendeinundzwanzig"),
])
def test_ordinal_case_follows_previous_word(reader, text, expected):
    assert words(render(reader, text)) == words(expected)


def test_enumeration_at_sentence_start_is_a_number(reader):
    assert render(reader, "1. Einleitung und Motivation folgen.").startswith("eins")


@pytest.mark.parametrize("text, expected", [
    ("1 Sekunde", "eine Sekunde"), ("1 Bit", "ein Bit"), ("2 Sekunden", "zwei Sekunden"),
    ("1,5 GB", "eins Komma fünf Gigabyte"), ("1 GHz", "ein Gigahertz"), ("-5 °C", "minus fünf Grad Celsius"),
    ("100 Mbit/s", "hundert Megabit pro Sekunde"), ("1 Mio. Nutzer", "eine Million Nutzer"),
    ("mit 1 Methode", "mit einer Methode"), ("nach 1 Schritt", "nach einem Schritt"),
])
def test_number_agrees_with_noun(reader, text, expected):
    assert words(render(reader, text)) == words(expected)


def test_feminine_heuristic():
    assert feminine("Sekunde") and feminine("Methode") and feminine("Verbindung") and feminine("Information")
    assert not feminine("Computer") and not feminine("Name") and not feminine("Programm")


@pytest.mark.parametrize("text, expected", [
    ("vom 12. bis 14. Juni", "vom zwölften bis vierzehnten Juni"),
    ("1792–1872", "siebzehnhundertzweiundneunzig bis achtzehnhundertzweiundsiebzig"),
    ("2019/882", "zweitausendneunzehn Schrägstrich achthundertzweiundachtzig"),
    ("3:1", "drei zu eins"),
    ("um 9:05", "um neun Uhr fünf"),
    ("1.2. Abschnitt", "eins Punkt zwei Abschnitt"),
    ("Version 3.01", "Version drei Punkt null eins"),
    ("1.000 Einträge", "tausend Einträge"),
    ("12 345 Zeilen", "zwölftausenddreihundertfünfundvierzig Zeilen"),
    ("die 1980ern", "die neunzehnhundertachtzigern"),
    ("§ 9a", "Paragraf neun Ah"),
])
def test_numbers_in_context(reader, text, expected):
    assert words(render(reader, text)) == words(expected)


def test_tokens_keep_their_place_in_text(reader):
    text = "Ab 1954 nutzt z. B. die CPU 12 GB."
    document = reader.prepare(text)
    for sentence in document.sentences:
        assert text[sentence.start:sentence.end] == sentence.text
        for token in sentence.tokens:
            assert text[token.start:token.end] == token.text
    kinds = {t.text: t.kind for t in document.sentences[0].tokens}
    assert kinds["1954"] == "year" and kinds["z. B."] == "abbreviation" and kinds["CPU"] == "acronym"
    assert kinds["12 GB"] == "unit"


def test_changes_are_reported(reader):
    data = reader.prepare("Ab 1954 nutzt z. B. die CPU.").to_dict()
    changes = data["paragraphs"][0]["sentences"][0]["changes"]
    assert [c["text"] for c in changes] == ["1954", "z. B.", "CPU"]
    assert changes[2]["say"] == "Zeh Peh Uh" and changes[0]["kind_ru"] == "год"
    assert data["stats"]["changed"] == 3


def test_english_terms(reader):
    sentence = reader.prepare("Deep Learning nutzt die Cloud und Softwareentwicklung im Quellcode.").sentences[0]
    english = [t for t in sentence.tokens if t.kind == "english"]
    assert [t.text for t in english] == ["Deep Learning", "Cloud", "Softwareentwicklung", "Quellcode"]
    assert english[0].say == "'Diep 'Lörning" and english[1].say == "'Klaud"
    assert english[2].say == "'Softwär-entwicklung" and english[3].say == "Quell-kohd"
    # браузеру — как написано, собственному синтезатору — по записи
    assert "Deep Learning" in sentence.render("written") and "Diep Lörning" in sentence.render("plain")


def test_function_notation_and_initials(reader):
    assert render(reader, "O(n log n)", "plain") == "Oh von Enn log Enn."
    assert render(reader, "J. von Neumann baute ihn.", "plain") == "Jott von Noimann baute ihn."


def test_options_switch_rules_off(reader):
    raw = ReadingOptions.raw()
    assert render(reader, "Ab 1954 nutzt z. B. die CPU.", "plain", **raw.to_dict()) == "Ab 1954 nutzt z. B. die CPU."
    assert "Quelle zwölf" in render(reader, "Eine Studie [12].", "plain", citations=True)
    assert "12" not in render(reader, "Eine Studie [12].", "plain")
    assert render(reader, "Siehe https://example.org/a/b.", "plain", urls="skip") == "Siehe."
    assert "Schrägstrich" in render(reader, "Siehe https://example.org/a/b.", "plain", urls="full")
    assert "Cloud" in render(reader, "Die Cloud.", "plain", english=False)


def test_reading_options_from_dict():
    options = ReadingOptions.from_dict({"numbers": False, "urls": "full", "bogus": 1, "citations": 1})
    assert options.numbers is False and options.urls == "full" and options.citations is True
    assert ReadingOptions.from_dict({"urls": "everything"}).urls == "short"


def test_tidy_keeps_one_final_period():
    assert tidy("Ein Satz. Mitten drin , und Ende") == "Ein Satz, Mitten drin, und Ende."
    assert tidy("Wirklich?") == "Wirklich?"
    assert tidy(", , Anfang") == "Anfang."
    assert tidy("Teil eins,", final=False) == "Teil eins"


def test_question_and_exclamation_kinds(reader):
    kinds = [s.kind for s in reader.prepare("Wie geht das? Ganz einfach! Und so.").sentences]
    assert kinds == ["question", "exclamation", "statement"]


def test_user_lexicon_wins(tmp_path):
    from glashatai.text import TextReader
    from glashatai.text.lexicon import Lexicon, UserLexicon

    user = UserLexicon(tmp_path / "lexicon.json")
    user.add("GitLab", "Gitt 'Läbb")
    user.add("CPU", "Prozessor")
    reader = TextReader(Lexicon(user=user))
    text = "Mit GitLab und der CPU."
    assert render(reader, text, "plain") == "Mit Gitt Läbb und der Prozessor."
    assert render(reader, text, "plain", lexicon=False) == "Mit GitLab und der Zeh Peh Uh."
    user.remove(user.all()[1].id)
    assert render(reader, text, "plain") == "Mit Gitt Läbb und der Zeh Peh Uh."
