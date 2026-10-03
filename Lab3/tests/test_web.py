"""Веб-интерфейс без OSTIS (IZBORNIK_OSTIS=off задан в conftest.py)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from izbornik.web.app import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize("url", ["/", "/text", "/evaluation", "/ostis", "/help", "/kb/concepts.scs"])
def test_pages(client, url):
    assert client.get(url).status_code == 200


def test_summary_page_has_both_sections_and_active_source_link(client):
    html = client.get("/doc/ru-cs-ostis").text
    assert "1. Классический реферат" in html and "2. Реферат в виде списка ключевых слов" in html
    assert 'href="/doc/ru-cs-ostis/source' in html
    assert "cyberleninka.ru/article" in html
    assert "Локальный расчёт" in html


def test_ostis_engine_falls_back_when_off(client):
    html = client.get("/doc/de-cs-nn?engine=ostis").text
    assert "OSTIS недоступна" in html


def test_source_page_marks_summary_sentences(client):
    html = client.get("/doc/de-lit-effi/source?n=7").text
    assert html.count('class="pick-no"') == 7


def test_raw_text(client):
    response = client.get("/raw/ru-lit-woe")
    assert response.status_code == 200 and "Чацкий" in response.text


@pytest.mark.parametrize("fmt", ["txt", "html", "docx", "json", "scs"])
def test_export(client, fmt):
    response = client.get(f"/export/doc/de-lit-verwandlung.{fmt}?n=5")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert len(response.content) > 1000


def test_print_view(client):
    html = client.get("/print/doc/ru-cs-vision?n=5").text
    assert "window.print()" in html and html.count("<li>") >= 5


def test_unknown_document_is_404(client):
    assert client.get("/doc/no-such").status_code == 404
    assert client.get("/export/doc/no-such.txt").status_code == 404
    assert client.get("/export/doc/ru-cs-ostis.exe").status_code == 404
    assert client.get("/report/../run.py").status_code == 404


def test_own_text_and_file(client, collection):
    text = collection.text("de-cs-os")
    response = client.post("/text", data={"text": text, "title": "Test", "language": "auto", "n": "6"},
                           follow_redirects=False)
    assert response.status_code == 303
    page = client.get(response.headers["location"])
    assert page.status_code == 200 and "немецкий" in page.text
    upload = client.post("/text", files={"upload": ("doc.txt", collection.text("ru-lit-souls").encode("utf-8"),
                                                    "text/plain")}, data={"n": "5"})
    assert upload.status_code == 200 and "Чичиков" in upload.text


def test_too_short_text_rejected(client):
    response = client.post("/text", data={"text": "Коротко.", "n": "10"})
    assert "слишком короткий" in response.text


def test_sentence_count_is_limited(client):
    html = client.get("/doc/ru-cs-crypto?n=500").text
    assert html.count("предложение № ") == 50
