"""Проверка веб-интерфейса.

Проверяется не вёрстка, а то, что каждая страница вообще собирается и
содержит осмысленные данные. Шаблон, обращающийся к несуществующему полю,
или изменившаяся подпись метода фреймворка обнаруживаются именно здесь: без
этих проверок ошибка видна лишь при ручном открытии страницы в браузере.
"""

from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tolmach.web.app import app  # noqa: E402

PAGES = ["/", "/compare", "/profiles", "/check", "/help", "/print"]


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as instance:
        yield instance


@pytest.mark.parametrize("path", PAGES)
def test_page_renders(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert len(response.text) > 1000


@pytest.mark.parametrize("path", PAGES)
def test_page_is_in_russian_and_utf8(client, path):
    """Кириллица должна доходить до браузера неискажённой."""
    response = client.get(path)
    assert "charset=utf-8" in response.headers["content-type"]
    assert "русский" in response.text or "Русский" in response.text


def test_index_lists_the_collection(client):
    text = client.get("/").text
    assert "ru-01-zodchestvo.html" in text
    assert "de-01-holzbau.html" in text
    # имя документа — активная ссылка на исходный файл
    assert 'href="/raw/ru-01-zodchestvo.html"' in text


def test_document_page_shows_every_method(client):
    text = client.get("/document/ru-04-pchely.html").text
    assert "Метод N-грамм" in text
    assert "Алфавитный метод" in text
    assert "Нейросетевой метод" in text
    assert "русский" in text


def test_missing_document_returns_404(client):
    response = client.get("/document/no-such-file.html")
    assert response.status_code == 404


def test_raw_serves_the_original_file(client):
    response = client.get("/raw/de-02-kaffee.html")
    assert response.status_code == 200
    assert "Kaffee" in response.text
    # отдаётся именно исходная разметка, а не извлечённый текст
    assert "<style>" in response.text


def test_raw_rejects_path_traversal(client):
    """Имя файла не должно позволять выйти из каталога коллекции."""
    for name in ("../labels.csv", "..%2Flabels.csv", "....//labels.csv"):
        response = client.get(f"/raw/{name}")
        assert response.status_code in (400, 404), name
        assert "language" not in response.text


def test_check_recognises_russian(client):
    response = client.post("/check", data={"text": "Совершенно определённо русское предложение."})
    assert response.status_code == 200
    assert "tag-ru" in response.text


def test_check_recognises_german(client):
    response = client.post(
        "/check", data={"text": "Dieser Satz wurde eindeutig auf Deutsch geschrieben."}
    )
    assert response.status_code == 200
    assert "tag-de" in response.text


def test_check_strips_markup_from_pasted_html(client):
    response = client.post(
        "/check",
        data={"text": "<html><style>body{font-family:Georgia}</style>"
                      "<p>Ein deutscher Satz mit mehreren Wörtern darin.</p></html>"},
    )
    assert response.status_code == 200
    assert "tag-de" in response.text


def test_check_with_empty_text_reports_it(client):
    response = client.post("/check", data={"text": "   "})
    assert response.status_code == 200
    assert "не задан" in response.text


def test_check_accepts_an_uploaded_file(client):
    path = Path(__file__).resolve().parent.parent / "data" / "collection" / "de-07-brot.html"
    with path.open("rb") as handle:
        response = client.post(
            "/check",
            data={"text": ""},
            files={"upload": ("de-07-brot.html", handle, "text/html")},
        )
    assert response.status_code == 200
    assert "tag-de" in response.text


def test_export_csv_is_a_table(client):
    response = client.get("/export/csv")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0][0] == "file"


def test_export_json_is_valid(client):
    payload = json.loads(client.get("/export/json").text)
    assert payload["variant"] == 4
    assert payload["documents"]


def test_export_txt_is_a_protocol(client):
    text = client.get("/export/txt").text
    assert "ТОЧНОСТЬ И БЫСТРОДЕЙСТВИЕ" in text


def test_unknown_export_format_is_rejected(client):
    assert client.get("/export/pdf").status_code == 400


def test_run_and_train_redirect(client):
    assert client.post("/run", follow_redirects=False).status_code == 303
    assert client.post("/train", follow_redirects=False).status_code == 303


def test_compare_shows_all_experiments(client):
    text = client.get("/compare").text
    assert "Точность и быстродействие" in text
    assert "Зависимость точности от длины входа" in text
    assert "смешанном тексте" in text
    assert "Матрицы ошибок" in text


def test_profiles_show_language_images(client):
    text = client.get("/profiles").text
    assert "Поисковые образы языков" in text
    assert "Алфавитный метод" in text


def test_help_covers_the_basics(client):
    text = client.get("/help").text
    for heading in ("С чего начать", "Как это работает", "Три метода",
                    "Сохранение и печать", "Если что-то пошло не так"):
        assert heading in text


def test_print_page_has_print_rules(client):
    text = client.get("/print").text
    assert "Протокол распознавания" in text
    assert "no-print" in text


def test_static_stylesheet_is_served(client):
    response = client.get("/static/style.css")
    assert response.status_code == 200
    assert "@media print" in response.text


# --- Пафнутий: паук, шахматы и викторина -------------------------------------


@pytest.mark.parametrize("path", PAGES)
def test_spider_sits_on_every_page(client, path):
    """Пафнутий присутствует всюду, кроме версии для печати."""
    text = client.get(path).text
    if path == "/print":
        assert "companion-spider" not in text
    else:
        assert "companion-spider" in text
        assert "Пафнутий" in text


def test_chess_page_renders(client):
    text = client.get("/chess").text
    assert "Партия с Пафнутием" in text
    assert 'id="board"' in text
    assert "/static/chess.js" in text


def test_spider_name_is_declined_correctly(client):
    """«Пафнутийем» — след склейки имени с окончанием в шаблоне."""
    for path in ("/chess", "/"):
        assert "Пафнутийем" not in client.get(path).text


def test_check_form_is_guarded_by_a_puzzle(client):
    text = client.get("/check").text
    assert 'id="gate"' in text
    assert 'id="gate-board"' in text
    assert "мат" in text.lower()


def test_puzzle_endpoint_hides_the_solution(client):
    """Решение не должно уходить в браузер — иначе задача бессмысленна."""
    payload = client.get("/api/chess/puzzle?index=0").json()
    assert payload["fen"] and payload["task"]
    assert "key" not in payload and "solution" not in payload
    assert payload["legal"]


def test_puzzle_endpoint_accepts_the_solution(client):
    from tolmach.chess import puzzles

    puzzle = puzzles.PUZZLES[0]
    result = client.post(
        "/api/chess/puzzle",
        json={"index": 0, "frm": puzzle.key_from, "to": puzzle.key_to},
    ).json()
    assert result["solved"] is True


def test_puzzle_endpoint_rejects_a_wrong_move(client):
    result = client.post(
        "/api/chess/puzzle", json={"index": 0, "frm": "e5", "to": "e8", "attempts": 3}
    ).json()
    assert result["solved"] is False
    assert result["hint"]


def test_quiz_word_hides_the_language(client):
    payload = client.get("/api/quiz/word").json()
    assert payload["word"] and len(payload["options"]) == 2
    assert "language" not in payload


def test_quiz_answer_reports_the_truth_and_the_system(client):
    word = client.get("/api/quiz/word").json()["word"]
    verdict = client.post("/api/quiz/answer", json={"word": word, "answer": "ru"}).json()
    assert verdict["known"] is True
    assert verdict["language"] in ("ru", "de")
    assert verdict["original"]
    assert set(verdict["opinions"]) == set(METHOD_CODES := {"ngram", "alphabet", "neural"})
    assert verdict["correct"] == (verdict["language"] == "ru")


def test_quiz_answer_for_unknown_word(client):
    verdict = client.post(
        "/api/quiz/answer", json={"word": "qqqzzz", "answer": "ru"}
    ).json()
    assert verdict["known"] is False


def test_chess_move_is_played(client):
    from tolmach.chess import START_FEN

    result = client.post(
        "/api/chess/move",
        json={"fen": START_FEN, "frm": "e2", "to": "e4", "quiz_passed": None},
    ).json()
    assert result["ok"] and result["reply"]


def test_chess_capture_asks_for_the_quiz(client):
    result = client.post(
        "/api/chess/move",
        json={
            "fen": "rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 2",
            "frm": "e4", "to": "d5", "quiz_passed": None,
        },
    ).json()
    assert result["kind"] == "quiz"


def test_chess_rejects_a_malformed_square(client):
    response = client.post(
        "/api/chess/move",
        json={"fen": "8/8/8/8/8/8/8/K6k w - - 0 1", "frm": "zz", "to": "a2"},
    )
    assert response.status_code in (400, 422)


def test_chess_rejects_a_malformed_fen(client):
    response = client.post(
        "/api/chess/move", json={"fen": "не фен вовсе", "frm": "e2", "to": "e4"}
    )
    assert response.status_code in (400, 422)


def test_help_mentions_the_companion(client):
    text = client.get("/help").text
    assert "Пафнутий" in text
