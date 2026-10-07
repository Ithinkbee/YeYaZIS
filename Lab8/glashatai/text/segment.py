"""Деление текста на абзацы и предложения.

Синтезатор читает текст по предложениям: так первое предложение звучит,
пока синтезируются следующие, после каждого можно сделать паузу, а на
странице видно, какое предложение звучит. Делить нужно точно: точка в
немецком научном тексте часто не конец предложения —

* сокращения: «z. B. die Syntaxanalyse», «vgl. Abb. 3», «S. 12 f.»;
* порядковые числительные: «im 19. Jahrhundert», «die 2. Auflage»;
* инициалы: «J. von Neumann», «G. Boole»;
* версии и даты: «Python 3.11», «12.03.2021» (здесь после точки нет пробела).

Деление сохраняет положение каждого предложения в исходном тексте: по нему
страница подсвечивает то, что звучит.

Абзацы. Пустая строка всегда разделяет абзацы. Одиночный перевод строки —
только если строка закончилась точкой (или это заголовок, пункт списка); иначе
это перенос внутри абзаца, как в тексте, скопированном из PDF. Строка,
начинающаяся с «# », — заголовок раздела (так размечены статьи коллекции).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from glashatai.text.lexicon import Abbreviation

#: слова, с которых обычно начинается немецкое предложение. Нужны, чтобы
#: решить, кончилось ли предложение на «usw.» или на «3.»: «… usw. Die …» —
#: конец, «im 3. Jahrhundert» — нет
STARTERS = set("""
Der Die Das Den Dem Des Ein Eine Einer Eines Einem Einen Es Er Sie Wir Ich Ihr Man Dies Diese Dieser Dieses
Diesen Diesem Damit Dabei Dadurch Daher Darum Dann Danach Daneben Dagegen Darüber Dazu Doch Denn Aber Und
Oder So Somit Also Auch Allerdings Jedoch Trotzdem Zudem Außerdem Ferner Weiterhin Hierbei Hier Heute
Hingegen Insbesondere Im In Am An Auf Aus Bei Mit Nach Seit Von Vor Zu Zum Zur Für Durch Über Unter Um Als
Wenn Weil Da Obwohl Während Wie Was Wer Welche Welcher Welches Wo Nur Erst Bereits Schon Ab Bis Alle Viele
Einige Manche Jede Jeder Jedes Kein Keine Nicht Ohne Sowohl Neben Gegen Laut Trotz Wegen Statt Anschließend
Schließlich Zunächst Zuerst Später Ebenso Beispielsweise Insgesamt Meist Oft Häufig Seine Sein Ihre Unser
Unsere Solche Solch Jene Jener Andere Weitere Nun Gleichzeitig Folglich Demnach Dementsprechend Zusätzlich
""".split())

TERMINAL = ".!?…"
#: после знака конца предложения могут стоять закрывающие кавычки и скобки
CLOSERS = "\"»“”’)]"
#: с чего может начинаться новое предложение
OPENERS = "„\"«‚(['"


@dataclass
class Block:
    """Абзац: положение в тексте, заголовок ли он, предложения внутри."""
    index: int
    start: int
    end: int
    heading: bool = False
    sentences: list[tuple[int, int]] = field(default_factory=list)


def _lines(text: str) -> list[tuple[int, int]]:
    """Строки текста: (начало, конец) без знака перевода строки."""
    result = []
    position = 0
    for line in text.split("\n"):
        result.append((position, position + len(line)))
        position += len(line) + 1
    return result


_BULLET = re.compile(r"^\s*(?:[-•*–·▪]|\d{1,2}[.)]|[a-z][)])\s+")
_HEADING = re.compile(r"^\s*#{1,6}\s")


def _looks_like_heading(line: str) -> bool:
    """Короткая строка без знака препинания в конце: «Einleitung», «2 Grundlagen»."""
    stripped = line.strip()
    if not stripped or len(stripped) > 80 or len(stripped.split()) > 10:
        return False
    if stripped[-1] in ".!?:;,—–-" or not any(ch.isalpha() for ch in stripped):
        return False
    return stripped[0].isupper() or bool(re.match(r"^\d+(\.\d+)*\.?\s+[A-ZÄÖÜ]", stripped))


def paragraphs(text: str) -> list[Block]:
    """Абзацы текста. Заголовки — отдельные абзацы с отметкой heading."""
    blocks: list[Block] = []
    current: Block | None = None
    previous = ""
    lines = _lines(text)
    # есть ли непустые строки после строки i — чтобы не просматривать хвост для каждой строки
    text_after = [False] * len(lines)
    seen = False
    for index in range(len(lines) - 1, -1, -1):
        text_after[index] = seen
        seen = seen or bool(text[lines[index][0]:lines[index][1]].strip())

    def close() -> None:
        nonlocal current
        if current is not None:
            blocks.append(current)
            current = None

    for number, (start, end) in enumerate(lines):
        line = text[start:end]
        stripped = line.strip()
        if not stripped:
            close()
            previous = ""
            continue
        # отступы по краям строки в абзац не входят
        left = start + (len(line) - len(line.lstrip()))
        right = start + len(line.rstrip())
        heading = bool(_HEADING.match(line))
        next_line = text[lines[number + 1][0]:lines[number + 1][1]] if number + 1 < len(lines) else ""
        more_text = text_after[number]
        # строка-заголовок стоит особняком: перед ней пусто, после — пусто или новое предложение
        lone = (not previous) and (not next_line.strip() or _starts_sentence(next_line))
        if not heading and lone and more_text and _looks_like_heading(line):
            heading = True
        new_block = (
            current is None or heading or current.heading or bool(_BULLET.match(line))
            or _ends_sentence(previous) and _starts_sentence(line)
        )
        if new_block:
            close()
            current = Block(len(blocks), left, right, heading)
        else:
            current.end = right
        previous = line
    close()
    for index, block in enumerate(blocks):
        block.index = index
    return blocks


def _ends_sentence(line: str) -> bool:
    stripped = line.rstrip()
    while stripped and stripped[-1] in CLOSERS:
        stripped = stripped[:-1]
    return bool(stripped) and stripped[-1] in TERMINAL + ":;"


def _starts_sentence(line: str) -> bool:
    stripped = line.lstrip()
    return bool(stripped) and (stripped[0].isupper() or stripped[0].isdigit() or stripped[0] in OPENERS
                               or bool(_BULLET.match(line)))


class Segmenter:
    """Делит абзац на предложения с учётом сокращений, порядковых и инициалов."""

    def __init__(self, abbreviations: list[Abbreviation]) -> None:
        self.abbreviations = abbreviations
        alternatives = "|".join(f"(?:{a.pattern})" for a in abbreviations)
        self._abbr = re.compile(rf"(?<![\wÄÖÜäöüß])(?:{alternatives})") if alternatives else None
        self._by_text = {re.sub(r"\s", "", a.written): a for a in abbreviations}

    def _abbreviation_periods(self, text: str, start: int, end: int) -> tuple[set[int], dict[int, Abbreviation]]:
        """Точки внутри сокращений и точки, которыми сокращения кончаются."""
        inside: set[int] = set()
        final: dict[int, Abbreviation] = {}
        if self._abbr is None:
            return inside, final
        for match in self._abbr.finditer(text, start, end):
            found = self._by_text.get(re.sub(r"\s", "", match.group(0)))
            if found is None:
                continue
            last = match.end() - 1
            for position in range(match.start(), last):
                if text[position] == ".":
                    inside.add(position)
            if text[last] == ".":
                final[last] = found
        return inside, final

    def sentences(self, text: str, start: int, end: int) -> list[tuple[int, int]]:
        inside, final = self._abbreviation_periods(text, start, end)
        result: list[tuple[int, int]] = []
        begin = start
        position = start
        while position < end:
            if text[position] not in TERMINAL:
                position += 1
                continue
            first = position
            while position < end and text[position] in TERMINAL:
                position += 1
            while position < end and text[position] in CLOSERS:
                position += 1
            if position >= end:
                break
            if not text[position].isspace():
                continue
            following = position
            while following < end and text[following].isspace():
                following += 1
            if following >= end:
                break
            if self._is_boundary(text, begin, first, position, following, inside, final):
                result.append(self._trim(text, begin, position))
                begin = following
        if begin < end:
            result.append(self._trim(text, begin, end))
        return [span for span in result if span[1] > span[0]]

    @staticmethod
    def _trim(text: str, start: int, end: int) -> tuple[int, int]:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        return start, end

    def _is_boundary(self, text: str, begin: int, first: int, after: int, following: int,
                     inside: set[int], final: dict[int, Abbreviation]) -> bool:
        nxt = text[following]
        if not (nxt.isupper() or nxt.isdigit() or nxt in OPENERS):
            return False
        mark = text[first]
        if mark != ".":
            return True
        word_after = re.match(r"[\wÄÖÜäöüß]+", text[following:following + 40])
        next_word = word_after.group(0) if word_after else ""
        if first in inside:
            return False
        if first in final:
            # сокращение кончается точкой: конец предложения, только если оно
            # из тех, что ставят в конце («usw.»), и дальше идёт начало фразы
            return final[first].when == "end" and next_word in STARTERS
        token = re.search(r"(\S+)$", text[begin:first])
        word = token.group(1) if token else ""
        word = word.lstrip("(\"„«‚'[")
        if re.fullmatch(r"\d{1,3}|\d+(?:\.\d+)+", word):
            # «im 19. Jahrhundert», «am 3. Mai» — порядковое, «1.2. Abschnitt» — номер раздела;
            # «… seit 1954. Danach» — конец
            return next_word in STARTERS
        if re.fullmatch(r"[A-ZÄÖÜ]", word):
            # инициал: «J. von Neumann», «G. Boole»
            return False
        return True

    def split_long(self, text: str, start: int, end: int, limit: int) -> list[tuple[int, int]]:
        """Слишком длинное предложение — на части по «;», «:» и запятым, ближе к середине.

        Части читаются подряд, без паузы предложения: это одно предложение,
        просто синтезатору легче работать с короткими кусками.
        """
        if end - start <= limit:
            return [(start, end)]
        segment = text[start:end]
        best = None
        middle = len(segment) / 2
        for pattern in (r"[;:]\s", r",\s", r"\s[–—]\s", r"\s"):
            candidates = [m.end() for m in re.finditer(pattern, segment) if 20 < m.end() < len(segment) - 20]
            if candidates:
                best = min(candidates, key=lambda cut: abs(cut - middle))
                break
        if best is None:
            return [(start, end)]
        left = self._trim(text, start, start + best)
        right = self._trim(text, start + best, end)
        return self.split_long(text, *left, limit) + self.split_long(text, *right, limit)


def blocks(text: str, segmenter: Segmenter, limit: int | None = None) -> list[Block]:
    """Абзацы с предложениями внутри."""
    result = paragraphs(text)
    for block in result:
        if block.heading:
            block.sentences = [(block.start, block.end)]
            continue
        spans = segmenter.sentences(text, block.start, block.end)
        if limit:
            spans = [part for span in spans for part in segmenter.split_long(text, *span, limit)]
        block.sentences = spans
    return result
