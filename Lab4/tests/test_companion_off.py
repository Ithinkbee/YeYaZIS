"""Паук Пафнутий выключается переменной окружения и ни на что не влияет.

Без него пропадает и его игра — тир; перевод, словарь и оценка остаются.
Настройка читается при импорте, поэтому приложение поднимается в отдельном
процессе.
"""

from __future__ import annotations

import os
import subprocess
import sys

from .conftest import ROOT

SCRIPT = r"""
from fastapi.testclient import TestClient
from dragoman.web.app import app
client = TestClient(app)
html = client.get("/").text + client.get("/doc/cs-os").text
print("SPIDER" if 'id="companion"' in html else "CLEAN")
print("OK" if "1. Частотный список слов" in html else "BROKEN")
print("GAME" if 'href="/shooter' in html else "NO-GAME")
codes = [client.get(url).status_code for url in ("/shooter", "/api/shooter/plan?doc=cs-os", "/dictionary",
                                                 "/evaluation")]
print("CODES", *codes)
"""


def run(companion: str, tmp_path) -> list[str]:
    env = {**os.environ, "DRAGOMAN_COMPANION": companion, "DRAGOMAN_DB": str(tmp_path / f"c{companion}.sqlite"),
           "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT, env=env, capture_output=True,
                            text=True, encoding="utf-8", timeout=300)
    assert result.returncode == 0, result.stderr
    return result.stdout.split()


def test_companion_can_be_switched_off(tmp_path):
    assert run("0", tmp_path) == ["CLEAN", "OK", "NO-GAME", "CODES", "404", "404", "200", "200"]


def test_companion_is_on_by_default(tmp_path):
    assert run("1", tmp_path) == ["SPIDER", "OK", "GAME", "CODES", "200", "200", "200", "200"]
