"""Тестовая коллекция документов и локальное реферирование.

Коллекция описана в data/catalog.json (см. tools/build_collection.py): для
каждого документа — файл с текстом, язык, предметная область, источник с
лицензией и эталон для оценки (реферат источника и ключевые слова авторов).
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from izbornik import config, summary as summary_module
from izbornik.text.analysis import AnalyzedDocument, analyze
from izbornik.weights import CorpusStats


@dataclass
class CatalogEntry:
    id: str
    file: str
    title: str
    language: str
    domain: str
    chars: int
    paragraphs: int
    source: dict = field(default_factory=dict)
    reference_abstract: str = ""
    reference_keywords: list[str] = field(default_factory=list)

    @property
    def path(self) -> Path:
        return config.COLLECTION_DIR / self.file

    @property
    def source_url(self) -> str:
        return self.source.get("url", "")

    @property
    def pages(self) -> float:
        return self.chars / config.PAGE_CHARS

    @property
    def group(self) -> str:
        return f"{self.language}-{self.domain}"


def detect_language(text: str) -> str:
    """Язык своего текста пользователя: у пары «русский — немецкий» разные алфавиты."""
    cyrillic = sum(1 for ch in text if "Ѐ" <= ch <= "ӿ")
    latin = sum(1 for ch in text if ch.isalpha() and ch.isascii() or ch in "äöüÄÖÜß")
    return "ru" if cyrillic >= latin else "de"


class Collection:
    """Документы коллекции, их разбор и статистика df по языкам.

    Разбор документа (сегментация и морфология) — самая долгая часть работы,
    поэтому он выполняется один раз и хранится в памяти.
    """

    def __init__(self, catalog_path: Path = config.CATALOG_PATH) -> None:
        self.catalog_path = catalog_path
        self.entries: list[CatalogEntry] = []
        self.meta: dict = {}
        self._analyzed: dict[str, AnalyzedDocument] = {}
        self._analysis_ms: dict[str, float] = {}
        self._stats: dict[tuple[str, str], CorpusStats] = {}
        self._lock = threading.RLock()
        self.load()

    def load(self) -> None:
        if not self.catalog_path.exists():
            self.entries = []
            return
        data = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        self.meta = {k: v for k, v in data.items() if k != "documents"}
        self.entries = [
            CatalogEntry(
                id=item["id"],
                file=item["file"],
                title=item["title"],
                language=item["language"],
                domain=item["domain"],
                chars=item.get("chars", 0),
                paragraphs=item.get("paragraphs", 0),
                source=item.get("source", {}),
                reference_abstract=item.get("reference", {}).get("abstract", ""),
                reference_keywords=item.get("reference", {}).get("keywords", []),
            )
            for item in data.get("documents", [])
        ]
        self._analyzed.clear()
        self._stats.clear()

    # -- доступ ---------------------------------------------------------------

    def __iter__(self):
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def get(self, doc_id: str) -> CatalogEntry | None:
        return next((e for e in self.entries if e.id == doc_id), None)

    def by_language(self, language: str) -> list[CatalogEntry]:
        return [e for e in self.entries if e.language == language]

    def text(self, doc_id: str) -> str:
        entry = self.get(doc_id)
        if entry is None:
            raise KeyError(doc_id)
        return entry.path.read_text(encoding="utf-8")

    # -- разбор и статистика ------------------------------------------------------

    def analyzed(self, doc_id: str) -> AnalyzedDocument:
        with self._lock:
            if doc_id not in self._analyzed:
                entry = self.get(doc_id)
                if entry is None:
                    raise KeyError(doc_id)
                started = time.perf_counter()
                self._analyzed[doc_id] = analyze(self.text(doc_id), entry.language, entry.id, entry.title)
                self._analysis_ms[doc_id] = (time.perf_counter() - started) * 1000
            return self._analyzed[doc_id]

    def analysis_ms(self, doc_id: str) -> float:
        self.analyzed(doc_id)
        return self._analysis_ms[doc_id]

    def stats(self, language: str, scope: str | None = None) -> CorpusStats:
        """|DB| и df(t): по документам языка или по всей коллекции (config.IDF_SCOPE)."""
        scope = scope or config.IDF_SCOPE
        key = (language if scope == "language" else "*", scope)
        with self._lock:
            if key not in self._stats:
                entries = self.by_language(language) if scope == "language" else self.entries
                self._stats[key] = CorpusStats.from_documents(
                    (self.analyzed(e.id) for e in entries), scope=scope
                )
            return self._stats[key]

    def warm_up(self) -> float:
        """Разбирает все документы заранее; возвращает затраченное время, мс."""
        started = time.perf_counter()
        for entry in self.entries:
            self.analyzed(entry.id)
        for language in config.LANGUAGE_CODES:
            self.stats(language)
        return (time.perf_counter() - started) * 1000

    # -- локальное реферирование -------------------------------------------------

    def summarize(self, doc_id: str, count: int = config.SUMMARY_SENTENCES,
                  scope: str | None = None) -> summary_module.Result:
        entry = self.get(doc_id)
        if entry is None:
            raise KeyError(doc_id)
        document = self.analyzed(doc_id)
        return summary_module.build(
            document,
            self.stats(entry.language, scope),
            count,
            domain=entry.domain,
            source_url=entry.source_url,
            analysis_ms=self._analysis_ms.get(doc_id),
        )

    def summarize_text(self, text: str, language: str | None = None, title: str = "",
                       count: int = config.SUMMARY_SENTENCES, doc_id: str = "",
                       scope: str | None = None) -> summary_module.Result:
        """Реферат своего текста пользователя; df берётся по коллекции того же языка."""
        language = language or detect_language(text)
        started = time.perf_counter()
        document = analyze(text, language, doc_id, title or "Свой текст")
        analysis_ms = (time.perf_counter() - started) * 1000
        return summary_module.build(document, self.stats(language, scope), count, analysis_ms=analysis_ms)
