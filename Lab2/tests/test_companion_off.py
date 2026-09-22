"""Проверка выключателя игровой надстройки.

При TOLMACH_COMPANION=0 от паука, шахмат и викторины не должно остаться
ничего: ни разметки, ни страниц, ни API. Лабораторная работа обязана
выглядеть и работать так, будто изюминки никогда не было.

Модуль конфигурации читает переменную окружения при импорте, поэтому здесь
приложение поднимается в отдельном процессе: менять уже загруженный
`config` на ходу значило бы проверять не то, что работает у пользователя.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

PROBE = r"""
import json, os, sys
sys.path.insert(0, r"{root}")
os.environ["TOLMACH_COMPANION"] = "0"
from fastapi.testclient import TestClient
from tolmach.web.app import app

out = {{}}
with TestClient(app) as client:
    for path in ("/", "/check", "/compare", "/profiles", "/help"):
        text = client.get(path).text
        out[path] = {{
            "spider": "companion-spider" in text,
            "gate": "gate-board" in text,
            "chess_link": "/chess" in text,
        }}
    out["chess_page"] = client.get("/chess").status_code
    out["api_puzzle"] = client.get("/api/chess/puzzle").status_code
    out["api_word"] = client.get("/api/quiz/word").status_code
    out["api_move"] = client.post(
        "/api/chess/move",
        json={{"fen": "8/8/8/8/8/8/8/K6k w - - 0 1", "frm": "a1", "to": "a2"}},
    ).status_code
    out["api_answer"] = client.post(
        "/api/quiz/answer", json={{"word": "rabota", "answer": "ru"}}
    ).status_code
    recognised = client.post("/check", data={{"text": "Совершенно русское предложение."}})
    out["recognition_works"] = recognised.status_code == 200 and "tag-ru" in recognised.text
print(json.dumps(out))
""".format(root=str(ROOT))


@pytest.fixture(scope="module")
def probe() -> dict:
    """Поднимает приложение с выключенной надстройкой в отдельном процессе."""
    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(ROOT),
        timeout=300,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("path", ["/", "/check", "/compare", "/profiles", "/help"])
def test_no_trace_of_the_spider(probe, path):
    assert probe[path]["spider"] is False
    assert probe[path]["gate"] is False
    assert probe[path]["chess_link"] is False


def test_chess_page_is_gone(probe):
    assert probe["chess_page"] == 404


def test_game_api_refuses(probe):
    for key in ("api_puzzle", "api_word", "api_move", "api_answer"):
        assert probe[key] == 403, key


def test_recognition_still_works(probe):
    """Главное: распознавание языка от надстройки не зависит."""
    assert probe["recognition_works"] is True
