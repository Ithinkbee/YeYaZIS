"""Проверка системы целиком: корпус, оркестратор, оценка и выгрузка."""

from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tolmach import config, corpus, evaluation, experiments, export, preprocess  # noqa: E402
from tolmach.methods import METHOD_CODES  # noqa: E402
from tolmach.models import Document  # noqa: E402
from tolmach.recognizer import Recognizer  # noqa: E402


@pytest.fixture(scope="module")
def recognizer() -> Recognizer:
    """Система, обученная на настоящем корпусе проекта."""
    instance = Recognizer()
    instance.fit()
    return instance


@pytest.fixture(scope="module")
def documents() -> list[Document]:
    return corpus.load_collection()


@pytest.fixture(scope="module")
def report(recognizer, documents):
    return evaluation.build_report(recognizer.recognize_all(documents), METHOD_CODES)


# --- корпус и коллекция ------------------------------------------------------


def test_training_corpus_within_methodology_limits():
    """Методичка требует от 20 до 120 Кб на язык."""
    for code, stats in corpus.corpus_stats().items():
        assert stats.within_limits, (
            f"корпус языка {code}: {stats.kilobytes:.1f} Кб вне границ "
            f"{config.TRAIN_MIN_BYTES / 1024:.0f}–{config.TRAIN_MAX_BYTES / 1024:.0f} Кб"
        )


def test_corpora_are_comparable_in_size():
    """Перекос корпусов сделал бы профили языков неравноточными."""
    letters = [stats.letters for stats in corpus.corpus_stats().values()]
    assert max(letters) / min(letters) < 1.5


def test_collection_is_not_empty(documents):
    assert len(documents) >= 10


def test_every_document_is_labelled(documents):
    unlabelled = [document.doc_id for document in documents if document.gold is None]
    assert not unlabelled, f"нет эталона для: {unlabelled}"


def test_both_languages_present(documents):
    languages = {document.gold for document in documents}
    assert languages == set(config.LANGUAGE_CODES)


def test_documents_are_of_similar_size(documents):
    """Методичка требует документы одинакового размера (страница А4)."""
    letters = [document.letters for document in documents]
    assert min(letters) > 1500
    assert max(letters) / min(letters) < 1.6


def test_collection_files_are_html(documents):
    for document in documents:
        assert document.path is not None
        assert document.path.suffix.lower() in config.COLLECTION_EXTENSIONS


def test_markup_does_not_leak_into_text(documents):
    """В извлечённом тексте не должно быть следов CSS и сценариев."""
    for document in documents:
        for marker in ("font-family", "queryselectorall", "doctype", "stylesheet"):
            assert marker not in document.text, f"{document.doc_id}: просочилось «{marker}»"


def test_russian_documents_are_mostly_cyrillic(documents):
    for document in documents:
        if document.gold != "ru":
            continue
        letters = [char for char in document.text if char != " "]
        cyrillic = sum(1 for char in letters if "Ѐ" <= char <= "ӿ")
        assert cyrillic / len(letters) > 0.9


def test_labels_match_files_on_disk(documents):
    labels = corpus.load_labels()
    on_disk = {path.name for path in corpus.collection_files()}
    assert set(labels) == on_disk


# --- распознавание -----------------------------------------------------------


def test_all_methods_are_perfect_on_full_documents(report):
    """На полной странице текста пара «русский — немецкий» разделяется без ошибок."""
    for code, score in report.scores.items():
        assert score.accuracy == 1.0, f"{code}: {score.errors} ошибок"
    assert report.consensus.accuracy == 1.0


def test_methods_agree_on_every_document(report):
    assert report.disagreements() == []


def test_recognize_text_accepts_plain_text(recognizer):
    verdict = recognizer.recognize_text("Это предложение написано по-русски.")
    assert verdict.language == "ru"


def test_recognize_text_accepts_html(recognizer):
    verdict = recognizer.recognize_text(
        "<html><head><title>Titel</title><style>a{color:red}</style></head>"
        "<body><p>Dieser Satz ist auf Deutsch geschrieben worden.</p></body></html>",
        is_html=True,
    )
    assert verdict.language == "de"
    assert verdict.document.title == "Titel"


def test_consensus_needs_no_tie_break_when_all_agree(recognizer):
    verdict = recognizer.recognize_text("Совершенно однозначный русский текст здесь.")
    assert verdict.agreement == 1.0


def test_empty_text_does_not_crash(recognizer):
    verdict = recognizer.recognize_text("")
    assert verdict.language in config.LANGUAGE_CODES


def test_save_and_load_preserves_results(recognizer, documents, tmp_path):
    recognizer.save(tmp_path)
    restored = Recognizer()
    assert restored.load(tmp_path)
    for document in documents[:5]:
        assert restored.recognize(document).language == recognizer.recognize(document).language


# --- метрики -----------------------------------------------------------------


def test_scores_are_consistent(report):
    for score in report.scores.values():
        assert score.correct + score.errors == score.total
        assert score.total == report.labelled
        total_in_matrix = sum(sum(row.values()) for row in score.confusion.values())
        assert total_in_matrix == score.total


def test_precision_recall_are_perfect_when_accuracy_is(report):
    for score in report.scores.values():
        for code in config.LANGUAGE_CODES:
            assert score.precision(code) == 1.0
            assert score.recall(code) == 1.0
            assert score.f1(code) == 1.0


def test_speed_comparison_is_sorted(report):
    rows = evaluation.speed_comparison(report)
    assert len(rows) == len(METHOD_CODES)
    keys = [(-row["accuracy"], row["mean_ms"]) for row in rows]
    assert keys == sorted(keys)


def test_alphabet_method_is_the_fastest(report):
    """Алфавитный метод извлекает меньше всего признаков и обязан лидировать."""
    times = {code: score.mean_ms for code, score in report.scores.items()}
    assert min(times, key=times.get) == "alphabet"


# --- опыты -------------------------------------------------------------------


def test_windows_respect_word_boundaries():
    text = preprocess.normalize("один два три четыре пять шесть семь восемь девять")
    for piece in experiments.windows(text, 20, 3):
        assert not piece.startswith(" ") and not piece.endswith(" ")


def test_mix_keeps_proportions():
    first, second = "а" * 100, "b" * 100
    mixed = experiments.mix(first, second, 0.25)
    assert mixed.count("а") == 75
    assert mixed.count("b") == 25


def test_mix_at_the_extremes():
    assert experiments.mix("аааа", "bbbb", 0.0).strip() == "аааа"
    assert experiments.mix("аааа", "bbbb", 1.0).strip() == "bbbb"


def test_length_study_reaches_full_accuracy(recognizer, documents):
    """На фрагменте в 300 символов все методы обязаны быть безошибочны."""
    study = experiments.run_length_study(recognizer, documents, lengths=(300,), windows_per_document=2)
    for code in recognizer.methods:
        assert study.points[code][300].accuracy == 1.0


def test_mixture_crossover_is_near_the_middle(recognizer, documents):
    """Граница решения должна лежать около равной смеси, а не на краю."""
    study = experiments.run_mixture_study(recognizer, documents, ratios=(0.0, 0.25, 0.5, 0.75, 1.0))
    for code in recognizer.methods:
        assert study.shares[code][0.0] == 0.0
        assert study.shares[code][1.0] == 1.0
        assert study.crossover(code) is not None


# --- выгрузка ----------------------------------------------------------------


def test_csv_export_has_a_row_per_document(report):
    rows = list(csv.reader(io.StringIO(export.to_csv(report))))
    header = rows[0]
    assert header[0] == "file"
    document_rows = [row for row in rows[1:] if row and row[0].endswith(".html")]
    assert len(document_rows) == report.size


def test_json_export_is_valid_and_complete(report):
    payload = json.loads(export.to_json(report))
    assert payload["variant"] == 4
    assert len(payload["documents"]) == report.size
    assert set(payload["scores"]) == set(METHOD_CODES)
    for entry in payload["documents"]:
        assert set(entry["methods"]) == set(METHOD_CODES)


def test_text_export_contains_every_section(report):
    text = export.to_text(report)
    for heading in ("ТЕСТОВАЯ КОЛЛЕКЦИЯ", "РЕЗУЛЬТАТ ПО ДОКУМЕНТАМ",
                    "ТОЧНОСТЬ И БЫСТРОДЕЙСТВИЕ", "МАТРИЦЫ ОШИБОК", "РАЗНОГЛАСИЯ"):
        assert heading in text


def test_unknown_export_format_raises(report):
    with pytest.raises(ValueError):
        export.render(report, "pdf")


def test_save_writes_a_file(report, tmp_path):
    path = export.save(report, "csv", tmp_path)
    assert path.exists() and path.stat().st_size > 0
    assert path.suffix == ".csv"
