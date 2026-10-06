"""Разбиение английского текста на абзацы, предложения и слова.

Слова выделяются так же, как в корпусах Universal Dependencies, на которых
учились теггер и анализатор (правила Penn Treebank): знаки препинания —
отдельные слова, сокращённые формы отделяются («don't» → «do» + «n't»,
«it's» → «it» + «'s», «can't» → «ca» + «n't»), притяжательное «'s» — тоже.
Слово через дефис («state-of-the-art») остаётся одним словом: для перевода это
одна единица словаря (в корпусах такие слова склеиваются при чтении).

Каждое слово помнит своё место в тексте — по нему перевод и список слов
связываются с исходным текстом.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

HEADING_MARK = "#"

#: сокращения, после точки в которых предложение не кончается
ABBREVIATIONS = frozenset(
    """
    mr mrs ms dr prof st jr sr vs etc al cf fig figs eq eqs no nos vol vols pp ch chap sec sect ed eds
    approx ca inc ltd co corp dept univ assn gen gov lt col capt sgt rev hon mt ft jan feb mar apr jun jul aug
    sep sept oct nov dec mon tue wed thu fri sat sun e.g i.e et u.s u.k u.n a.m p.m ph.d b.c a.d viz resp
    est min max op cit ibid
    """.split()
)
#: после этих сокращений предложение может кончиться, если дальше — заглавная буква
SOFT_ABBREVIATIONS = frozenset({"etc", "al", "ibid", "a.m", "p.m", "b.c", "a.d"})

_SPACES = re.compile(r"[ \t  -   　]+")
_INVISIBLE = dict.fromkeys(map(ord, "﻿​‌‍⁠­"), None)
_BOUNDARY = re.compile(r"([.!?…]+)([\"'”’)\]]*)(\s+)")
_PREV_TOKEN = re.compile(r"(\S+)$")

# --- слова ------------------------------------------------------------------------------

#: сокращённые формы, которые отделяются от слова (апостроф — любой из двух)
_CLITIC = re.compile(r"(?i)^(.+?)(n['’]t|['’]s|['’]re|['’]ve|['’]ll|['’]d|['’]m)$")
_SPECIAL = {
    "can't": ("ca", "n't"), "can’t": ("ca", "n’t"), "won't": ("wo", "n't"), "won’t": ("wo", "n’t"),
    "cannot": ("can", "not"), "gonna": ("gon", "na"), "wanna": ("wan", "na"), "gotta": ("got", "ta"),
    "shan't": ("sha", "n't"), "ain't": ("ai", "n't"),
}
_LEADING = "\"'“‘«([{`*"
_TRAILING = "\"'”’»)]}*,;:!?…"
_NUMBER = re.compile(r"^[+-]?(\d+[.,:/]?)*\d+$")
_URL = re.compile(r"^(https?://|www\.)\S+$|^\S+@\S+\.\w+$")


@dataclass
class Token:
    text: str
    start: int                 # смещение в тексте предложения
    end: int
    space_after: bool = True


def _split_chunk(chunk: str, offset: int) -> list[Token]:
    """Слово без пробелов -> слова Penn Treebank со смещениями."""
    tokens: list[Token] = []
    tail: list[Token] = []
    start, end = 0, len(chunk)

    # «person(s)», «compiler(s)» — одно слово
    plural_mark = re.match(r"^(\w+)\(s\)([.,;:!?]*)$", chunk)
    if plural_mark:
        body = plural_mark.group(1) + "(s)"
        tail = [Token(chunk[k], offset + k, offset + k + 1, False) for k in range(len(body), len(chunk))]
        return [Token(body, offset, offset + len(body), False)] + tail

    if _URL.match(chunk):
        while end > start and chunk[end - 1] in ".,;:!?)":
            end -= 1
        tail = [Token(chunk[k], offset + k, offset + k + 1, False) for k in range(end, len(chunk))]
        return [Token(chunk[:end], offset, offset + end, False)] + tail

    # открывающие знаки
    while start < end and chunk[start] in _LEADING:
        tokens.append(Token(chunk[start], offset + start, offset + start + 1, False))
        start += 1
    # закрывающие знаки, многоточие, точка в конце
    while end > start:
        last = chunk[end - 1]
        if chunk[start:end].endswith("..."):
            tail.insert(0, Token("...", offset + end - 3, offset + end, False))
            end -= 3
            continue
        if last in _TRAILING:
            # апостроф после s — притяжательная форма: «students'»
            if last in "'’" and end - start > 2 and chunk[end - 2] in "sS" and chunk[start:end - 1].isalpha():
                tail.insert(0, Token(last, offset + end - 1, offset + end, False))
                end -= 1
                break
            tail.insert(0, Token(last, offset + end - 1, offset + end, False))
            end -= 1
            continue
        if last == "." and end - start > 1:
            body = chunk[start:end - 1]
            if _is_abbreviation(body):
                break
            tail.insert(0, Token(".", offset + end - 1, offset + end, False))
            end -= 1
            continue
        break
    body = chunk[start:end]
    if body:
        tokens.extend(_split_word(body, offset + start))
    tokens.extend(tail)
    return tokens


def _is_abbreviation(body: str) -> bool:
    lower = body.lower()
    if lower in ABBREVIATIONS:
        return True
    # инициалы и сокращения с точками: «J», «U.S», «e.g», «Ph.D»
    if len(body) == 1 and body.isalpha():
        return True
    return bool(re.fullmatch(r"(?:[A-Za-z]\.)+[A-Za-z]", body))


def _split_word(word: str, offset: int) -> list[Token]:
    lower = word.lower()
    if lower in _SPECIAL:
        first, second = _SPECIAL[lower]
        cut = len(first)
        return [Token(word[:cut], offset, offset + cut, False), Token(word[cut:], offset + cut, offset + len(word), False)]
    # проценты и денежные знаки: «50%» → «50» «%», «$5» → «$» «5»
    if len(word) > 1 and word.endswith("%") and word[:-1].replace(".", "").replace(",", "").isdigit():
        return [Token(word[:-1], offset, offset + len(word) - 1, False),
                Token("%", offset + len(word) - 1, offset + len(word), False)]
    if len(word) > 1 and word[0] in "$€£" and word[1:2].isdigit():
        return [Token(word[0], offset, offset + 1, False), Token(word[1:], offset + 1, offset + len(word), False)]
    match = _CLITIC.match(word)
    if match and match.group(1)[-1].isalnum():
        head, clitic = match.group(1), match.group(2)
        cut = len(head)
        return [Token(head, offset, offset + cut, False), Token(clitic, offset + cut, offset + len(word), False)]
    return [Token(word, offset, offset + len(word), False)]


#: тире и многоточие внутри слитного куска: «flesh;—it», «feelings?...Do» — граница слов
_INNER_BREAK = re.compile(r"(?<=[^—–\-])(?=—|–|--)|(?<=[—–])(?=[^—–\-])|(?<=--)(?=[^—–\-])"
                          r"|(?<=\w)(?=[?!]+\.\.\.\w)|(?<=\.\.\.)(?=\w)")


def _pieces(chunk: str, offset: int) -> list[tuple[str, int]]:
    result, start = [], 0
    for cut in _INNER_BREAK.finditer(chunk):
        if cut.start() > start:
            result.append((chunk[start:cut.start()], offset + start))
            start = cut.start()
    result.append((chunk[start:], offset + start))
    return result


def tokenize(text: str) -> list[Token]:
    """Слова предложения со смещениями; space_after — есть ли пробел после слова."""
    tokens: list[Token] = []
    pieces = [piece for match in re.finditer(r"\S+", text) for piece in _pieces(match.group(), match.start())]
    for piece, start in pieces:
        chunk_tokens = _split_chunk(piece, start)
        # дефисы и тире внутри слова: «word—word» → три слова
        for token in chunk_tokens:
            tokens.extend(_split_dashes(token))
    for i, token in enumerate(tokens):
        following = tokens[i + 1].start if i + 1 < len(tokens) else len(text)
        token.space_after = following > token.end or i + 1 == len(tokens)
    return tokens


def _split_dashes(token: Token) -> list[Token]:
    """Тире без пробелов («words—like this», «1990–2000») и «--» отделяются."""
    parts = re.split(r"(—|–|--)", token.text)
    if len(parts) == 1:
        return [token]
    result = []
    position = token.start
    for part in parts:
        if not part:
            continue
        result.append(Token(part, position, position + len(part), False))
        position += len(part)
    return result


# --- предложения ----------------------------------------------------------------------------

@dataclass
class Sentence:
    index: int
    paragraph: int
    text: str
    start: int                 # смещение в тексте документа
    heading: bool = False
    tokens: list[Token] = field(default_factory=list)

    @property
    def words(self) -> list[str]:
        return [t.text for t in self.tokens]


@dataclass
class Paragraph:
    index: int
    text: str
    start: int
    heading: bool
    sentences: list[int] = field(default_factory=list)


@dataclass
class Layout:
    """Документ: текст (абзацы через перевод строки), абзацы и предложения."""

    text: str
    paragraphs: list[Paragraph]
    sentences: list[Sentence]


def clean(text: str) -> str:
    text = text.translate(_INVISIBLE).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(_SPACES.sub(" ", line).strip() for line in text.split("\n"))


def paragraphs_of(text: str) -> list[tuple[str, bool]]:
    """Абзацы текста: (текст, заголовок ли). Абзацы разделены пустой строкой;
    если пустых строк нет — каждая строка считается абзацем."""
    text = clean(text)
    blocks = [b for b in re.split(r"\n\s*\n", text) if b.strip()]
    if len(blocks) == 1 and text.count("\n") >= 2:
        blocks = [line for line in text.split("\n") if line.strip()]
    result = []
    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        # заголовок, а за ним абзац без пустой строки
        if lines[0].startswith(HEADING_MARK) and len(lines) > 1:
            result.append((lines[0].lstrip(HEADING_MARK).strip(), True))
            lines = lines[1:]
        joined = " ".join(lines)
        if joined.startswith(HEADING_MARK):
            result.append((joined.lstrip(HEADING_MARK).strip(), True))
        else:
            result.append((joined, _looks_like_heading(joined)))
    return result


def _looks_like_heading(text: str) -> bool:
    return len(text) <= 80 and not re.search(r"[.!?:;…]$", text) and len(text.split()) <= 10 \
        and text[:1].isupper()


def split_sentences(text: str) -> list[tuple[int, int]]:
    """Границы предложений абзаца: пары (начало, конец)."""
    spans = []
    start = 0
    for match in _BOUNDARY.finditer(text):
        end = match.end(2)
        after = match.end()
        if after >= len(text):
            continue
        if not _is_sentence_end(text, start, match, after):
            continue
        spans.append((start, end))
        start = after
    if start < len(text) and text[start:].strip():
        spans.append((start, len(text.rstrip())))
    return [(s, e) for s, e in spans if text[s:e].strip()]


def _is_sentence_end(text: str, start: int, match: re.Match, after: int) -> bool:
    following = text[after:after + 2]
    first = following[:1]
    if not (first.isupper() or first.isdigit() or first in "\"'“‘([«"):
        return False
    if match.group(1) != ".":
        return True
    previous = _PREV_TOKEN.search(text[start:match.start(1)])
    word = previous.group(1).lstrip("\"'“‘([") if previous else ""
    lower = word.lower()
    if lower in SOFT_ABBREVIATIONS:
        return True
    if lower in ABBREVIATIONS:
        return False
    if len(word) == 1 and word.isupper():
        return False                     # инициал: «J. K. Rowling»
    if re.fullmatch(r"(?:[A-Za-z]\.)+[A-Za-z]", word):
        return False                     # «e.g.», «U.S.»
    return True


def layout(text: str) -> Layout:
    paragraphs: list[Paragraph] = []
    sentences: list[Sentence] = []
    chunks = []
    offset = 0
    for index, (body, heading) in enumerate(paragraphs_of(text)):
        paragraph = Paragraph(index, body, offset, heading)
        spans = [(0, len(body))] if heading else split_sentences(body)
        for s, e in spans:
            sentence_text = body[s:e].strip()
            lead = len(body[s:e]) - len(body[s:e].lstrip())
            sentence = Sentence(len(sentences), index, sentence_text, offset + s + lead, heading,
                                tokenize(sentence_text))
            paragraph.sentences.append(sentence.index)
            sentences.append(sentence)
        paragraphs.append(paragraph)
        chunks.append(body)
        offset += len(body) + 1
    return Layout("\n".join(chunks), paragraphs, sentences)
