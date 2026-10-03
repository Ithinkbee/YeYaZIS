"""Паук Пафнутий выключается переменной окружения и ни на что не влияет.

Без него пропадают и его игры — сапёр и бой; реферат вручную остаётся: это
задание на реферирование, а не игра паука. Настройка читается при импорте,
поэтому приложение поднимается в отдельном процессе.
"""

from __future__ import annotations

import os
import subprocess
import sys

from .conftest import ROOT

SCRIPT = r"""
from fastapi.testclient import TestClient
from izbornik.web.app import app
client = TestClient(app)
html = client.get("/").text + client.get("/doc/ru-cs-crypto").text
print("SPIDER" if 'id="companion"' in html else "CLEAN")
print("OK" if "1. Классический реферат" in html else "BROKEN")
print("GAMES" if 'href="/battle"' in html or 'href="/sweeper"' in html else "NO-GAMES")
codes = [client.get(url).status_code for url in ("/sweeper", "/battle", "/api/battle/grid", "/manual")]
print("CODES", *codes)
"""


def run(companion: str) -> list[str]:
    env = {**os.environ, "IZBORNIK_COMPANION": companion, "IZBORNIK_OSTIS": "off", "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT, env=env, capture_output=True,
                            text=True, encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stderr
    return result.stdout.split()


def test_companion_can_be_switched_off():
    assert run("0") == ["CLEAN", "OK", "NO-GAMES", "CODES", "404", "404", "404", "200"]


def test_companion_is_on_by_default():
    assert run("1") == ["SPIDER", "OK", "GAMES", "CODES", "200", "200", "200", "200"]
