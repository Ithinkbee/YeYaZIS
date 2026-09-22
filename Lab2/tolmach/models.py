"""Структуры данных системы.

Вход и выход системы описываются четырьмя уровнями объектов:

    Document      — входной документ после предварительной обработки;
    Profile       — поисковый образ языка (ПОЯ) или документа (ПОД);
    MethodResult  — решение одного метода по одному документу;
    Verdict       — сводное решение всех методов по одному документу;
    Report        — результаты по всей тестовой коллекции и метрики качества.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import config


@dataclass(slots=True)
class Document:
    """Входной документ после извлечения текста из HTML.

    Поля `raw` и `text` различаются: первое — исходная разметка, второе —
    видимый текст без тегов, скриптов и стилей.
    """

    doc_id: str
    title: str
    #: путь к исходному файлу; None — если текст введён вручную
    path: Path | None
    #: нормализованный текст (строчные буквы, без знаков препинания)
    text: str
    #: количество букв в нормализованном тексте
    letters: int
    #: количество слов
    words: int
    #: размер исходного файла в байтах
    size: int
    #: язык по эталонной разметке; None — если разметки нет
    gold: str | None = None

    @property
    def gold_name(self) -> str:
        return config.language_name(self.gold) if self.gold else "не размечен"


@dataclass(slots=True)
class Profile:
    """Поисковый образ: упорядоченный по убыванию частоты набор признаков.

    Одна и та же структура описывает и профиль языка (ПОЯ, построенный по
    обучающему корпусу), и профиль входного документа (ПОД).
    """

    #: код языка или идентификатор документа
    owner: str
    #: метод, которым построен профиль
    method: str
    #: признак -> ранг (0 — самый частый)
    ranks: dict[str, int] = field(default_factory=dict)
    #: признак -> относительная частота
    weights: dict[str, float] = field(default_factory=dict)
    #: сколько признаков всего просмотрено при построении
    total: int = 0

    def top(self, count: int = 20) -> list[tuple[str, int, float]]:
        """Первые `count` признаков профиля: (признак, ранг, частота)."""
        items = sorted(self.ranks.items(), key=lambda pair: pair[1])[:count]
        return [(feature, rank, self.weights.get(feature, 0.0)) for feature, rank in items]

    def __len__(self) -> int:
        return len(self.ranks)


@dataclass(slots=True)
class MethodResult:
    """Решение одного метода по одному документу.

    `distances` хранит метрику расстояния до каждого языка; решением является
    язык с наименьшим значением метрики.
    """

    method: str
    #: код языка -> расстояние (чем меньше, тем ближе)
    distances: dict[str, float]
    #: выбранный язык
    language: str
    #: время работы метода на этом документе, миллисекунды
    elapsed_ms: float
    #: пояснение для интерфейса: что именно сравнивалось
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def language_name(self) -> str:
        return config.language_name(self.language)

    @property
    def confidence(self) -> float:
        """Уверенность в решении: насколько ближайший язык оторвался от второго.

        Ноль означает, что расстояния до всех языков совпали и выбор случаен.
        """
        ordered = sorted(self.distances.values())
        if len(ordered) < 2:
            return 1.0
        best, second = ordered[0], ordered[1]
        if second <= 0:
            return 0.0
        return max(0.0, min(1.0, (second - best) / second))

    def ranked(self) -> list[tuple[str, float]]:
        """Языки, упорядоченные по возрастанию расстояния."""
        return sorted(self.distances.items(), key=lambda pair: pair[1])


@dataclass(slots=True)
class Verdict:
    """Сводное решение по документу: итог всех методов и согласованный ответ."""

    document: Document
    #: имя метода -> результат
    results: dict[str, MethodResult]
    #: язык, выбранный большинством методов
    language: str
    #: доля методов, согласившихся с итоговым языком
    agreement: float
    #: суммарное время распознавания, миллисекунды
    elapsed_ms: float

    @property
    def language_name(self) -> str:
        return config.language_name(self.language)

    @property
    def correct(self) -> bool | None:
        """Совпало ли сводное решение с эталоном; None — эталона нет."""
        if self.document.gold is None:
            return None
        return self.document.gold == self.language

    def is_correct(self, method: str) -> bool | None:
        """Совпало ли решение конкретного метода с эталоном."""
        if self.document.gold is None or method not in self.results:
            return None
        return self.document.gold == self.results[method].language


@dataclass(slots=True)
class MethodScore:
    """Качество и быстродействие одного метода на всей тестовой коллекции."""

    method: str
    #: число документов, язык которых определён верно
    correct: int
    #: число размеченных документов
    total: int
    #: суммарное время, миллисекунды
    elapsed_ms: float
    #: матрица ошибок: эталон -> (ответ -> количество)
    confusion: dict[str, dict[str, int]] = field(default_factory=dict)
    #: средняя уверенность решения
    confidence: float = 0.0

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def errors(self) -> int:
        return self.total - self.correct

    @property
    def mean_ms(self) -> float:
        """Среднее время распознавания одного документа."""
        return self.elapsed_ms / self.total if self.total else 0.0

    @property
    def per_second(self) -> float:
        """Быстродействие: документов в секунду."""
        return 1000.0 / self.mean_ms if self.mean_ms else 0.0

    def precision(self, code: str) -> float:
        """Точность по языку: доля верных среди отнесённых к этому языку."""
        assigned = sum(row.get(code, 0) for row in self.confusion.values())
        if not assigned:
            return 0.0
        return self.confusion.get(code, {}).get(code, 0) / assigned

    def recall(self, code: str) -> float:
        """Полнота по языку: доля найденных среди документов этого языка."""
        row = self.confusion.get(code, {})
        total = sum(row.values())
        if not total:
            return 0.0
        return row.get(code, 0) / total

    def f1(self, code: str) -> float:
        p, r = self.precision(code), self.recall(code)
        return 2 * p * r / (p + r) if (p + r) else 0.0


@dataclass(slots=True)
class Report:
    """Результат прогона всей тестовой коллекции."""

    verdicts: list[Verdict]
    #: имя метода -> оценка качества и быстродействия
    scores: dict[str, MethodScore]
    #: оценка согласованного решения
    consensus: MethodScore
    #: когда выполнен прогон
    created_at: str

    @property
    def size(self) -> int:
        return len(self.verdicts)

    @property
    def labelled(self) -> int:
        return sum(1 for verdict in self.verdicts if verdict.document.gold is not None)

    def by_language(self) -> dict[str, int]:
        """Сколько документов коллекции отнесено к каждому языку."""
        counts: dict[str, int] = {code: 0 for code in config.LANGUAGE_CODES}
        for verdict in self.verdicts:
            counts[verdict.language] = counts.get(verdict.language, 0) + 1
        return counts

    def disagreements(self) -> list[Verdict]:
        """Документы, по которым методы разошлись во мнениях."""
        return [verdict for verdict in self.verdicts if verdict.agreement < 1.0]

    def best_method(self) -> str | None:
        """Метод с наибольшей точностью; при равенстве — более быстрый."""
        if not self.scores:
            return None
        return max(
            self.scores,
            key=lambda name: (self.scores[name].accuracy, -self.scores[name].mean_ms),
        )
