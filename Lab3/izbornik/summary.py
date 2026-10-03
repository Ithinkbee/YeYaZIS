"""Построение реферата методом sentence extraction.

Одна и та же функция `build` вызывается в обоих режимах работы системы: в
локальном — из веб-интерфейса, в режиме OSTIS — из sc-агента, который прочитал
документ и коллекцию из базы знаний. Поэтому результат двух режимов обязан
совпадать, и это проверяется тестами.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import datetime

from izbornik import config, keywords as keywords_module, weights as w
from izbornik.keywords import KeywordSummary
from izbornik.text.analysis import AnalyzedDocument
from izbornik.text.compress import compress


@dataclass
class SummarySentence:
    index: int              # номер предложения в документе (с 0)
    paragraph: int          # номер абзаца (с 0)
    text: str
    compressed: str
    score: float            # Score(Sᵢ)
    posd: float             # Posd(Sᵢ)
    posp: float             # Posp(Sᵢ)
    weight: float           # Score · Posd · Posp
    rank: int               # место по весу среди всех предложений
    #: термины с наибольшим вкладом в Score: (вид термина, вклад)
    top_terms: list[tuple[str, float]] = field(default_factory=list)


@dataclass
class Summary:
    """Выходная информация системы по одному документу."""

    doc_id: str
    title: str
    language: str
    domain: str | None
    source_url: str | None
    requested: int                             # запрошенный размер реферата
    sentences: list[SummarySentence]           # предложения реферата в порядке текста
    keywords: KeywordSummary
    stats: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)  # этап -> мс
    engine: str = "local"                      # local | ostis
    ostis: dict | None = None                  # сведения о действии в базе знаний
    created: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @property
    def text(self) -> str:
        """Классический реферат одной строкой (исходные предложения)."""
        return " ".join(s.text for s in self.sentences)

    @property
    def compressed_text(self) -> str:
        return " ".join(s.compressed for s in self.sentences)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["keywords"] = self.keywords.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Summary":
        sentences = [
            SummarySentence(**{**s, "top_terms": [tuple(t) for t in s.get("top_terms", [])]})
            for s in data["sentences"]
        ]
        return cls(
            doc_id=data["doc_id"],
            title=data["title"],
            language=data["language"],
            domain=data.get("domain"),
            source_url=data.get("source_url"),
            requested=data.get("requested", len(sentences)),
            sentences=sentences,
            keywords=KeywordSummary.from_dict(data["keywords"]),
            stats=data.get("stats", {}),
            timings=data.get("timings", {}),
            engine=data.get("engine", "local"),
            ostis=data.get("ostis"),
            created=data.get("created", ""),
        )


@dataclass
class Result:
    """Реферат вместе с промежуточными данными — для разбора в интерфейсе."""

    summary: Summary
    document: AnalyzedDocument
    stats: w.CorpusStats
    term_weights: dict[str, w.TermWeight]
    scores: list[w.SentenceScore]
    ranks: dict[int, int]

    @property
    def selected(self) -> set[int]:
        return {s.index for s in self.summary.sentences}

    def top_terms(self, limit: int = 25) -> list[w.TermWeight]:
        return sorted(self.term_weights.values(), key=lambda t: (-t.weight, t.term))[:limit]


def build(
    document: AnalyzedDocument,
    stats: w.CorpusStats,
    count: int = config.SUMMARY_SENTENCES,
    *,
    domain: str | None = None,
    source_url: str | None = None,
    analysis_ms: float | None = None,
) -> Result:
    """Строит оба раздела реферата: классический и в виде ключевых слов."""
    timings: dict[str, float] = {}
    if analysis_ms is not None:
        timings["analysis"] = analysis_ms

    started = time.perf_counter()
    stats = stats.including(document)
    term_weights = w.term_weights(document, stats)
    timings["term_weights"] = _ms(started)

    started = time.perf_counter()
    scores = w.sentence_scores(document, term_weights)
    chosen = w.select(scores, count)
    ranks = w.ranks(scores)
    timings["sentences"] = _ms(started)

    started = time.perf_counter()
    keyword_summary = keywords_module.extract(document, term_weights)
    timings["keywords"] = _ms(started)

    sentences = []
    for index in chosen:
        sentence = document.layout.sentences[index]
        score = scores[index]
        top = sorted(score.contributions.items(), key=lambda item: (-item[1], item[0]))[:5]
        sentences.append(
            SummarySentence(
                index=index,
                paragraph=sentence.paragraph,
                text=sentence.text,
                compressed=compress(sentence.text, document.language) if config.COMPRESS_SENTENCES else sentence.text,
                score=score.score,
                posd=score.posd,
                posp=score.posp,
                weight=score.weight,
                rank=ranks[index],
                top_terms=[(document.show(term), value) for term, value in top],
            )
        )

    layout = document.layout
    summary_chars = sum(len(s.text) for s in sentences)
    summary = Summary(
        doc_id=document.doc_id,
        title=document.title,
        language=document.language,
        domain=domain,
        source_url=source_url,
        requested=count,
        sentences=sentences,
        keywords=keyword_summary,
        stats={
            "chars": layout.length,
            "paragraphs": sum(1 for p in layout.paragraphs if not p.heading),
            "headings": sum(1 for p in layout.paragraphs if p.heading),
            "sentences": len(layout.sentences),
            "words": document.words_total,
            "words_counted": document.words_counted,
            "terms": len(document.tf),
            "tf_max": document.tf_max,
            "db_docs": stats.n_docs,
            "idf_scope": stats.scope,
            "summary_chars": summary_chars,
            "compressed_chars": sum(len(s.compressed) for s in sentences),
            "compression": summary_chars / layout.length if layout.length else 0.0,
        },
        timings=timings,
    )
    return Result(summary, document, stats, term_weights, scores, ranks)


def _ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000
