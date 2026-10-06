"""Паук Пафнутий выключается переменной окружения и ни на что не влияет.

Без него пропадают его фигура, прогулка и операция «открыть игру»;
распознавание, операции и пасхалки работают по-прежнему, а ответ системы
остаётся в журнале и подписывается «Система». Настройка читается при
импорте, поэтому приложение поднимается в отдельном процессе.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

from .conftest import ROOT

SCRIPT = r"""
import json, re
from fastapi.testclient import TestClient
from sluhach.web.app import app
client = TestClient(app)
html = client.get("/").text
boot = json.loads(re.search(r'id="console-data">(.*?)</script>', html, re.S).group(1))
print("SPIDER" if 'id="companion"' in html or "pafnuty.js" in html else "CLEAN")
print("GAME" if 'href="/walk"' in html else "NO-GAME")
print("VOICE", boot["voice"])
print("OPERATIONS", len(boot["cheatsheet"]["de"]))
print("SECRET" if 'id="secret"' in html else "NO-SECRET")
print("CODES", *[client.get(url).status_code for url in ("/walk", "/operations", "/evaluation", "/help")])
def react(text, language):
    return client.post("/api/react", json={"text": text, "session": {"language": language}}).json()
print("OPEN", react("öffne aufsatz zwei", "de")["session"]["essay"])
print("EGG", react("сколько стоит слон", "ru")["kind"])
print("PLAY", react("ich will spielen", "de")["kind"])
"""


def run(companion: str) -> dict[str, str]:
    env = {**os.environ, "SLUHACH_COMPANION": companion, "PYTHONIOENCODING": "utf-8",
           "SLUHACH_STATE_DIR": tempfile.mkdtemp(prefix="sluhach-tests-")}
    result = subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT, env=env, capture_output=True,
                            text=True, encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stderr
    lines = [line.split(maxsplit=1) for line in result.stdout.splitlines() if line.strip()]
    return {line[0]: line[1] if len(line) > 1 else "" for line in lines}


def test_companion_can_be_switched_off():
    out = run("0")
    assert "CLEAN" in out and "NO-GAME" in out and "SECRET" in out          # тайник остаётся: он не про паука
    assert out["VOICE"] == "Система" and out["OPERATIONS"] == "23"
    assert out["CODES"] == "404 200 200 200"
    assert out["OPEN"] == "de-lit-werther" and out["EGG"] == "egg"
    assert out["PLAY"] == "echo"                                             # операции «открыть игру» больше нет


def test_companion_is_on_by_default():
    out = run("1")
    assert "SPIDER" in out and "GAME" in out and "SECRET" in out
    assert out["VOICE"] == "Пафнутий" and out["OPERATIONS"] == "24"
    assert out["CODES"] == "200 200 200 200"
    assert out["OPEN"] == "de-lit-werther" and out["EGG"] == "egg" and out["PLAY"] == "operation"
