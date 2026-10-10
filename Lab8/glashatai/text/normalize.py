"""Нормализация немецкого научного текста: что и как произносится.

Синтезатор речи читает слова. В научной статье по информатике слов в
обычном смысле меньше, чем кажется: «1954», «3,5 %», «z. B.», «CPU»,
«IPv6», «O(n log n)», «12 GB», «[12]», «JIT-Compiler», «Deep Learning». Если
отдать их синтезатору как есть, он прочтёт «1954» как количество, разорвёт
предложение на точке в «z. B.», произнесёт «Cloud» как «Клут». Нормализация
решает за него:

* числа: количество, год, порядковое с падежным окончанием, десятичная
  дробь, диапазон, дата, время, десятилетие, номер версии, простая дробь;
* единицы после числа — с родом и числом: «1 Sekunde», «12 Gigabyte»;
* сокращения — по словарю: «z. B.» — „zum Beispiel“;
* аббревиатуры — по буквам или как слово, по словарю или по правилу;
* знаки формул и греческие буквы, адреса, ссылки на источники;
* английские термины — по записи немецкими буквами из словаря.

Каждый кусок текста становится токеном, который помнит своё место в
исходном тексте, запись после нормализации (`written`: „zwölf Gigabyte“) и
произношение (`say`: „zwölf Gigabait“). По месту страница подсвечивает
прочитанное; запись видна во вкладке «Как прочтёт»; произношение получает
синтезатор.
"""

from __future__ import annotations

import re
import threading
from dataclasses import asdict, dataclass, field, fields

from glashatai.text import acronyms, numbers
from glashatai.text.lexicon import Entry, Lexicon
from glashatai.text.units import MATH, SYMBOLS, UNITS

#: названия видов токенов для страницы
KINDS = {
    "word": "слово", "number": "число", "year": "год", "ordinal": "порядковое числительное",
    "decimal": "десятичная дробь", "range": "диапазон", "date": "дата", "time": "время",
    "decade": "десятилетие", "version": "номер версии", "fraction": "дробь", "unit": "число с единицей",
    "abbreviation": "сокращение", "acronym": "аббревиатура", "english": "английский термин",
    "user": "словарь пользователя", "symbol": "знак", "formula": "формула", "url": "адрес сайта",
    "email": "электронная почта", "citation": "ссылка на источник", "roman": "римская цифра",
    "letter": "буква", "mixed": "буквы и цифры", "punct": "знак препинания", "space": "пробел",
    "quote": "кавычки", "pause": "пауза", "heading": "заголовок",
}

#: эти виды токенов только отделяют слова друг от друга
SEPARATORS = {"space", "punct", "quote", "pause"}

#: после этих слов порядковое стоит в дательном или родительном падеже: «am dritten»
_DATIVE = {"am", "im", "vom", "zum", "beim", "dem", "den", "des", "einem", "einen", "eines", "diesem", "diesen",
           "dieses", "seinem", "seinen", "ihrem", "ihren", "jedem", "jeden", "zur", "einer", "ab", "bis", "seit",
           "vor", "nach", "zwischen", "unserem", "unseren"}
_PREPOSITIONS = {"in", "an", "auf", "aus", "bei", "mit", "nach", "von", "zu", "seit", "vor", "während", "wegen",
                 "trotz", "unter", "über", "hinter", "neben", "zwischen", "ab", "bis", "gegenüber", "laut", "gemäß"}
_MONTHS = set(numbers.MONTHS) | {"Jänner"}
#: предлоги, после которых «1» перед существительным — «einem», «einer»
_DATIVE_PREPOSITIONS = {"mit", "nach", "von", "aus", "bei", "seit", "zu", "gegenüber", "nebst", "samt"}

#: окончания существительных женского рода: перед ними «1» читается «eine»
_FEMININE = ("ung", "heit", "keit", "schaft", "ion", "tät", "ie", "ik", "ur", "enz", "anz", "ei", "in", "e")
#: существительные на «-e» и «-in» мужского и среднего рода
_NOT_FEMININE = {"ende", "name", "auge", "interesse", "gebäude", "gelände", "erbe", "käse", "junge", "kunde",
                 "experte", "bote", "affe", "löwe", "hase", "gedanke", "glaube", "wille", "friede", "buchstabe",
                 "termin", "benzin", "magazin", "medizin", "protein", "vitamin", "ruin", "pinguin", "kamin",
                 "teil", "bit", "byte", "programm", "computer", "prozess", "modell", "verfahren", "netz",
                 "beispiel", "element", "kriterium", "zeichen", "jahr"}


def feminine(noun: str) -> bool:
    """Женского ли рода существительное — по окончанию; для «1» перед ним."""
    word = noun.lower()
    if word in _NOT_FEMININE:
        return False
    return word.endswith(_FEMININE)


@dataclass
class ReadingOptions:
    """Правила чтения; каждое можно выключить на странице «Настройки чтения»."""
    numbers: bool = True            # числа, даты, единицы словами
    abbreviations: bool = True      # сокращения полностью
    acronyms: bool = True           # аббревиатуры по буквам или по словарю
    english: bool = True            # английские термины по-английски
    formulas: bool = True           # знаки формул словами
    citations: bool = False         # «[12]» читать как «Quelle zwölf»; иначе пропускать
    urls: str = "short"             # адреса: short — только сайт, full — целиком, skip — пропускать
    lexicon: bool = True            # словарь пользователя

    @classmethod
    def from_dict(cls, raw: dict | None) -> "ReadingOptions":
        options = cls()
        for item in fields(cls):
            if raw and item.name in raw:
                value = raw[item.name]
                if item.type == "bool" or isinstance(getattr(options, item.name), bool):
                    setattr(options, item.name, bool(value))
                elif item.name == "urls" and value in ("short", "full", "skip"):
                    options.urls = value
        return options

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def is_raw(self) -> bool:
        """Все правила выключены: синтезатор получает текст как есть."""
        return not (self.numbers or self.abbreviations or self.acronyms or self.english or self.formulas
                    or self.lexicon)

    @classmethod
    def raw(cls) -> "ReadingOptions":
        """Без нормализации: текст уходит синтезатору как есть (для сравнения на проверке)."""
        return cls(numbers=False, abbreviations=False, acronyms=False, english=False, formulas=False,
                   citations=True, urls="full", lexicon=False)


@dataclass
class Token:
    start: int              # положение в исходном тексте
    end: int
    text: str               # как написано
    written: str            # как записывается словами
    say: str                # как произносится (немецкими буквами, апостроф — ударение)
    kind: str = "word"
    lang: str = "de"        # en — термин произносится по-английски

    @property
    def changed(self) -> bool:
        return self.kind not in SEPARATORS and self.say.replace("'", "") != self.text

    def to_dict(self) -> dict:
        return {"start": self.start, "end": self.end, "text": self.text, "written": self.written,
                "say": self.say.replace("'", ""), "kind": self.kind, "kind_ru": KINDS.get(self.kind, self.kind)}


@dataclass
class Sentence:
    """Предложение: место в тексте, токены и всё, что нужно синтезатору."""
    index: int
    paragraph: int
    start: int
    end: int
    text: str
    tokens: list[Token] = field(default_factory=list)
    heading: bool = False
    #: часть длинного предложения, за которой предложение продолжается (без паузы)
    continued: bool = False
    #: без нормализации: синтезатору уходит исходный текст
    raw: bool = False

    def render(self, mode: str = "say") -> str:
        """Текст для синтезатора.

        mode: say — произношение с отметками ударения (собственный синтезатор);
        plain — произношение без отметок (голоса Windows); written — запись
        словами, английские термины как написаны (голоса браузера);
        normalized — запись словами, аббревиатуры по буквам (проверка).
        """
        if self.raw:
            return self.text
        parts = []
        for token in self.tokens:
            if mode == "normalized":
                # запись словами, но аббревиатуры — как читаются: так нормализацию сверяют с эталоном
                spelled = token.kind in {"acronym", "mixed", "letter", "roman"}
                parts.append(token.say.replace("'", "") if spelled else token.written)
            elif mode == "written":
                parts.append(token.written)
            elif mode == "plain":
                parts.append(token.say.replace("'", ""))
            else:
                parts.append(token.say)
        return tidy("".join(parts), final=not self.continued)

    @property
    def kind(self) -> str:
        """Вид предложения для интонации: вопрос, восклицание, утверждение."""
        stripped = self.text.rstrip("\"»“”’)] ")
        if stripped.endswith("?"):
            return "question"
        if stripped.endswith("!"):
            return "exclamation"
        return "statement"

    def to_dict(self) -> dict:
        return {"index": self.index, "paragraph": self.paragraph, "start": self.start, "end": self.end,
                "text": self.text, "heading": self.heading, "continued": self.continued, "kind": self.kind,
                "say": self.render("plain"), "written": self.render("written"),
                "changes": [token.to_dict() for token in self.tokens if token.changed]}


def tidy(text: str, final: bool = True) -> str:
    """Чистка собранного текста: пробелы, повторы знаков, точки внутри предложения.

    Точка внутри предложения для синтезатора — конец предложения: eSpeak NG
    разрывает на ней фразу и роняет интонацию. Поэтому внутри остаются только
    запятые, а точка — в конце.
    """
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,;:])(?:\s*[,;:])+", r"\1", text)
    text = re.sub(r"^[\s,;:.]+", "", text)
    body = text.rstrip()
    end = ""
    match = re.search(r"[.!?]+$", body)
    if match:
        end = match.group(0)[0] if match.group(0)[0] in "!?" else "."
        body = body[: match.start()]
    body = re.sub(r"\.(?=\s|$)", ",", body)
    body = re.sub(r"[!?](?=\s)", ",", body)
    body = re.sub(r"([,;:])(?:\s*[,;:])+", r"\1", body).rstrip(" ,;:")
    if not final:
        return body
    return body + (end or ".") if body else ""


_W = "A-Za-zÄÖÜäöüßÀ-ÖØ-öø-ÿ"


class Normalizer:
    """Разбирает предложение на токены и решает, как каждый произносится."""

    def __init__(self, lexicon: Lexicon) -> None:
        self.lexicon = lexicon
        self._version = -1
        self._patterns: dict[bool, re.Pattern] = {}
        self._users: dict[str, Entry] = {}
        self._specials = {e.written: e for e in lexicon.acronyms if re.search(rf"[^{_W}0-9]", e.written)}
        self._abbr = {re.sub(r"\s", "", a.written): a for a in lexicon.abbreviations}
        #: открытые скобки записи функции «O(…)» — свои у каждого потока: сервер разбирает
        #: несколько предложений одновременно
        self._local = threading.local()

    # --- регулярное выражение ---------------------------------------------------------

    def _build(self, with_user: bool) -> re.Pattern:
        users = sorted(self.lexicon.user_entries(), key=lambda e: -len(e.written)) if with_user else []
        if with_user:
            self._users = {e.written.lower(): e for e in users}
        abbreviations = []
        for item in self.lexicon.abbreviations:
            pattern = item.pattern
            if item.when == "number":
                pattern += r"(?=\s?\d)"
            elif item.when == "after":
                pattern = r"(?<=\d\s)" + pattern
            abbreviations.append(pattern)
        unit_keys = sorted(UNITS, key=len, reverse=True)
        units = "|".join(re.escape(key) for key in unit_keys)
        specials = "|".join(re.escape(key) for key in sorted(self._specials, key=len, reverse=True))
        parts = []
        if users:
            alternatives = "|".join(re.escape(e.written) for e in users)
            parts.append(rf"(?P<user>(?<![{_W}0-9])(?i:{alternatives})(?![{_W}0-9]))")
        parts += [
            r"(?P<url>(?:https?://|www\.)[^\s<>\"„“”]+[^\s<>\"„“”.,;:!?)\]])",
            r"(?P<email>[\w.+-]+@[\w-]+(?:\.[\w-]+)+)",
            r"(?P<citation>\[(?:\d+(?:\s*[,;–-]\s*\d+)*|…|\.\.\.)\])",
            r"(?P<date>(?<![\d.])(?P<date_d>\d{1,2})\.\s?(?P<date_m>\d{1,2})\.\s?(?P<date_y>\d{4}|\d{2})(?![\d.,]\d))",
            r"(?P<time>(?<![\d:])(?P<time_h>\d{1,3}):(?P<time_m>\d{1,3})(?![\d:])(?:\s?(?P<time_uhr>Uhr)\b)?)",
            rf"(?P<special>{specials})" if specials else None,
            rf"(?P<abbr>(?<![{_W}])(?:{'|'.join(abbreviations)}))" if abbreviations else None,
            rf"(?P<decade>(?<![\d.,])(?P<decade_n>\d{{2,4}})er(?P<decade_end>n|s)?(?P<decade_years>-Jahre[n]?)?(?![{_W}]))",
            r"(?P<range>(?<![\w.,])(?P<range_a>\d+)\s?[–—-]\s?(?P<range_b>\d+)(?![.,]?\d)(?![\w]))",
            r"(?P<version>(?<![\w.,])(?!\d{1,3}(?:\.\d{3})+(?![\d.]))\d+(?:\.\d+)+(?!\d|,\d))",
            rf"(?P<ordinal>(?<![\w.,])(?P<ordinal_n>\d{{1,3}})\.(?=\s+[{_W}„\"(]))",
            r"(?P<fraction>(?<![\w/.,])(?P<fraction_a>\d+)/(?P<fraction_b>\d+)(?![\w/]))",
            r"(?P<power>(?P<power_a>\d+|[A-Za-z])\^(?P<power_b>-?\d+|[A-Za-z]))",
            rf"(?P<num>(?<![\w.,])(?P<num_sign>-(?=\d))?(?P<num_int>\d{{1,3}}(?:[.\u00a0\u202f]\d{{3}})+(?!\d)"
            rf"|\d{{1,3}}(?: \d{{3}})+(?![\d.,])|\d+)"
            rf"(?:,(?P<num_frac>\d+))?(?![\d{_W}])(?:(?P<num_space>\s?)(?P<num_unit>{units})(?![{_W}0-9]))?)",
            rf"(?P<mixed>(?<![{_W}0-9])(?=[{_W}]*[0-9])(?=[0-9]*[{_W}])[{_W}0-9]+(?![{_W}0-9]))",
            rf"(?P<acronym>(?<![{_W}0-9])[A-ZÄÖÜ]{{2,}}[a-z]?(?![{_W}0-9]))",
            rf"(?P<word>[{_W}]+(?:'[a-z]{{1,2}}(?![{_W}]))?)",
            r"(?P<space>\s+)",
            r"(?P<punct>[.,;:!?…]+)",
            r"(?P<quote>[„“”\"‚‘’'«»›‹])",
            r"(?P<paren>[()\[\]{}])",
            r"(?P<dash>\s[–—-]\s|[–—])",
            r"(?P<hyphen>-)",
            r"(?P<slash>/)",
            r"(?P<other>.)",
        ]
        return re.compile("|".join(part for part in parts if part), re.S)

    def _ensure(self, with_user: bool = True) -> re.Pattern:
        """Выражение разбора; пересобирается, когда пользователь меняет словарь."""
        if self._version != self.lexicon.version:
            self._patterns = {}
            self._version = self.lexicon.version
        if with_user not in self._patterns:
            self._patterns[with_user] = self._build(with_user)
        return self._patterns[with_user]

    # --- разбор -------------------------------------------------------------------------

    def tokens(self, text: str, start: int = 0, end: int | None = None,
               options: ReadingOptions | None = None) -> list[Token]:
        """Токены куска text[start:end]; положения — в координатах всего текста."""
        options = options or ReadingOptions()
        end = len(text) if end is None else end
        pattern = self._ensure(options.lexicon)
        result: list[Token] = []
        self._local.calls = 0
        for match in pattern.finditer(text, start, end):
            result.extend(self._token(match, text, options, result))
        self._context(result, options)
        if options.english:
            result = self._english(result)
        return result

    def _make(self, match: re.Match, written: str, kind: str, say: str | None = None, lang: str = "de") -> Token:
        return Token(match.start(), match.end(), match.group(0), written, written if say is None else say, kind, lang)

    def _raw(self, match: re.Match) -> Token:
        """Кусок, который правило не трогает: синтезатор получит его как есть."""
        return self._make(match, match.group(0), "word")

    def _token(self, match: re.Match, text: str, options: ReadingOptions, before: list[Token]) -> list[Token]:
        kind = match.lastgroup
        value = match.group(0)
        group = match.group

        if kind == "user":
            entry = self._users.get(value.lower())
            return [self._make(match, value, "user", entry.reading if entry else value)]

        if kind == "url":
            return [self._url(match, options)]

        if kind == "email":
            name, host = value.split("@", 1)
            spoken = f"{self._dotted(name)} at {self._dotted(host)}"
            return [self._make(match, spoken, "email")]

        if kind == "citation":
            if not options.citations:
                return [self._make(match, "", "citation")]
            found = [int(n) for n in re.findall(r"\d+", value)]
            if not found:
                return [self._make(match, "", "citation")]
            words = " und ".join(numbers.cardinal(n) for n in found)
            return [self._make(match, ("Quellen " if len(found) > 1 else "Quelle ") + words, "citation")]

        if not options.numbers and kind in {"date", "time", "decade", "range", "version", "ordinal", "fraction",
                                            "power", "num"}:
            return [self._raw(match)]

        if kind == "date":
            day, month, year = int(group("date_d")), int(group("date_m")), group("date_y")
            name = numbers.month(month)
            if name is None or not 1 <= day <= 31:
                return [self._make(match, " ".join(numbers.cardinal(int(x)) for x in re.findall(r"\d+", value)),
                                   "number")]
            year_words = numbers.year(int(year)) if len(year) == 4 else numbers.cardinal(int(year))
            token = self._make(match, f"{numbers.ordinal(day, 'er')} {name} {year_words}", "date")
            token.say = token.written
            return [token]

        if kind == "time":
            hours, minutes = int(group("time_h")), int(group("time_m"))
            clock = len(group("time_m")) == 2 and hours <= 24 and minutes < 60
            if clock and (group("time_uhr") or self._previous_word(before) in {"um", "gegen", "ab", "bis", "von",
                                                                              "seit"}):
                return [self._make(match, numbers.time_of_day(hours, minutes), "time")]
            return [self._make(match, f"{numbers.cardinal(hours)} zu {numbers.cardinal(minutes)}", "number")]

        if kind == "special":
            entry = self._specials.get(value)
            if not options.acronyms or entry is None:
                return [self._raw(match)]
            return [self._make(match, value, "acronym", entry.reading)]

        if kind == "abbr":
            if not options.abbreviations:
                return [self._raw(match)]
            found = self._abbr.get(re.sub(r"\s", "", value))
            if found is None:
                return [self._raw(match)]
            return [self._make(match, found.expansion, "abbreviation")]

        if kind == "decade":
            n = int(group("decade_n"))
            word = numbers.decade(n) + (group("decade_end") or "")
            years = group("decade_years")
            if years:
                word += " " + years.lstrip("-")
            return [self._make(match, word, "decade")]

        if kind == "range":
            a, b = int(group("range_a")), int(group("range_b"))
            both_years = all(1100 <= n <= 2099 for n in (a, b)) and len(group("range_a")) == 4
            say = numbers.year if both_years else numbers.cardinal
            return [self._make(match, f"{say(a)} bis {say(b)}", "range")]

        if kind == "version":
            parts = value.split(".")
            words = [numbers.digits(part) if part.startswith("0") and len(part) > 1 else numbers.cardinal(int(part))
                     for part in parts]
            return [self._make(match, " Punkt ".join(words), "version")]

        if kind == "ordinal":
            n = int(group("ordinal_n"))
            # окончание уточнит разбор контекста; пока — именительный падеж
            token = self._make(match, numbers.ordinal(n, "e"), "ordinal")
            return [token]

        if kind == "fraction":
            a, b = int(group("fraction_a")), int(group("fraction_b"))
            words = numbers.fraction(a, b) if 0 < a < b <= 100 else None
            if words is None:
                return [self._make(match, f"{numbers.cardinal(a)} Schrägstrich {numbers.cardinal(b)}", "number")]
            return [self._make(match, words, "fraction")]

        if kind == "power":
            if not options.formulas:
                return [self._raw(match)]
            a, b = group("power_a"), group("power_b")
            return [self._make(match, f"{self._operand(a)} hoch {self._operand(b)}", "formula")]

        if kind == "num":
            return [self._number(match)]

        if kind == "mixed":
            entry = self.lexicon.acronym(value)
            if entry is not None and options.acronyms:
                return [self._make(match, value, "acronym", entry.reading)]
            if not options.acronyms:
                return [self._raw(match)]
            return [self._make(match, self._mixed(value), "mixed")]

        if kind == "acronym":
            return [self._acronym(match, options, before)]

        if kind == "word":
            return [self._word(match, options)]

        if kind == "space":
            return [self._make(match, " ", "space")]

        if kind == "punct":
            marks = value
            if "…" in marks or marks == "...":
                marks = ","
            previous = before[-1] if before else None
            if (marks == "." and previous is not None and previous.kind == "letter" and previous.text.isupper()
                    and re.match(r"\s+[A-ZÄÖÜa-zäöü]", text[match.end():match.end() + 3])):
                # инициал: «J. von Neumann» — точка не читается и паузы не даёт
                return [self._make(match, "", "quote")]
            return [self._make(match, marks[0] if marks[0] in "!?" else marks[-1], "punct")]

        if kind == "quote":
            return [self._make(match, "", "quote")]

        if kind == "paren" and options.formulas:
            previous = before[-1] if before else None
            if value == "(" and previous is not None and previous.kind in {"letter", "word", "acronym"} and                     previous.end == match.start() and len(previous.text) <= 3:
                # запись функции: «O(n log n)» — „O von n log n“
                self._local.calls = getattr(self._local, "calls", 0) + 1
                return [self._make(match, " von ", "formula")]
            if value == ")" and getattr(self._local, "calls", 0) > 0:
                self._local.calls -= 1
                return [self._make(match, " ", "formula")]

        if kind in {"paren", "dash"}:
            return [self._make(match, ", ", "pause")]

        if kind in {"hyphen", "slash"}:
            return [self._make(match, " ", "space")]

        # прочие знаки
        if value in SYMBOLS:
            if value in MATH and not options.formulas:
                return [self._make(match, value, "symbol")]
            word = SYMBOLS[value]
            if value == "²" or value == "³":
                return [self._make(match, " " + word, "formula")]
            return [self._make(match, f" {word} ", "formula" if value in MATH else "symbol")]
        if value == "#":
            return [self._make(match, "", "symbol")]
        if value == "*":
            return [self._make(match, " mal " if options.formulas else "", "formula")]
        if value == "~":
            return [self._make(match, " ungefähr ", "symbol")]
        return [self._make(match, "", "symbol")]

    # --- отдельные виды -------------------------------------------------------------------

    @staticmethod
    def _previous_word(before: list[Token]) -> str:
        for token in reversed(before):
            if token.kind in SEPARATORS:
                if token.kind == "punct":
                    return ""
                continue
            return token.text.lower()
        return ""

    def _dotted(self, text: str) -> str:
        """«de.wikipedia.org» -> «Deh Eh Punkt wikipedia Punkt org»."""
        words = []
        for part in re.split(r"([./_-])", text):
            if not part:
                continue
            if part == ".":
                words.append("Punkt")
            elif part == "/":
                words.append("Schrägstrich")
            elif part in "_-":
                words.append("Strich")
            elif part.isdigit():
                words.append(numbers.cardinal(int(part)) if len(part) <= 4 else numbers.digits(part))
            elif re.search(r"\d", part):
                words.append(self._mixed(part))
            elif len(part) <= 2:
                words.append(acronyms.spell(part))
            else:
                words.append(part)
        return " ".join(words)

    def _url(self, match: re.Match, options: ReadingOptions) -> Token:
        value = match.group(0)
        if options.urls == "skip":
            return self._make(match, "", "url")
        body = re.sub(r"^(?:https?://)?(?:www\.)?", "", value)
        host, _, path = body.partition("/")
        spoken = self._dotted(host)
        if options.urls == "full" and path:
            spoken += " Schrägstrich " + self._dotted(path.rstrip("/"))
        return self._make(match, spoken, "url")

    @staticmethod
    def _operand(value: str) -> str:
        if value.lstrip("-").isdigit():
            n = int(value)
            return numbers.cardinal(n)
        return acronyms.letter(value)

    def _number(self, match: re.Match) -> Token:
        group = match.group
        digits_text = re.sub(r"[.\u00a0\u202f ]", "", group("num_int"))
        n = int(digits_text)
        negative = bool(group("num_sign"))
        fraction = group("num_frac")
        unit = group("num_unit")
        grouped = digits_text != group("num_int")
        if fraction is not None:
            words = numbers.decimal(digits_text, fraction)
            kind = "decimal"
        elif unit is None and not grouped and not negative and 1100 <= n <= 1999:
            words = numbers.year(n)
            kind = "year"
        elif len(digits_text) > 1 and digits_text.startswith("0"):
            words = numbers.digits(digits_text)
            kind = "number"
        else:
            words = numbers.cardinal(n)
            kind = "number"
        if negative:
            words = "minus " + words
        if unit:
            single, plural, gender = UNITS[unit]
            if fraction is None and n == 1 and not negative:
                words = numbers.article_form(1, gender)
                unit_words = single
            else:
                unit_words = plural
            words = f"{words} {unit_words}"
            kind = "unit"
        return self._make(match, words, kind)

    def _mixed(self, value: str) -> str:
        """Буквы вперемешку с цифрами: «IPv6», «W3C», «x86», «MP3», «9a»."""
        words = []
        for part in re.findall(r"[0-9]+|[A-ZÄÖÜ][a-zäöüß]{2,}|[A-ZÄÖÜ]+|[a-zäöüß]+", value):
            if part.isdigit():
                words.append(numbers.cardinal(int(part)) if len(part) <= 6 and not
                             (len(part) > 1 and part.startswith("0")) else numbers.digits(part))
            elif part.isupper() or len(part) <= 2:
                entry = self.lexicon.acronym(part)
                words.append(entry.reading if entry else acronyms.spell(part))
            else:
                words.append(part)
        return " ".join(words)

    def _acronym(self, match: re.Match, options: ReadingOptions, before: list[Token]) -> Token:
        value = match.group(0)
        if not options.acronyms:
            return self._raw(match)
        entry = self.lexicon.acronym(value)
        if entry is not None:
            return self._make(match, value, "acronym", entry.reading)
        number = acronyms.roman(value)
        if number is not None and before:
            previous = next((t for t in reversed(before) if t.kind not in SEPARATORS), None)
            if previous is not None and previous.text[:1].isupper() and previous.kind in {"word", "acronym",
                                                                                          "english", "user"}:
                return self._make(match, numbers.cardinal(number), "roman")
        stem, tail = value, ""
        if value[-1].islower():
            stem, tail = value[:-1], value[-1]
        entry = self.lexicon.acronym(stem)
        if entry is not None:
            reading = entry.reading + ("s" if tail == "s" else (" " + acronyms.letter(tail) if tail else ""))
            return self._make(match, value, "acronym", reading)
        if not tail and acronyms.pronounceable(value):
            return self._make(match, value, "acronym", acronyms.as_word(value))
        if tail == "s":
            reading = acronyms.spell_plural(stem)
        else:
            reading = acronyms.spell(stem) + (" " + acronyms.letter(tail) if tail else "")
        return self._make(match, value, "acronym", self._stress_last(reading))

    @staticmethod
    def _stress_last(spelled: str) -> str:
        """Ударение аббревиатуры — на последней букве: «Zeh Peh 'Uh»."""
        parts = spelled.split(" ")
        if len(parts) > 1:
            parts[-1] = "'" + parts[-1]
        return " ".join(parts)

    def _word(self, match: re.Match, options: ReadingOptions) -> Token:
        value = match.group(0)
        if options.acronyms:
            entry = self.lexicon.acronym(value)
            if entry is not None:
                return self._make(match, value, "acronym", entry.reading)
        if len(value) == 1 and value.isalpha() and options.formulas:
            # одиночная буква — переменная формулы: «O(n log n)»
            return self._make(match, value, "letter", acronyms.letter(value))
        return self._make(match, value, "word")

    # --- контекст -------------------------------------------------------------------------

    def _context(self, tokens: list[Token], options: ReadingOptions) -> None:
        """Правила, которым нужны соседи: падеж порядкового, «ein» перед существительным."""
        meaningful = [i for i, t in enumerate(tokens) if t.kind not in SEPARATORS]
        for position, index in enumerate(meaningful):
            token = tokens[index]
            previous = tokens[meaningful[position - 1]] if position > 0 else None
            following = tokens[meaningful[position + 1]] if position + 1 < len(meaningful) else None
            if token.kind in {"ordinal", "date"}:
                self._ordinal_case(tokens, index, previous, following, meaningful, position)
            elif token.kind == "number" and token.text == "1" and following is not None:
                if following.kind == "abbreviation" and following.written in {"Millionen", "Milliarden"}:
                    # «1 Mio.» -> «eine Million»
                    token.written = token.say = "eine"
                    following.written = following.say = {"Millionen": "Million",
                                                         "Milliarden": "Milliarde"}[following.written]
                elif (following.kind in {"word", "english"} and following.text[:1].isupper()
                      and self._adjacent(tokens, index, meaningful[position + 1])):
                    # «1 Computer» -> «ein Computer», «1 Sekunde» -> «eine Sekunde»,
                    # «nach 1 Durchlauf» -> «nach einem Durchlauf»
                    female = feminine(following.text)
                    if self._previous_word(tokens[:index]) in _DATIVE_PREPOSITIONS:
                        token.written = token.say = "einer" if female else "einem"
                    else:
                        token.written = token.say = "eine" if female else "ein"
            elif token.kind == "symbol" and token.text == "#" and following is not None and \
                    following.kind in {"number", "year"}:
                token.written = token.say = "Nummer "

    @staticmethod
    def _adjacent(tokens: list[Token], left: int, right: int) -> bool:
        """Между токенами только пробел — без знаков препинания."""
        return all(tokens[i].kind == "space" for i in range(left + 1, right))

    def _ordinal_case(self, tokens: list[Token], index: int, previous: Token | None, following: Token | None,
                      meaningful: list[int], position: int) -> None:
        token = tokens[index]
        word = previous.text.lower() if previous is not None and previous.kind in {"word", "abbreviation"} else ""
        before_previous = ""
        if position > 1:
            candidate = tokens[meaningful[position - 2]]
            before_previous = candidate.text.lower() if candidate.kind == "word" else ""
        if previous is None and token.kind == "ordinal":
            # «1. Einleitung» в начале фразы — перечисление: номер и пауза
            n = int(re.match(r"\d+", token.text).group(0))
            token.written = token.say = numbers.cardinal(n) + ","
            token.kind = "number"
            return
        if word in _DATIVE or (word == "der" and before_previous in _PREPOSITIONS):
            ending = "en"
        elif word in {"der", "die", "das", "diese", "dieses", "jede", "jedes", "eine"}:
            ending = "e"
        elif word in {"ein", "kein", "jeder"}:
            ending = "er"
        elif word in {"einem"}:
            ending = "en"
        elif token.kind == "date":
            ending = "er"
        elif following is not None and following.text in _MONTHS:
            ending = "er"
        else:
            ending = "e"
        if token.kind == "ordinal":
            n = int(re.match(r"\d+", token.text).group(0))
            token.written = token.say = numbers.ordinal(n, ending)
        else:
            day = int(re.match(r"\d+", token.text).group(0))
            rest = token.written.split(" ", 1)[1]
            token.written = token.say = f"{numbers.ordinal(day, ending)} {rest}"

    # --- английские термины -----------------------------------------------------------------

    def _english(self, tokens: list[Token]) -> list[Token]:
        """Английские термины: сочетания из нескольких слов, слова, части сложных слов."""
        result: list[Token] = []
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token.kind == "word":
                merged = self._english_phrase(tokens, index)
                if merged is not None:
                    phrase, last = merged
                    result.append(phrase)
                    index = last + 1
                    continue
                entry = self.lexicon.english_word(token.text)
                if entry is not None:
                    token.say = entry.reading
                    token.kind = "english"
                    token.lang = "en"
                elif len(token.text) > 4:
                    part = self.lexicon.compound_part(token.text)
                    if part is not None:
                        entry, head, tail = part
                        reading = entry.reading
                        if head:
                            # термин в конце: ударение остаётся на немецкой части — «Quellcode»
                            token.say = f"{head}-{reading.replace(chr(39), '').lower()}"
                        else:
                            token.say = f"{reading}-{tail}"
                        token.kind = "english"
                        token.lang = "en"
            elif token.kind in {"unit", "abbreviation"}:
                words = []
                for word in token.say.split(" "):
                    exact = self.lexicon.english_word(word)
                    part = self.lexicon.compound_part(word) if len(word) > 4 else None
                    if exact is not None:
                        words.append(exact.reading)
                    elif part is not None and part[1]:
                        words.append(f"{part[1]}-{part[0].reading.replace(chr(39), '').lower()}")
                    else:
                        words.append(word)
                token.say = " ".join(words)
            result.append(token)
            index += 1
        return result

    def _english_phrase(self, tokens: list[Token], index: int) -> tuple[Token, int] | None:
        for entry in self.lexicon.english_phrases():
            words = re.split(r"[\s-]+", entry.written)
            position = index
            matched = True
            last = index
            for number, word in enumerate(words):
                if position >= len(tokens) or tokens[position].kind != "word" or \
                        tokens[position].text.lower() != word.lower():
                    matched = False
                    break
                last = position
                position += 1
                if number < len(words) - 1:
                    # между словами — один пробел или дефис
                    if position >= len(tokens) or tokens[position].kind != "space" or \
                            tokens[position].text not in {" ", "-", "\u00a0"}:
                        matched = False
                        break
                    position += 1
            if matched:
                first = tokens[index]
                end_token = tokens[last]
                text = "".join(t.text for t in tokens[index:last + 1])
                return Token(first.start, end_token.end, text, text, entry.reading, "english", "en"), last
        return None
