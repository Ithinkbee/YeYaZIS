"""Словарь в базе данных: поиск, правка, пополнение; догадки по правилам словообразования.

Тесты работают с отдельной временной базой, а не с общей тестовой, — правки
одних тестов не влияют на переводы в других.
"""

from __future__ import annotations

import pytest

from dragoman.lexicon import guess
from dragoman.lexicon.db import Entry, Lexicon, clean, read_tsv


@pytest.fixture()
def lex(tmp_path):
    lexicon = Lexicon(tmp_path / "dictionary.sqlite")
    yield lexicon
    lexicon.close()


def test_seed_loads_all_tables(lex):
    from dragoman import config

    expected = sum(len(read_tsv(p)) for p in sorted(config.LEXICON_DIR.glob("*.tsv")))
    stats = lex.stats()
    assert stats["total"] == expected > 3500
    assert stats["phrases"] > 300
    assert {"NOUN", "VERB", "ADJ", "ADV", "ADP", "PROPN"} <= set(stats["by_pos"])
    assert {"gen", "cs", "lit"} <= set(stats["by_domain"])


def test_seed_is_not_reloaded_when_tables_did_not_change(lex):
    assert lex.seed() == 0
    assert lex.seed(force=True) == lex.stats()["total"]


def test_domain_entry_comes_first(lex):
    assert clean(lex.best("play", "NOUN", "lit").de) == "Theaterstück"
    assert clean(lex.best("play", "NOUN", "cs").de) == "Spiel"
    assert clean(lex.best("editor", "NOUN", "lit").de) == "Lektor"


def test_noun_entry_has_gender_plural_and_display(lex):
    entry = lex.best("network", "NOUN", "cs")
    assert (clean(entry.de), entry.gender) == ("Netzwerk", "n")
    assert entry.display.startswith("das Netzwerk")


def test_separable_verb_marker_and_properties(lex):
    entry = lex.best("introduce", "VERB")
    assert "|" in entry.de and clean(entry.de) == "einführen"
    know = lex.best("know", "VERB")
    assert know.props.get("ccomp") == "wissen"


def test_phrases_are_indexed_by_first_word(lex):
    phrases = {e.en for e in lex.phrases_from("operating")}
    assert "operating system" in phrases


def test_add_update_delete_and_overrides_survive_reseed(lex):
    added = lex.add(Entry("blorptastic", "ADJ", "blorptastisch"))
    assert lex.best("blorptastic", "ADJ").de == "blorptastisch" and added.source == "user"
    # правка записи исходного словаря: запоминается и не затирается при перезагрузке таблиц
    seed = lex.best("compiler", "NOUN")
    lex.update(seed.id, {"de": "Übersetzer", "gender": "m", "plural": "Übersetzer"})
    lex.seed(force=True)
    assert clean(lex.best("compiler", "NOUN").de) == "Übersetzer"
    # удаление записи исходного словаря тоже переживает перезагрузку
    entry = lex.best("stack", "NOUN")
    lex.delete(entry.id)
    lex.seed(force=True)
    assert all(e.id != entry.id for e in lex.lookup("stack", "NOUN", strict=True))
    # сброс возвращает исходный словарь
    lex.reset()
    assert clean(lex.best("compiler", "NOUN").de) == "Compiler"
    assert lex.best("blorptastic", "ADJ") is None


def test_user_entry_wins_over_seed(lex):
    lex.add(Entry("cache", "NOUN", "Zwischenspeicher", "m", "Zwischenspeicher"))
    assert clean(lex.best("cache", "NOUN", "cs").de) == "Zwischenspeicher"


def test_unknown_words_journal(lex):
    lex.log_unknown([("flibber", "NOUN", "The flibber works."), ("flibber", "NOUN", "")])
    rows = {r["en"]: r for r in lex.unknown()}
    assert rows["flibber"]["count"] == 2 and rows["flibber"]["example"] == "The flibber works."
    # добавленное слово уходит из журнала
    lex.add(Entry("flibber", "NOUN", "Flibber", "m", "Flibber"))
    assert "flibber" not in {r["en"] for r in lex.unknown()}


def test_export_and_import_tsv(lex, tmp_path):
    lex.add(Entry("zorbit", "NOUN", "Zorbit", "m", "Zorbits", domain="cs"))
    text = lex.export_tsv(source="user")
    assert text.startswith("# en\tpos\tde") and "zorbit\tNOUN\tZorbit\tm\tZorbits" in text
    other = Lexicon(tmp_path / "other.sqlite")
    try:
        assert other.import_tsv(text) == 1
        assert other.import_tsv(text) == 0          # повторный импорт не дублирует
        assert clean(other.best("zorbit", "NOUN", "cs").de) == "Zorbit"
    finally:
        other.close()


def test_search_finds_both_languages(lex):
    entries, total = lex.search("netzwerk")
    assert total >= 1 and any(e.en == "network" for e in entries)
    entries, _ = lex.search("network", pos="NOUN")
    assert entries[0].en == "network"


@pytest.mark.parametrize("word, pos, german, gender", [
    ("modularization", "NOUN", "Modularisierung", "f"),
    ("composability", "NOUN", "Komposabilität", "f"),
    ("formalism", "NOUN", "Formalismus", "m"),
    ("cryptology", "NOUN", "Kryptologie", "f"),
    ("algorithmic", "ADJ", "algorithmisch", ""),
    ("interactive", "ADJ", "interaktiv", ""),
    ("virtualize", "VERB", "virtualisieren", ""),
])
def test_derivation_rules(lex, word, pos, german, gender):
    entry = guess.guess(word, pos, lex)
    assert entry is not None and entry.de == german and entry.gender == gender
    assert 0 < entry.confidence <= 1 and entry.source == "rule"


def test_compound_from_two_dictionary_words(lex):
    entry = guess.guess("dataflow", "NOUN", lex)
    assert entry is not None and entry.de.lower().startswith("daten")


def test_rules_do_not_guess_short_or_function_words(lex):
    assert guess.guess("ab", "NOUN", lex) is None
    assert guess.guess("upon", "ADP", lex) is None
