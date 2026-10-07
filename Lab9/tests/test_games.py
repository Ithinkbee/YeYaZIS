"""Прогулка с Пафнутием, его модель и правила голосового вывода.

Правила прогулки, геометрия модели паука и деление ответа на части написаны
на JavaScript и проверяются отдельными наборами
(`tests/walk_rules.test.js`, `tests/pafnuty_model.test.js`,
`tests/voice_rules.test.js`), которые здесь запускаются через node. Если
node в системе нет, эти проверки пропускаются: распознавание от него не
зависит.

Со стороны Python проверяется то, за что отвечает Python: страница игры и
реплики паука — у каждого события игры есть реплика.
"""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from sluhach import config, pafnuty

from .conftest import ROOT

STATIC = ROOT / "sluhach" / "web" / "static"


@pytest.fixture(scope="module")
def client():
    from sluhach.web.app import app

    with TestClient(app) as test_client:
        yield test_client


# --- реплики -------------------------------------------------------------------------

def test_every_game_event_has_a_line():
    """Поводы, по которым игра просит реплику, есть в наборе реплик — паук не молчит невпопад."""
    script = (STATIC / "walk.js").read_text(encoding="utf-8")
    asked = set(re.findall(r"say\('(walk_\w+)'", script))
    assert "walk_finish_" in asked and "say('walk_finish_' + earned" in script
    asked.discard("walk_finish_")                                        # повод собирается из числа звёзд
    asked |= {f"walk_finish_{stars}" for stars in (1, 2, 3)}
    lines = pafnuty.client_lines("walk")
    assert asked and asked <= set(lines), asked - set(lines)
    assert set(lines) <= asked, set(lines) - asked                       # и нет реплик, которые никто не произносит


def test_selftest_lines_are_the_ones_the_page_asks_for():
    script = (STATIC / "selftest.js").read_text(encoding="utf-8")
    asked = set(re.findall(r"'(selftest_\w+)'", script))
    assert asked == set(pafnuty.client_lines("selftest")) and len(asked) == 4


def test_lines_for_every_page():
    for page in ("console", "operations", "evaluation", "walk", "help", "idle"):
        assert len(pafnuty.LINES[page]) >= 2
    assert all(text.strip() and len(text) <= 70 for variants in pafnuty.LINES.values() for text in variants)


def test_line_avoids_recent_ones():
    variants = pafnuty.LINES["walk_water"]
    for _ in range(30):
        assert pafnuty.line("walk_water", avoid=variants[1:]) == variants[0]
    assert pafnuty.line("walk_water", avoid=variants) in variants       # всё уже сказано — повтор допустим
    assert pafnuty.line("нет такого повода") in pafnuty.LINES["idle"]


def test_name_forms():
    assert (pafnuty.NAME, pafnuty.NAME_GENITIVE, pafnuty.NAME_INSTRUMENTAL) == ("Пафнутий", "Пафнутия", "Пафнутием")


# --- страницы ---------------------------------------------------------------------------

def test_walk_page(client):
    html = client.get("/walk").text
    assert "Прогулка с Пафнутием" in html and "Пафнутийем" not in html
    assert "/static/walk.js?v=" in html and "/static/mic.js?v=" in html and "/static/pafnuty.js?v=" in html
    assert '"walk_water"' in html and 'id="stage-back"' in html and 'id="stage-front"' in html
    assert 'id="mic-toggle"' in html and 'id="quiet-threshold"' in html and 'id="loud-threshold"' in html


def test_navigation_has_the_game(client):
    html = client.get("/").text
    assert 'href="/walk"' in html and "Прогулка с Пафнутием" in html


def test_companion_is_on_every_page(client):
    for url in ("/", "/operations", "/evaluation", "/walk", "/help"):
        html = client.get(url).text
        assert 'id="companion"' in html and 'id="companion-figure"' in html, url
        assert "/static/pafnuty.js?v=" in html and 'id="secret"' in html


def test_scripts_export_their_rules(client):
    assert "WalkRules" in client.get("/static/walk.js").text
    assert "module.exports = geometry" in client.get("/static/pafnuty.js").text
    worklet = client.get("/static/capture-worklet.js")
    assert worklet.status_code == 200 and "registerProcessor('sluhach-capture'" in worklet.text
    assert "javascript" in worklet.headers["content-type"]               # иначе браузер не загрузит обработчик звука


def test_worklet_name_matches_the_page_script():
    assert "'sluhach-capture'" in (STATIC / "mic.js").read_text(encoding="utf-8")


def test_game_does_not_touch_the_server(client):
    """Прогулка идёт в браузере: ей нужна только громкость, распознавание не участвует."""
    script = (STATIC / "walk.js").read_text(encoding="utf-8")
    assert "fetch(" not in script and "WebSocket" not in script and "/api/" not in script
    assert "processing: false" in script                                 # громкость не выравнивается браузером


def test_companion_name_is_configured():
    assert config.COMPANION_ENABLED and config.COMPANION_NAME == pafnuty.NAME


# --- правила (JavaScript) ----------------------------------------------------------------

@pytest.mark.skipif(shutil.which("node") is None, reason="node не установлен")
@pytest.mark.parametrize("script", ["walk_rules.test.js", "pafnuty_model.test.js", "voice_rules.test.js"])
def test_javascript_rules(script):
    result = subprocess.run(["node", str(ROOT / "tests" / script)], capture_output=True, text=True,
                            encoding="utf-8", cwd=str(ROOT), timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Все проверки пройдены" in result.stdout
