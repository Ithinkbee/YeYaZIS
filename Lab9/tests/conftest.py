"""Общие настройки тестов.

Список операций и фразы-пасхалки система хранит в файлах. Чтобы тесты не
трогали настоящие настройки, каталог этих файлов до импорта приложения
уводится во временный (SLUHACH_STATE_DIR); отдельные тесты заводят свои
хранилища в tmp_path.

Тесты распознавания работают на записях из tests/audio и пропускаются, если
не установлен пакет vosk или не скачаны модели.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["SLUHACH_STATE_DIR"] = tempfile.mkdtemp(prefix="sluhach-tests-")
os.environ.pop("SLUHACH_COMPANION", None)
os.environ.pop("SLUHACH_ADMIN_PASSWORD", None)
os.environ.pop("SLUHACH_LANGUAGE", None)

AUDIO_DIR = ROOT / "tests" / "audio"


def audio_index() -> list[dict]:
    try:
        return json.loads((AUDIO_DIR / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


@pytest.fixture(scope="session")
def collection():
    from sluhach.essays import Collection

    return Collection()


@pytest.fixture()
def operations(tmp_path):
    from sluhach.operations import OperationSet

    return OperationSet(tmp_path / "operations.json", companion=True)


@pytest.fixture()
def eggs(tmp_path):
    from sluhach.eggs import EggStore

    return EggStore(tmp_path / "eggs.json")


@pytest.fixture()
def reactor(collection, operations, eggs):
    from sluhach.reactions import Reactor

    return Reactor(collection, operations, eggs)


@pytest.fixture(scope="session")
def engine():
    """Распознаватель Vosk с обеими моделями; без него тест пропускается."""
    from sluhach import config
    from sluhach.recognizer import VoskEngine

    found = VoskEngine()
    missing = [code for code in config.LANGUAGE_CODES if not found.available(code)]
    if missing:
        pytest.skip("нет пакета vosk или моделей: python tools/get_models.py")
    return found


@pytest.fixture(scope="session")
def recordings():
    """Записи фраз для тестов распознавания: [{file, language, voice, text, path}]."""
    items = [dict(item, path=AUDIO_DIR / item["file"]) for item in audio_index()]
    items = [item for item in items if item["path"].exists()]
    if not items:
        pytest.skip("нет записей tests/audio: python tools/make_test_audio.py")
    return items
