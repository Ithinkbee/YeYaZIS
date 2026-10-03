"""Весовые коэффициенты терминов и предложений — формулы методички.

Вес термина (модифицированная функция TF·IDF):

    w(t, D) = 0,5 · (1 + tf(t, D) / tf_max(D)) · log(|DB| / df(t))

Оценка предложения по терминам:

    Score(Sᵢ) = Σ_{t ∈ Sᵢ} tf(t, Sᵢ) · w(t, D)

Положение предложения в документе и в абзаце:

    Posd(Sᵢ) = 1 − BD(Sᵢ) / |D|        Posp(Sᵢ) = 1 − BP(Sᵢ) / |P|

Вес предложения — произведение этих функций:

    Weight(Sᵢ) = Score(Sᵢ) · Posd(Sᵢ) · Posp(Sᵢ)

Логарифм натуральный. Основание на порядок предложений не влияет: оно
умножает все веса терминов на одно и то же число.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

from izbornik.text.analysis import AnalyzedDocument


@dataclass
class CorpusStats:
    """Статистика коллекции DB: число документов и документная частота df(t)."""

    n_docs: int
    df: Counter
    doc_ids: tuple[str, ...] = ()
    scope: str = "language"

    @classmethod
    def from_documents(cls, documents: Iterable[AnalyzedDocument], scope: str = "language") -> "CorpusStats":
        df: Counter = Counter()
        ids = []
        for document in documents:
            df.update(set(document.tf))
            ids.append(document.doc_id)
        return cls(n_docs=len(ids), df=df, doc_ids=tuple(ids), scope=scope)

    def including(self, document: AnalyzedDocument) -> "CorpusStats":
        """Статистика, в которой учтён и этот документ.

        Документ коллекции в ней уже есть. Новый документ (свой текст
        пользователя) добавляется: без этого у его собственных терминов df(t)
        было бы равно нулю и формула не имела бы смысла.
        """
        if document.doc_id and document.doc_id in self.doc_ids:
            return self
        df = self.df.copy()
        df.update(set(document.tf))
        return CorpusStats(self.n_docs + 1, df, self.doc_ids + (document.doc_id or "new",), self.scope)

    def idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        if df <= 0:
            return 0.0
        return math.log(self.n_docs / df)


@dataclass
class TermWeight:
    term: str
    display: str
    tf: int              # tf(t, D)
    df: int              # df(t)
    idf: float           # log(|DB| / df(t))
    weight: float        # w(t, D)


def term_weights(document: AnalyzedDocument, stats: CorpusStats) -> dict[str, TermWeight]:
    """w(t, D) для всех терминов документа."""
    tf_max = document.tf_max
    result: dict[str, TermWeight] = {}
    if not tf_max:
        return result
    for term, tf in document.tf.items():
        idf = stats.idf(term)
        weight = 0.5 * (1 + tf / tf_max) * idf
        result[term] = TermWeight(term, document.show(term), tf, stats.df.get(term, 0), idf, weight)
    return result


@dataclass
class SentenceScore:
    index: int
    score: float             # Score(Sᵢ)
    posd: float              # Posd(Sᵢ)
    posp: float              # Posp(Sᵢ)
    weight: float            # Score · Posd · Posp
    terms: int               # учтённых слов в предложении
    #: вклад терминов в Score: термин -> tf(t, Sᵢ) · w(t, D)
    contributions: dict[str, float] = field(default_factory=dict)


def sentence_scores(document: AnalyzedDocument, weights: dict[str, TermWeight]) -> list[SentenceScore]:
    layout = document.layout
    total = layout.length or 1
    scores: list[SentenceScore] = []
    for sentence, tokens in zip(layout.sentences, document.sentence_tokens):
        tf_s = Counter(token.term for token in tokens if token.counted)
        contributions = {
            term: count * weights[term].weight for term, count in tf_s.items() if term in weights
        }
        score = sum(contributions.values())
        paragraph = layout.paragraphs[sentence.paragraph]
        posd = 1 - sentence.start / total
        posp = 1 - sentence.start_in_paragraph / (paragraph.length or 1)
        scores.append(
            SentenceScore(
                index=sentence.index,
                score=score,
                posd=posd,
                posp=posp,
                weight=score * posd * posp,
                terms=sum(tf_s.values()),
                contributions=contributions,
            )
        )
    return scores


def select(scores: list[SentenceScore], count: int) -> list[int]:
    """Номера предложений реферата: count самых весомых — в порядке текста.

    При равном весе предпочтение отдаётся предложению, стоящему раньше: так
    результат не зависит от порядка сортировки.
    """
    ranked = sorted(scores, key=lambda s: (-s.weight, s.index))
    return sorted(s.index for s in ranked[: max(0, count)])


def ranks(scores: list[SentenceScore]) -> dict[int, int]:
    """Место каждого предложения по весу (1 — самое весомое)."""
    ranked = sorted(scores, key=lambda s: (-s.weight, s.index))
    return {s.index: position for position, s in enumerate(ranked, start=1)}
