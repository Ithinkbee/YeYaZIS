"""Разбиение на абзацы и предложения; смещения для Posd и Posp."""

from __future__ import annotations

import pytest

from izbornik.text.segment import clean, looks_like_heading, parse, split_blocks, split_sentences


def sentences(text: str, language: str) -> list[str]:
    return [text[a:b] for a, b in split_sentences(text, language)]


def test_simple_russian():
    assert sentences("Первое предложение. Второе! Третье? Четвёртое…", "ru") == [
        "Первое предложение.", "Второе!", "Третье?", "Четвёртое…"]


@pytest.mark.parametrize("text", [
    "Это важно, т. е. необходимо учитывать. Далее.",
    "Роман написал А. С. Пушкин в Михайловском. Далее.",
    "См. рис. 3 и табл. 2 в приложении. Далее.",
    "Работа выполнена в 1990-х гг. и опубликована. Далее.",
])
def test_russian_abbreviations_do_not_split(text):
    assert len(sentences(text, "ru")) == 2


@pytest.mark.parametrize("text", [
    "Das gilt z. B. für Datenbanken. Weiter.",
    "Er lebte im 19. Jahrhundert in Weimar. Weiter.",
    "Goethe schrieb am 4. Mai einen Brief. Weiter.",
    "Das Buch von J. W. Goethe erschien 1774. Weiter.",
    "Siehe dazu vgl. Abb. 3 und bzw. Kap. 2 im Anhang. Weiter.",
])
def test_german_abbreviations_and_ordinals(text):
    assert len(sentences(text, "de")) == 2


def test_german_year_ends_sentence():
    assert len(sentences("Der Roman erschien 1774. Danach folgte eine Welle.", "de")) == 2


def test_quotes_stay_with_sentence():
    parts = sentences("Он сказал: «Готово.» Потом ушёл.", "ru")
    assert parts == ["Он сказал: «Готово.»", "Потом ушёл."]


def test_direct_speech_continues_after_dash():
    parts = sentences("— Пойдёшь? — спросил он. Она кивнула.", "ru")
    assert parts == ["— Пойдёшь? — спросил он.", "Она кивнула."]


def test_page_reference_stays_with_quotation():
    parts = sentences("Sie sagte: „Ich gehe.“ (164) – Als Wochen später alles endet. Weiter.", "de")
    assert parts == ["Sie sagte: „Ich gehe.“ (164)", "– Als Wochen später alles endet.", "Weiter."]


def test_list_numbers_stay_with_items():
    parts = sentences("Этапы метода. 2. Загрузка данных выполняется. 2.1. Проверка идёт следом.", "ru")
    assert parts == ["Этапы метода.", "2. Загрузка данных выполняется.", "2.1. Проверка идёт следом."]


def test_two_letter_initial():
    assert len(sentences("Поэма Дж. Байрона вышла в 1819 году. Далее.", "ru")) == 2


def test_lowercase_after_period_does_not_split():
    assert len(sentences("Версия 2.0 вышла. и ещё текст без заглавной.", "ru")) == 1


def test_blocks_by_blank_lines_and_by_lines():
    assert split_blocks("а\nб\n\nв") == ["а б", "в"]
    assert split_blocks("а\nб\nв") == ["а", "б", "в"]


def test_clean_normalizes_spaces_and_invisible():
    assert clean("a  b­ c\r\n") == "a b c\n"


def test_heading_detection():
    assert looks_like_heading("Введение")
    assert looks_like_heading("2. Материалы и методы")
    assert not looks_like_heading("Это обычное предложение.")
    assert not looks_like_heading("х" * 200)


def test_offsets_match_formula_definitions():
    raw = "# Заголовок\n\nПервое предложение абзаца. Второе предложение.\n\nНовый абзац здесь."
    layout = parse(raw, "ru")
    assert layout.text == "Заголовок\nПервое предложение абзаца. Второе предложение.\nНовый абзац здесь."
    heading, first, second = layout.paragraphs
    assert heading.heading and not heading.sentences
    assert len(layout.sentences) == 3
    for sentence in layout.sentences:
        assert layout.text[sentence.start:sentence.end] == sentence.text
        paragraph = layout.paragraphs[sentence.paragraph]
        assert paragraph.text[sentence.start_in_paragraph:].startswith(sentence.text)
    s0, s1, s2 = layout.sentences
    assert s0.start == len("Заголовок\n") and s0.start_in_paragraph == 0
    assert s1.start_in_paragraph == len("Первое предложение абзаца. ")
    assert s2.paragraph == 2 and s2.start_in_paragraph == 0


def test_explicit_heading_marker_is_stripped():
    layout = parse("# Введение\n\nТекст.", "ru")
    assert layout.paragraphs[0].text == "Введение"
    assert layout.paragraphs[0].heading
