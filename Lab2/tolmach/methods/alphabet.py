"""Алфавитный метод.

Самый мелкий уровень знаний о языке из перечисленных в методичке: язык
описывается не словами и не N-граммами, а распределением частот отдельных
букв своего алфавита.

Правило построения образа: подсчитываются вхождения каждой буквы, частоты
делятся на общее число букв. Профиль — вектор относительных частот.

Стратегия сравнения: манхэттенское расстояние между векторами частот,
посчитанное по объединению алфавитов всех языков и приведённое к отрезку
[0, 1] делением на 2 (теоретический максимум для двух вероятностных
распределений). Буква, которой в языке нет, даёт в сумму всю свою частоту —
поэтому для языков с разными системами письма расстояние сразу близко к
максимуму.

Для русско-немецкой пары метод разделяет кириллицу и латиницу и потому почти
безошибочен; его слабое место — языки с общим алфавитом, где решение
приходится принимать по одним лишь оттенкам частот.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from .. import config
from ..models import Profile
from .base import Method, build_profile

#: буква считается принадлежащей алфавиту языка, если её доля в обучающем
#: корпусе выше этого порога: так из алфавита выпадают латинские вкрапления
#: в русском тексте (названия, аббревиатуры) и наоборот
ALPHABET_THRESHOLD = 1e-4


def extract_letters(normalized: str) -> Counter[str]:
    """Считает частоты букв нормализованного текста (пробелы не учитываются)."""
    return Counter(char for char in normalized if char != " ")


class AlphabetMethod(Method):
    """Распознавание языка по частотному профилю алфавита."""

    code = "alphabet"
    title = "Алфавитный метод"
    summary = "вектор частот букв, манхэттенское расстояние"
    description = (
        "Образ языка — вектор относительных частот букв алфавита, построенный "
        "по обучающему корпусу. Расстояние между образами — сумма модулей "
        "разностей частот по объединению алфавитов, делённая на 2. Метод "
        "работает на уровне алфавита и потому самый быстрый из трёх."
    )

    def __init__(self) -> None:
        super().__init__()
        #: код языка -> множество букв его алфавита
        self.alphabets: dict[str, set[str]] = {}

    # --- построение профилей -------------------------------------------------

    def fit(self, corpus: dict[str, str]) -> None:
        self.profiles = {}
        self.alphabets = {}
        for code, text in corpus.items():
            counts = extract_letters(text)
            profile = build_profile(counts, owner=code, method=self.code)
            self.profiles[code] = profile
            self.alphabets[code] = {
                letter
                for letter, weight in profile.weights.items()
                if weight >= ALPHABET_THRESHOLD
            }
            self.info.setdefault("languages", {})[code] = {
                "letters": profile.total,
                "alphabet_size": len(self.alphabets[code]),
                "alphabet": "".join(sorted(self.alphabets[code])),
            }

    def profile(self, text: str) -> Profile:
        return build_profile(extract_letters(text), owner="document", method=self.code)

    # --- сравнение профилей --------------------------------------------------

    def distance(self, document: Profile, language: Profile) -> float:
        """Манхэттенское расстояние между векторами частот, нормированное."""
        if not document.weights:
            return 1.0
        total = 0.0
        for letter in document.weights.keys() | language.weights.keys():
            total += abs(document.weights.get(letter, 0.0) - language.weights.get(letter, 0.0))
        return min(1.0, total / 2.0)

    def coverage(self, document: Profile, code: str) -> float:
        """Доля букв документа, входящих в алфавит языка.

        Величина справочная: в метрике она не участвует, но наглядно
        объясняет решение — у русского текста покрытие немецким алфавитом
        близко к нулю.
        """
        alphabet = self.alphabets.get(code, set())
        return sum(
            weight for letter, weight in document.weights.items() if letter in alphabet
        )

    def explain(self, document: Profile, distances: dict[str, float]) -> dict[str, Any]:
        return {
            "profile_size": len(document),
            "top": [
                {"feature": feature, "rank": rank, "weight": weight}
                for feature, rank, weight in document.top(config.ALPHABET_TOP_LETTERS)
            ],
            "coverage": {code: self.coverage(document, code) for code in self.profiles},
            "alien": {
                code: "".join(
                    sorted(
                        letter
                        for letter in document.weights
                        if letter not in self.alphabets.get(code, set())
                    )
                )[:40]
                for code in self.profiles
            },
        }

    def _save_extra(self) -> dict[str, Any]:
        return {"alphabets": {code: sorted(letters) for code, letters in self.alphabets.items()}}

    def _load_extra(self, extra: dict[str, Any]) -> None:
        self.alphabets = {
            code: set(letters) for code, letters in extra.get("alphabets", {}).items()
        }
