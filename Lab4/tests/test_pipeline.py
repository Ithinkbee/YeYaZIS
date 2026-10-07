"""Перевод документа целиком: статистика, частотный список, сохранение в файл.

Методичка требует: число слов во входном тексте, число переведённых слов,
грамматическую информацию, частотный список слов с переводами и сохранение
результатов в TXT в кодировке Unicode.
"""

from __future__ import annotations

import pytest

from dragoman import export
from dragoman.collection import Collection
from dragoman.translate.lexical import DICT, NAME, UNKNOWN

TEXT = ("# Compilers\n\n"
        "A compiler translates source code into machine code. The compiler checks the code, "
        "and the compiler reports errors. Grace Hopper wrote the first compiler in 1952.\n\n"
        "The flibbergast compiler is unknown.")


@pytest.fixture(scope="module")
def t(translator):
    return translator.translate(TEXT, log_unknown=False)


def test_statistics(t):
    stats = t.stats
    assert stats["sentences"] == 5
    # слова — без знаков препинания и чисел: 2 + 9 + 9 + 7 + 5
    assert stats["words"] == 1 + 9 + 10 + 6 + 5
    assert stats["names"] == 2 and stats["numbers"] == 0
    assert stats["translated"] == stats["dictionary"] + stats["rule"]
    assert stats["translated"] + stats["names"] + stats["numbers"] + stats["unknown"] == stats["words"]
    assert stats["unknown_words"] == ["flibbergast"]
    assert 0.9 < stats["coverage"] < 1


def test_domain_is_detected(t, translator):
    assert t.domain == "cs" and t.domain_auto
    lit = translator.translate("The novel tells the story of a young woman and her love. "
                               "The heroine marries the hero in the last chapter.", log_unknown=False)
    assert lit.domain == "lit"


def test_frequency_list_with_grammar(t):
    words = t.words
    counts = [item.count for item in words]
    assert counts == sorted(counts, reverse=True)
    top = words[0]
    assert (top.lemma, top.count) == ("compiler", 6)           # и «Compilers» в заголовке
    assert top.translation == "der Compiler (мн. ч. Compiler)"
    assert top.tags["NN"] == 5 and "существительное" in top.tag_text
    assert top.forms == {"compiler": 5, "Compilers": 1}
    assert top.status == DICT
    by_lemma = {item.lemma: item for item in words}
    verb = by_lemma["translate"]
    assert verb.pos == "VERB" and "übersetzt" in verb.german_grammar and "hat übersetzt" in verb.german_grammar
    assert by_lemma["Grace"].status == NAME
    assert by_lemma["flibbergast"].status == UNKNOWN


def test_translation_text(t):
    german = [" ".join(s.text for s in sentences) for heading, sentences in t.paragraphs]
    assert german[0] == "Compiler"
    assert german[1].startswith("Ein Compiler übersetzt Quellcode in Maschinencode.")
    assert "Grace Hopper schrieb den ersten Compiler 1952." in german[1]


def test_export_is_unicode_with_crlf(t):
    text = export.render_text(t)
    data = export.encode(text, "utf-16")
    assert data[:2] == b"\xff\xfe"                       # UTF-16 LE с меткой порядка байтов
    decoded = data.decode("utf-16")
    assert "\r\n" in decoded and "\n" not in decoded.replace("\r\n", "")
    for part in ["СТАТИСТИКА", "Слов во входном тексте:", "Переведено слов:", "ПЕРЕВОД (DE)",
                 "ИСХОДНЫЙ ТЕКСТ (EN)", "ЧАСТОТНЫЙ СПИСОК", "ОБОЗНАЧЕНИЯ ТЕГОВ", "Maschinencode", "der Compiler"]:
        assert part in decoded, part
    utf8 = export.encode(text, "utf-8")
    assert utf8[:3] == b"\xef\xbb\xbf" and utf8[3:].decode("utf-8") == text


def test_export_parts(t):
    only_words = export.render_text(t, "words")
    assert "ЧАСТОТНЫЙ СПИСОК" in only_words and "ПЕРЕВОД (DE)" not in only_words
    only_translation = export.render_text(t, "translation", with_source=False)
    assert "ПЕРЕВОД (DE)" in only_translation and "ИСХОДНЫЙ ТЕКСТ" not in only_translation
    assert "ЧАСТОТНЫЙ СПИСОК" not in only_translation
    assert export.filename(t, "utf-16") == "dragoman-Compilers.txt"


def test_translations_are_cached(translator):
    first = translator.translate("The cache is fast.", domain="cs", log_unknown=False)
    second = translator.translate("The cache is fast.", domain="cs", log_unknown=False)
    assert first is second


def test_unknown_words_are_logged(translator, lexicon):
    translator.translate("The quuxifier frobnicates.", domain="cs")
    assert "quuxifier" in {row["en"] for row in lexicon.unknown()}
    lexicon.forget_unknown("quuxifier")


@pytest.mark.parametrize("entry", Collection().entries, ids=lambda e: e.id)
def test_collection_document_translates(translator, entry):
    collection = Collection()
    t = translator.translate(collection.text(entry.id), entry.title, entry.domain, log_unknown=False)
    assert t.stats["words"] > 300
    assert t.stats["coverage"] > 0.93
    assert all(s.text for s in t.sentences)
