"""Метод N-грамм (В. Кавнар, Дж. Тренкл, 1994).

Правило построения образа: текст режется на слова, каждое слово обрамляется
символом-заполнителем (`_слово_`), из полученных строк извлекаются все
подстроки длины от 1 до N. N-граммы упорядочиваются по убыванию частоты, и
первые `NGRAM_PROFILE_SIZE` из них образуют профиль. Ранг N-граммы — её номер
в этом списке.

Стратегия сравнения — мера несовпадения позиций (out-of-place): для каждой
N-граммы профиля документа берётся модуль разности её рангов в профиле
документа и профиле языка; N-грамме, которой в профиле языка нет, назначается
максимальный штраф, равный размеру профиля. Расстояние — сумма этих величин.

Метод опирается на закон Ципфа: частотный «хвост» N-грамм у каждого языка
свой, и порядок верхних трёхсот N-грамм оказывается устойчивой характеристикой
языка, слабо зависящей от темы конкретного документа.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from .. import config
from ..models import Profile
from .base import Method, build_profile


def extract_ngrams(normalized: str, max_n: int = config.NGRAM_MAX_N) -> Counter[str]:
    """Считает частоты N-грамм длины 1..max_n в нормализованном тексте.

    Обрамление слова заполнителем делает значимой позицию буквы в слове:
    `_de` — это начало слова, а `de_` — его конец, и это разные признаки.
    """
    pad = config.NGRAM_PAD
    counts: Counter[str] = Counter()
    for word in normalized.split():
        padded = f"{pad}{word}{pad}"
        length = len(padded)
        for n in range(1, max_n + 1):
            if n > length:
                break
            for start in range(length - n + 1):
                counts[padded[start : start + n]] += 1
    return counts


class NgramMethod(Method):
    """Распознавание языка по профилю N-грамм."""

    code = "ngram"
    title = "Метод N-грамм"
    summary = "профиль из 300 самых частых N-грамм, мера несовпадения позиций"
    description = (
        "Образ языка — упорядоченный по убыванию частоты список из "
        f"{config.NGRAM_PROFILE_SIZE} N-грамм длиной до {config.NGRAM_MAX_N} символов. "
        "Расстояние между образами считается мерой несовпадения позиций "
        "(out-of-place): для каждой N-граммы документа берётся модуль разности "
        "её рангов в двух профилях, а отсутствующей в профиле языка N-грамме "
        "назначается максимальный штраф."
    )

    def __init__(
        self,
        max_n: int = config.NGRAM_MAX_N,
        profile_size: int = config.NGRAM_PROFILE_SIZE,
    ) -> None:
        super().__init__()
        self.max_n = max_n
        self.profile_size = profile_size

    # --- построение профилей -------------------------------------------------

    def fit(self, corpus: dict[str, str]) -> None:
        self.profiles = {}
        for code, text in corpus.items():
            counts = extract_ngrams(text, self.max_n)
            self.profiles[code] = build_profile(
                counts,
                owner=code,
                method=self.code,
                limit=self.profile_size,
            )
            self.info.setdefault("languages", {})[code] = {
                "letters": sum(1 for char in text if char != " "),
                "unique_ngrams": len(counts),
                "profile_size": len(self.profiles[code]),
            }
        self.info["max_n"] = self.max_n
        self.info["profile_size"] = self.profile_size

    def profile(self, text: str) -> Profile:
        counts = extract_ngrams(text, self.max_n)
        return build_profile(
            counts,
            owner="document",
            method=self.code,
            limit=self.profile_size,
        )

    # --- сравнение профилей --------------------------------------------------

    def distance(self, document: Profile, language: Profile) -> float:
        """Мера несовпадения позиций, приведённая к отрезку [0, 1]."""
        if not document.ranks:
            return 1.0
        penalty = max(len(language), self.profile_size)
        total = 0
        for ngram, doc_rank in document.ranks.items():
            language_rank = language.ranks.get(ngram)
            total += penalty if language_rank is None else abs(doc_rank - language_rank)
        return total / (len(document.ranks) * penalty)

    def explain(self, document: Profile, distances: dict[str, float]) -> dict[str, Any]:
        """Показывает, сколько N-грамм документа нашлось в каждом языке."""
        overlap: dict[str, dict[str, Any]] = {}
        for code, language in self.profiles.items():
            found = sum(1 for ngram in document.ranks if ngram in language.ranks)
            overlap[code] = {
                "found": found,
                "missing": len(document.ranks) - found,
                "share": found / len(document.ranks) if document.ranks else 0.0,
            }
        return {
            "profile_size": len(document),
            "top": [
                {"feature": feature.replace(config.NGRAM_PAD, "␣"), "rank": rank, "weight": weight}
                for feature, rank, weight in document.top(15)
            ],
            "overlap": overlap,
        }
