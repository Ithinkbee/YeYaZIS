"""Тестовая коллекция: английские тексты по computer science и литературе."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from dragoman import config


@dataclass
class CatalogEntry:
    id: str
    file: str
    title: str
    domain: str
    chars: int = 0
    words: int = 0
    sections: list[str] = field(default_factory=list)
    source: dict = field(default_factory=dict)

    @property
    def source_url(self) -> str:
        return self.source.get("url", "")


class Collection:
    def __init__(self, catalog: Path | None = None, directory: Path | None = None) -> None:
        self.catalog_path = Path(catalog or config.CATALOG_PATH)
        self.directory = Path(directory or config.COLLECTION_DIR)
        self.entries: list[CatalogEntry] = []
        if self.catalog_path.exists():
            data = json.loads(self.catalog_path.read_text(encoding="utf-8"))
            for item in data.get("documents", []):
                self.entries.append(CatalogEntry(**item))

    def __iter__(self):
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def get(self, doc_id: str) -> CatalogEntry | None:
        return next((e for e in self.entries if e.id == doc_id), None)

    def text(self, doc_id: str) -> str:
        entry = self.get(doc_id)
        if entry is None:
            raise KeyError(doc_id)
        return (self.directory / entry.file).read_text(encoding="utf-8")

    def by_domain(self, domain: str) -> list[CatalogEntry]:
        return [e for e in self.entries if e.domain == domain]
