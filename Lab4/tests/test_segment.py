"""Разбиение на предложения и слова по правилам корпусов Universal Dependencies."""

from __future__ import annotations

import pytest

from dragoman.text.segment import layout, tokenize


def words(text):
    return [t.text for t in tokenize(text)]


def test_contractions_are_split():
    assert words("It doesn't work, can't you see?") == ["It", "does", "n't", "work", ",", "ca", "n't", "you",
                                                        "see", "?"]


def test_possessives():
    assert words("Hamlet's father and the students' books") == ["Hamlet", "'s", "father", "and", "the",
                                                               "students", "'", "books"]


def test_hyphenated_word_is_one_token():
    assert words("a state-of-the-art compiler") == ["a", "state-of-the-art", "compiler"]


def test_abbreviations_and_numbers():
    assert words("e.g., GCC and Mr. Smith in the U.S.") == ["e.g.", ",", "GCC", "and", "Mr.", "Smith", "in",
                                                           "the", "U.S."]
    assert words("50% of $5") == ["50", "%", "of", "$", "5"]
    assert words("the person(s) involved") == ["the", "person(s)", "involved"]


def test_offsets_point_into_text():
    text = "The compiler (CPU) runs."
    for token in tokenize(text):
        assert text[token.start:token.end] == token.text


def test_sentences_and_headings():
    doc = layout("# Introduction\n\nCompilers translate code. J. K. Rowling wrote it in 1997. The U.S. Army is "
                 "big. It works!\n\nSecond paragraph etc. The end.")
    texts = [s.text for s in doc.sentences]
    assert texts == ["Introduction", "Compilers translate code.", "J. K. Rowling wrote it in 1997.",
                     "The U.S. Army is big.", "It works!", "Second paragraph etc.", "The end."]
    assert doc.sentences[0].heading and not doc.sentences[1].heading
    assert [s.paragraph for s in doc.sentences] == [0, 1, 1, 1, 1, 2, 2]


@pytest.mark.parametrize("text, expected", [
    ("nor even of mortal flesh;—it is", ["nor", "even", "of", "mortal", "flesh", ";", "—", "it", "is"]),
    ("without feelings?...Do you", ["without", "feelings", "?", "...", "Do", "you"]),
    ('He said: "no!"—and left.', ["He", "said", ":", '"', "no", "!", '"', "—", "and", "left", "."]),
    ("a cross-compiler -- really", ["a", "cross-compiler", "--", "really"]),
])
def test_punctuation_glued_to_dashes_and_ellipses(text, expected):
    assert [t.text for s in layout(text).sentences for t in s.tokens] == expected

