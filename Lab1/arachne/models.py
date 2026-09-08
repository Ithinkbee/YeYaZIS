"""Сущности предметной области.

Состав классов повторяет диаграммы из методички (рис. 1-3): Document,
Search (см. search.py) и SearchResult.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Document:
    """Документ — основная сущность, над которой работает система (рис. 1)."""

    path: str
    uri: str
    host: str
    title: str
    text: str
    ext: str
    size_bytes: int = 0
    mtime: float = 0.0
    date_added: str = ""
    time_added: str = ""
    content_hash: str = ""
    term_count: int = 0
    vector_norm: float = 0.0
    document_id: int | None = None


@dataclass
class SearchResult:
    """Одна ссылка в поисковой выдаче (рис. 3)."""

    document_id: int
    title: str
    snippet: str
    rank: float
    date: str
    #: слова запроса, реально присутствующие в документе (требование методички)
    matched_words: list[str] = field(default_factory=list)
    uri: str = ""
    path: str = ""
    host: str = ""
    #: вклад отдельных терминов в ранг — для объяснения выдачи
    explanation: list[tuple[str, float]] = field(default_factory=list)


@dataclass
class QueryAnalysis:
    """Результат «понимания» естественно-языкового запроса системой."""

    raw: str
    tokens: list[str] = field(default_factory=list)
    lemmas: list[str] = field(default_factory=list)
    stopwords: list[str] = field(default_factory=list)
    #: [(словоформа, лемма, часть речи, есть ли в словаре системы)]
    morphology: list[dict] = field(default_factory=list)
    corrections: dict[str, str] = field(default_factory=dict)
    synonyms: dict[str, list[str]] = field(default_factory=dict)
    unknown: list[str] = field(default_factory=list)


@dataclass
class CrawlReport:
    """Итог обхода ЛВС пауком."""

    added: int = 0
    updated: int = 0
    skipped: int = 0
    removed: int = 0
    errors: int = 0
    files_seen: int = 0
    took_ms: float = 0.0
    messages: list[str] = field(default_factory=list)

    def merge(self, other: "CrawlReport") -> None:
        self.added += other.added
        self.updated += other.updated
        self.skipped += other.skipped
        self.removed += other.removed
        self.errors += other.errors
        self.files_seen += other.files_seen
        self.messages.extend(other.messages)
