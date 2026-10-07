"""Немецкие числительные: как число записывается словами.

Синтезатор речи цифр не читает — он читает слова. Поэтому «1954»
превращается в „neunzehnhundertvierundfünfzig“, если это год, и в
„eintausendneunhundertvierundfünfzig“, если это количество; «3.» перед
существительным — в порядковое „dritte“, „dritten“ или „dritter“ в
зависимости от того, что стоит перед ним; «3,14» — в „drei Komma eins vier“.

Немецкое числительное до миллиона пишется одним словом: единицы перед
десятками через „und“ („vierundfünfzig“), сотни и тысячи слитно. Длинное
слово синтезаторы читают хуже коротких: им приходится самим угадывать, где
кончается одна часть и начинается другая. Поэтому функции умеют ставить
пробелы между тысячами и сотнями (`spaced=True`): звучит так же, а слова
короче.
"""

from __future__ import annotations

ONES = ["null", "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun",
        "zehn", "elf", "zwölf", "dreizehn", "vierzehn", "fünfzehn", "sechzehn", "siebzehn",
        "achtzehn", "neunzehn"]
TENS = ["", "", "zwanzig", "dreißig", "vierzig", "fünfzig", "sechzig", "siebzig", "achtzig", "neunzig"]

#: большие разряды: (значение, единственное число, множественное); все — женского рода
SCALES = [
    (10 ** 12, "Billion", "Billionen"),
    (10 ** 9, "Milliarde", "Milliarden"),
    (10 ** 6, "Million", "Millionen"),
]

#: порядковые, основа которых не строится по правилу «+t» / «+st»
ORDINAL_STEMS = {1: "erst", 3: "dritt", 7: "siebt", 8: "acht"}

#: окончания порядкового числительного; выбираются по слову перед ним (см. normalize.py)
ORDINAL_ENDINGS = ("e", "en", "er", "es", "em")

MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September",
          "Oktober", "November", "Dezember"]

#: дроби, у которых есть собственное слово знаменателя
DENOMINATORS = {2: "halb", 3: "Drittel", 4: "Viertel", 5: "Fünftel", 6: "Sechstel", 7: "Siebtel",
                8: "Achtel", 9: "Neuntel", 10: "Zehntel", 100: "Hundertstel", 1000: "Tausendstel"}


def _below_hundred(n: int) -> str:
    if n < 20:
        return ONES[n]
    tens, ones = divmod(n, 10)
    if ones == 0:
        return TENS[tens]
    unit = "ein" if ones == 1 else ONES[ones]
    return f"{unit}und{TENS[tens]}"


def _below_thousand(n: int, spaced: bool = False) -> str:
    """0 < n < 1000; «eins» в конце остаётся «eins»: hunderteins."""
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        # «hundert», а не «einhundert»: так число и звучит в речи
        parts.append(("" if hundreds == 1 else ONES[hundreds]) + "hundert")
    if rest:
        parts.append(_below_hundred(rest))
    return (" " if spaced else "").join(parts)


def cardinal(n: int, spaced: bool = False) -> str:
    """Количественное числительное: 1954 -> tausendneunhundertvierundfünfzig.

    Отдельно стоящая единица — „eins“; перед существительным её заменяет
    `article_form` („ein“, „eine“).
    """
    if n < 0:
        return "minus " + cardinal(-n, spaced)
    if n < 1000:
        if n == 0:
            return "null"
        return _below_thousand(n, spaced)
    words: list[str] = []
    rest = n
    for value, single, plural in SCALES:
        count, rest = divmod(rest, value)
        if count:
            if count == 1:
                words.append(f"eine {single}")
            else:
                words.append(f"{cardinal(count, spaced)} {plural}")
    thousands, rest = divmod(rest, 1000)
    tail: list[str] = []
    if thousands:
        head = "" if thousands == 1 else _below_thousand(thousands, spaced)
        if head.endswith("eins"):
            head = head[:-1]          # hunderteintausend
        tail.append(head + "tausend")
    if rest:
        tail.append(_below_thousand(rest, spaced))
    if tail:
        words.append((" " if spaced else "").join(tail))
    return " ".join(words)


def article_form(n: int, gender: str = "n") -> str:
    """Числительное перед существительным: 1 -> ein/eine, остальные как обычно.

    gender — род существительного: m, f, n. «1 Bit» — „ein Bit“, «1 Sekunde» —
    „eine Sekunde“, «21 Sekunden» — „einundzwanzig Sekunden“ (здесь «ein»
    уже внутри слова).
    """
    if n == 1:
        return "eine" if gender == "f" else "ein"
    return cardinal(n)


def year(n: int, spaced: bool = False) -> str:
    """Год: 1954 -> neunzehnhundertvierundfünfzig; 2009 -> zweitausendneun.

    Годы с 1100 по 1999 называются сотнями; остальные — как обычное число.
    """
    if 1100 <= n <= 1999:
        hundreds, rest = divmod(n, 100)
        head = _below_hundred(hundreds) + "hundert"
        if not rest:
            return head
        return head + (" " if spaced else "") + _below_hundred(rest)
    return cardinal(n, spaced)


def ordinal(n: int, ending: str = "e") -> str:
    """Порядковое числительное: 3, «en» -> dritten; 19, «e» -> neunzehnte.

    До 19 основа — число + «t» (vierte, neunzehnte), с 20 — + «st»
    (zwanzigste, hundertste). Составное порядковое меняет только последнюю
    часть: einundzwanzigste.
    """
    if ending not in ORDINAL_ENDINGS:
        ending = "e"
    if n in ORDINAL_STEMS:
        return ORDINAL_STEMS[n] + ending
    if 0 < n < 20:
        return ONES[n] + "t" + ending
    last = n % 100
    if 0 < last < 20 and n > 100:
        # 101. -> hunderterste: последняя часть — порядковое до двадцати
        head = cardinal(n - last)
        return head + ordinal(last, ending)
    word = cardinal(n)
    if word.endswith("eins"):
        word = word[:-1]
    return word + "st" + ending


def decade(n: int) -> str:
    """Десятилетие: 1950 -> neunzehnhundertfünfziger, 80 -> achtziger, 2010 -> zweitausendzehner."""
    rest = n % 100
    tail = TENS[rest // 10] if rest >= 20 else (_below_hundred(rest) if rest else "")
    if n < 100:
        return tail + "er"
    return year(n - rest) + tail + "er"


def digits(text: str) -> str:
    """Цифры по одной: «14» -> «eins vier» (дробная часть, номера)."""
    return " ".join(ONES[int(ch)] for ch in text if ch.isdigit())


def decimal(integer: str, fraction: str) -> str:
    """Десятичная дробь с запятой: 3,14 -> drei Komma eins vier."""
    whole = cardinal(int(integer)) if integer else "null"
    return f"{whole} Komma {digits(fraction)}"


def fraction(numerator: int, denominator: int) -> str | None:
    """Простая дробь словами: 3/4 -> drei Viertel, 1/2 -> ein halb.

    Для знаменателей без собственного слова возвращает None — такое число
    читается как «… durch …» или через «Schrägstrich».
    """
    word = DENOMINATORS.get(denominator)
    if word is None and 10 < denominator < 20:
        word = ONES[denominator].capitalize() + "tel"
    elif word is None and 20 <= denominator < 100:
        word = cardinal(denominator).capitalize() + "stel"
    if word is None:
        return None
    if denominator == 2:
        return "ein halb" if numerator == 1 else f"{cardinal(numerator)} halbe"
    head = "ein" if numerator == 1 else cardinal(numerator)
    return f"{head} {word}"


def month(number: int) -> str | None:
    return MONTHS[number - 1] if 1 <= number <= 12 else None


def time_of_day(hours: int, minutes: int) -> str:
    """12:30 -> zwölf Uhr dreißig; 1:05 -> ein Uhr fünf."""
    head = "ein" if hours == 1 else cardinal(hours)
    if minutes == 0:
        return f"{head} Uhr"
    return f"{head} Uhr {cardinal(minutes)}"
