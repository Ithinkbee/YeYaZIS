"""Научные статьи по computer science на немецком — тексты для чтения вслух.

Пять статей немецкой Википедии (CC BY-SA 4.0) — те же, что в коллекции
работы № 3: компилятор, операционная система, искусственная нейронная сеть,
информационная безопасность, семантическая паутина. В них есть всё, что
затрудняет синтез: годы и числа, сокращения («z. B.», «d. h.»),
аббревиатуры («RDF», «CPU», «KNN»), английские термины, формулы, ссылки.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from glashatai import config


@dataclass
class Article:
    id: str
    title: str
    title_ru: str
    text: str
    source: dict

    @property
    def words(self) -> int:
        return len(re.findall(r"\w+", self.text))

    @property
    def sections(self) -> list[str]:
        return [line[2:].strip() for line in self.text.splitlines() if line.startswith("# ")]

    @property
    def minutes(self) -> float:
        """Время чтения вслух при обычном темпе (около 150 слов в минуту)."""
        return self.words / 150

    def summary(self) -> dict:
        return {"id": self.id, "title": self.title, "title_ru": self.title_ru, "words": self.words,
                "sections": len(self.sections), "minutes": round(self.minutes, 1), "source": self.source}


class Collection:
    def __init__(self, directory: Path | None = None, catalog: Path | None = None) -> None:
        self.directory = directory or config.ARTICLES_DIR
        self.catalog = catalog or config.CATALOG_PATH
        self.articles: list[Article] = []
        self.load()

    def load(self) -> None:
        try:
            entries = json.loads(self.catalog.read_text(encoding="utf-8")).get("articles", [])
        except (OSError, ValueError):
            entries = []
        found = []
        for entry in entries:
            path = self.directory / entry["file"]
            try:
                text = path.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            found.append(Article(entry["id"], entry["title"], entry.get("title_ru", ""), text,
                                 entry.get("source", {})))
        self.articles = found

    def get(self, article_id: str) -> Article | None:
        return next((a for a in self.articles if a.id == article_id), None)

    def __len__(self) -> int:
        return len(self.articles)

    def __iter__(self):
        return iter(self.articles)
