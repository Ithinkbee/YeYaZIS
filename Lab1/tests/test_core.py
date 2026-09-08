"""Тесты ядра ИПС: извлечение текста, морфология, формулы индексирования и поиск."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arachne import crawler, db, indexer  # noqa: E402
from arachne.ai import feedback, suggest  # noqa: E402
from arachne.search import Search  # noqa: E402
from arachne.text import extract, morphology  # noqa: E402


@pytest.fixture()
def collection(tmp_path: Path) -> Path:
    """Крошечная коллекция, для которой веса можно посчитать вручную."""
    node = tmp_path / "NODE-TEST"
    node.mkdir()
    (node / "d1.txt").write_text("Сеть сеть коммутатор", encoding="utf-8")
    (node / "d2.txt").write_text("Сети маршрутизатор", encoding="utf-8")
    (node / "d3.txt").write_text("Борщ рецепт", encoding="utf-8")
    return node


@pytest.fixture()
def conn(tmp_path: Path, collection: Path):
    connection = db.connect(tmp_path / "test.db")
    db.init_db(connection)
    crawler.add_source(connection, str(collection), "NODE-TEST")
    crawler.crawl(connection)
    indexer.build_index(connection)
    yield connection
    connection.close()


# --- Морфология -------------------------------------------------------------

def test_lemmatization_normalizes_word_forms():
    assert morphology.lemma("сетях") == "сеть"
    assert morphology.lemma("локальные") == "локальный"
    assert morphology.lemma("искал") == "искать"


def test_stopwords_are_dropped():
    tokens = morphology.tokenize("поиск в локальной сети и на сервере")
    significant = [t for t in tokens if morphology.is_significant(t)]
    assert "в" not in significant and "и" not in significant
    assert "поиск" in significant


def test_query_lemmas_are_unique_and_ordered():
    assert morphology.query_lemmas("сети сетей коммутаторы") == ["сеть", "коммутатор"]


# --- Извлечение текста ------------------------------------------------------

def test_extract_plain_text(tmp_path: Path):
    path = tmp_path / "doc.txt"
    path.write_text("Заголовок\n\nТекст документа.", encoding="utf-8")
    title, text = extract.extract(path)
    assert title == "Заголовок"
    assert "Текст документа." in text


def test_extract_html_strips_markup(tmp_path: Path):
    path = tmp_path / "page.html"
    path.write_text(
        "<html><head><title>Про сети</title></head>"
        "<body><script>x=1</script><p>Коммутатор передаёт кадры.</p></body></html>",
        encoding="utf-8",
    )
    title, text = extract.extract(path)
    assert title == "Про сети"
    assert "Коммутатор передаёт кадры." in text
    assert "x=1" not in text


def test_extract_cp1251(tmp_path: Path):
    path = tmp_path / "old.txt"
    path.write_bytes("Локальная сеть предприятия".encode("cp1251"))
    _, text = extract.extract(path)
    assert "Локальная сеть" in text


def test_unsupported_format_raises(tmp_path: Path):
    path = tmp_path / "archive.zip"
    path.write_bytes(b"PK\x03\x04")
    with pytest.raises(extract.ExtractionError):
        extract.extract(path)


# --- Формулы (1.5) и (1.6) --------------------------------------------------

def test_inverse_frequency_formula():
    # B_i = log(N / P_i), десятичный логарифм
    assert indexer.inverse_frequency(10, 1) == pytest.approx(1.0)
    assert indexer.inverse_frequency(3, 2) == pytest.approx(math.log10(1.5))
    # термин, встречающийся во всех документах, ничего не различает
    assert indexer.inverse_frequency(5, 5) == pytest.approx(0.0)


def test_index_weights_match_manual_calculation(conn):
    # N = 3, «сеть» встречается в двух документах, «коммутатор» — в одном
    assert indexer.get_lemma_inverse_frequency(conn, "сеть") == pytest.approx(math.log10(1.5))
    assert indexer.get_lemma_inverse_frequency(conn, "коммутатор") == pytest.approx(math.log10(3))

    doc_id = conn.execute(
        "SELECT id FROM documents WHERE path LIKE '%d1.txt'"
    ).fetchone()["id"]
    # A_ij = Q_ij * B_i, в первом документе «сеть» встречается дважды
    assert indexer.get_word_weight_in_document(conn, "сеть", doc_id) == pytest.approx(
        2 * math.log10(1.5)
    )
    assert indexer.get_word_weight_in_document(conn, "коммутатор", doc_id) == pytest.approx(
        math.log10(3)
    )


def test_vector_norm_matches_weights(conn):
    doc_id = conn.execute(
        "SELECT id FROM documents WHERE path LIKE '%d1.txt'"
    ).fetchone()["id"]
    vector = indexer.get_document_vector(conn, doc_id)
    expected = math.sqrt(sum(value * value for value in vector.values()))
    stored = conn.execute(
        "SELECT vector_norm FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()["vector_norm"]
    assert stored == pytest.approx(expected)


# --- Векторный поиск --------------------------------------------------------

def test_search_finds_document_by_word_form(conn):
    # запрос в другой словоформе должен находить документ
    results = Search(conn=conn, search_query="сетей").get_search_result()
    assert len(results) == 2
    assert results[0].rank > results[1].rank


def test_search_ranking_prefers_rare_term(conn):
    results = Search(conn=conn, search_query="коммутатор").get_search_result()
    assert len(results) == 1
    assert "d1" in results[0].path


def test_cosine_is_normalized(conn):
    results = Search(conn=conn, search_query="борщ рецепт").get_search_result()
    # документ полностью совпадает с запросом — косинус равен единице
    assert results[0].rank == pytest.approx(1.0, abs=1e-6)


def test_all_words_together_filters_results(conn):
    loose = Search(conn=conn, search_query="сеть борщ").get_search_result()
    strict = Search(
        conn=conn, search_query="сеть борщ", all_words_together=True
    ).get_search_result()
    assert len(loose) > len(strict) == 0


def test_matched_words_are_reported(conn):
    results = Search(conn=conn, search_query="сеть коммутатор").get_search_result()
    assert "коммутатор" in results[0].matched_words
    assert results[0].explanation


def test_scalar_product_and_norm():
    assert Search.scalar_product({"a": 2.0, "b": 1.0}, {"a": 3.0}) == pytest.approx(6.0)
    assert Search.euclidean_norm({"a": 3.0, "b": 4.0}) == pytest.approx(5.0)


# --- Интеллектуальные функции интерфейса ------------------------------------

def test_typo_correction(conn):
    corrections = suggest.corrections_for(conn, ["комутатор"])
    assert corrections.get("комутатор") == "коммутатор"


def test_damerau_levenshtein_counts_transposition():
    assert suggest.damerau_levenshtein("коммутатор", "коммутатро") == 1
    assert suggest.damerau_levenshtein("сеть", "сеть") == 0


def test_autocomplete_uses_index_vocabulary(conn):
    assert any(
        item.startswith("комм") for item in suggest.autocomplete(conn, "комм")
    )


def test_query_analysis_reports_morphology(conn):
    analysis = suggest.analyze(conn, "в локальных сетях")
    assert "в" in analysis.stopwords
    assert "сеть" in analysis.lemmas
    assert any(item["lemma"] == "сеть" for item in analysis.morphology)


def test_rocchio_shifts_query_vector(conn):
    doc_id = conn.execute(
        "SELECT id FROM documents WHERE path LIKE '%d3.txt'"
    ).fetchone()["id"]
    base = {"сеть": 1.0}
    shifted = feedback.rocchio_vector(conn, base, [doc_id], [])
    assert "борщ" in shifted  # термины отмеченного документа вошли в запрос
    assert shifted["сеть"] == pytest.approx(1.0)


def test_similar_documents(conn):
    doc_id = conn.execute(
        "SELECT id FROM documents WHERE path LIKE '%d1.txt'"
    ).fetchone()["id"]
    similar = feedback.similar_documents(conn, doc_id)
    assert similar and similar[0]["title"]


# --- Паук -------------------------------------------------------------------

def test_crawl_is_incremental(conn, collection: Path):
    report = crawler.crawl(conn)
    assert report.added == 0 and report.skipped == 3

    (collection / "d4.txt").write_text("Новый документ про сеть", encoding="utf-8")
    report = crawler.crawl(conn)
    assert report.added == 1


def test_crawl_removes_missing_files(conn, collection: Path):
    (collection / "d3.txt").unlink()
    report = crawler.crawl(conn)
    assert report.removed == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"] == 2
