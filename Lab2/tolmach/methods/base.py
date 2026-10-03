"""Общий интерфейс методов распознавания языка.

Все три метода варианта различаются только двумя вещами: правилом построения
поискового образа и стратегией сравнения образов. Поэтому у них один интерфейс:

    fit(corpus)        — построить профили языков (ПОЯ) по обучающему корпусу;
    profile(text)      — построить профиль входного документа (ПОД);
    distances(text)    — расстояние от ПОД до каждого ПОЯ;
    classify(text)     — язык с наименьшим расстоянием плюс замер времени.

Такая развязка позволяет добавить новый метод, не трогая ни оркестратор, ни
интерфейс: достаточно зарегистрировать класс в `methods/__init__.py`.
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .. import config
from ..models import MethodResult, Profile


class Method(ABC):
    """Базовый класс метода распознавания."""

    #: короткий код метода, он же имя файла с профилями
    code: str = "base"

    #: название метода для интерфейса и отчёта
    title: str = "Базовый метод"

    #: чем метод описывает язык — одна строка для справки
    summary: str = ""

    #: развёрнутое описание правила построения образа и стратегии сравнения
    description: str = ""

    def __init__(self) -> None:
        #: код языка -> поисковый образ языка
        self.profiles: dict[str, Profile] = {}
        #: сведения о построении профилей (объём корпуса, параметры)
        self.info: dict[str, Any] = {}

    # --- обучение и распознавание -------------------------------------------

    @property
    def trained(self) -> bool:
        return bool(self.profiles)

    @abstractmethod
    def fit(self, corpus: dict[str, str]) -> None:
        """Строит профили языков по обучающему корпусу.

        `corpus` — отображение «код языка -> нормализованный текст корпуса».
        """

    @abstractmethod
    def profile(self, text: str) -> Profile:
        """Строит поисковый образ входного документа."""

    @abstractmethod
    def distance(self, document: Profile, language: Profile) -> float:
        """Метрика расстояния между образом документа и образом языка.

        Значение неотрицательно и нормировано так, чтобы его можно было
        сравнивать между методами: 0 — полное совпадение, 1 — максимальное
        расхождение.
        """

    def distances(self, text: str) -> dict[str, float]:
        """Расстояния от документа до каждого языка."""
        self._require_trained()
        document = self.profile(text)
        return {
            code: self.distance(document, language)
            for code, language in self.profiles.items()
        }

    def classify(self, text: str) -> MethodResult:
        """Шаги 2 и 3 алгоритма: сравнение профилей и выбор языка.

        Время замеряется на полном цикле «построить ПОД — сравнить с ПОЯ»,
        то есть включает предварительный разбор текста самим методом.
        """
        self._require_trained()
        started = time.perf_counter()
        document = self.profile(text)
        distances = {
            code: self.distance(document, language)
            for code, language in self.profiles.items()
        }
        elapsed = (time.perf_counter() - started) * 1000.0

        # При равенстве расстояний берётся первый язык в порядке config —
        # так результат не зависит от порядка обхода словаря.
        language = min(
            config.LANGUAGE_CODES,
            key=lambda code: (distances.get(code, float("inf")), config.LANGUAGE_CODES.index(code)),
        )
        return MethodResult(
            method=self.code,
            distances=distances,
            language=language,
            elapsed_ms=elapsed,
            detail=self.explain(document, distances),
        )

    def explain(self, document: Profile, distances: dict[str, float]) -> dict[str, Any]:
        """Данные для интерфейса: что именно сравнивалось.

        Переопределяется методами, которым есть что показать пользователю.
        """
        return {"profile_size": len(document)}

    def _require_trained(self) -> None:
        if not self.trained:
            raise RuntimeError(
                f"метод «{self.title}» не обучен: постройте профили командой "
                f"python tools/train.py"
            )

    # --- сохранение и загрузка ----------------------------------------------

    def model_path(self, directory: Path | None = None) -> Path:
        base = directory or config.MODELS_DIR
        return base / f"{self.code}.json"

    def save(self, directory: Path | None = None) -> Path:
        """Сохраняет профили языков в JSON."""
        self._require_trained()
        path = self.model_path(directory)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "method": self.code,
            "info": self.info,
            "profiles": {
                code: {
                    "owner": profile.owner,
                    "method": profile.method,
                    "ranks": profile.ranks,
                    "weights": profile.weights,
                    "total": profile.total,
                }
                for code, profile in self.profiles.items()
            },
            "extra": self._save_extra(),
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        return path

    def load(self, directory: Path | None = None) -> bool:
        """Загружает профили из JSON; False — файла нет или он несовместим."""
        path = self.model_path(directory)
        if not path.exists():
            return False
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        if payload.get("method") != self.code:
            return False
        self.profiles = {
            code: Profile(
                owner=item["owner"],
                method=item["method"],
                ranks={key: int(value) for key, value in item["ranks"].items()},
                weights={key: float(value) for key, value in item["weights"].items()},
                total=int(item.get("total", 0)),
            )
            for code, item in payload.get("profiles", {}).items()
        }
        self.info = payload.get("info", {})
        self._load_extra(payload.get("extra", {}))
        return self.trained

    def _save_extra(self) -> dict[str, Any]:
        """Дополнительные данные метода (например, веса сети)."""
        return {}

    def _load_extra(self, extra: dict[str, Any]) -> None:
        """Восстанавливает дополнительные данные метода."""


def build_profile(
    counts: dict[str, int],
    *,
    owner: str,
    method: str,
    limit: int | None = None,
) -> Profile:
    """Превращает частоты признаков в поисковый образ.

    Признаки сортируются по убыванию частоты; при равных частотах порядок
    задаётся самим признаком, иначе профиль зависел бы от порядка обхода и
    результаты перестали бы воспроизводиться.
    """
    total = sum(counts.values())
    ordered = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    if limit is not None:
        ordered = ordered[:limit]
    ranks = {feature: rank for rank, (feature, _) in enumerate(ordered)}
    weights = {
        feature: (count / total if total else 0.0) for feature, count in ordered
    }
    return Profile(owner=owner, method=method, ranks=ranks, weights=weights, total=total)
