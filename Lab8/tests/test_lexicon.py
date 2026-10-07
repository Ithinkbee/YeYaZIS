"""Словари произношения: встроенные и словарь пользователя."""

from __future__ import annotations

import json

import pytest

from glashatai.text import acronyms
from glashatai.text.lexicon import Lexicon, LexiconError, UserLexicon, load_abbreviations


def test_builtin_tables_load():
    lexicon = Lexicon()
    assert len(lexicon.english) > 150 and len(lexicon.acronyms) > 80 and len(lexicon.abbreviations) > 70
    assert lexicon.english_word("software").reading == "'Softwär"
    assert lexicon.acronym("RAM").reading == "'Ramm"
    assert lexicon.acronym("ram") is None                      # аббревиатуры различают регистр


def test_abbreviation_patterns_allow_missing_spaces():
    import re

    found = {a.written: a for a in load_abbreviations()}
    assert re.fullmatch(found["z. B."].pattern, "z.B.") and re.fullmatch(found["z. B."].pattern, "z. B.")
    assert found["S."].when == "number" and found["f."].when == "after" and found["usw."].when == "end"
    # длинные раньше коротких: «u. v. m.» не должно съесться как «u.»
    order = [a.written for a in load_abbreviations()]
    assert order.index("u. v. m.") < order.index("u. a.")


@pytest.mark.parametrize("word, part", [
    ("Softwareentwicklung", ("Software", "", "entwicklung")),
    ("Quellcode", ("Code", "Quell", "")),
    ("Netzwerkserver", ("Server", "Netzwerk", "")),
    ("Gigabyte", ("Byte", "Giga", "")),
])
def test_compound_parts(word, part):
    entry, head, tail = Lexicon().compound_part(word)
    assert (entry.written, head, tail) == part


@pytest.mark.parametrize("word", ["Angebot", "Verbot", "Hubraum", "knapp", "Coder", "Webs", "Branche"])
def test_no_false_compounds(word):
    assert Lexicon().compound_part(word) is None


@pytest.mark.parametrize("word, expected", [
    ("NASA", True), ("DARPA", True), ("COBOL", True), ("ADALINE", True),
    ("HTML", False), ("DSGVO", False), ("LSTM", False), ("CPU", False), ("IJCNN", False), ("NGEN", False),
])
def test_pronounceable(word, expected):
    assert acronyms.pronounceable(word) is expected


def test_spelling():
    assert acronyms.spell("CPU") == "Zeh Peh Uh"
    assert acronyms.spell_plural("URI") == "Uh Err Ihs"
    assert acronyms.as_word("DARPA") == "Darpa"
    assert acronyms.roman("XII") == 12 and acronyms.roman("XP") is None


def test_user_lexicon_add_update_remove(tmp_path):
    path = tmp_path / "lexicon.json"
    user = UserLexicon(path)
    entry = user.add("  GitLab ", "Gitt  'Läbb")
    assert entry.written == "GitLab" and entry.reading == "Gitt 'Läbb" and entry.plain == "Gitt Läbb"
    assert json.loads(path.read_text(encoding="utf-8"))["entries"][0]["written"] == "GitLab"
    version = user.version
    user.update(entry.id, "GitLab", "Gitt 'Läb")
    assert user.version > version and user.all()[0].reading == "Gitt 'Läb"
    again = UserLexicon(path)
    assert [e.reading for e in again.all()] == ["Gitt 'Läb"]
    assert again.remove(entry.id) and not again.remove(entry.id)
    assert again.all() == []


@pytest.mark.parametrize("written, reading", [("", "x"), ("GitLab", ""), ("!!!", "Ausrufe"),
                                              ("GitLab", "Gitt <b>"), ("x" * 61, "lang")])
def test_user_lexicon_rejects_bad_entries(tmp_path, written, reading):
    with pytest.raises(LexiconError):
        UserLexicon(tmp_path / "lexicon.json").add(written, reading)


def test_user_lexicon_rejects_duplicates(tmp_path):
    user = UserLexicon(tmp_path / "lexicon.json")
    first = user.add("Kubernetes", "Kuber'netis")
    second = user.add("Docker", "'Docker")
    with pytest.raises(LexiconError):
        user.add("kubernetes", "anders")
    with pytest.raises(LexiconError):
        user.update(second.id, "KUBERNETES", "anders")
    with pytest.raises(LexiconError):
        user.update("missing", "Docker", "x")
    assert len(user.all()) == 2 and first.id != second.id


def test_broken_file_means_empty_lexicon(tmp_path):
    path = tmp_path / "lexicon.json"
    path.write_text("{ broken", encoding="utf-8")
    assert UserLexicon(path).all() == []
