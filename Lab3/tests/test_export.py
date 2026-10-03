"""Сохранение реферата в файл."""

from __future__ import annotations

import io
import json

import pytest

from izbornik import export
from izbornik.ostis.scs import escape, to_scs
from izbornik.summary import Summary


@pytest.fixture(scope="module")
def summary(collection):
    return collection.summarize("ru-lit-onegin", 10).summary


@pytest.fixture
def ctx():
    return export.Context(source_link="http://127.0.0.1:8030/doc/ru-lit-onegin/source",
                          source_site="Википедия", license="CC BY-SA 4.0")


def test_txt_has_both_sections_and_source_link(summary, ctx):
    text = export.to_txt(summary, ctx)
    assert "1. КЛАССИЧЕСКИЙ РЕФЕРАТ" in text and "2. РЕФЕРАТ В ВИДЕ СПИСКА КЛЮЧЕВЫХ СЛОВ" in text
    assert ctx.source_link in text
    assert summary.sentences[0].compressed in text


def test_docx_opens(summary, ctx):
    import docx

    document = docx.Document(io.BytesIO(export.to_docx(summary, ctx)))
    body = "\n".join(p.text for p in document.paragraphs)
    assert "Классический реферат" in body and "ключевых слов" in body


def test_json_roundtrip(summary, ctx):
    data = json.loads(export.to_json(summary, ctx))
    again = Summary.from_dict(data)
    assert [s.index for s in again.sentences] == [s.index for s in summary.sentences]
    assert again.keywords.texts() == summary.keywords.texts()


def test_scs_escaping():
    assert escape("a[b]c\\d") == "a\\[b\\]c\\\\d"
    assert escape("*важно") .startswith("∗")


def test_scs_structure(summary):
    text = to_scs(summary)
    assert "doc_ru_lit_onegin" in text and "=> nrel_summary:" in text
    assert text.count("<- concept_sentence;;") == len(summary.sentences)
    assert "rrel_classic_summary" in text and "rrel_keyword_summary" in text
    # каждая sc-ссылка закрыта: открывающих и закрывающих неэкранированных скобок поровну
    unescaped = text.replace("\\[", "").replace("\\]", "")
    assert unescaped.count("[") == unescaped.count("]")


def test_filenames_are_ascii(summary):
    for fmt in export.FORMATS:
        assert export.filename(summary, fmt).isascii()
