"""Реестр методов распознавания языка.

Порядок в `METHOD_CLASSES` определяет порядок столбцов в таблицах и вкладок в
интерфейсе: от самого «глубокого» знания о языке к самому мелкому и далее к
обучаемому решающему правилу.
"""

from __future__ import annotations

from .alphabet import AlphabetMethod
from .base import Method, build_profile
from .neural import NeuralMethod
from .ngram import NgramMethod

#: классы методов в порядке отображения
METHOD_CLASSES: tuple[type[Method], ...] = (NgramMethod, AlphabetMethod, NeuralMethod)

#: код метода -> класс
METHOD_REGISTRY: dict[str, type[Method]] = {cls.code: cls for cls in METHOD_CLASSES}

#: коды методов в порядке отображения
METHOD_CODES: tuple[str, ...] = tuple(cls.code for cls in METHOD_CLASSES)


def create(code: str) -> Method:
    """Создаёт метод по коду."""
    try:
        return METHOD_REGISTRY[code]()
    except KeyError:
        raise KeyError(f"неизвестный метод: {code}") from None


def create_all() -> dict[str, Method]:
    """Создаёт по одному экземпляру каждого метода."""
    return {cls.code: cls() for cls in METHOD_CLASSES}


def describe() -> list[dict[str, str]]:
    """Краткие сведения о методах для справки и отчёта."""
    return [
        {
            "code": cls.code,
            "title": cls.title,
            "summary": cls.summary,
            "description": cls.description,
        }
        for cls in METHOD_CLASSES
    ]


__all__ = [
    "AlphabetMethod",
    "METHOD_CLASSES",
    "METHOD_CODES",
    "METHOD_REGISTRY",
    "Method",
    "NeuralMethod",
    "NgramMethod",
    "build_profile",
    "create",
    "create_all",
    "describe",
]
