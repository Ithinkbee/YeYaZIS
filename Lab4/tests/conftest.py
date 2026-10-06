"""Общие настройки тестов.

Словарь в тестах — временная база данных: правки, которые делают тесты, не
попадают в рабочий словарь data/dictionary.sqlite.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TEST_DB = Path(tempfile.gettempdir()) / f"dragoman-test-{os.getpid()}.sqlite"
os.environ["DRAGOMAN_DB"] = str(TEST_DB)


@pytest.fixture(scope="session")
def lexicon():
    from dragoman.lexicon import db

    return db.get()


@pytest.fixture(scope="session")
def translator(lexicon):
    from dragoman.translate.pipeline import Translator

    return Translator(lexicon)


@pytest.fixture(scope="session")
def de(translator):
    """Перевод одного предложения с трансфером — текстом."""

    def run(text: str, domain: str = "cs") -> str:
        t = translator.translate(text, domain=domain, log_unknown=False)
        return " ".join(s.text for s in t.sentences)

    return run


def pytest_sessionfinish(session, exitstatus):
    from dragoman.lexicon import db

    instance = db._instance
    if instance is not None:
        instance.close()
    try:
        TEST_DB.unlink()
    except OSError:
        pass
