"""Подготовка консоли к выводу на русском языке.

Консоль Windows по умолчанию работает не в UTF-8, а в однобайтовой кодировке
(cp866 или cp1251). Кириллица в неё обычно проходит, а типографские знаки
вроде «×» и «✓» — нет, и сценарий падает с UnicodeEncodeError на середине
вывода. Переключение потоков на UTF-8 снимает вопрос целиком.
"""

from __future__ import annotations

import sys
from typing import TextIO


def setup() -> None:
    """Переводит стандартные потоки на UTF-8, если это возможно.

    Вызывается в начале каждой точки входа. Если поток перенастроить нельзя
    (например, он подменён на объект без `reconfigure`), вывод остаётся как
    был: терять работу сценария из-за оформления не следует.
    """
    for stream in (sys.stdout, sys.stderr):
        _reconfigure(stream)


def _reconfigure(stream: TextIO | None) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        pass
