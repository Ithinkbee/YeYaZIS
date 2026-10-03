"""Сжатие предложений классического реферата."""

from __future__ import annotations

from izbornik.text.compress import compress


def test_citations_and_figure_refs_removed():
    assert compress("Метод известен [3] и описан ранее [1, с. 45] (рис. 2).", "ru") == \
        "Метод известен и описан ранее."
    assert compress("Das Verfahren [12–14] ist bekannt (vgl. Abb. 3).", "de") == "Das Verfahren ist bekannt."


def test_russian_introductory_phrase_removed():
    assert compress("Таким образом, система строит реферат по формулам.", "ru") == \
        "Система строит реферат по формулам."


def test_german_introductory_word_kept():
    text = "Außerdem ist das System schnell und genau."
    assert compress(text, "de") == text


def test_short_remainder_is_not_mutilated():
    assert compress("Однако, верно.", "ru") == "Однако, верно."
