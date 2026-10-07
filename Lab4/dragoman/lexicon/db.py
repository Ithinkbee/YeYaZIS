"""Англо-немецкий словарь системы — таблица базы данных SQLite.

Запись словаря — английское слово или оборот, часть речи, немецкий перевод и
грамматические сведения о нём: род и множественное число существительного,
отделяемая приставка и управление глагола, падеж после предлога. Запись может
относиться к предметной области (cs — computer science, lit — литература) или
быть общей (gen); при переводе предпочтение отдаётся записи своей области:
«character» в статье о романе — «Figur», в статье о кодировках — «Zeichen».

Исходный словарь хранится в текстовых таблицах data/lexicon/*.tsv (столбцы:
en, pos, de, gender, plural, extra, domain) и при первом запуске загружается в
базу. Правки пользователя живут в базе: исправленная или удалённая запись
исходного словаря при следующей загрузке не восстанавливается.

Обозначения в немецком переводе:

* «vor|stellen» — отделяемая приставка (stellt … vor, vorgestellt);
* «sich befassen» — возвратный глагол;
* «in Betracht ziehen» — глагол с неизменяемой частью (zieht … in Betracht);
* «neuronal* Netz» — прилагательное, которое склоняется вместе с существительным;
* «Stand~ der Technik» — склоняемое слово сочетания, если оно не последнее.

Поле extra — пары «ключ=значение» через «;»: prep=von+D (управление), obj=D
(дополнение в дательном падеже), case=A (падеж после предлога), aux=sein,
weak (слабое склонение), gen=Namens, cf=Sprach (форма в составе сложного
слова), comp=besser,best (неправильные степени сравнения), sub (союз
подчинительный: глагол в конец).
"""

from __future__ import annotations

import csv
import hashlib
import io
import sqlite3
import threading
from collections import defaultdict
from dataclasses import dataclass, fields
from datetime import datetime
from functools import cached_property
from pathlib import Path

from dragoman import config

COLUMNS = ("en", "pos", "de", "gender", "plural", "extra", "domain")
POS_NAMES = {
    "NOUN": "существительное", "PROPN": "имя собственное", "VERB": "глагол", "ADJ": "прилагательное",
    "ADV": "наречие", "ADP": "предлог", "SCONJ": "подчинительный союз", "CCONJ": "сочинительный союз",
    "DET": "определитель", "PRON": "местоимение", "NUM": "числительное", "PART": "частица",
    "INTJ": "междометие",
}
SOURCES = {"seed": "исходный словарь", "user": "правка пользователя", "ding": "словарь Ding",
           "rule": "правило словообразования"}

#: в каком порядке искать записи при неуверенной части речи
FALLBACK = {
    "NOUN": ("NOUN", "PROPN"),
    "PROPN": ("PROPN", "NOUN"),
    "VERB": ("VERB",),
    "AUX": ("VERB",),
    "ADJ": ("ADJ",),
    "ADV": ("ADV", "ADP", "PART"),
    "ADP": ("ADP", "SCONJ", "ADV"),
    "SCONJ": ("SCONJ", "ADP"),
    "CCONJ": ("CCONJ",),
    "DET": ("DET", "PRON"),
    "PRON": ("PRON", "DET"),
    "NUM": ("NUM",),
    "PART": ("PART", "ADV"),
    "INTJ": ("INTJ",),
    "X": ("ADV", "NOUN"),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    en TEXT NOT NULL,
    pos TEXT NOT NULL,
    de TEXT NOT NULL,
    gender TEXT NOT NULL DEFAULT '',
    plural TEXT NOT NULL DEFAULT '',
    extra TEXT NOT NULL DEFAULT '',
    domain TEXT NOT NULL DEFAULT 'gen',
    source TEXT NOT NULL DEFAULT 'seed',
    rank INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    updated TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS entries_en ON entries(en, pos);
CREATE INDEX IF NOT EXISTS entries_source ON entries(source);
CREATE TABLE IF NOT EXISTS overrides (
    en TEXT NOT NULL, pos TEXT NOT NULL, domain TEXT NOT NULL,
    PRIMARY KEY (en, pos, domain)
);
CREATE TABLE IF NOT EXISTS unknown (
    en TEXT NOT NULL,
    pos TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    texts INTEGER NOT NULL DEFAULT 0,
    example TEXT NOT NULL DEFAULT '',
    first_seen TEXT NOT NULL DEFAULT '',
    last_seen TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (en, pos)
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


@dataclass
class Entry:
    en: str
    pos: str
    de: str
    gender: str = ""
    plural: str = ""
    extra: str = ""
    domain: str = config.GENERAL_DOMAIN
    source: str = "seed"
    rank: int = 0
    note: str = ""
    updated: str = ""
    id: int | None = None
    #: уверенность догадки (для записей, выведенных правилами)
    confidence: float = 1.0

    @cached_property
    def props(self) -> dict[str, str]:
        result = {}
        for item in self.extra.split(";"):
            item = item.strip()
            if not item:
                continue
            key, _, value = item.partition("=")
            result[key.strip()] = value.strip() or "1"
        return result

    @property
    def words(self) -> list[str]:
        return self.en.split()

    @property
    def is_phrase(self) -> bool:
        return " " in self.en

    @property
    def lemma(self) -> str:
        """Немецкое слово без служебных пометок."""
        return clean(self.de)

    @property
    def plural_form(self) -> str:
        if self.gender == "pl":
            return clean(self.de)
        if self.plural == "-":
            return ""
        return self.plural

    @property
    def display(self) -> str:
        """Немецкий перевод для списков: «das Netz, -e» — с артиклем и мн. ч."""
        word = clean(self.de)
        if self.pos in {"NOUN", "PROPN"} and self.gender in {"m", "f", "n"}:
            article = {"m": "der", "f": "die", "n": "das"}[self.gender]
            text = f"{article} {word}"
            if self.plural and self.plural != "-":
                text += f" (мн. ч. {self.plural})"
            return text
        if self.pos in {"NOUN", "PROPN"} and self.gender == "pl":
            return f"die {word} (мн. ч.)"
        return word

    def as_row(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name != "confidence"}


def clean(german: str) -> str:
    """«vor|stellen» → «vorstellen», «neuronal* Netz» → «neuronal Netz»."""
    return german.replace("|", "").replace("*", "").replace("~", "")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_tsv(path: Path) -> list[Entry]:
    """Записи из текстовой таблицы; строки с «#» — комментарии, порядок строк — приоритет."""
    entries = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cells = line.split("\t")
        if len(cells) < 3:
            raise ValueError(f"{path.name}, строка {number}: нужно хотя бы три столбца — en, pos, de")
        cells += [""] * (len(COLUMNS) - len(cells))
        en, pos, de, gender, plural, extra, domain = (c.strip() for c in cells[:7])
        entries.append(Entry(en, pos.upper(), de, gender, plural, extra, domain or config.GENERAL_DOMAIN,
                             rank=number))
    return entries


class Lexicon:
    """Словарь в базе данных с кэшем в памяти."""

    def __init__(self, path: Path | None = None, seed_dir: Path | None = None) -> None:
        self.path = Path(path or config.DICTIONARY_DB)
        self.seed_dir = Path(seed_dir or config.LEXICON_DIR)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self.version = 0
        self._index: dict[tuple[str, str], list[Entry]] = {}
        self._words: set[str] = set()
        self._phrases: dict[str, list[Entry]] = {}
        self.seed()
        self._reload()

    # --- загрузка исходного словаря -------------------------------------------------

    def _seed_files(self) -> list[Path]:
        return sorted(self.seed_dir.glob("*.tsv")) if self.seed_dir.exists() else []

    def seed_hash(self) -> str:
        digest = hashlib.sha1()
        for path in self._seed_files():
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
        return digest.hexdigest()

    def seed(self, force: bool = False) -> int:
        """Загружает data/lexicon/*.tsv, если таблицы изменились. Возвращает число записей."""
        current = self.seed_hash()
        with self._lock:
            stored = self._db.execute("SELECT value FROM meta WHERE key='seed_hash'").fetchone()
            if stored and stored[0] == current and not force:
                return 0
            overridden = {(r["en"], r["pos"], r["domain"]) for r in self._db.execute("SELECT * FROM overrides")}
            self._db.execute("DELETE FROM entries WHERE source='seed'")
            count = 0
            offset = 0
            for path in self._seed_files():
                for entry in read_tsv(path):
                    if (entry.en, entry.pos, entry.domain) in overridden:
                        continue
                    self._db.execute(
                        "INSERT INTO entries (en, pos, de, gender, plural, extra, domain, source, rank, updated) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, 'seed', ?, ?)",
                        (entry.en, entry.pos, entry.de, entry.gender, entry.plural, entry.extra, entry.domain,
                         offset + entry.rank, ""))
                    count += 1
                offset += 100_000
            self._db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('seed_hash', ?)", (current,))
            self._db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('seeded', ?)", (_now(),))
            self._db.commit()
            self._reload()
            return count

    def _reload(self) -> None:
        index: dict[tuple[str, str], list[Entry]] = defaultdict(list)
        phrases: dict[str, list[Entry]] = defaultdict(list)
        rows = self._db.execute("SELECT * FROM entries ORDER BY rank, id").fetchall()
        for row in rows:
            entry = self._entry(row)
            index[(entry.en.lower(), entry.pos)].append(entry)
            if entry.is_phrase:
                phrases[entry.words[0].lower()].append(entry)
        for items in phrases.values():
            items.sort(key=lambda e: -len(e.words))
        self._index = dict(index)
        self._words = {word for word, _ in index}
        self._phrases = dict(phrases)
        self.version += 1
        from dragoman.german import morphology

        morphology.KNOWN_VERBS.update(
            clean(e.de).removeprefix("sich ").split()[-1] for items in index.values() for e in items
            if e.pos == "VERB" and e.de)

    @staticmethod
    def _entry(row: sqlite3.Row) -> Entry:
        return Entry(row["en"], row["pos"], row["de"], row["gender"], row["plural"], row["extra"], row["domain"],
                     row["source"], row["rank"], row["note"], row["updated"], row["id"])

    # --- поиск ------------------------------------------------------------------------

    def lookup(self, en: str, pos: str, domain: str | None = None, strict: bool = False) -> list[Entry]:
        """Записи для слова и части речи; своя предметная область — первой."""
        key = en.lower()
        found: list[Entry] = []
        for candidate in (FALLBACK.get(pos, (pos,)) if not strict else (pos,)):
            found = list(self._index.get((key, candidate), ()))
            if found:
                break
        if not found:
            return []

        def order(entry: Entry) -> tuple[int, int]:
            if domain and entry.domain == domain:
                place = 0
            elif entry.domain == config.GENERAL_DOMAIN:
                place = 1
            else:
                place = 2
            # правка пользователя важнее исходного словаря
            return place, (0 if entry.source == "user" else 1), entry.rank

        return sorted(found, key=order)

    def best(self, en: str, pos: str, domain: str | None = None, strict: bool = False) -> Entry | None:
        found = self.lookup(en, pos, domain, strict)
        return found[0] if found else None

    def knows(self, en: str) -> bool:
        """Есть ли слово в словаре под какой-нибудь частью речи."""
        return en.lower() in self._words

    def any_pos(self, en: str, domain: str | None = None) -> list[Entry]:
        result = []
        for (word, pos), items in self._index.items():
            if word == en.lower():
                result.extend(items)
        return sorted(result, key=lambda e: (0 if e.domain == domain else 1, e.rank))

    def phrases_from(self, word: str) -> list[Entry]:
        """Обороты, которые начинаются с этого слова, — длинные первыми."""
        return self._phrases.get(word.lower(), [])

    def has(self, en: str, pos: str) -> bool:
        return bool(self.lookup(en, pos))

    def __len__(self) -> int:
        return sum(len(v) for v in self._index.values())

    # --- правка -------------------------------------------------------------------------

    def get(self, entry_id: int) -> Entry | None:
        row = self._db.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
        return self._entry(row) if row else None

    def add(self, entry: Entry, source: str = "user") -> Entry:
        with self._lock:
            rank = self._db.execute("SELECT COALESCE(MIN(rank), 0) FROM entries WHERE lower(en)=? AND pos=?",
                                    (entry.en.lower(), entry.pos)).fetchone()[0]
            cursor = self._db.execute(
                "INSERT INTO entries (en, pos, de, gender, plural, extra, domain, source, rank, note, updated) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (entry.en.strip(), entry.pos, entry.de.strip(), entry.gender, entry.plural, entry.extra,
                 entry.domain or config.GENERAL_DOMAIN, source, rank - 1 if source == "user" else rank + 1,
                 entry.note, _now()))
            self._db.execute("DELETE FROM unknown WHERE lower(en)=?", (entry.en.lower(),))
            self._db.commit()
            self._reload()
            return self.get(cursor.lastrowid)

    def update(self, entry_id: int, values: dict) -> Entry | None:
        with self._lock:
            current = self.get(entry_id)
            if current is None:
                return None
            if current.source == "seed":
                self._db.execute("INSERT OR IGNORE INTO overrides (en, pos, domain) VALUES (?, ?, ?)",
                                 (current.en, current.pos, current.domain))
            allowed = {k: str(v).strip() for k, v in values.items() if k in COLUMNS or k == "note"}
            allowed["source"] = "user"
            allowed["updated"] = _now()
            assignments = ", ".join(f"{k}=?" for k in allowed)
            self._db.execute(f"UPDATE entries SET {assignments} WHERE id=?", (*allowed.values(), entry_id))
            self._db.commit()
            self._reload()
            return self.get(entry_id)

    def delete(self, entry_id: int) -> bool:
        with self._lock:
            current = self.get(entry_id)
            if current is None:
                return False
            if current.source == "seed":
                self._db.execute("INSERT OR IGNORE INTO overrides (en, pos, domain) VALUES (?, ?, ?)",
                                 (current.en, current.pos, current.domain))
            self._db.execute("DELETE FROM entries WHERE id=?", (entry_id,))
            self._db.commit()
            self._reload()
            return True

    def reset(self) -> int:
        """Убирает все правки пользователя и пополнения, возвращает исходный словарь."""
        with self._lock:
            self._db.execute("DELETE FROM entries WHERE source != 'seed'")
            self._db.execute("DELETE FROM overrides")
            self._db.commit()
            return self.seed(force=True)

    # --- просмотр ---------------------------------------------------------------------------

    def search(self, query: str = "", pos: str = "", source: str = "", domain: str = "",
               limit: int = 100, offset: int = 0) -> tuple[list[Entry], int]:
        where, params = [], []
        if query:
            where.append("(lower(en) LIKE ? OR lower(de) LIKE ?)")
            like = f"%{query.lower()}%"
            params += [like, like]
        if pos:
            where.append("pos=?")
            params.append(pos)
        if source:
            where.append("source=?")
            params.append(source)
        if domain:
            where.append("domain=?")
            params.append(domain)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        total = self._db.execute(f"SELECT COUNT(*) FROM entries {clause}", params).fetchone()[0]
        order = "CASE WHEN lower(en)=? THEN 0 WHEN lower(en) LIKE ? THEN 1 ELSE 2 END, lower(en), rank" \
            if query else "lower(en), rank"
        extra = [query.lower(), f"{query.lower()}%"] if query else []
        rows = self._db.execute(f"SELECT * FROM entries {clause} ORDER BY {order} LIMIT ? OFFSET ?",
                                (*params, *extra, limit, offset)).fetchall()
        return [self._entry(r) for r in rows], total

    def stats(self) -> dict:
        by_pos = dict(self._db.execute("SELECT pos, COUNT(*) FROM entries GROUP BY pos ORDER BY COUNT(*) DESC"))
        by_source = dict(self._db.execute("SELECT source, COUNT(*) FROM entries GROUP BY source"))
        by_domain = dict(self._db.execute("SELECT domain, COUNT(*) FROM entries GROUP BY domain"))
        total = self._db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        words = self._db.execute("SELECT COUNT(DISTINCT lower(en)) FROM entries").fetchone()[0]
        phrases = self._db.execute("SELECT COUNT(*) FROM entries WHERE en LIKE '% %'").fetchone()[0]
        seeded = self._db.execute("SELECT value FROM meta WHERE key='seeded'").fetchone()
        unknown = self._db.execute("SELECT COUNT(*) FROM unknown").fetchone()[0]
        return {"total": total, "words": words, "phrases": phrases, "by_pos": by_pos, "by_source": by_source,
                "by_domain": by_domain, "seeded": seeded[0] if seeded else "", "unknown": unknown,
                "path": self._shown_path()}

    def _shown_path(self) -> str:
        """Путь к базе для показа: относительно папки системы, если база лежит в ней."""
        try:
            return self.path.resolve().relative_to(config.BASE_DIR).as_posix()
        except ValueError:
            return str(self.path)

    # --- неизвестные слова ---------------------------------------------------------------------

    def log_unknown(self, words: list[tuple[str, str, str]]) -> None:
        """Журнал слов, которых не нашлось в словаре: (слово, часть речи, пример)."""
        if not words:
            return
        now = _now()
        counts: dict[tuple[str, str], list] = {}
        for en, pos, example in words:
            if not any(ch.isalpha() for ch in en):
                continue                                # знаки препинания и числа словарю не нужны
            item = counts.setdefault((en, pos), [0, example])
            item[0] += 1
        with self._lock:
            for (en, pos), (count, example) in counts.items():
                self._db.execute(
                    "INSERT INTO unknown (en, pos, count, texts, example, first_seen, last_seen) "
                    "VALUES (?, ?, ?, 1, ?, ?, ?) ON CONFLICT(en, pos) DO UPDATE SET "
                    "count=count+excluded.count, texts=texts+1, last_seen=excluded.last_seen, "
                    "example=CASE WHEN example='' THEN excluded.example ELSE example END",
                    (en, pos, count, example[:300], now, now))
            self._db.commit()

    def unknown(self, limit: int = 300) -> list[dict]:
        rows = self._db.execute("SELECT * FROM unknown ORDER BY count DESC, en LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def forget_unknown(self, en: str, pos: str | None = None) -> None:
        with self._lock:
            if pos:
                self._db.execute("DELETE FROM unknown WHERE en=? AND pos=?", (en, pos))
            else:
                self._db.execute("DELETE FROM unknown WHERE en=?", (en,))
            self._db.commit()

    # --- выгрузка -------------------------------------------------------------------------------

    def export_tsv(self, source: str = "") -> str:
        out = io.StringIO()
        out.write("# " + "\t".join(COLUMNS) + "\n")
        query = "SELECT * FROM entries" + (" WHERE source=?" if source else "") + " ORDER BY lower(en), pos, rank"
        for row in self._db.execute(query, (source,) if source else ()):
            out.write("\t".join(str(row[c] or "") for c in COLUMNS) + "\n")
        return out.getvalue()

    def import_tsv(self, text: str, source: str = "user") -> int:
        count = 0
        reader = csv.reader(io.StringIO(text), delimiter="\t")
        for cells in reader:
            if not cells or cells[0].startswith("#") or len(cells) < 3:
                continue
            cells += [""] * (len(COLUMNS) - len(cells))
            entry = Entry(*[c.strip() for c in cells[:7]])
            entry.pos = entry.pos.upper()
            if not entry.en or not entry.de or entry.pos not in POS_NAMES:
                continue
            exists = any(e.de == entry.de and e.domain == (entry.domain or config.GENERAL_DOMAIN)
                         for e in self._index.get((entry.en.lower(), entry.pos), ()))
            if exists:
                continue
            self.add(entry, source=source)
            count += 1
        return count

    def close(self) -> None:
        self._db.close()


_lock = threading.Lock()
_instance: Lexicon | None = None


def get() -> Lexicon:
    global _instance
    with _lock:
        if _instance is None:
            _instance = Lexicon()
        return _instance


def set_instance(lexicon: Lexicon | None) -> None:
    """Подменить словарь (для тестов: временная база)."""
    global _instance
    with _lock:
        _instance = lexicon
