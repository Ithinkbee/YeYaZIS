"""Сочинения по литературе: тексты, абзацы, объём, поиск слова.

Предметная область варианта — сочинения по литературе, поэтому операции
системы работают с ними: открыть сочинение, прочитать абзац вслух, найти
слово, назвать объём. Тексты лежат в data/essays, сведения о них — в
data/catalog.json. Абзацы разделены пустой строкой, заголовок раздела
начинается со знака «# ».

К сочинениям каталога во время работы добавляются надиктованные (см.
dictation.py): их текст хранится не в файле, а в самом объекте.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Iterator, Sequence

from sluhach import config
from sluhach.text import normalize, similarity

_WORD = re.compile(r"[^\W\d_]+")
#: возможный конец предложения: знак, за которым идёт слово с заглавной буквы
_BOUNDARY = re.compile(r"([.!?…]+[»“”\")]*)\s+(?=[«„“\"(]*[A-ZÄÖÜА-ЯЁ])")
#: сокращения, после которых точка предложение не заканчивает
_ABBREVIATIONS = {
    "ru": {"г", "гг", "в", "вв", "т", "тт", "д", "др", "пр", "см", "ср", "стр", "им", "ок", "тыс", "млн", "руб",
           "напр", "проф", "акад", "ул", "кн", "гл", "ч", "изд", "ред", "соч", "нач", "сер", "кон"},
    "de": {"bzw", "vgl", "ca", "nr", "dr", "prof", "hrsg", "bd", "jh", "jhd", "etc", "usw", "evtl", "ggf", "inkl",
           "str", "st", "chr", "geb", "gest", "sog", "zit", "aufl", "kap", "abs"},
}

#: слова, которые в просьбе «открой сочинение про …» названием не являются
_LOOKUP_SKIP = {
    "ru": {"про", "о", "об", "обо", "на", "тему", "сочинение", "сочинения", "сочинению", "сочинении",
           "текст", "роман", "книгу", "номер"},
    "de": {"ueber", "den", "der", "das", "die", "dem", "ein", "einen", "zum", "zu", "von", "im", "thema",
           "aufsatz", "text", "roman", "buch", "nummer"},
}
#: насколько слово просьбы должно быть похоже на слово названия: «онегина» —
#: «онегин», «душах» — «души»
_LOOKUP_WORD = 0.6


def _keeps_sentence(word: str, language: str) -> bool:
    """Точка после этого слова — не конец предложения."""
    word = word.strip("«„“\"(").lower()
    if len(word) == 1 and word.isalpha():           # инициал или «т. е.», „z. B.“
        return True
    if word.isdigit():
        # „im 19. Jahrhundert“, „1. Akt“, «1. Пункт» — порядковое числительное или
        # номер пункта; год в конце предложения („… im Jahr 1774. Der Roman …“) — нет
        return len(word) <= 2
    return word in _ABBREVIATIONS.get(language, ())


def sentences(text: str, language: str = "") -> list[str]:
    """Предложения абзаца.

    Точка заканчивает предложение, если за ней идёт заглавная буква и перед
    ней — не инициал, не сокращение и не порядковое числительное.
    """
    language = language or ("ru" if re.search("[а-яё]", text.lower()) else "de")
    parts, start = [], 0
    for found in _BOUNDARY.finditer(text):
        before = text[start:found.start()].split()
        if found.group(1).startswith(".") and before and _keeps_sentence(before[-1], language):
            continue
        parts.append(text[start:found.end(1)].strip())
        start = found.end()
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _same_word(a: str, b: str) -> float:
    """Сходство слова просьбы со словом названия с поправкой на падеж.

    «Чацкого» и «Чацкий» расходятся в трёх буквах из семи — по расстоянию
    Левенштейна это уже разные слова. Но начало у них общее, а отличается
    только окончание: такие слова считаются одним.
    """
    score = similarity(a, b)
    prefix = 0
    for left, right in zip(a, b):
        if left != right:
            break
        prefix += 1
    if prefix >= 4 and prefix >= 0.6 * min(len(a), len(b)):
        score = max(score, 0.75)
    return score


def stem(word: str) -> str:
    """Основа для поиска словоформ: длинное слово ищется без окончания."""
    cut = 2 if len(word) >= 7 else 1 if len(word) >= 5 else 0
    return word[:len(word) - cut]


@dataclass(frozen=True)
class Paragraph:
    index: int                 # номер абзаца в сочинении, с нуля
    text: str
    section: str               # заголовок раздела, в который входит абзац
    opens_section: bool        # первый абзац своего раздела


@dataclass(frozen=True)
class Stats:
    paragraphs: int
    sections: int
    sentences: int
    words: int
    chars: int


@dataclass(frozen=True)
class Occurrences:
    """Где в сочинении встречается слово."""

    word: str
    count: int
    paragraphs: tuple[int, ...]        # номера абзацев по порядку, без повторов
    forms: tuple[str, ...]             # словоформы, как они записаны в тексте

    def nearest(self, paragraph: int) -> int | None:
        """Ближайший абзац со словом — начиная с текущего, по кругу."""
        if not self.paragraphs:
            return None
        return next((p for p in self.paragraphs if p >= paragraph), self.paragraphs[0])


@dataclass
class Essay:
    id: str
    language: str
    title: str
    author: str
    year: str
    about: str                 # что это за произведение — на языке сочинения
    about_ru: str              # то же по-русски (для немецких сочинений)
    title_ru: str
    aliases: tuple[str, ...]
    path: Path
    source: dict
    text: str | None = None    # текст надиктованного сочинения; у сочинений каталога он в файле
    dictated: bool = False
    created: str = ""          # когда надиктовано

    @cached_property
    def paragraphs(self) -> tuple[Paragraph, ...]:
        raw = self.text if self.text is not None else self.path.read_text(encoding="utf-8")
        blocks = [block.strip() for block in re.split(r"\n\s*\n", raw)]
        result: list[Paragraph] = []
        section, fresh = "", False
        for block in blocks:
            if not block:
                continue
            if block.startswith("#"):
                section, fresh = block.lstrip("# ").strip(), True
                continue
            result.append(Paragraph(len(result), " ".join(block.split()), section, fresh))
            fresh = False
        return tuple(result)

    @cached_property
    def stats(self) -> Stats:
        paragraphs = self.paragraphs
        return Stats(
            paragraphs=len(paragraphs),
            sections=sum(1 for p in paragraphs if p.opens_section),
            sentences=sum(len(sentences(p.text, self.language)) for p in paragraphs),
            words=sum(len(_WORD.findall(p.text)) for p in paragraphs),
            chars=sum(len(p.text) for p in paragraphs),
        )

    def find(self, word: str) -> Occurrences:
        """Все вхождения слова в любой его форме: ищется основа («дуэл» — дуэль, дуэли)."""
        base = stem(normalize(word).replace(" ", ""))
        if not base:
            return Occurrences(word, 0, (), ())
        count, where, forms = 0, [], {}
        for paragraph in self.paragraphs:
            for form in _WORD.findall(paragraph.text):
                if normalize(form).startswith(base):
                    count += 1
                    forms.setdefault(form, None)
                    if not where or where[-1] != paragraph.index:
                        where.append(paragraph.index)
        return Occurrences(word, count, tuple(where), tuple(forms))

    def summary(self) -> dict:
        """Сведения о сочинении для списка на странице."""
        stats = self.stats
        return {"id": self.id, "language": self.language, "title": self.title, "title_ru": self.title_ru,
                "author": self.author, "year": self.year, "about": self.about, "about_ru": self.about_ru,
                "paragraphs": stats.paragraphs, "words": stats.words, "source": self.source,
                "dictated": self.dictated, "created": self.created}

    def content(self) -> dict:
        """Сочинение целиком: абзацы с заголовками разделов."""
        return {**self.summary(), "sentences": self.stats.sentences,
                "items": [{"index": p.index, "text": p.text, "section": p.section if p.opens_section else ""}
                          for p in self.paragraphs]}


class Collection:
    """Сочинения по литературе на языках варианта."""

    def __init__(self, catalog: Path | None = None, directory: Path | None = None) -> None:
        catalog = catalog or config.CATALOG_PATH
        directory = directory or config.ESSAYS_DIR
        try:
            data = json.loads(catalog.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        self.note: str = data.get("note", "")
        self.essays: list[Essay] = []
        for item in data.get("essays", []):
            path = directory / item["file"]
            if not path.exists():
                continue
            self.essays.append(Essay(
                id=item["id"], language=item["language"], title=item["title"], author=item.get("author", ""),
                year=str(item.get("year", "")), about=item.get("about", ""),
                about_ru=item.get("about_ru", "") or item.get("about", ""),
                title_ru=item.get("title_ru", "") or item["title"],
                aliases=tuple(item.get("aliases") or [item["title"]]), path=path, source=item.get("source", {}),
            ))
        self._by_id = {essay.id: essay for essay in self.essays}

    def __iter__(self) -> Iterator[Essay]:
        return iter(self.essays)

    def __len__(self) -> int:
        return len(self.essays)

    def get(self, essay_id: str | None) -> Essay | None:
        return self._by_id.get(essay_id or "")

    def add(self, essay: Essay) -> None:
        """Добавляет сочинение в конец списка; сочинение с тем же идентификатором заменяется на месте."""
        if essay.id in self._by_id:
            self.essays = [essay if item.id == essay.id else item for item in self.essays]
        else:
            self.essays = [*self.essays, essay]
        self._by_id[essay.id] = essay

    def remove(self, essay_id: str) -> Essay | None:
        essay = self._by_id.pop(essay_id, None)
        if essay is not None:
            self.essays = [item for item in self.essays if item.id != essay_id]
        return essay

    def by_language(self, language: str) -> list[Essay]:
        return [essay for essay in self.essays if essay.language == language]

    def number(self, essay: Essay) -> int:
        """Номер сочинения в списке своего языка, с единицы."""
        return self.by_language(essay.language).index(essay) + 1

    def by_number(self, language: str, number: int) -> Essay | None:
        essays = self.by_language(language)
        return essays[number - 1] if 1 <= number <= len(essays) else None

    def neighbour(self, essay: Essay, step: int) -> Essay | None:
        return self.by_number(essay.language, self.number(essay) + step)

    def lookup(self, words: Sequence[str], language: str) -> Essay | None:
        """Сочинение по словам названия, героя или автора: «про онегина», „über Kafka“.

        Слова должны быть нормализованы. Каждое слово известного названия
        ищется среди слов просьбы с допуском на падеж и ошибку распознавания;
        побеждает название, совпавшее лучше и полнее.
        """
        skip = _LOOKUP_SKIP.get(language, set())
        query = [word for word in words if word not in skip]
        if not query:
            return None
        best, best_score = None, 0.0
        for essay in self.by_language(language):
            for alias in essay.aliases:
                wanted = [word for word in normalize(alias).split() if word not in skip]
                if not wanted:
                    continue
                found = [max(_same_word(word, other) for other in query) for word in wanted]
                if min(found) < _LOOKUP_WORD:
                    continue
                score = sum(found) / len(found) + 0.05 * (len(wanted) - 1)
                if score > best_score:
                    best, best_score = essay, score
        return best
