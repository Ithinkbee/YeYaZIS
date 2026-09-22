"""Оркестратор распознавания: связывает корпус, методы и документы.

Здесь собраны все три шага алгоритма из методички:

    шаг 1 — предварительная обработка (`corpus`/`preprocess`);
    шаг 2 — сравнительный анализ профилей модели и входного документа;
    шаг 3 — выбор языка с наименьшим значением метрики.

Дополнительно считается согласованное решение: язык, выбранный большинством
методов. При равенстве голосов предпочтение отдаётся методу с наибольшей
уверенностью — так двухметодная ничья разрешается детерминированно.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from . import config, corpus as corpus_module, methods as methods_module
from .models import Document, MethodResult, Verdict


class Recognizer:
    """Набор обученных методов и операции над документами."""

    def __init__(self, selected: tuple[str, ...] = methods_module.METHOD_CODES) -> None:
        self.methods: dict[str, methods_module.Method] = {
            code: methods_module.create(code) for code in selected
        }
        #: сведения об обучении: объём корпуса, время построения профилей
        self.training: dict[str, object] = {}

    # --- построение профилей -------------------------------------------------

    def fit(self, training_corpus: dict[str, str] | None = None) -> dict[str, float]:
        """Строит профили всех методов. Возвращает время обучения по методам."""
        if training_corpus is None:
            training_corpus = corpus_module.load_training_corpus()
        timings: dict[str, float] = {}
        for code, method in self.methods.items():
            started = time.perf_counter()
            method.fit(training_corpus)
            timings[code] = (time.perf_counter() - started) * 1000.0
        self.training = {
            "languages": {
                code: len(text) for code, text in training_corpus.items()
            },
            "fit_ms": timings,
            "trained_at": datetime.now().isoformat(timespec="seconds"),
        }
        return timings

    def save(self, directory: Path | None = None) -> list[Path]:
        """Сохраняет профили всех методов на диск."""
        return [method.save(directory) for method in self.methods.values()]

    def load(self, directory: Path | None = None) -> bool:
        """Загружает профили всех методов; False — хотя бы один не загрузился."""
        return all(method.load(directory) for method in self.methods.values())

    def load_or_fit(self, directory: Path | None = None) -> bool:
        """Поднимает профили с диска, а при неудаче строит их заново.

        Возвращает True, если профили были прочитаны из файлов.
        """
        if self.load(directory):
            return True
        self.fit()
        self.save(directory)
        return False

    @property
    def trained(self) -> bool:
        return all(method.trained for method in self.methods.values())

    # --- распознавание -------------------------------------------------------

    def recognize(self, document: Document) -> Verdict:
        """Шаги 2 и 3 для одного документа всеми методами сразу."""
        results: dict[str, MethodResult] = {}
        elapsed = 0.0
        for code, method in self.methods.items():
            result = method.classify(document.text)
            results[code] = result
            elapsed += result.elapsed_ms

        language, agreement = self._consensus(results)
        return Verdict(
            document=document,
            results=results,
            language=language,
            agreement=agreement,
            elapsed_ms=elapsed,
        )

    def recognize_all(self, documents: list[Document]) -> list[Verdict]:
        """Распознаёт всю коллекцию."""
        return [self.recognize(document) for document in documents]

    @staticmethod
    def _consensus(results: dict[str, MethodResult]) -> tuple[str, float]:
        """Голосование методов.

        Голоса считаются по языкам; при равенстве побеждает язык, за который
        высказался метод с наибольшей уверенностью. Уверенность — относительный
        отрыв ближайшего языка от второго (см. `MethodResult.confidence`).
        """
        if not results:
            return config.LANGUAGE_CODES[0], 0.0

        votes: dict[str, int] = {}
        strength: dict[str, float] = {}
        for result in results.values():
            votes[result.language] = votes.get(result.language, 0) + 1
            strength[result.language] = max(
                strength.get(result.language, 0.0), result.confidence
            )

        best = max(
            votes,
            key=lambda code: (votes[code], strength[code], -config.LANGUAGE_CODES.index(code)),
        )
        return best, votes[best] / len(results)

    # --- удобные обёртки -----------------------------------------------------

    def recognize_text(self, source: str, *, title: str = "Введённый текст", is_html: bool = False) -> Verdict:
        """Распознаёт произвольный текст или HTML, не сохраняя его на диск."""
        document = corpus_module.document_from_text(source, title=title, is_html=is_html)
        return self.recognize(document)

    def recognize_collection(self) -> list[Verdict]:
        """Распознаёт тестовую коллекцию целиком."""
        return self.recognize_all(corpus_module.load_collection())
