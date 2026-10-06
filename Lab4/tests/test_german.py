"""Немецкая морфология: спряжение, причастия, склонение, сложные слова."""

from __future__ import annotations

import pytest

from dragoman.german import morphology as gm


@pytest.mark.parametrize("verb, present, past, participle, zu", [
    ("verwenden", "verwendet", "verwendete", "verwendet", "zu verwenden"),
    ("vor|stellen", "stellt", "stellte", "vorgestellt", "vorzustellen"),
    ("an|geben", "gibt", "gab", "angegeben", "anzugeben"),
    ("verstehen", "versteht", "verstand", "verstanden", "zu verstehen"),
    ("implementieren", "implementiert", "implementierte", "implementiert", "zu implementieren"),
    ("arbeiten", "arbeitet", "arbeitete", "gearbeitet", "zu arbeiten"),
    ("rechnen", "rechnet", "rechnete", "gerechnet", "zu rechnen"),
    ("lernen", "lernt", "lernte", "gelernt", "zu lernen"),
    ("entwickeln", "entwickelt", "entwickelte", "entwickelt", "zu entwickeln"),
    ("gehören", "gehört", "gehörte", "gehört", "zu gehören"),
    ("bringen", "bringt", "brachte", "gebracht", "zu bringen"),
])
def test_conjugation(verb, present, past, participle, zu):
    assert gm.present(verb, 3, "sg")[0] == present
    assert gm.past(verb, 3, "sg")[0] == past
    assert gm.participle(verb) == participle
    assert gm.zu_infinitive(verb) == zu


def test_separable_prefix_is_returned_separately():
    assert gm.present("vor|stellen", 1, "pl") == ("stellen", "vor")
    assert gm.past("durch|führen", 3, "pl") == ("führten", "durch")


def test_irregular_paradigms():
    assert [gm.present("sein", p, n)[0] for p, n in ((1, "sg"), (3, "sg"), (1, "pl"))] == ["bin", "ist", "sind"]
    assert gm.past("werden", 3, "pl")[0] == "wurden"
    assert gm.subjunctive("können", 3, "sg")[0] == "könnte"
    assert gm.present("müssen", 3, "sg")[0] == "muss"


def test_perfect_auxiliary():
    assert gm.auxiliary("kommen") == "sein"
    assert gm.auxiliary("an|kommen") == "sein"
    assert gm.auxiliary("bekommen") == "haben"
    assert gm.auxiliary("entstehen") == "sein"
    assert gm.auxiliary("verwenden") == "haben"


def test_noun_declension():
    assert gm.noun_form("Programm", "n", "Programme", "sg", "G") == "Programms"
    assert gm.noun_form("Prozess", "m", "Prozesse", "sg", "G") == "Prozesses"
    assert gm.noun_form("Gott", "m", "Götter", "sg", "G") == "Gottes"
    assert gm.noun_form("Algorithmus", "m", "Algorithmen", "sg", "G") == "Algorithmus"
    assert gm.noun_form("Student", "m", "Studenten", "sg", "A", weak=True) == "Studenten"
    assert gm.noun_form("Netz", "n", "Netze", "pl", "D") == "Netzen"
    assert gm.noun_form("Daten", "pl", "Daten", "pl", "D") == "Daten"


@pytest.mark.parametrize("kind, gender, number, case, expected", [
    ("def", "n", "sg", "N", "das neuronale Netz"),
    ("indef", "n", "sg", "N", "ein neuronales Netz"),
    ("none", "n", "sg", "N", "neuronales Netz"),
    ("def", "n", "pl", "D", "den neuronalen Netzen"),
    ("def", "m", "sg", "A", "den neuronalen Netz"),
])
def test_adjective_declension(kind, gender, number, case, expected):
    table = gm.adjective_table(kind)
    det = gm.determiner(kind, gender, number, case)
    noun = gm.noun_form("Netz", "n", "Netze", number, case)
    text = " ".join(x for x in (det, gm.adjective_form("neuronal", "pos", table, gender, number, case), noun) if x)
    assert text == expected


def test_comparison():
    assert gm.adjective_form("schnell", "comp", None, "n", "sg", "N") == "schneller"
    assert gm.adjective_form("gut", "comp", None, "n", "sg", "N") == "besser"
    assert gm.adjective_form("wichtig", "sup", None, "n", "sg", "N") == "am wichtigsten"
    assert gm.adjective_form("hoch", "pos", gm.WEAK, "f", "sg", "D") == "hohen"


def test_compounds():
    assert gm.compound([gm.compound_part("Sicherheit", "f")], "Lücke") == "Sicherheitslücke"
    assert gm.compound([gm.compound_part("Netzwerk", "n")], "Protokoll") == "Netzwerkprotokoll"
    assert gm.compound([gm.compound_part("Seite", "f")], "Zahl") == "Seitenzahl"
    assert gm.compound([gm.compound_part("Entwurf", "m")], "Muster") == "Entwurfsmuster"
    assert gm.compound([gm.compound_part("Kompilieren", "n")], "Prozess") == "Kompilierprozess"
    assert gm.compound(["CPU-"], "Zeit") == "CPU-Zeit"


def test_pronouns():
    assert gm.personal(3, "sg", "m", "A") == "ihn"
    assert gm.personal(3, "pl", "", "D") == "ihnen"
    assert gm.relative("f", "sg", "D") == "der"
    assert gm.relative("n", "pl", "D") == "denen"
