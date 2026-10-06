"""Диктовка: сочинение записывается под голос.

По команде «начни диктовку» система перестаёт искать в речи операции: каждая
следующая фраза дописывается в текст, пока не прозвучит «конец диктовки».
Распознаватель отдаёт слова строчными буквами и без знаков, поэтому текст
приходится собирать:

* знаки препинания называются словами — «запятая», «точка», «новый абзац»,
  „Komma“, „Punkt“, „neuer Absatz“ — и заменяются знаками;
* первое слово предложения пишется с заглавной буквы;
* заглавная буква возвращается именам и немецким существительным — тем, что
  встречаются в сочинениях коллекции (Lexicon): «онегин» — «Онегин»,
  „räuber“ — „Räuber“;
* после каждой фразы ставится точка, если фраза не закончилась своим знаком
  (это можно выключить).

Готовый текст сохраняется как сочинение (Dictations), и с ним работают все
операции системы: его можно открыть, прочитать вслух, посчитать в нём слова.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sluhach import config
from sluhach.essays import Collection, Essay, sentences
from sluhach.text import normalize

PARAGRAPH = "\n\n"
#: знаки, которыми кончается предложение: слово после них пишется с заглавной буквы
SENTENCE_ENDS = ".!?…"
#: знаки, вплотную к которым второй знак не ставится: названный позже заменяет прежний
_PUNCTUATION = ".,;:!?…"
#: после этого предложение явно продолжается — точку в конце фразы ставить рано
_CONTINUES = ",;:—–«„("
_OPENING = "«„("
_CLOSING = "»“)\""


@dataclass(frozen=True)
class Mark:
    """Знак препинания, названный словом."""

    text: str
    kind: str = "after"     # after — вплотную к слову слева, before — к слову справа,
    #                         dash — отбивается пробелами, paragraph — новый абзац


_BREAK = Mark(PARAGRAPH, "paragraph")


def _pattern(mark: Mark, *positions: str) -> tuple[tuple[frozenset[str], ...], Mark]:
    """Слова, которыми называют знак; варианты одного слова — через «|»."""
    return tuple(frozenset(normalize(word) for word in position.split("|")) for position in positions), mark


#: слова-знаки по языкам. Варианты вроде «новые абзац» и „neue Absatz“ — то, что
#: распознаватель на самом деле слышит вместо «новый абзац» и „neuer Absatz“
#: (проверено на озвученных фразах); „komme“ он часто слышит вместо „Komma“.
_MARKS: dict[str, tuple[tuple[tuple[frozenset[str], ...], Mark], ...]] = {
    "ru": (
        _pattern(Mark(";"), "точка", "с", "запятой"),
        _pattern(_BREAK, "с", "красной|красные|красная", "строки|строка"),
        _pattern(Mark("?"), "вопросительный", "знак"),
        _pattern(Mark("!"), "восклицательный", "знак"),
        _pattern(_BREAK, "новый|новые|новой", "абзац"),
        _pattern(_BREAK, "красная|красные|красной", "строка|строки"),
        _pattern(Mark("«", "before"), "открыть", "кавычки"),
        _pattern(Mark("»"), "закрыть", "кавычки"),
        _pattern(Mark("…"), "многоточие"),
        _pattern(Mark(":"), "двоеточие"),
        _pattern(Mark(","), "запятая"),
        _pattern(Mark("."), "точка"),
        _pattern(Mark("—", "dash"), "тире"),
    ),
    "de": (
        _pattern(Mark("„", "before"), "anführungszeichen", "auf"),
        _pattern(Mark("“"), "anführungszeichen", "zu"),
        _pattern(Mark("„", "before"), "zitat", "anfang|anfangen"),
        _pattern(Mark("“"), "zitat", "ende"),
        _pattern(_BREAK, "neuer|neue|neuen", "absatz"),
        _pattern(_BREAK, "neue", "zeile"),
        _pattern(Mark("…"), "drei", "punkte"),
        _pattern(Mark("?"), "fragezeichen"),
        _pattern(Mark("!"), "ausrufezeichen"),
        _pattern(Mark(":"), "doppelpunkt"),
        _pattern(Mark(";"), "semikolon|strichpunkt"),
        _pattern(Mark(","), "komma|komme"),
        _pattern(Mark("."), "punkt"),
        _pattern(Mark("–", "dash"), "gedankenstrich"),
    ),
}

#: как называть знаки — подсказка для страницы диктовки: (что сказать, что получится)
SPOKEN: dict[str, tuple[tuple[str, str], ...]] = {
    "ru": (("запятая", ","), ("точка", "."), ("вопросительный знак", "?"), ("восклицательный знак", "!"),
           ("двоеточие", ":"), ("точка с запятой", ";"), ("тире", "—"), ("многоточие", "…"),
           ("открыть кавычки", "«"), ("закрыть кавычки", "»"), ("новый абзац", "¶")),
    "de": (("Komma", ","), ("Punkt", "."), ("Fragezeichen", "?"), ("Ausrufezeichen", "!"), ("Doppelpunkt", ":"),
           ("Semikolon", ";"), ("Gedankenstrich", "–"), ("drei Punkte", "…"),
           ("Anführungszeichen auf", "„"), ("Anführungszeichen zu", "“"), ("neuer Absatz", "¶")),
}

#: «точка» перед этими словами — слово, а не знак: «точка зрения»
_WORD_BEFORE: dict[str, dict[str, frozenset[str]]] = {
    "ru": {"точка": frozenset({"зрения", "опоры", "отсчета", "кипения", "невозврата"})},
}
#: „Punkt“ после этих слов — слово: „der Punkt“, „zum Punkt“; „komme“ после „ich“ — глагол
_WORD_AFTER: dict[str, dict[str, frozenset[str]]] = {
    "de": {"punkt": frozenset({"der", "den", "dem", "ein", "einen", "einem", "kein", "keinen", "diesem", "diesen",
                               "dieser", "jedem", "jeden", "zum", "im", "am"}),
           "komme": frozenset({"ich"})},
}


def _is_word(keys: list[str], index: int, language: str) -> bool:
    """Слово-знак здесь стоит в своём обычном значении."""
    key = keys[index]
    before = _WORD_BEFORE.get(language, {}).get(key)
    if before and index + 1 < len(keys) and keys[index + 1] in before:
        return True
    after = _WORD_AFTER.get(language, {}).get(key)
    return bool(after and index > 0 and keys[index - 1] in after)


def parse(phrase: str, language: str) -> list[str | Mark]:
    """Слова фразы и знаки, названные словами, по порядку."""
    chunks = (phrase or "").split()
    keys = [normalize(chunk) for chunk in chunks]
    patterns = _MARKS.get(language, ())
    result: list[str | Mark] = []
    index = 0
    while index < len(chunks):
        for words, mark in patterns:
            end = index + len(words)
            if end > len(chunks) or any(keys[index + offset] not in words[offset] for offset in range(len(words))):
                continue
            if len(words) == 1 and _is_word(keys, index, language):
                continue
            result.append(mark)
            index = end
            break
        else:
            result.append(chunks[index])
            index += 1
    return result


# --- сборка текста --------------------------------------------------------------------

def _fresh(out: str) -> bool:
    """Абзац только начат: текста ещё нет или он кончается переводом строки."""
    return not out or out.endswith("\n")


def _gap(out: str) -> str:
    """Текст, готовый принять слово: с пробелом, если слово не первое в абзаце и не после открывающей кавычки."""
    if _fresh(out) or out[-1] in _OPENING or out[-1] == " ":
        return out
    return out + " "


def _starts_sentence(out: str) -> bool:
    """Следующее слово начинает предложение."""
    body = out.rstrip(" ")
    quoted = False
    while body and body[-1] in _OPENING:
        body, quoted = body[:-1].rstrip(" "), True
    if _fresh(body):
        return True
    if body[-1] in _CLOSING:
        # «…вернусь.» — предложение кончилось внутри кавычек; «…вернусь» — нет
        inner = body.rstrip(_CLOSING)
        return bool(inner) and inner[-1] in SENTENCE_ENDS
    # прямая речь после двоеточия тоже начинается с заглавной: Он сказал: «Я вернусь»
    return body[-1] in SENTENCE_ENDS or (quoted and body[-1] == ":")


def _capital(word: str) -> str:
    for position, char in enumerate(word):
        if char.isalpha():
            return word[:position] + char.upper() + word[position + 1:]
    return word


def _finish(out: str) -> str:
    """Текст с точкой в конце, если предложение не закончено своим знаком и явно не продолжается."""
    body = out.rstrip(" ")
    if _fresh(body):
        return body
    if body[-1] in _CLOSING:
        inner = body.rstrip(_CLOSING)
        return body if inner and inner[-1] in SENTENCE_ENDS else body + "."
    if body[-1] in SENTENCE_ENDS or body[-1] in _CONTINUES:
        return body
    return body + "."


def _put(out: str, mark: Mark, period: bool) -> str:
    if mark.kind == "paragraph":
        if _fresh(out):
            return out
        return (_finish(out) if period else out.rstrip(" ")) + PARAGRAPH
    if mark.kind == "before":
        return _gap(out) + mark.text
    body = out.rstrip(" ")
    if _fresh(body):
        return out                      # знаку не к чему примкнуть
    if mark.kind == "dash":
        return body + " " + mark.text
    if mark.text in _PUNCTUATION and body[-1] in _PUNCTUATION:
        # точка, поставленная после прошлой фразы, оказалась запятой: названный знак заменяет прежний
        body = body[:-1]
    return body + mark.text


def write(text: str, phrase: str, language: str, lexicon: "Lexicon | None" = None, period: bool = True) -> str:
    """Текст с дописанной фразой.

    `period` — ставить ли точку после фразы, которая не кончилась своим
    знаком. Пауза в речи обычно и есть конец предложения; если точка
    поставлена зря, следующую фразу начинают со слова «запятая».
    """
    out = (text or "").rstrip(" \t")
    for token in parse(phrase, language):
        if isinstance(token, Mark):
            out = _put(out, token, period)
            continue
        if _starts_sentence(out):
            word = _capital(token)
        else:
            word = lexicon.restore(token, language) if lexicon is not None else token
        out = _gap(out) + word
    return _finish(out) if period else out


def difference(old: str, new: str) -> tuple[int, str]:
    """Чем новый текст отличается от прежнего: длина общего начала и то, что после него было.

    По этой паре последняя фраза стирается: `new[:k] + removed` — снова
    прежний текст. Обычно `removed` пуст; не пуст, когда фраза заменила
    знак в конце прежнего текста.
    """
    common = 0
    for left, right in zip(old, new):
        if left != right:
            break
        common += 1
    return common, old[common:]


def clean(text: str) -> str:
    """Текст для сохранения: без пробелов по краям строк, абзацы разделены одной пустой строкой."""
    lines = [line.strip() for line in (text or "").replace("\r", "").split("\n")]
    return re.sub(r"\n{3,}", PARAGRAPH, "\n".join(lines)).strip()[:config.MAX_DRAFT_CHARS]


def title_of(text: str) -> str:
    """Название по первым словам текста: «Онегин, добрый мой приятель…»."""
    words = text.strip().split("\n", 1)[0].lstrip("# ").split()
    title = " ".join(words[:config.DICTATED_TITLE_WORDS])
    cut = len(words) > config.DICTATED_TITLE_WORDS
    if len(title) > config.MAX_TITLE_CHARS:
        title, cut = title[:config.MAX_TITLE_CHARS].rsplit(" ", 1)[0], True
    title = title.rstrip(_PUNCTUATION + "—– ")
    return title + "…" if cut and title else title


# --- заглавные буквы -------------------------------------------------------------------

class Lexicon:
    """Слова, которые пишутся с заглавной буквы, — по сочинениям коллекции.

    Распознаватель регистра не знает. В сочинениях же видно, какие слова
    пишутся с заглавной буквы не потому, что стоят в начале предложения:
    имена и названия, а в немецком — все существительные. Слово считается
    таким, если в середине предложения оно почти всегда написано с заглавной.
    Слова, которых в коллекции нет, остаются строчными.

    В русском заглавная буква — признак имени, и одного написания мало:
    «Большого театра» не делает именем слово «большого». Поэтому русское
    слово не считается именем, если другие его формы («большой», «большая»)
    пишутся в сочинениях со строчной буквы не реже, чем оно само — с
    заглавной. У «Чацкого» таких форм нет, у «Раскольникова» они редки.
    """

    #: какая доля написаний в середине предложения должна быть с заглавной буквы
    SHARE = 0.9
    #: языки, где заглавная буква в середине предложения — признак имени
    NAMES_ONLY = frozenset({"ru"})
    #: формы одного слова: общее начало — всё слово без трёх последних букв (но не короче
    #: четырёх), длины различаются не больше чем на три буквы
    FORM_TAIL = 3
    FORM_HEAD = 4

    def __init__(self, collection: Collection) -> None:
        self._collection = collection
        self._capitals: dict[str, frozenset[str]] = {}

    def capitals(self, language: str) -> frozenset[str]:
        if language not in self._capitals:
            self._capitals[language] = self._build(language)
        return self._capitals[language]

    def _build(self, language: str) -> frozenset[str]:
        seen: dict[str, list[int]] = defaultdict(lambda: [0, 0])      # слово -> [строчных, заглавных]
        for essay in self._collection.by_language(language):
            if essay.dictated:
                continue                # надиктованное само написано по этому словарю
            for paragraph in essay.paragraphs:
                for sentence in sentences(paragraph.text, language):
                    chunks = sentence.split()
                    for previous, chunk in zip(chunks, chunks[1:]):
                        # после кавычки, двоеточия и тире заглавная буква может значить начало реплики
                        if chunk[0] in _OPENING + "\"" or previous[-1] in ":—–-" or previous[-1] in _OPENING:
                            continue
                        core = chunk.strip(".,;:!?…»“”\")(")
                        # сокращения из заглавных букв («СССР») сюда не относятся
                        if not core.isalpha() or sum(1 for char in core if char.isupper()) > 1:
                            continue
                        seen[normalize(core)][core[0].isupper()] += 1
        capitals = {key for key, (lower, upper) in seen.items()
                    if len(key) >= 3 and upper >= self.SHARE * (lower + upper)}
        if language in self.NAMES_ONLY:
            ordinary: dict[str, list[tuple[str, int]]] = defaultdict(list)      # начало -> слова со строчной
            for key, (lower, _upper) in seen.items():
                if lower:
                    ordinary[key[:self.FORM_HEAD]].append((key, lower))

            def forms(key: str) -> int:
                """Сколько раз другие формы слова написаны со строчной буквы."""
                head = key[:max(self.FORM_HEAD, len(key) - self.FORM_TAIL)]
                return sum(count for other, count in ordinary.get(key[:self.FORM_HEAD], ())
                           if other.startswith(head) and abs(len(other) - len(key)) <= self.FORM_TAIL)

            capitals = {key for key in capitals if forms(key) < seen[key][1]}
        return frozenset(capitals)

    def restore(self, word: str, language: str) -> str:
        """Слово с заглавной буквы, если в сочинениях оно пишется так."""
        if any(char.isupper() for char in word):
            return word                 # регистр уже расставлен (распознаватель браузера)
        return _capital(word) if normalize(word) in self.capitals(language) else word


# --- надиктованные сочинения --------------------------------------------------------------

#: что это за сочинение — вместо «роман Пушкина»: (на языке сочинения, по-русски)
ABOUT = {"de": "diktierter Aufsatz", "ru": "надиктованное сочинение"}


class DictationError(ValueError):
    """Сочинение нельзя сохранить; code — повод, по которому система об этом скажет."""

    def __init__(self, code: str, **fields) -> None:
        super().__init__(code)
        self.code, self.fields = code, fields


class Dictations:
    """Надиктованные сочинения: хранятся в dictated.json и входят в общий список сочинений."""

    def __init__(self, collection: Collection, path: Path | None = None) -> None:
        self.collection = collection
        self.path = path or config.DICTATED_PATH
        self._lock = threading.RLock()
        self._items: list[dict] = []
        self.load()

    def load(self) -> None:
        with self._lock:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                items = data["essays"]
            except (OSError, ValueError, KeyError, TypeError):
                items = []
            self._items = []
            for item in items:
                if not isinstance(item, dict) or item.get("language") not in config.LANGUAGES:
                    continue
                record = {"id": str(item.get("id") or ""), "language": item["language"],
                          "title": str(item.get("title") or ""), "text": clean(str(item.get("text") or "")),
                          "created": str(item.get("created") or "")}
                if record["id"] and record["title"] and self._essay(record).paragraphs:
                    self._items.append(record)
                    self.collection.add(self._essay(record))

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"version": 1, "essays": self._items}, ensure_ascii=False, indent=1) + "\n",
                             encoding="utf-8")
        os.replace(temporary, self.path)

    def _essay(self, record: dict) -> Essay:
        return Essay(
            id=record["id"], language=record["language"], title=record["title"], author="", year="",
            about=ABOUT[record["language"]], about_ru=ABOUT["ru"], title_ru=record["title"],
            aliases=(record["title"],), path=self.path, source={"site": "диктовка"},
            text=record["text"], dictated=True, created=record["created"],
        )

    def all(self) -> list[Essay]:
        with self._lock:
            return [essay for essay in (self.collection.get(item["id"]) for item in self._items) if essay]

    def save(self, language: str, title: str, text: str, essay_id: str = "", now: datetime | None = None) -> Essay:
        """Сохраняет текст как сочинение; с `essay_id` — заменяет уже надиктованное."""
        if language not in config.LANGUAGES:
            raise DictationError("empty")
        text = clean(text)
        title = " ".join((title or "").split())[:config.MAX_TITLE_CHARS] or title_of(text)
        with self._lock:
            old = next((item for item in self._items if item["id"] == essay_id and item["language"] == language), None)
            if old is None and len(self._items) >= config.MAX_DICTATED:
                raise DictationError("limit", count=len(self._items))
            record = {"id": old["id"] if old else "dict-" + secrets.token_hex(4), "language": language,
                      "title": title, "text": text,
                      "created": old["created"] if old else (now or datetime.now()).strftime("%d.%m.%Y %H:%M")}
            essay = self._essay(record)
            if not title or not essay.paragraphs:
                raise DictationError("empty")
            self._items = [record if item is old else item for item in self._items] if old else [*self._items, record]
            self._save()
            self.collection.add(essay)
            return essay

    def remove(self, essay_id: str) -> Essay | None:
        with self._lock:
            if not any(item["id"] == essay_id for item in self._items):
                return None
            self._items = [item for item in self._items if item["id"] != essay_id]
            self._save()
            return self.collection.remove(essay_id)
