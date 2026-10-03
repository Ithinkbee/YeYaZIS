"""Реферат вручную, сапёр и бой с Пафнутием.

Правила сапёра и боя написаны на JavaScript и проверяются отдельными
наборами (`tests/sweeper_rules.test.js`, `tests/battle_rules.test.js`),
которые здесь запускаются через node. Если node в системе нет, эти проверки
пропускаются: реферирование от него не зависит.

Со стороны Python проверяется то, за что отвечает Python: поля букв из
ключевых слов рефератов, отрывки и сравнение реферата человека с рефератом
системы, страницы и API.
"""

from __future__ import annotations

import random
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from izbornik import config, practice, wordgrid
from izbornik.evaluation import Rouge

from .conftest import ROOT


@pytest.fixture(scope="module")
def client():
    from izbornik.web.app import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def bank(collection):
    return wordgrid.WordBank(collection)


def source(collection, doc_id: str) -> practice.Source:
    entry = collection.get(doc_id)
    return practice.Source("doc", entry.id, entry.title, entry.language, entry.domain, collection.text(doc_id))


# --- поле букв --------------------------------------------------------------------------

def test_grid_letters_keep_one_letter_per_cell():
    assert wordgrid.grid_letters("Räuber") == "RÄUBER"
    assert wordgrid.grid_letters("Straße") == "STRAẞE"          # не «STRASSE»: одна буква — одна клетка


@pytest.mark.parametrize("word, language, ok", [
    ("онтология", "ru", True),
    ("БЗ", "ru", False),                     # аббревиатура и слишком короткое
    ("СУБД", "ru", False),                   # аббревиатура
    ("Га-Ноцри", "ru", False),               # дефис
    ("структуризация", "ru", False),         # 14 букв — длиннее поля
    ("Räuberbande", "de", True),
    ("URIs", "de", False),
    ("IT-Sicherheit", "de", False),
    ("Netz", "de", True),
    ("сеть", "de", False),                   # чужой алфавит
])
def test_eligible_words(word, language, ok):
    assert wordgrid.eligible(word, language, 13) is ok


def test_bank_words_are_summary_keywords(bank, collection):
    words = bank.words("ru-lit-onegin")
    keywords = collection.summarize("ru-lit-onegin").summary.keywords.texts()
    assert len(words) >= config.BATTLE_WORDS[0]
    assert all(w.text in keywords for w in words)
    assert words[0].text == "Онегин" and words[0].rank == 1


@pytest.mark.parametrize("language", ["ru", "de"])
def test_grid_hides_each_word_exactly_once(bank, language):
    alphabet = set(wordgrid.grid_letters(wordgrid.ALPHABETS[language]))
    for seed in range(12):
        grid = bank.grid(language, random.Random(seed))
        assert (grid.rows, grid.cols) == (config.BATTLE_GRID_ROWS, config.BATTLE_GRID_COLS)
        assert config.BATTLE_WORDS[0] <= len(grid.words) <= config.BATTLE_WORDS[1]
        assert all(ch in alphabet for row in grid.letters for ch in row)
        cells = [cell for word in grid.words for cell in word.cells]
        assert len(cells) == len(set(cells)), "слова не пересекаются"
        for word in grid.words:
            assert "".join(grid.letters[r][c] for r, c in word.cells) == word.letters
            assert grid.occurrences(word.letters) == 1
            assert all(0 <= r < grid.rows and 0 <= c < grid.cols for r, c in word.cells)
        assert not any(a.letters in b.letters for a in grid.words for b in grid.words if a is not b)


def test_grid_skips_documents_already_played(bank, collection):
    played = [e.id for e in collection.by_language("ru")][:4]
    grids = {bank.grid("ru", random.Random(seed), exclude=played).doc_id for seed in range(8)}
    assert grids.isdisjoint(played)


def test_fill_retries_until_words_are_unique():
    words = [wordgrid.BankWord("кот", "КОТ", 1), wordgrid.BankWord("лес", "ЛЕС", 2)]
    # заполнение только из К, О, Т: второй «КОТ» среди них складывается в трёх полях из четырёх
    frequencies = {"К": 1.0, "О": 1.0, "Т": 1.0}
    grid = wordgrid.make_grid(words, "ru", frequencies, random.Random(1), rows=5, cols=6)
    assert grid.occurrences("КОТ") == 1 and grid.occurrences("ЛЕС") == 1


def test_words_that_do_not_fit_are_refused():
    too_long = [wordgrid.BankWord("абвгдежзик", "АБВГДЕЖЗИК", 1)]
    with pytest.raises(ValueError):
        wordgrid.make_grid(too_long, "ru", {"А": 1.0}, random.Random(0), rows=4, cols=5)


# --- отрывки ---------------------------------------------------------------------------------

def test_excerpt_windows_fit_limits(collection):
    for entry in collection:
        item = practice.random_excerpt([source(collection, entry.id)], random.Random(4))
        assert item is not None, entry.id
        assert config.PRACTICE_MIN_CHARS <= item.chars <= config.PRACTICE_MAX_CHARS
        assert item.sentences >= config.PRACTICE_MIN_SENTENCES


def test_excerpt_stays_within_one_section(collection):
    """Нумерованный заголовок статьи с точкой («2.1. ENUM hardcoding.») — граница отрывка."""
    doc = source(collection, "ru-cs-antipatterns")
    from izbornik.text import segment

    layout = segment.parse(doc.text, "ru")
    for first, last in practice.windows(layout):
        assert not any(practice.is_boundary(p) for p in layout.paragraphs[first:last + 1])


def test_excerpt_key_roundtrip(collection):
    item = practice.random_excerpt([source(collection, "ru-lit-master")], random.Random(2))
    kind, doc_id, first, last = practice.parse_key(item.key)
    again = practice.excerpt(source(collection, doc_id), first, last)
    assert kind == "doc" and again.text == item.text
    assert practice.parse_key("mine:0123abcd:3-5") == ("mine", "0123abcd", 3, 5)
    assert practice.parse_key("../etc:1-2") is None


# --- сравнение с системой ---------------------------------------------------------------

@pytest.fixture(scope="module")
def excerpt(collection):
    return practice.excerpt(source(collection, "ru-lit-master"), 4, 5)


def test_system_summary_of_excerpt(collection, excerpt):
    result, ms = practice.summarize_excerpt(collection, excerpt)
    assert len(result.summary.sentences) == practice.system_size(len(result.document.layout.sentences))
    assert 2 <= len(result.summary.sentences) <= 4 and ms >= 0


def test_good_summary_gets_high_mark(collection, excerpt):
    text = ("В ершалаимских главах прокуратор Понтий Пилат допрашивает бродячего философа Иешуа Га-Ноцри, но не "
            "может спасти его от казни и приказывает убить предателя Иуду. В финале Левий Матвей просит Воланда "
            "наградить Мастера и Маргариту покоем, и они покидают Москву вместе со свитой.")
    result = practice.compare(collection, excerpt, text, 120)
    assert result.verdict.stars >= 4
    assert result.coverage >= 0.8
    assert any(c.text == "Га-Ноцри" for c in result.concepts), "составное имя показано как в тексте"
    assert any(concept for _, concept in result.segments)
    assert result.style == "own"


def test_copy_of_system_summary_is_an_extract(collection, excerpt):
    system, _ = practice.summarize_excerpt(collection, excerpt)
    result = practice.compare(collection, excerpt, system.summary.text)
    assert result.style == "extract" and result.rouge1.r == pytest.approx(1.0)


def test_whole_excerpt_is_not_a_summary(collection, excerpt):
    result = practice.compare(collection, excerpt, excerpt.text)
    assert result.verdict.stars <= 2
    assert result.verdict.occasion == "manual_long"
    assert any("пересказ" in note for note in result.verdict.notes)


def test_unrelated_text_gets_one_star(collection, excerpt):
    result = practice.compare(collection, excerpt, "Нейронные сети используются для классификации изображений.")
    assert result.verdict.stars == 1 and result.coverage == 0


def test_other_language_is_not_rated(collection, excerpt):
    result = practice.compare(collection, excerpt, "Pilatus verurteilt Jeschua, obwohl er ihn retten möchte.")
    assert result.verdict.stars == 0 and result.verdict.occasion == "manual_language"


def test_marks_are_lenient():
    """Короткий, но точный реферат не получает меньше трёх звёзд."""
    assert practice.stars(practice.score(0.5, Rouge(p=0.56, r=0.1, f=0.18))) >= 3
    assert practice.stars(practice.score(0.0, Rouge(p=0.0, r=0.0, f=0.0))) == 1
    assert practice.stars(practice.score(1.0, Rouge(p=0.6, r=0.45, f=0.5))) == 5


# --- страницы ----------------------------------------------------------------------------

@pytest.mark.parametrize("url", ["/manual", "/manual?source=lang:de", "/manual?source=any",
                                 "/manual?source=ru-cs-ostis", "/sweeper", "/battle"])
def test_game_pages(client, url):
    assert client.get(url).status_code == 200


def test_navigation_has_new_pages(client):
    html = client.get("/").text
    assert 'href="/manual"' in html and 'href="/sweeper"' in html and 'href="/battle"' in html
    assert "Бой с Пафнутием" in html and "Пафнутийем" not in html


def test_manual_page_shows_excerpt_and_form(client):
    html = client.get("/manual?key=ru-lit-master:4-5").text
    assert "прокуратор" in html and 'name="key" value="ru-lit-master:4-5"' in html
    assert "Сравнить с системой" in html


def test_manual_check(client):
    response = client.post("/manual", data={
        "key": "ru-lit-master:4-5", "seconds": "95.5",
        "text": "Пилат не спасает Иешуа от казни. Мастер и Маргарита получают покой и покидают Москву.",
    })
    html = response.text
    assert response.status_code == 200
    assert "Реферат системы" in html and "Ключевые понятия" in html
    assert "1 мин 36 с" in html
    assert 'class="s picked"' in html
    assert 'data-speaks="1"' in html              # Пафнутий оглашает вердикт сам


def test_manual_rejects_empty_text_and_bad_key(client):
    assert "хотя бы одно предложение" in client.post("/manual", data={"key": "ru-lit-master:4-5", "text": " "}).text
    assert client.get("/manual?key=ru-lit-master:0-0").status_code == 404      # заголовок раздела
    assert client.get("/manual?key=no-such:1-2").status_code == 404
    assert client.get("/manual?key=garbage").status_code == 404


def test_manual_uses_own_documents(client, collection):
    text = collection.text("de-lit-westen")
    response = client.post("/text", data={"text": text, "title": "Мой текст", "language": "auto", "n": "5"},
                           follow_redirects=False)
    uid = response.headers["location"].split("/")[2].split("?")[0]
    html = client.get(f"/manual?source=mine:{uid}").text
    assert "Мой текст" in html and f"mine:{uid}:" in html


def test_battle_grid_api(client):
    data = client.get("/api/battle/grid?language=de").json()
    assert data["language"] == "de" and data["link"].startswith("/doc/de-")
    assert len(data["letters"]) == data["rows"] and all(len(row) == data["cols"] for row in data["letters"])
    for word in data["words"]:
        dr, dc = (0, 1) if word["dir"] == "right" else (1, 0)
        spelled = "".join(data["letters"][word["row"] + dr * i][word["col"] + dc * i]
                          for i in range(len(word["letters"])))
        assert spelled == word["letters"]
    assert client.get("/api/battle/grid?language=fr").status_code == 400


def test_game_scripts_and_lines(client):
    html = client.get("/battle").text
    assert "/static/battle.js?v=" in html and '"battle_start"' in html and 'id="spider-glyph"' in html
    assert "/static/sweeper.js?v=" in client.get("/sweeper").text
    assert "BattleRules" in client.get("/static/battle.js").text


# --- правила игр (JavaScript) ----------------------------------------------------------

@pytest.mark.skipif(shutil.which("node") is None, reason="node не установлен")
@pytest.mark.parametrize("script", ["sweeper_rules.test.js", "battle_rules.test.js"])
def test_javascript_rules(script):
    result = subprocess.run(["node", str(ROOT / "tests" / script)], capture_output=True, text=True,
                            encoding="utf-8", cwd=str(ROOT), timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
