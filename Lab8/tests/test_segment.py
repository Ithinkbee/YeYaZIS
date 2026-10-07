"""Деление текста на абзацы и предложения."""

from __future__ import annotations

import pytest

from glashatai.text.segment import paragraphs


def sentences(reader, text):
    return [s.text for s in reader.prepare(text).sentences]


@pytest.mark.parametrize("text, expected", [
    ("Das gilt z. B. für Compiler. Es gilt auch für Linker.", 2),
    ("Im 19. Jahrhundert begann alles. Dann kam mehr.", 2),
    ("Am 3. Mai beginnt es.", 1),
    ("Er kam 1954. Danach blieb er.", 2),
    ("J. von Neumann und G. Boole sind bekannt.", 1),
    ("Siehe Abb. 3 und Tab. 2 sowie S. 12 f. die Regel.", 1),
    ("Listen, Bäume usw. Die Wahl ist frei.", 2),
    ("Es gibt u. a. Listen. Die Wahl ist frei.", 2),
    ("Python 3.11 ist neu. Es ist schnell.", 2),
    ("Er sagte: „Das geht.“ Dann ging er.", 2),
    ("Wirklich? Ja! Natürlich.", 3),
    ("Am 12.03.2021 erschien sie. Später nicht.", 2),
    ("Das ist i. d. R. so. Manchmal nicht.", 2),
    ("Der Wert ist ca. 5. Das reicht.", 2),
])
def test_sentence_boundaries(reader, text, expected):
    assert len(sentences(reader, text)) == expected


def test_paragraphs_and_headings():
    text = "# Grundlagen\n\nErster Absatz.\nZweite Zeile ohne Punkt\nwird fortgesetzt.\n\n- Punkt eins\n- Punkt zwei"
    blocks = paragraphs(text)
    assert [b.heading for b in blocks] == [True, False, False, False, False]
    assert text[blocks[1].start:blocks[1].end] == "Erster Absatz."
    assert text[blocks[2].start:blocks[2].end] == "Zweite Zeile ohne Punkt\nwird fortgesetzt."
    assert text[blocks[3].start:blocks[3].end] == "- Punkt eins"


def test_short_line_before_text_is_a_heading():
    blocks = paragraphs("Einleitung\nDer Compiler übersetzt Programme.")
    assert blocks[0].heading and not blocks[1].heading
    assert not paragraphs("Nur eine Zeile ohne Punkt")[0].heading


def test_soft_wrapped_lines_join():
    blocks = paragraphs("Ein Satz, der über\nmehrere Zeilen geht\nund endet.")
    assert len(blocks) == 1


def test_heading_marker_is_not_read(reader):
    document = reader.prepare("# Datenmodell: RDF\n\nText.")
    first = document.sentences[0]
    assert first.heading and first.text == "Datenmodell: RDF"
    assert first.render("plain") == "Datenmodell: Err Deh Eff."


def test_long_sentence_is_split_without_pause(reader):
    clause = "die Analyse der Eingabe erfolgt in mehreren aufeinander folgenden Schritten"
    text = "Zuerst " + ", ".join([clause] * 8) + "."
    document = reader.prepare(text)
    parts = document.sentences
    assert len(parts) > 1
    assert all(len(p.text) <= 400 for p in parts)
    assert all(p.continued for p in parts[:-1]) and not parts[-1].continued
    assert parts[0].render("plain")[-1] != "."


def test_positions_cover_the_text(reader):
    text = "Erster Satz. Zweiter Satz!\n\nDritter Satz?"
    document = reader.prepare(text)
    assert [text[s.start:s.end] for s in document.sentences] == ["Erster Satz.", "Zweiter Satz!", "Dritter Satz?"]
    assert [s.paragraph for s in document.sentences] == [0, 0, 1]


def test_empty_and_silent_text(reader):
    assert reader.prepare("").sentences == []
    assert reader.prepare("   \n\n  ").sentences == []
    assert reader.prepare("[12]").sentences == []
