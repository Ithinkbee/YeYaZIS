"""Общие настройки тестов.

Словарь пользователя, сохранённые настройки и синтезированные реплики
Пафнутия система хранит в файлах. Чтобы тесты не трогали настоящие, их
каталоги до импорта приложения уводятся во временные (GLASHATAI_STATE_DIR,
GLASHATAI_CACHE_DIR).

Тесты нейросетевых голосов пропускаются, если нет пакета piper-tts или
скачанных голосов; тесты буфера обмена и горячих клавиш — не в Windows;
тесты в браузере — без Chrome или Edge.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["GLASHATAI_STATE_DIR"] = tempfile.mkdtemp(prefix="glashatai-tests-")
os.environ["GLASHATAI_CACHE_DIR"] = tempfile.mkdtemp(prefix="glashatai-cache-")
for name in ("GLASHATAI_COMPANION", "GLASHATAI_VOICE", "GLASHATAI_DESKTOP"):
    os.environ.pop(name, None)


@pytest.fixture(scope="session")
def reader():
    from glashatai.text import TextReader

    return TextReader()


@pytest.fixture(scope="session")
def speaker():
    from glashatai.speaker import Speaker

    return Speaker()


@pytest.fixture(scope="session")
def piper(speaker):
    """Движок Piper с голосом Thorsten; без него тест пропускается."""
    from glashatai.engines.piper import installed

    if not installed() or not speaker.piper.has("de_DE-thorsten-medium"):
        pytest.skip("нет piper-tts или голоса Thorsten: pip install piper-tts; python tools/get_voices.py")
    return speaker.piper


def render(reader, text: str, mode: str = "normalized", **options) -> str:
    """Текст после нормализации, все предложения подряд."""
    from glashatai.text import ReadingOptions

    document = reader.prepare(text, ReadingOptions(**options) if options else None, limit=None)
    return " ".join(sentence.render(mode) for sentence in document.sentences)
