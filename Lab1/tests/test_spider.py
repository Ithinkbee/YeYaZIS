"""Тесты пасьянса «Паук».

Правила пасьянса написаны на JavaScript и проверяются отдельным набором
(`tests/spider_rules.test.js`), который здесь запускается через node. Если
node в системе нет, эта проверка пропускается: разработка ИПС от него не
зависит, а терять из-за его отсутствия весь прогон тестов незачем.

Со стороны Python проверяется то, за что отвечает Python: страница отдаётся,
сценарий подключён, вкладка есть в меню и вся затея исчезает при выключенном
компаньоне.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from arachne.web.app import app  # noqa: E402


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as instance:
        yield instance


# --- страница ----------------------------------------------------------------


def test_page_opens(client):
    response = client.get("/spider")
    assert response.status_code == 200
    assert "Пасьянс" in response.text


def test_page_has_the_board_and_controls(client):
    text = client.get("/spider").text
    for element in (
        'id="spider-board"',
        'id="spider-suits"',
        'id="spider-deal"',
        'id="spider-undo"',
        'id="spider-new"',
        'id="spider-again"',
        'id="spider-stock"',
        'id="spider-collected"',
        'id="spider-moves"',
    ):
        assert element in text, element


def test_page_loads_the_script(client):
    assert "/static/spider.js" in client.get("/spider").text


def test_script_is_served(client):
    response = client.get("/static/spider.js")
    assert response.status_code == 200
    assert "SpiderRules" in response.text


def test_styles_cover_the_cards(client):
    css = client.get("/static/style.css").text
    for rule in (".spider-board", ".spider-pile", ".spider-card", ".spider-card.is-down"):
        assert rule in css, rule


# --- изоляция оформления ------------------------------------------------------


STYLE_PATH = ROOT / "arachne" / "web" / "static" / "style.css"
SPIDER_MARK = "--- Пасьянс"


def _split_stylesheet() -> tuple[str, str]:
    """Делит таблицу стилей на общую часть и часть пасьянса."""
    css = STYLE_PATH.read_text(encoding="utf-8")
    border = css.index(SPIDER_MARK)
    return css[:border], css[border:]


def _class_names(css: str) -> set[str]:
    import re

    return set(re.findall(r"\.([a-z][\w-]*)", css))


def test_solitaire_styles_do_not_touch_the_rest_of_the_interface():
    """Пасьянс не имеет права переопределять чужие классы.

    Проверка появилась не от хорошей жизни: карта сначала называлась просто
    `.card`, а этим же классом в «Арахне» размечены панели на всех страницах.
    Правило `position: absolute` разъехалось по всему интерфейсу, и вёрстка
    сложилась. Теперь все классы пасьянса носят собственный префикс.
    """
    common, spider = _split_stylesheet()
    clash = _class_names(spider) & _class_names(common)
    assert not clash, "пасьянс переопределяет чужие классы: " + ", ".join(sorted(clash))


def test_solitaire_classes_are_prefixed():
    """Каждый класс пасьянса — либо spider-*, либо модификатор is-*."""
    _, spider = _split_stylesheet()
    stray = {
        name for name in _class_names(spider)
        if not name.startswith("spider-") and not name.startswith("is-")
    }
    assert not stray, "классы без префикса: " + ", ".join(sorted(stray))


def test_modifiers_are_never_used_alone():
    """Модификатор is-* обязан стоять в паре со своим классом.

    Одиночный `.is-empty` снова зацепил бы чужую разметку — ради этого
    префиксы и вводились.
    """
    import re

    _, spider = _split_stylesheet()
    for modifier in ("is-down", "is-red", "is-picked", "is-empty", "is-good", "is-warn"):
        alone = re.findall(r"(?<![\w.-])\." + modifier + r"\b", spider)
        assert not alone, f".{modifier} использован отдельным селектором"


def test_card_class_still_belongs_to_panels(client):
    """`.card` должен остаться обычной панелью, а не игральной картой."""
    css = client.get("/static/style.css").text
    import re

    rule = re.search(r"(?<![\w-])\.card\s*\{([^}]*)\}", css)
    assert rule, "правило .card исчезло"
    body = rule.group(1)
    assert "position: absolute" not in body
    assert "background" in body and "border-radius" in body


def test_tab_is_in_the_menu(client):
    assert 'href="/spider"' in client.get("/").text


def test_all_three_difficulties_are_offered(client):
    text = client.get("/spider").text
    for value in ('value="1"', 'value="2"', 'value="4"'):
        assert value in text, value


def test_rules_are_explained_on_the_page(client):
    """Пасьянс должен объясняться сам: отдельной справки у него нет."""
    text = client.get("/spider").text
    assert "Правила" in text
    assert "одной масти" in text
    assert "пустых столбцов" in text


def test_page_promises_nothing(client):
    """Пасьянс ничего не начисляет — это сказано на самой странице."""
    text = client.get("/spider").text
    assert "ни на что в системе не влияет" in text


# --- выключенный компаньон ----------------------------------------------------


PROBE = r"""
import os, sys
sys.path.insert(0, r"{root}")
os.environ["ARACHNE_COMPANION"] = "0"
from fastapi.testclient import TestClient
from arachne.web.app import app

with TestClient(app) as client:
    page = client.get("/spider", follow_redirects=False)
    menu = client.get("/").text
    print(page.status_code, "/spider" in menu, sep="|")
""".format(root=str(ROOT))


def test_hidden_without_the_companion():
    """При ARACHNE_COMPANION=0 пасьянса нет ни в меню, ни по адресу.

    Флаг читается при импорте конфигурации, поэтому приложение поднимается в
    отдельном процессе: подмена уже загруженного config проверяла бы не то,
    что видит пользователь.
    """
    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT), timeout=180,
    )
    assert result.returncode == 0, result.stderr
    status, in_menu = result.stdout.strip().splitlines()[-1].split("|")
    assert status == "303", "страница должна уводить на главную"
    assert in_menu == "False", "вкладки не должно быть в меню"


# --- правила (JavaScript) ------------------------------------------------------


@pytest.mark.skipif(shutil.which("node") is None, reason="node не установлен")
def test_javascript_rules():
    """Прогоняет tests/spider_rules.test.js: раздача, ходы, целостность колоды."""
    result = subprocess.run(
        ["node", str(ROOT / "tests" / "spider_rules.test.js")],
        capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT), timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ошибок: 0" in result.stdout
