"""Общие настройки тестов.

Веб-интерфейс в тестах работает без OSTIS: режим задаётся до импорта
приложения. Проверки живой ostis-системы собраны в test_ostis_live.py и
пропускаются, если sc-сервер недоступен.
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("IZBORNIK_OSTIS", "off")


@pytest.fixture(scope="session")
def collection():
    from izbornik.collection import Collection

    return Collection()


def port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def sc_server_alive(url: str = "ws://127.0.0.1:8090", timeout: float = 3.0) -> bool:
    """sc-сервер не только принимает соединение, но и отвечает на запрос.

    Зависший sc-сервер держит порт открытым, и py-sc-client ждал бы ответа
    бесконечно, поэтому проверка идёт напрямую через websocket с таймаутом.
    """
    if not port_open("127.0.0.1", 8090):
        return False
    try:
        import json

        import websocket

        connection = websocket.create_connection(url, timeout=timeout)
        try:
            connection.send(json.dumps({"id": 1, "type": "keynodes",
                                        "payload": [{"command": "find", "idtf": "nrel_main_idtf"}]}))
            json.loads(connection.recv())        # ответ пришёл до таймаута — сервер жив
            return True
        finally:
            connection.close()
    except Exception:  # noqa: BLE001
        return False
