"""Общее для тестов: сервер «Поклона» во временных папках.

Настоящие music/ и data/ тесты не трогают: папки подменяются на время теста,
а сервер поднимается на свободном порту.
"""

from __future__ import annotations

import http.client
import json
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from poklon import config  # noqa: E402
from poklon.server import make_server  # noqa: E402


class Client:
    """Запросы к серверу теста."""

    def __init__(self, port: int) -> None:
        self.port = port

    def request(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def get(self, path: str, headers: dict | None = None):
        return self.request("GET", path, headers=headers)

    def json(self, method: str, path: str, data: object | None = None, headers: dict | None = None):
        body = None if data is None else json.dumps(data).encode("utf-8")
        status, _, raw = self.request(method, path, body, headers)
        return status, json.loads(raw.decode("utf-8"))


@pytest.fixture
def folders(tmp_path, monkeypatch):
    """Временные папки музыки и данных вместо настоящих."""
    music = tmp_path / "music"
    data = tmp_path / "data"
    music.mkdir()
    data.mkdir()
    monkeypatch.setattr(config, "MUSIC", music)
    monkeypatch.setattr(config, "DATA_DIR", data)
    return music, data


@pytest.fixture
def client(folders):
    server = make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield Client(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
