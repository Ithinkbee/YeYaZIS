"""Проверки сценариев страницы: расчёты без DOM запускаются в node.

Партитура, геометрия паука и расстановка труппы написаны так, чтобы
работать и в браузере, и в node; их проверки — tests/*.test.js. Здесь они
запускаются из pytest. Без node тесты пропускаются.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from .conftest import ROOT

NODE = shutil.which("node")
SCRIPTS = sorted((ROOT / "tests").glob("*.test.js"))


def test_there_are_script_checks():
    assert {path.name for path in SCRIPTS} >= {"score.test.js", "spider.test.js", "troupe.test.js"}


@pytest.mark.skipif(NODE is None, reason="нет node")
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda path: path.name)
def test_script(script):
    result = subprocess.run([NODE, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-2000:]
    assert "ошибок: 0" in result.stdout


@pytest.mark.skipif(NODE is None, reason="нет node")
@pytest.mark.parametrize("script", sorted((ROOT / "poklon" / "web" / "static").glob("*.js")), ids=lambda path: path.name)
def test_syntax(script):
    """Сценарии страницы разбираются без ошибок (в том числе те, что работают только в браузере)."""
    result = subprocess.run([NODE, "--check", str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stderr
