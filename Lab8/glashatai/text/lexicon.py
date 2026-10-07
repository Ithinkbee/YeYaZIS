"""Словари произношения: встроенные и словарь пользователя.

Встроенные словари лежат в data/pronunciation:

* abbreviations.tsv — сокращения и их полные формы («z. B.» — „zum Beispiel“);
* acronyms.tsv — аббревиатуры и имена, которые читаются не по буквам
  («RAM» — „Ramm“, «JSON» — „Dschäison“, «LaTeX» — „Latech“);
* english.tsv — английские термины и их запись немецкими буквами
  («Software» — „Softwär“, «Machine Learning» — „Mäschien Lörning“).

Словарь пользователя — data/lexicon.json; его пишет страница «Словарь».
Слово из словаря пользователя важнее любого правила: если пользователь
записал, что «GitLab» читается „Gitt Läbb“, так и будет.

Запись произношения — немецкими буквами, как слово звучало бы по немецким
правилам чтения. Апостроф перед слогом отмечает ударение; его понимает
собственный синтезатор системы, остальным он не передаётся.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from glashatai import config

WORD_CHARS = "A-Za-zÄÖÜäöüßÀ-ÿ"


@dataclass(frozen=True)
class Abbreviation:
    written: str            # «z. B.»
    expansion: str          # «zum Beispiel»
    when: str = "any"       # any | number | after | end

    @property
    def pattern(self) -> str:
        """Регулярное выражение: пробелы внутри необязательны, «z.B.» тоже узнаётся."""
        parts = [re.escape(part) for part in self.written.split(" ")]
        return r"\s?".join(parts)


@dataclass(frozen=True)
class Entry:
    """Слово или сочетание и как оно звучит."""
    written: str            # «Machine Learning»
    reading: str            # «Mä'schien 'Lörning»
    kind: str = "english"   # english | acronym | user
    compound: bool = False  # бывает частью немецкого сложного слова
    id: str = ""

    @property
    def plain(self) -> str:
        """Запись без отметок ударения — её получают внешние синтезаторы."""
        return self.reading.replace("'", "")

    def to_dict(self) -> dict:
        return {"id": self.id, "written": self.written, "reading": self.reading, "kind": self.kind,
                "compound": self.compound}


def _rows(path: Path) -> list[list[str]]:
    rows = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines:
        if not line.strip() or line.startswith("#"):
            continue
        rows.append([cell.strip() for cell in line.split("\t")])
    return rows


def load_abbreviations(path: Path | None = None) -> list[Abbreviation]:
    path = path or config.PRONUNCIATION_DIR / "abbreviations.tsv"
    found = [Abbreviation(row[0], row[1], row[2] if len(row) > 2 else "any") for row in _rows(path) if len(row) >= 2]
    # длинные — первыми: «u. v. m.» раньше «u.»
    return sorted(found, key=lambda item: -len(item.written))


def load_entries(path: Path, kind: str) -> list[Entry]:
    entries = []
    for row in _rows(path):
        if len(row) < 2:
            continue
        flags = row[2] if len(row) > 2 else ""
        entries.append(Entry(row[0], row[1], kind, "c" in flags))
    return entries


# --- словарь пользователя ------------------------------------------------------------

MAX_USER_ENTRIES = 500
MAX_WRITTEN_CHARS = 60
MAX_READING_CHARS = 120


class LexiconError(ValueError):
    pass


class UserLexicon:
    """Слова, произношение которых задал пользователь; хранятся в data/lexicon.json."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config.LEXICON_PATH
        self._lock = threading.Lock()
        self._entries: list[Entry] = []
        self.version = 0
        self.load()

    def load(self) -> None:
        entries: list[Entry] = []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        for item in raw.get("entries", []) if isinstance(raw, dict) else []:
            try:
                entries.append(Entry(str(item["written"]), str(item["reading"]), "user", False,
                                     str(item.get("id") or uuid.uuid4().hex[:8])))
            except (KeyError, TypeError):
                continue
        with self._lock:
            self._entries = entries
            self.version += 1

    def all(self) -> list[Entry]:
        with self._lock:
            return list(self._entries)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"saved": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "entries": [{"id": e.id, "written": e.written, "reading": e.reading} for e in self._entries]}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    @staticmethod
    def _clean(written: str, reading: str) -> tuple[str, str]:
        written = " ".join(str(written or "").split())
        reading = " ".join(str(reading or "").split())
        if not written:
            raise LexiconError("Впишите слово или сочетание, как оно пишется в тексте.")
        if not reading:
            raise LexiconError("Впишите, как слово читается — немецкими буквами.")
        if len(written) > MAX_WRITTEN_CHARS or len(reading) > MAX_READING_CHARS:
            raise LexiconError(f"Слово — до {MAX_WRITTEN_CHARS} знаков, чтение — до {MAX_READING_CHARS}.")
        if not re.search(r"\w", written):
            raise LexiconError("В слове должна быть хоть одна буква или цифра.")
        if not re.fullmatch(rf"[{WORD_CHARS}' \-]+", reading):
            raise LexiconError("Чтение записывается буквами; апостроф ставится перед ударным слогом.")
        return written, reading

    def add(self, written: str, reading: str) -> Entry:
        written, reading = self._clean(written, reading)
        with self._lock:
            if len(self._entries) >= MAX_USER_ENTRIES:
                raise LexiconError(f"В словаре уже {MAX_USER_ENTRIES} слов — больше не помещается.")
            if any(e.written.lower() == written.lower() for e in self._entries):
                raise LexiconError(f"«{written}» уже есть в словаре — исправьте его строку.")
            entry = Entry(written, reading, "user", False, uuid.uuid4().hex[:8])
            self._entries.append(entry)
            self._save()
            self.version += 1
            return entry

    def update(self, entry_id: str, written: str, reading: str) -> Entry:
        written, reading = self._clean(written, reading)
        with self._lock:
            for index, entry in enumerate(self._entries):
                if entry.id == entry_id:
                    if any(e.id != entry_id and e.written.lower() == written.lower() for e in self._entries):
                        raise LexiconError(f"«{written}» уже есть в словаре.")
                    self._entries[index] = Entry(written, reading, "user", False, entry_id)
                    self._save()
                    self.version += 1
                    return self._entries[index]
        raise LexiconError("Такого слова в словаре нет.")

    def remove(self, entry_id: str) -> bool:
        with self._lock:
            kept = [e for e in self._entries if e.id != entry_id]
            if len(kept) == len(self._entries):
                return False
            self._entries = kept
            self._save()
            self.version += 1
            return True

    def clear(self) -> None:
        with self._lock:
            self._entries = []
            self.path.unlink(missing_ok=True)
            self.version += 1


@dataclass
class Lexicon:
    """Все словари вместе: то, к чему обращается разбор текста."""
    abbreviations: list[Abbreviation] = field(default_factory=load_abbreviations)
    acronyms: list[Entry] = field(default_factory=lambda: load_entries(config.PRONUNCIATION_DIR / "acronyms.tsv", "acronym"))
    english: list[Entry] = field(default_factory=lambda: load_entries(config.PRONUNCIATION_DIR / "english.tsv", "english"))
    user: UserLexicon | None = None

    def __post_init__(self) -> None:
        self._acronyms = {entry.written: entry for entry in self.acronyms}
        self._english = {entry.written.lower(): entry for entry in self.english}
        self._english_phrases = sorted((e for e in self.english if " " in e.written or "-" in e.written),
                                       key=lambda e: -len(e.written))
        self._compound = sorted((e for e in self.english if e.compound and " " not in e.written),
                                key=lambda e: -len(e.written))

    def acronym(self, written: str) -> Entry | None:
        return self._acronyms.get(written)

    def english_word(self, written: str) -> Entry | None:
        return self._english.get(written.lower())

    def english_phrases(self) -> list[Entry]:
        return self._english_phrases

    def compound_part(self, word: str) -> tuple[Entry, str, str] | None:
        """Английский термин в начале или в конце немецкого сложного слова.

        «Softwareentwicklung» -> (Software, «», «entwicklung»);
        «Quellcode» -> (Code, «Quell», «»). Оставшаяся часть должна быть не
        короче четырёх букв (трёх — перед термином): иначе «Webs» или
        «Coder» разбирались бы как сложные слова.
        """
        lower = word.lower()
        for entry in self._compound:
            term = entry.written.lower()
            if len(lower) <= len(term):
                continue
            if lower.startswith(term) and len(lower) - len(term) >= 4:
                rest = word[len(term):]
                if rest[0].islower() or rest[0] in "-":
                    return entry, "", rest.lstrip("-")
            if lower.endswith(term) and len(lower) - len(term) >= 3:
                head = word[: len(word) - len(term)]
                return entry, head.rstrip("-"), ""
        return None

    def user_entries(self) -> list[Entry]:
        return self.user.all() if self.user else []

    @property
    def version(self) -> int:
        return self.user.version if self.user else 0
