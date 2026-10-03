"""Разбиение документа на абзацы и предложения.

Формулы методички опираются на положение предложения в символах: BD(Sᵢ) —
число символов до предложения в документе, BP(Sᵢ) — в абзаце. Поэтому здесь
фиксируется единое представление документа D: абзацы, соединённые переводом
строки. Смещения всех предложений отсчитываются в этой строке, и |D| — её
длина.

Заголовки разделов входят в D (они часть документа и занимают место), но
предложениями-кандидатами не считаются: заголовок «Введение» не может быть
предложением реферата.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

HEADING_MARK = "#"

#: знаки, после которых может кончаться предложение
TERMINAL = ".!?…"
#: закрывающие кавычки и скобки, которые остаются при предложении: «…так.»
CLOSERS = "»“”\"')]’"
#: с чего может начинаться новое предложение, кроме заглавной буквы и цифры
OPENERS = "«„“\"'([—–-"

_INVISIBLE = dict.fromkeys(map(ord, "﻿​‌‍⁠­"), None)
_SPACES = re.compile(r"[ \t      ]+")
_BOUNDARY = re.compile(r"([.!?…]+)([»“”\"')\]’]*)(\s+)")
_PREV_TOKEN = re.compile(r"(\S+)$")
_PAGE_REF = re.compile(r"\((?:[SsСс]\.\s*)?\d+(?:\s*[–-]\s*\d+)?\)")
_ENUMERATOR = re.compile(r"(?:\d{1,3}(?:\.\d{1,3})*|[IVXLC]{1,6})\.")

#: сокращения, после точки в которых предложение не кончается.
#: Однобуквенные сокращения и инициалы («т. е.», «А. С. Пушкин», «z. B.»)
#: здесь не перечислены — их отсекает общее правило про одну букву.
ABBREVIATIONS: dict[str, frozenset[str]] = {
    "ru": frozenset(
        """
        гг вв см ср рис табл стр др пр им ул проф акад доц канд техн тыс млн млрд
        руб коп долл гл пп изд ред вып англ нем фр франц лат греч рус букв напр
        прим сокр ок св кн ст мин сек кв км мм кг обл р-н пос дер нач кон зав
        гос мед биол физ хим мат ист филол пед экон юрид с.-х т.е т.д т.п т.к
        т.н т.ч н.э и.о etc al дж вл ал
        """.split()
    ),
    "de": frozenset(
        """
        bzw ca dr prof nr vgl usw etc sog jh jhd jahrh bspw evtl ggf inkl insb
        abb kap bd bde hrsg zit st str tel mio mrd min max ff chr jr sen gebr
        geb gest verh dt engl franz lat griech allg bes bzgl etw entspr gem
        zzgl abs vs hl röm ev kath ital span russ altgr mhd ahd urspr wörtl sp
        ebd al ders hg aufl ausg übers anm fn vol no pp bzgl z.b d.h u.a v.a
        o.ä u.ä z.t i.d.r o.g s.o s.u u.v.m v.chr n.chr
        """.split()
    ),
}


@dataclass
class Sentence:
    """Предложение документа."""

    index: int                 # номер в документе, с 0
    paragraph: int             # номер абзаца
    text: str
    start: int                 # BD(Sᵢ): символов до предложения в D
    end: int
    start_in_paragraph: int    # BP(Sᵢ): символов до предложения в абзаце

    @property
    def length(self) -> int:
        return self.end - self.start


@dataclass
class Paragraph:
    """Абзац документа или заголовок раздела."""

    index: int
    text: str
    start: int                 # смещение абзаца в D
    heading: bool = False
    sentences: list[int] = field(default_factory=list)

    @property
    def length(self) -> int:   # |P|
        return len(self.text)

    @property
    def end(self) -> int:
        return self.start + len(self.text)


@dataclass
class Layout:
    """Документ D: текст, абзацы и предложения с их смещениями."""

    text: str
    paragraphs: list[Paragraph]
    sentences: list[Sentence]

    @property
    def length(self) -> int:   # |D|
        return len(self.text)


# --- Предварительная нормализация ---------------------------------------------

def clean(raw: str) -> str:
    """Приводит текст к NFC, убирает невидимые символы и лишние пробелы в строках."""
    text = unicodedata.normalize("NFC", raw).translate(_INVISIBLE)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(_SPACES.sub(" ", line).strip() for line in text.split("\n"))


def split_blocks(text: str) -> list[str]:
    """Делит текст на абзацы.

    Если абзацы разделены пустыми строками, одиночный перевод строки считается
    переносом внутри абзаца. Если пустых строк нет вовсе (так выглядит текст,
    скопированный из Word), абзацем считается каждая строка.
    """
    if re.search(r"\n\s*\n", text):
        blocks = re.split(r"\n\s*\n", text)
        return [re.sub(r"\s*\n\s*", " ", block).strip() for block in blocks if block.strip()]
    return [line.strip() for line in text.split("\n") if line.strip()]


def looks_like_heading(text: str) -> bool:
    """Короткая строка без знака конца предложения — заголовок раздела."""
    if len(text) > 120 or not any(ch.isalpha() for ch in text):
        return False
    if text.rstrip(CLOSERS)[-1:] in TERMINAL + ":;,":
        return False
    if len(text.split()) > 14:
        return False
    first = text.lstrip("«„\"'(")[:1]
    return first.isupper() or first.isdigit()


# --- Предложения ----------------------------------------------------------------

def _is_abbreviation(token: str, language: str) -> bool:
    core = token.lstrip("«„\"'([").lower()
    core = core.rstrip(".")
    if not core:
        return False
    letters = core.replace(".", "").replace("-", "")
    # одна буква: инициал или часть сокращения «т. е.», «z. B.», «А. С.»
    if len(letters) == 1 and letters.isalpha():
        return True
    # сокращение с точками внутри: «т.е», «z.B», «u.a»
    if "." in core and all(part.isalpha() and len(part) <= 3 for part in core.split(".") if part):
        return True
    return core in ABBREVIATIONS.get(language, frozenset())


def _next_starts_sentence(text: str, position: int) -> bool:
    """Может ли с этой позиции начаться новое предложение."""
    rest = text[position:]
    if not rest:
        return False
    first = rest[0]
    if first.isupper() or first.isdigit():
        return True
    if first in OPENERS:
        # прямая речь: «— Пойдёшь? — спросил он.» — после тире строчная буква
        # означает, что предложение продолжается
        tail = rest.lstrip(OPENERS + " ")
        return bool(tail) and (tail[0].isupper() or tail[0].isdigit())
    return False


def split_sentences(text: str, language: str) -> list[tuple[int, int]]:
    """Границы предложений абзаца: список (начало, конец) в символах."""
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _BOUNDARY.finditer(text):
        punctuation = match.group(1)
        boundary = match.end(2)             # предложение включает закрывающие кавычки
        following = match.end(3)            # начало следующего предложения
        # ссылка на страницу после цитаты: «…verlassen.“ (164) – Als …» —
        # номер относится к цитате и остаётся в её предложении
        page = _PAGE_REF.match(text, following)
        if page:
            boundary = page.end()
            following = boundary + len(text[boundary:]) - len(text[boundary:].lstrip())
        if not _next_starts_sentence(text, following):
            continue
        # номер пункта списка «2.», «2.1.», «IV.» — не предложение, он остаётся с текстом пункта
        if _ENUMERATOR.fullmatch(text[start:boundary].strip()):
            continue
        if punctuation == ".":
            before = text[start:match.start(1)]
            token = _PREV_TOKEN.search(before)
            if token:
                word = token.group(1)
                if _is_abbreviation(word, language):
                    continue
                # немецкие порядковые числительные: «im 19. Jahrhundert», «am 3. Oktober»
                if language == "de" and word.isdigit() and len(word) <= 2:
                    continue
        if text[start:boundary].strip():
            spans.append((start, boundary))
        start = following
    if text[start:].strip():
        spans.append((start, len(text.rstrip())))
    return spans


# --- Документ -------------------------------------------------------------------

def parse(raw: str, language: str) -> Layout:
    """Строит документ D: абзацы, заголовки и предложения с их смещениями."""
    blocks = split_blocks(clean(raw))

    paragraphs: list[Paragraph] = []
    sentences: list[Sentence] = []
    offset = 0
    for block in blocks:
        heading = False
        if block.startswith(HEADING_MARK):
            block = block.lstrip(HEADING_MARK).strip()
            heading = True
        elif looks_like_heading(block):
            heading = True
        if not block:
            continue
        paragraph = Paragraph(index=len(paragraphs), text=block, start=offset, heading=heading)
        if not heading:
            for begin, finish in split_sentences(block, language):
                sentence = Sentence(
                    index=len(sentences),
                    paragraph=paragraph.index,
                    text=block[begin:finish],
                    start=offset + begin,
                    end=offset + finish,
                    start_in_paragraph=begin,
                )
                paragraph.sentences.append(sentence.index)
                sentences.append(sentence)
        paragraphs.append(paragraph)
        offset += len(block) + 1          # абзацы соединяются одним переводом строки

    text = "\n".join(p.text for p in paragraphs)
    return Layout(text=text, paragraphs=paragraphs, sentences=sentences)
