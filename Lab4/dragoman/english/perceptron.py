"""Усреднённый перцептрон — общий классификатор теггера, анализатора и разметчика отношений.

Классификатор линейный: у каждого признака — вес для каждого класса, оценка
класса — сумма весов признаков. При ошибке веса верного класса растут на
единицу, ошибочного — падают. Итоговые веса усредняются по всем шагам
обучения (Collins, 2002): усреднение гасит колебания последних примеров и
даёт заметно более устойчивую модель, чем веса последнего шага.

Признаки — строки («i suffix=ing», «s0w=is n0w=used»), значение каждого — 1,
поэтому признаки передаются списком. Усреднение ведётся «лениво»: для каждого
веса помнится, когда он менялся последний раз, и сумма досчитывается только
при изменении (иначе каждый шаг обучения обходил бы все веса).
"""

from __future__ import annotations

import gzip
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Hashable, Iterable


class AveragedPerceptron:
    def __init__(self, classes: Iterable[Hashable] = ()) -> None:
        #: признак -> {класс: вес}
        self.weights: dict[str, dict[Hashable, float]] = {}
        self.classes: list[Hashable] = list(classes)
        self._totals: dict[tuple[str, Hashable], float] = defaultdict(float)
        self._stamps: dict[tuple[str, Hashable], int] = defaultdict(int)
        self.instances = 0

    # --- предсказание ---------------------------------------------------------------

    def scores(self, features: Iterable[str]) -> dict[Hashable, float]:
        scores: dict[Hashable, float] = defaultdict(float)
        weights = self.weights
        for feature in features:
            row = weights.get(feature)
            if row:
                for cls, weight in row.items():
                    scores[cls] += weight
        return scores

    def predict(self, features: Iterable[str], valid: Iterable[Hashable] | None = None) -> Hashable:
        scores = self.scores(features)
        candidates = self.classes if valid is None else valid
        # при равенстве — первый по списку классов: результат не зависит от порядка словаря
        best, best_score = None, None
        for cls in candidates:
            score = scores.get(cls, 0.0)
            if best_score is None or score > best_score:
                best, best_score = cls, score
        return best

    # --- обучение --------------------------------------------------------------------

    def update(self, truth: Hashable, guess: Hashable, features: Iterable[str]) -> None:
        self.instances += 1
        if truth == guess:
            return
        for feature in features:
            row = self.weights.setdefault(feature, {})
            self._step(feature, truth, row, 1.0)
            self._step(feature, guess, row, -1.0)

    def _step(self, feature: str, cls: Hashable, row: dict[Hashable, float], delta: float) -> None:
        key = (feature, cls)
        weight = row.get(cls, 0.0)
        self._totals[key] += (self.instances - self._stamps[key]) * weight
        self._stamps[key] = self.instances
        row[cls] = weight + delta

    def average(self) -> None:
        """Заменяет веса средними за всё обучение."""
        for feature, row in self.weights.items():
            averaged = {}
            for cls, weight in row.items():
                key = (feature, cls)
                total = self._totals[key] + (self.instances - self._stamps[key]) * weight
                value = total / max(1, self.instances)
                if value:
                    averaged[cls] = value
            self.weights[feature] = averaged
        self._totals.clear()
        self._stamps.clear()

    # --- сохранение -------------------------------------------------------------------

    def prune(self, threshold: float) -> int:
        """Убирает веса меньше порога по модулю; возвращает число оставшихся весов."""
        kept = 0
        for feature in list(self.weights):
            row = {cls: w for cls, w in self.weights[feature].items() if abs(w) >= threshold}
            if row:
                self.weights[feature] = row
                kept += len(row)
            else:
                del self.weights[feature]
        return kept

    def to_dict(self, digits: int = 4) -> dict:
        index = {cls: i for i, cls in enumerate(self.classes)}
        return {
            "classes": self.classes,
            "weights": {feature: {str(index[cls]): round(w, digits) for cls, w in row.items()}
                        for feature, row in self.weights.items() if row},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AveragedPerceptron":
        model = cls(data["classes"])
        classes = model.classes
        model.weights = {feature: {classes[int(i)]: w for i, w in row.items()}
                         for feature, row in data["weights"].items()}
        return model


def save_json(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with gzip.open(path, "wb", compresslevel=9) as stream:
        stream.write(raw)


def load_json(path: Path) -> dict:
    with gzip.open(path, "rb") as stream:
        return json.loads(stream.read().decode("utf-8"))


def shuffled(items: list, seed: int, epoch: int) -> list:
    copy = list(items)
    random.Random(seed * 1000 + epoch).shuffle(copy)
    return copy
