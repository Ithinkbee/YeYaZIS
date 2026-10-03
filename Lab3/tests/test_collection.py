"""Тестовая коллекция: состав, одинаковый объём, эталоны отделены от текста."""

from __future__ import annotations

from collections import Counter

from izbornik import config
from izbornik.collection import detect_language


def test_twenty_documents_five_per_group(collection):
    assert len(collection) == 20
    groups = Counter(entry.group for entry in collection)
    assert groups == {"ru-cs": 5, "ru-lit": 5, "de-cs": 5, "de-lit": 5}


def test_documents_have_equal_size(collection):
    low = config.DOC_TARGET_CHARS * (1 - config.DOC_SIZE_TOLERANCE)
    high = config.DOC_TARGET_CHARS * (1 + config.DOC_SIZE_TOLERANCE)
    for entry in collection:
        size = collection.analyzed(entry.id).layout.length
        assert low <= size <= high, f"{entry.id}: {size} знаков"
        assert entry.path.exists()


def test_sources_and_licenses_are_recorded(collection):
    for entry in collection:
        assert entry.source_url.startswith("https://")
        assert entry.source.get("license", "").startswith("CC BY")


def test_references_exist_and_are_removed_from_text(collection):
    for entry in collection:
        assert len(entry.reference_abstract) > 300, entry.id
        text = collection.text(entry.id)
        probe = entry.reference_abstract[20:120]
        assert probe not in text, f"эталон {entry.id} попал в текст документа"


def test_author_keywords_for_scientific_articles(collection):
    for entry in collection:
        if entry.source.get("kind") == "cyberleninka":
            assert len(entry.reference_keywords) >= 4


def test_language_of_documents_matches_alphabet(collection):
    for entry in collection:
        assert detect_language(collection.text(entry.id)) == entry.language


def test_stats_are_per_language(collection):
    stats = collection.stats("ru")
    assert stats.n_docs == 10
    assert all(doc_id.startswith("ru-") for doc_id in stats.doc_ids)
    assert collection.stats("de", "collection").n_docs == 20


def test_every_document_gets_a_full_summary(collection):
    for entry in collection:
        summary = collection.summarize(entry.id).summary
        assert len(summary.sentences) == config.SUMMARY_SENTENCES
        indexes = [s.index for s in summary.sentences]
        assert indexes == sorted(indexes)
        assert len(summary.keywords.tree) == config.KEYWORDS_TOP
