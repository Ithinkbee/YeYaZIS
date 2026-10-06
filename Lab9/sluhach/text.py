"""Нормализация фраз, мера их сходства, числительные.

Распознаватель отдаёт фразу строчными буквами и без знаков препинания, а
человек вписывает ключевую фразу как привык — с заглавной буквы, с
вопросительным знаком и с «ё». Чтобы их сравнивать, обе приводятся к одному
виду. Сходство считается по расстоянию Левенштейна: распознаватель ошибается
обычно в одной-двух буквах («ließ vor» вместо «lies vor», «сочинении»
вместо «сочинение»), и такая фраза должна оставаться узнаваемой.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Sequence

#: умлауты и «ß» записываются так, как их пишут без немецкой раскладки, —
#: тогда «öffne» и «oeffne» равны; «ё» и «е» в русском не различаются
_FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "ё": "е"})


def normalize(text: str) -> str:
    """Фраза строчными буквами, без знаков препинания, слова через пробел."""
    folded = unicodedata.normalize("NFC", text or "").lower().translate(_FOLD)
    out: list[str] = []
    for char in folded:
        if "a" <= char <= "z" or "а" <= char <= "я" or char.isdigit():
            out.append(char)
            continue
        # «é» → «e»; кириллица сюда не доходит, поэтому «й» не превращается в «и»
        base = unicodedata.normalize("NFKD", char)[:1]
        out.append(base if "a" <= base <= "z" else " ")
    return " ".join("".join(out).split())


def tokens(text: str) -> list[str]:
    return normalize(text).split()


def script_language(text: str, default: str = "de") -> str:
    """Язык по алфавиту: кириллица — русский, латиница — немецкий."""
    cyrillic = sum(1 for char in text.lower() if "а" <= char <= "я" or char == "ё")
    latin = sum(1 for char in text.lower() if "a" <= char <= "z" or char in "äöüß")
    if not cyrillic and not latin:
        return default
    return "ru" if cyrillic >= latin else "de"


# --- расстояние Левенштейна ----------------------------------------------------

def levenshtein(a: Sequence, b: Sequence) -> int:
    """Наименьшее число вставок, удалений и замен, превращающих a в b."""
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, item in enumerate(a, start=1):
        current = [i]
        for j, other in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (item != other)))
        previous = current
    return previous[-1]


def similarity(a: str, b: str) -> float:
    """Сходство строк от 0 до 1: доля букв, которые не пришлось править."""
    longest = max(len(a), len(b))
    return 1.0 if not longest else 1.0 - levenshtein(a, b) / longest


def phrase_similarity(a: str, b: str) -> float:
    """Сходство двух фраз после нормализации."""
    return similarity(normalize(a), normalize(b))


# --- ошибки распознавания по словам ---------------------------------------------

_SPELLED = re.compile(r"[^\W_]+")


def spelled(text: str) -> list[tuple[str, str]]:
    """Слова фразы парами: как написано и как сравнивается — («Räuber», «raeuber»).

    Вторые элементы пар — в точности `tokens(text)`.
    """
    result: list[tuple[str, str]] = []
    for raw in _SPELLED.findall(unicodedata.normalize("NFC", text or "")):
        result.extend((raw, part) for part in normalize(raw).split())
    return result


@dataclass(frozen=True)
class Aligned:
    """Слово эталона и то, что распознано на его месте."""

    op: str         # ok — совпало, sub — замена, del — пропуск, ins — вставка
    said: str       # слово эталона, как оно написано; у вставки пусто
    heard: str      # распознанное слово; у пропуска пусто


def align(reference: str, hypothesis: str) -> list[Aligned]:
    """Выравнивает слова эталона и распознанной фразы с наименьшим числом правок.

    Слова сравниваются в нормализованном виде, а возвращаются как написаны.
    """
    ref, hyp = spelled(reference), spelled(hypothesis)
    rows, cols = len(ref) + 1, len(hyp) + 1
    # Цена — пара: число правок и то, насколько непохожи слова, поставленные друг против
    # друга. Правок всегда наименьшее число, а из равных выравниваний выбирается то, где на
    # месте слова стоит похожее: «сочинении» заменяет «сочинение», а не «три»
    cost = [[(0, 0.0)] * cols for _ in range(rows)]
    step = [[""] * cols for _ in range(rows)]
    for i in range(1, rows):
        cost[i][0], step[i][0] = (i, float(i)), "del"
    for j in range(1, cols):
        cost[0][j], step[0][j] = (j, float(j)), "ins"
    for i in range(1, rows):
        for j in range(1, cols):
            same = ref[i - 1][1] == hyp[j - 1][1]
            apart = 0.0 if same else 1.0 - similarity(ref[i - 1][1], hyp[j - 1][1])
            cost[i][j], step[i][j] = min(
                ((cost[i - 1][j - 1][0] + (not same), cost[i - 1][j - 1][1] + apart), "ok" if same else "sub"),
                ((cost[i - 1][j][0] + 1, cost[i - 1][j][1] + 1.0), "del"),
                ((cost[i][j - 1][0] + 1, cost[i][j - 1][1] + 1.0), "ins"),
                key=lambda option: option[0])
    result: list[Aligned] = []
    i, j = len(ref), len(hyp)
    while i > 0 or j > 0:
        op = step[i][j]
        if op in ("ok", "sub"):
            result.append(Aligned(op, ref[i - 1][0], hyp[j - 1][0]))
            i, j = i - 1, j - 1
        elif op == "del":
            result.append(Aligned("del", ref[i - 1][0], ""))
            i -= 1
        else:
            result.append(Aligned("ins", "", hyp[j - 1][0]))
            j -= 1
    result.reverse()
    return result


@dataclass(frozen=True)
class WordErrors:
    """Сравнение распознанной фразы с эталоном: замены, пропуски и вставки слов."""

    reference: int
    substitutions: int
    deletions: int
    insertions: int

    @property
    def errors(self) -> int:
        return self.substitutions + self.deletions + self.insertions

    @property
    def rate(self) -> float:
        """WER — доля ошибок от числа слов эталона."""
        return self.errors / self.reference if self.reference else float(self.errors > 0)


def word_errors(reference: str, hypothesis: str) -> WordErrors:
    """Выравнивает слова эталона и гипотезы и считает ошибки каждого вида."""
    counts = {"ok": 0, "sub": 0, "del": 0, "ins": 0}
    for item in align(reference, hypothesis):
        counts[item.op] += 1
    return WordErrors(counts["ok"] + counts["sub"] + counts["del"], counts["sub"], counts["del"], counts["ins"])


# --- числительные ------------------------------------------------------------------
#
# Vosk пишет числа словами («drei», «двадцать три»), распознаватель браузера —
# цифрами («3»). Номер сочинения или абзаца нужно понять в обоих видах, а по-
# русски ещё и в порядковой форме: «открой третье сочинение».

_RU_CARDINALS = {
    "ноль": 0, "один": 1, "одна": 1, "одно": 1, "одну": 1, "два": 2, "две": 2, "три": 3,
    "четыре": 4, "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10,
    "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13, "четырнадцать": 14, "пятнадцать": 15,
    "шестнадцать": 16, "семнадцать": 17, "восемнадцать": 18, "девятнадцать": 19, "двадцать": 20,
    "тридцать": 30, "сорок": 40, "пятьдесят": 50, "шестьдесят": 60, "семьдесят": 70,
    "восемьдесят": 80, "девяносто": 90,
}
#: основы порядковых числительных: «трет» + «ий», «ье», «ьего»…
_RU_ORDINAL_STEMS = {
    "перв": 1, "втор": 2, "трет": 3, "четверт": 4, "пят": 5, "шест": 6, "седьм": 7, "восьм": 8,
    "девят": 9, "десят": 10, "одиннадцат": 11, "двенадцат": 12, "тринадцат": 13, "четырнадцат": 14,
    "пятнадцат": 15, "шестнадцат": 16, "семнадцат": 17, "восемнадцат": 18, "девятнадцат": 19,
    "двадцат": 20, "тридцат": 30, "сороков": 40, "пятидесят": 50, "шестидесят": 60,
}
_RU_ORDINAL_ENDINGS = (
    "ый", "ой", "ий", "ая", "ое", "ее", "ые", "ого", "его", "ому", "ему", "ым", "им", "ом", "ем",
    "ую", "ых", "ья", "ье", "ью", "ьи", "ьего", "ьему", "ьем", "ьей", "ей",
)

_DE_CARDINALS = {
    "null": 0, "ein": 1, "eins": 1, "eine": 1, "einen": 1, "einem": 1, "einer": 1, "zwei": 2, "zwo": 2,
    "drei": 3, "vier": 4, "fuenf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10,
    "elf": 11, "zwoelf": 12, "dreizehn": 13, "vierzehn": 14, "fuenfzehn": 15, "sechzehn": 16,
    "siebzehn": 17, "achtzehn": 18, "neunzehn": 19, "zwanzig": 20, "dreissig": 30, "vierzig": 40,
    "fuenfzig": 50, "sechzig": 60, "siebzig": 70, "achtzig": 80, "neunzig": 90,
}
#: порядковые числительные без окончания: «dritt» + «e», «en», «er»…
_DE_ORDINALS = {
    "erst": 1, "zweit": 2, "dritt": 3, "viert": 4, "fuenft": 5, "sechst": 6, "siebt": 7, "siebent": 7,
    "acht": 8, "neunt": 9, "zehnt": 10, "elft": 11, "zwoelft": 12,
}
_DE_COMPOUND = re.compile(r"(ein|zwei|drei|vier|fuenf|sechs|sieben|acht|neun)und"
                          r"(zwanzig|dreissig|vierzig|fuenfzig|sechzig|siebzig|achtzig|neunzig)")
_DE_ENDING = re.compile(r"(.+?)(en|er|es|em|e)")

#: слова перед числом, которые числом не являются: «номер три», „Nummer drei“
_NUMBER_PREFIXES = {"номер", "номером", "номера", "под", "nummer", "nr", "no"}


def _ru_number(word: str) -> int | None:
    if word in _RU_CARDINALS:
        return _RU_CARDINALS[word]
    for stem, value in _RU_ORDINAL_STEMS.items():
        if word.startswith(stem) and word[len(stem):] in _RU_ORDINAL_ENDINGS:
            return value
    return None


def _de_cardinal(word: str) -> int | None:
    if word in _DE_CARDINALS:
        return _DE_CARDINALS[word]
    match = _DE_COMPOUND.fullmatch(word)
    if match:
        return _DE_CARDINALS[match.group(2)] + _DE_CARDINALS[match.group(1)]
    return None


def _de_number(word: str) -> int | None:
    value = _de_cardinal(word)
    if value is not None:
        return value
    match = _DE_ENDING.fullmatch(word)
    if not match:
        return None
    base = match.group(1)
    if base in _DE_ORDINALS:
        return _DE_ORDINALS[base]
    if base.endswith("st"):                       # zwanzigste, einundzwanzigsten
        value = _de_cardinal(base[:-2])
        return value if value is not None and value >= 20 else None
    if base.endswith("t"):                        # dreizehnte … neunzehnte
        value = _de_cardinal(base[:-1])
        return value if value is not None and 13 <= value <= 19 else None
    return None


def parse_number(words: Sequence[str], language: str) -> int | None:
    """Первое число во фразе: цифрами или словами, количественное или порядковое.

    Слова должны быть нормализованы (см. `tokens`). По-русски десятки и
    единицы — два слова («двадцать три»), по-немецки одно („dreiundzwanzig“).
    """
    single = _ru_number if language == "ru" else _de_number
    for index, word in enumerate(words):
        if word in _NUMBER_PREFIXES:
            continue
        if word.isdigit():
            return int(word) if len(word) <= 4 else None
        value = single(word)
        if value is None:
            continue
        if language == "ru" and value >= 20 and value % 10 == 0 and index + 1 < len(words):
            unit = single(words[index + 1])
            if unit is not None and 1 <= unit <= 9:
                return value + unit
        return value
    return None


def _number_words(language: str) -> dict[str, int]:
    """Числительные языка — то, с чем сверяется число, расслышанное с ошибкой."""
    if language == "ru":
        words = dict(_RU_CARDINALS)
        for stem, value in _RU_ORDINAL_STEMS.items():
            words[stem + ("ий" if stem == "трет" else "ой" if stem in {"втор", "шест", "седьм", "восьм", "сороков"}
                          else "ый")] = value
        return words
    words = dict(_DE_CARDINALS)
    words.update({base + "e": value for base, value in _DE_ORDINALS.items()})
    for tens in ("zwanzig", "dreissig", "vierzig", "fuenfzig"):
        for unit in ("ein", "zwei", "drei", "vier", "fuenf", "sechs", "sieben", "acht", "neun"):
            words[f"{unit}und{tens}"] = _DE_CARDINALS[tens] + _DE_CARDINALS[unit]
    return words


#: насколько расслышанное должно быть похоже на числительное
NUMBER_GUESS = 0.75


def guess_number(words: Sequence[str], language: str) -> int | None:
    """Число, даже если распознаватель исказил или разорвал слово: «sie bin» — это „sieben“.

    Сначала число ищется как есть; если его нет, слова параметра склеиваются
    и сравниваются с числительными языка по сходству букв.
    """
    exact = parse_number(words, language)
    if exact is not None:
        return exact
    heard = [word for word in words if word not in _NUMBER_PREFIXES]
    if not heard:
        return None
    best, best_score = None, 0.0
    for candidate in {"".join(heard), *heard}:
        if len(candidate) < 3:
            continue
        for word, value in _number_words(language).items():
            score = similarity(candidate, word)
            if score > best_score:
                best, best_score = value, score
    return best if best_score >= NUMBER_GUESS else None


# --- склонение при числе -----------------------------------------------------------

def plural_ru(number: int, one: str, few: str, many: str) -> str:
    """Форма слова при числе: 1 абзац, 3 абзаца, 5 абзацев, 21 абзац."""
    number = abs(number)
    if number % 10 == 1 and number % 100 != 11:
        return one
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return few
    return many


def plural_de(number: int, one: str, many: str) -> str:
    return one if abs(number) == 1 else many
