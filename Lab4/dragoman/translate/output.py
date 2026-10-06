"""Немецкое предложение как последовательность слов с привязкой к английским словам.

Каждое немецкое слово помнит, из каких английских слов оно получено. По этой
привязке интерфейс подсвечивает соответствие слов при наведении, список слов
показывает, во что превратилось слово в тексте, а игра Пафнутия знает, как
выглядит переведённое слово.

Здесь же сборка предложения: пробелы по правилам немецкой типографики,
кавычки „…“, лишние запятые, заглавная буква в начале предложения.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: виды слов: перевод из словаря, по правилу, без перевода, имя, число, знак
KINDS = ("word", "rule", "unknown", "name", "number", "punct")

_NO_SPACE_BEFORE = {",", ".", ";", ":", "!", "?", ")", "]", "}", "“", "‘", "%", "…", "'"}
_NO_SPACE_AFTER = {"(", "[", "{", "„", "‚", "/"}
_OPEN_QUOTES = {'"': ("„", "“"), "“": ("„", "“"), "”": ("„", "“"), "``": ("„", "“"), "''": ("„", "“"),
                "'": ("‚", "‘"), "‘": ("‚", "‘"), "’": ("‚", "‘")}
SENTENCE_END = {".", "!", "?"}


@dataclass
class G:
    text: str
    src: tuple[int, ...] = ()
    kind: str = "word"
    #: слово — существительное (в немецком пишется с заглавной)
    noun: bool = False
    #: слово с этой отметкой в начале предложения не меняет регистр (имена, «iOS»)
    keep_case: bool = False
    gloss: str = ""

    def copy(self, **changes) -> "G":
        values = {**self.__dict__, **changes}
        return G(**values)


@dataclass
class Sentence:
    """Переведённое предложение: немецкие слова, английский исходник, заметки трансфера."""

    index: int
    source: str
    tokens: list[G]
    notes: list[str] = field(default_factory=list)
    heading: bool = False

    @property
    def text(self) -> str:
        return assemble(self.tokens)


def word(text: str, src=(), kind: str = "word", noun: bool = False, keep_case: bool = False) -> G:
    if isinstance(src, int):
        src = (src,)
    return G(text, tuple(src), kind, noun, keep_case)


def punct(text: str, src=()) -> G:
    if isinstance(src, int):
        src = (src,)
    return G(text, tuple(src), "punct")


def is_punct(token: G) -> bool:
    return token.kind == "punct"


def tidy(tokens: list[G]) -> list[G]:
    """Убирает лишние запятые: в начале, двойные, перед точкой и закрывающей скобкой."""
    result: list[G] = []
    for token in tokens:
        if not token.text:
            continue
        if token.kind == "punct" and token.text == ",":
            if not result or (result[-1].kind == "punct" and result[-1].text in {",", "(", "[", "„", ";", ":", "–"}):
                continue
        if token.kind == "punct" and token.text in {".", "!", "?", ")", "]", "“", ";", ":"}:
            while result and result[-1].kind == "punct" and result[-1].text == ",":
                result.pop()
        result.append(token)
    while result and result[0].kind == "punct" and result[0].text in {",", ";"}:
        result.pop(0)
    return result


def quote_pairs(tokens: list[G]) -> list[G]:
    """Английские кавычки → немецкие „…“: открывающая — нечётная, закрывающая — чётная."""
    opened = {"double": False, "single": False}
    result = []
    for token in tokens:
        if token.kind == "punct" and token.text in _OPEN_QUOTES:
            style = "single" if token.text in {"'", "‘", "’"} else "double"
            pair = _OPEN_QUOTES[token.text]
            if token.text in {"“", "‘", "``"}:
                is_open = True
            elif token.text in {"”", "’", "''"}:
                is_open = False
            else:
                is_open = not opened[style]
            opened[style] = is_open
            result.append(token.copy(text=pair[0] if is_open else pair[1]))
        else:
            result.append(token)
    return result


def assemble(tokens: list[G], capitalize: bool = True) -> str:
    """Текст предложения из слов: пробелы, кавычки, заглавная буква в начале."""
    tokens = tidy(quote_pairs(tokens))
    out: list[str] = []
    no_space_next = True
    first_word = capitalize
    for token in tokens:
        text = token.text
        if token.noun and text[:1].islower():
            text = text[:1].upper() + text[1:]
        if first_word and token.kind != "punct" and text[:1].isalpha():
            if not token.keep_case:
                text = text[:1].upper() + text[1:]
            first_word = False
        elif first_word and token.kind != "punct":
            first_word = False
        if out and not no_space_next and not (token.kind == "punct" and text in _NO_SPACE_BEFORE):
            out.append(" ")
        out.append(text)
        no_space_next = token.kind == "punct" and text in _NO_SPACE_AFTER
    return "".join(out).strip()


def spans(tokens: list[G], capitalize: bool = True) -> list[tuple[str, G | None]]:
    """Текст предложения кусками: (кусок, слово или None для пробела) — для подсветки в интерфейсе."""
    tokens = tidy(quote_pairs(tokens))
    pieces: list[tuple[str, G | None]] = []
    no_space_next = True
    first_word = capitalize
    for token in tokens:
        text = token.text
        if token.noun and text[:1].islower():
            text = text[:1].upper() + text[1:]
        if first_word and token.kind != "punct" and text[:1].isalpha():
            if not token.keep_case:
                text = text[:1].upper() + text[1:]
            first_word = False
        elif first_word and token.kind != "punct":
            first_word = False
        if pieces and not no_space_next and not (token.kind == "punct" and text in _NO_SPACE_BEFORE):
            pieces.append((" ", None))
        pieces.append((text, token))
        no_space_next = token.kind == "punct" and text in _NO_SPACE_AFTER
    return pieces
