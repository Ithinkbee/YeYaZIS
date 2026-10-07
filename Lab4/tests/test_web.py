"""Веб-интерфейс: страницы, перевод, вкладки результата, сохранение, словарь, тир."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from dragoman.web.app import app

    with TestClient(app) as test_client:
        yield test_client


def uid_of(response) -> str:
    return re.search(r"/t/([0-9a-f]+)", str(response.url)).group(1)


@pytest.fixture(scope="module")
def compiler(client):
    return uid_of(client.get("/doc/cs-compiler"))


@pytest.mark.parametrize("url", ["/", "/collection", "/dictionary", "/dictionary?q=network&pos=NOUN",
                                 "/dictionary/replenish", "/evaluation", "/help", "/shooter", "/favicon.ico"])
def test_pages(client, url):
    assert client.get(url).status_code == 200


def test_translate_form(client):
    response = client.post("/translate", data={"text": "The compiler translates the source code.", "title": "Test",
                                               "domain": "cs", "mode": "transfer"})
    assert response.status_code == 200 and "/t/" in str(response.url)
    html = response.text
    assert "Der Compiler übersetzt den Quellcode." in html
    assert "1. Частотный список слов" in html and "2. Дерево разбора" in html


def test_translate_uploaded_file(client):
    files = {"upload": ("paper.txt", "Neural networks learn patterns.".encode("utf-8"), "text/plain")}
    response = client.post("/translate", data={"domain": "auto", "mode": "transfer"}, files=files)
    assert response.status_code == 200 and "Neuronale Netze lernen Muster." in response.text


@pytest.mark.parametrize("text, message", [("", "введите английский текст"), ("Привет, мир", "нет латинских букв")])
def test_translate_rejects_bad_input(client, text, message):
    response = client.post("/translate", data={"text": text, "domain": "auto", "mode": "transfer"})
    assert response.status_code == 400 and message in response.text


def test_result_tabs(client, compiler):
    words = client.get(f"/t/{compiler}?tab=words").text
    assert "der Compiler" in words and "NN" in words and "существительное" in words
    tree = client.get(f"/t/{compiler}?tab=tree&s=1").text
    assert "<svg" in tree and "nsubj" in tree
    assert client.get(f"/t/{compiler}?tab=compare").status_code == 200
    assert client.get(f"/t/{compiler}?tab=unknown").status_code == 200
    fragment = client.get(f"/t/{compiler}/tree?s=2")
    assert fragment.status_code == 200 and "<svg" in fragment.text


def test_word_list_sorting(client, compiler):
    for sort in ("freq", "alpha", "pos"):
        assert client.get(f"/t/{compiler}?tab=words&sort={sort}").status_code == 200


def test_statistics_are_shown(client, compiler):
    from dragoman.web.app import state

    stats = state.translations[compiler].stats
    html = client.get(f"/t/{compiler}").text
    for label, value in [("Слов во входном тексте", stats["words"]), ("Переведено слов", stats["translated"]),
                         ("Без перевода", stats["unknown"])]:
        shown = re.search(re.escape(label) + r'</h3><span class="big[^"]*">([^<]+)</span>', html)
        assert shown and re.sub(r"\D", "", shown.group(1)) == str(value), label


def test_export_txt(client, compiler):
    response = client.get(f"/export/{compiler}.txt")
    assert response.status_code == 200 and response.content[:2] == b"\xff\xfe"
    assert "attachment" in response.headers["content-disposition"]
    text = response.content.decode("utf-16")
    assert "ЧАСТОТНЫЙ СПИСОК" in text and "ПЕРЕВОД (DE)" in text
    utf8 = client.get(f"/export/{compiler}.txt?enc=utf-8&parts=words")
    assert utf8.content[:3] == b"\xef\xbb\xbf" and "ПЕРЕВОД (DE)" not in utf8.content.decode("utf-8-sig")


def test_print_view(client, compiler):
    html = client.get(f"/print/{compiler}").text
    assert "window.print()" in html and "der Compiler" in html


def test_direct_mode(client):
    response = client.get("/doc/cs-os?mode=direct")
    assert response.status_code == 200 and "пословн" in response.text.lower()


def test_unknown_pages(client):
    assert client.get("/t/ffffffffff").status_code == 404
    assert client.get("/doc/nothing").status_code == 404
    assert client.get("/export/ffffffffff.txt").status_code == 404
    assert client.get("/report/../run.py").status_code == 404


def test_dictionary_add_edit_delete(client, lexicon):
    response = client.post("/dictionary/add", data={"en": "spiderweb", "pos": "NOUN", "de": "Spinnennetz",
                                                    "gender": "n", "plural": "Spinnennetze", "domain": "gen"})
    assert response.status_code == 200 and "Spinnennetz" in response.text
    entry = lexicon.best("spiderweb", "NOUN")
    assert entry is not None and entry.source == "user"
    client.post(f"/dictionary/{entry.id}/edit", data={"en": "spiderweb", "pos": "NOUN", "de": "Spinnwebe",
                                                      "gender": "f", "plural": "Spinnweben", "domain": "gen"})
    assert lexicon.best("spiderweb", "NOUN").de == "Spinnwebe"
    # перевод сразу пользуется новой записью
    page = client.post("/translate", data={"text": "The spiderweb is large.", "domain": "cs", "mode": "transfer"})
    assert "Die Spinnwebe ist groß." in page.text
    client.post(f"/dictionary/{entry.id}/delete", data={"q": "spiderweb"})
    assert lexicon.best("spiderweb", "NOUN") is None


def test_dictionary_replenishment(client, lexicon):
    client.post("/translate", data={"text": "The virtualization of the quuxtron is modular.", "domain": "cs",
                                    "mode": "transfer"})
    page = client.get("/dictionary/replenish").text
    assert "quuxtron" in page
    client.post("/dictionary/auto", data={"threshold": "0.85"})
    assert lexicon.best("quuxtron", "NOUN") is None                 # догадки нет — слово остаётся в журнале
    client.post("/dictionary/forget", data={"en": "quuxtron", "pos": "NOUN"})
    assert "quuxtron" not in {row["en"] for row in lexicon.unknown()}


def test_replenish_hides_words_already_in_dictionary(client, lexicon):
    lexicon.log_unknown([("network", "NOUN", "The network learns."), ("zorblax", "NOUN", "The zorblax runs.")])
    page = client.get("/dictionary/replenish").text
    assert "zorblax" in page and ">network<" not in page
    lexicon.forget_unknown("network")
    lexicon.forget_unknown("zorblax")


def test_dictionary_export_import(client):
    exported = client.get("/dictionary/export.tsv")
    assert exported.status_code == 200 and exported.text.startswith("# en\tpos\tde")
    upload = {"upload": ("extra.tsv", "glorptron\tNOUN\tGlorptron\tm\tGlorptrons\t\tcs\n".encode("utf-8"),
                         "text/tab-separated-values")}
    response = client.post("/dictionary/import", files=upload)
    assert response.status_code == 200 and "1" in response.text


def test_shooter_plan_api(client, compiler):
    data = client.get("/api/shooter/plan?doc=lit-hamlet&waves=5").json()
    assert len(data["plan"]["waves"]) == 5 and data["translation"] and data["document"]
    sizes = [w["size"] for w in data["plan"]["waves"]]
    assert sizes == sorted(sizes)
    by_uid = client.get(f"/api/shooter/plan?uid={compiler}&waves=3").json()
    assert by_uid["uid"] == compiler and len(by_uid["plan"]["waves"]) == 3
    assert client.get("/api/shooter/plan").status_code == 400
    assert client.get("/api/shooter/plan?uid=ffffffffff").status_code == 404


def test_shooter_page_offers_texts(client, compiler):
    html = client.get(f"/shooter?uid={compiler}").text
    assert "shooter_rules.js" in html and "shooter.js" in html
    assert "lit-hamlet" in html
