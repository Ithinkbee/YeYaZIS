"""Проверка шага предварительной обработки."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tolmach import preprocess  # noqa: E402


def test_strip_html_removes_script_and_style():
    """Содержимое script и style не должно попадать в текст документа.

    Это существенно: в таблице стилей и в сценарии латиница, и если они
    просочатся в текст, профиль русского документа будет испорчен.
    """
    markup = """
    <html><head><title>Заголовок</title>
    <style>body { font-family: Georgia, serif; color: red; }</style>
    </head><body>
    <script>document.querySelectorAll('a').forEach(function (x) { x.id = 'link'; });</script>
    <p>Видимый текст документа.</p>
    </body></html>
    """
    text = preprocess.strip_html(markup)
    assert "Видимый текст документа" in text
    assert "font-family" not in text
    assert "querySelectorAll" not in text
    assert "Georgia" not in text


def test_normalize_keeps_german_diacritics():
    """Умлауты и эсцет — заметные признаки немецкого, их нельзя терять."""
    normalized = preprocess.normalize("Die Bäume grüßen über die Straße!")
    assert normalized == "die bäume grüßen über die straße"


def test_normalize_composed_and_decomposed_umlaut_match():
    """«ü» одним символом и «u + диерезис» должны давать одинаковый результат."""
    composed = preprocess.normalize("über")
    decomposed = preprocess.normalize("über")
    assert composed == decomposed == "über"


def test_normalize_drops_digits_and_punctuation():
    normalized = preprocess.normalize("Дом 12, улица — «Мира»; 2024 год.")
    assert normalized == "дом улица мира год"


def test_normalize_collapses_whitespace():
    assert preprocess.normalize("  а\n\n\tб   в  ") == "а б в"


def test_count_letters_ignores_spaces():
    assert preprocess.count_letters("аб вг") == 4


def test_detect_encoding_from_meta():
    assert preprocess.detect_encoding(b'<meta charset="windows-1251">') == "windows-1251"
    assert preprocess.detect_encoding(b"<html>") == "utf-8"
    assert preprocess.detect_encoding(b"\xef\xbb\xbf<html>") == "utf-8-sig"


def test_detect_encoding_rejects_unknown_charset():
    """Несуществующая кодировка не должна ронять чтение файла."""
    assert preprocess.detect_encoding(b'<meta charset="no-such-codec">') == "utf-8"


def test_extract_title_falls_back():
    assert preprocess.extract_title("<title>Имя</title>") == "Имя"
    assert preprocess.extract_title("<html></html>", fallback="файл") == "файл"


def test_entities_are_unescaped():
    text = preprocess.strip_html("<p>&laquo;Толмач&raquo; &amp; текст</p>")
    assert "«Толмач»" in text
    assert "&" in text and "&amp;" not in text


def test_prepare_text_handles_plain_text():
    visible, normalized = preprocess.prepare_text("Просто текст", is_html=False)
    assert visible == "Просто текст"
    assert normalized == "просто текст"


def test_block_tags_do_not_glue_words():
    """Без разрыва на границе блоков соседние слова слиплись бы в одно."""
    normalized = preprocess.normalize(preprocess.strip_html("<p>один</p><p>два</p>"))
    assert normalized == "один два"
