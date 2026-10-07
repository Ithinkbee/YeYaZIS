"""Аббревиатуры: по буквам или как слово.

Немецкий читатель произносит аббревиатуру одним из двух способов. Короткую
или непроизносимую — по буквам, с немецкими названиями букв и ударением на
последней: «CPU» — „Ze-Pe-U“, «HTTP» — „Ha-Te-Te-Pe“, «KI» — „Ka-I“.
Длинную, в которой гласные и согласные чередуются как в обычном слове, —
как слово: «NASA», «DARPA», «ADALINE». Для исключений («RAM» — „Ramm“,
«JSON» — „Dschäison“) есть словарь acronyms.tsv.

Здесь — названия букв и правило выбора. Названия записаны так, как они
звучат («Zeh», «Peh», «Uh»): так их одинаково прочтёт любой синтезатор,
а собственный синтезатор системы — по своим правилам чтения.
"""

from __future__ import annotations

import re

#: немецкие названия букв, записанные по произношению
LETTERS = {
    "a": "Ah", "b": "Beh", "c": "Zeh", "d": "Deh", "e": "Eh", "f": "Eff", "g": "Geh", "h": "Hah",
    "i": "Ih", "j": "Jott", "k": "Kah", "l": "Ell", "m": "Emm", "n": "Enn", "o": "Oh", "p": "Peh",
    "q": "Kuh", "r": "Err", "s": "Ess", "t": "Teh", "u": "Uh", "v": "Fau", "w": "Weh", "x": "Iks",
    "y": "Üpsilon", "z": "Zett", "ä": "Äh", "ö": "Öh", "ü": "Üh", "ß": "Eszett",
}

#: буквы, которые в слове несут слог
VOWELS = set("AEIOUÄÖÜY")

#: сочетания согласных, с которых может начинаться немецкий слог: «DARPA» —
#: DAR-PA, а «DSGVO» с «DSGV» в начале словом не прочесть
ONSETS = {
    "", "B", "C", "D", "F", "G", "H", "J", "K", "L", "M", "N", "P", "Q", "R", "S", "T", "V", "W", "X", "Z",
    "BL", "BR", "CH", "DR", "FL", "FR", "GL", "GN", "GR", "KL", "KN", "KR", "PL", "PR", "SCH", "SK", "SL",
    "SM", "SN", "SP", "ST", "SW", "TR", "TW", "ZW", "SPR", "STR", "PH", "TH", "SH",
}

ROMAN = {"II": 2, "III": 3, "IV": 4, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "XI": 11, "XII": 12, "XIII": 13,
         "XIV": 14, "XV": 15, "XVI": 16, "XX": 20}


def letter(ch: str) -> str:
    return LETTERS.get(ch.lower(), ch)


def spell(text: str) -> str:
    """По буквам: «CPU» -> «Zeh Peh Uh»; цифры остаются для разбора чисел."""
    return " ".join(letter(ch) for ch in text if ch.isalpha())


def spell_plural(stem: str) -> str:
    """Множественное число аббревиатуры: «URIs» -> «Uh Err Ihs»."""
    spelled = spell(stem)
    return spelled + "s" if spelled else spelled


def pronounceable(word: str) -> bool:
    """Можно ли прочесть аббревиатуру как слово.

    Слово должно быть не короче четырёх букв, а между гласными — не больше
    трёх согласных, причём слог должен начинаться с допустимого сочетания.
    «NASA», «DARPA», «COBOL» проходят; «HTML», «DSGVO», «LSTM» — нет.
    """
    word = word.upper()
    if len(word) < 4 or not re.fullmatch(r"[A-ZÄÖÜ]+", word):
        return False
    if not any(ch in VOWELS for ch in word):
        return False
    groups = re.findall(r"[^AEIOUÄÖÜY]+|[AEIOUÄÖÜY]+", word)
    if len(groups) < 2:
        return False
    for index, group in enumerate(groups):
        if group[0] in VOWELS:
            if len(group) > 2:
                return False
            continue
        if index == 0:
            # начало слова: только допустимое начало слога
            if group not in ONSETS:
                return False
        elif index == len(groups) - 1:
            # конец слова: не больше двух согласных
            if len(group) > 2:
                return False
        else:
            # середина: часть уходит в конец слога, часть начинает следующий
            if len(group) > 3 or not any(group[cut:] in ONSETS for cut in range(len(group) + 1)):
                return False
    return True


def as_word(word: str) -> str:
    """Аббревиатура как слово: «DARPA» -> «Darpa» (с заглавной, как существительное)."""
    return word[:1].upper() + word[1:].lower()


def roman(word: str) -> int | None:
    return ROMAN.get(word)
