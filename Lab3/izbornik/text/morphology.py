"""Морфология: приведение слова к термину и сведения о части речи.

Термин — единица, по которой считаются частоты tf и df. Разные формы одного
слова должны давать один термин, иначе «сеть», «сети» и «сетей» делили бы
между собой вес одного понятия.

* Русский язык — лемматизация pymorphy3: «нейронных сетей» → «нейронный»,
  «сеть». Лемма читаема, поэтому она же служит видом ключевого слова.
* Немецкий язык — стемминг Snowball: «Datenbanken», «Datenbank» → «datenbank».
  Готового морфологического анализатора немецкого, который не требовал бы
  загрузки моделей в сотни мегабайт, нет, а основа Snowball для подсчёта
  частот годится. Видом ключевого слова служит самая частая форма слова в
  документе: основа «verschlussel» для чтения не годится.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

_CYRILLIC = re.compile(r"^[а-яё]+(?:-[а-яё]+)*$", re.I)
_LATIN = re.compile(r"^[a-zäöüßàáâçèéêëìíîïñòóôùúûÿœæ]+(?:[-'][a-zäöüßàáâçèéêëìíîïñòóôùúûÿœæ]+)*$", re.I)


def script_ok(word: str, language: str) -> bool:
    """Слово записано алфавитом языка документа.

    Методичка требует не учитывать слова из латинских букв — для русского
    документа это иноязычные вставки, названия программ, код. Для немецкого
    документа латиница — родной алфавит, и чужими там оказываются слова
    кириллицей. Числа отсекаются ещё при выделении слов.
    """
    pattern = _CYRILLIC if language == "ru" else _LATIN
    return bool(pattern.match(word))


@dataclass(frozen=True)
class WordInfo:
    """Сведения о словоформе, нужные для весов и для словосочетаний."""

    term: str                 # ключ термина: лемма (ru) или основа (de)
    lemma: str                # начальная форма для показа (ru) или сама форма (de)
    noun: bool = False
    adjective: bool = False
    # согласование (ru): падеж, число, род
    case: str = ""
    number: str = ""
    gender: str = ""
    genitive: bool = False    # может стоять в родительном падеже (ru)
    proper: bool = False      # имя собственное (ru): имя, фамилия, топоним
    name: bool = False        # личное имя (ru)
    surname: bool = False     # фамилия (ru)
    person: bool = False      # часть имени человека: имя, отчество или фамилия (ru)
    abbreviation: bool = False
    #: возможные начальные формы имени собственного: «Евгения» — это и
    #: «Евгения», и родительный падеж от «Евгений»
    alternatives: tuple[str, ...] = ()


class RussianMorphology:
    language = "ru"

    def __init__(self) -> None:
        import pymorphy3

        self._morph = pymorphy3.MorphAnalyzer()

    @lru_cache(maxsize=200_000)
    def info(self, word: str) -> WordInfo:
        # аббревиатура: «БЗ», «СУБД», «ОС» — существительное, показывается капсом
        if word.isupper() and 2 <= len(word) <= 6:
            return WordInfo(term=word.lower().replace("ё", "е"), lemma=word, noun=True, abbreviation=True)
        parses = self._morph.parse(word.lower())
        best = parses[0]
        tag = best.tag
        # «Онегин» с заглавной — фамилия, а не нарицательное: берём разбор имени
        # собственного, если слово написано с заглавной и такой разбор есть
        if word[:1].isupper():
            proper_parse = next((p for p in parses[:4] if p.tag.POS == "NOUN"
                                 and self.PROPER & set(p.tag.grammemes)), None)
            if proper_parse is not None:
                best, tag = proper_parse, proper_parse.tag
        lemma = best.normal_form.replace("ё", "е")
        grammemes = set(tag.grammemes)
        proper = bool(self.PROPER & grammemes) and word[:1].isupper()
        noun = tag.POS == "NOUN"
        adjective = tag.POS in {"ADJF", "PRTF"}
        genitive = any(p.tag.case == "gent" and p.tag.POS == "NOUN" for p in parses[:3])
        alternatives: tuple[str, ...] = ()
        if proper:
            kind = self.PERSON & grammemes
            alternatives = tuple(dict.fromkeys(
                p.normal_form.replace("ё", "е") for p in parses[:6]
                if p.tag.POS == "NOUN" and kind & set(p.tag.grammemes)
            ))
        # отчество само по себе ключевым словом не бывает: «Сергеевич» при
        # «Елена Сергеевна»; в имени человека оно учитывается (см. person)
        if proper and "Patr" in grammemes:
            noun = False
        return WordInfo(
            term=lemma,
            lemma=lemma.capitalize() if proper else lemma,
            noun=noun,
            adjective=adjective,
            case=tag.case or "",
            number=tag.number or "",
            gender=tag.gender or "",
            genitive=genitive,
            proper=proper,
            name=proper and "Name" in grammemes,
            surname=proper and "Surn" in grammemes,
            person=proper and bool(self.PERSON & grammemes),
            alternatives=alternatives if len(alternatives) > 1 else (),
        )

    PERSON = {"Name", "Surn", "Patr"}

    #: граммемы имён собственных pymorphy3: имя, фамилия, отчество, топоним, организация
    PROPER = {"Name", "Surn", "Patr", "Geox", "Orgn", "Trad"}

    @lru_cache(maxsize=10_000)
    def person_form(self, words: tuple[str, ...], first_lemma: str = "") -> str:
        """Имя человека в именительном падеже.

        «Татьяны Лариной» → «Татьяна Ларина», «Елены Сергеевны» → «Елена
        Сергеевна». Род берётся у первого слова; если его начальная форма
        неоднозначна («Евгения»), используется first_lemma, выбранная по
        документу.
        """
        first = [p for p in self._morph.parse(words[0].lower()) if self.PERSON & set(p.tag.grammemes)]
        if first_lemma:
            first = [p for p in first if p.normal_form.replace("ё", "е") == first_lemma] or first
        if not first:
            return " ".join(words)
        head = first[0]
        gender = head.tag.gender or "masc"
        result = [head.normal_form.capitalize()]
        for word in words[1:]:
            parse = next((p for p in self._morph.parse(word.lower()) if self.PERSON & set(p.tag.grammemes)), None)
            inflected = parse.inflect({"nomn", "sing", gender}) if parse else None
            result.append((inflected.word if inflected else word).capitalize())
        return " ".join(result)

    def surface(self, word: str) -> str:
        """Слово внутри словосочетания: имя собственное — с заглавной, прочее — строчными."""
        info = self.info(word)
        if info.abbreviation:
            return word
        return word.capitalize() if info.proper else word.lower()

    @lru_cache(maxsize=100_000)
    def agree(self, adjective: str, noun: str) -> bool:
        """Согласуются ли прилагательное и существительное хотя бы в одном разборе."""
        adj_parses = [p for p in self._morph.parse(adjective.lower())[:4] if p.tag.POS in {"ADJF", "PRTF"}]
        noun_parses = [p for p in self._morph.parse(noun.lower())[:4] if p.tag.POS == "NOUN"]
        for a in adj_parses:
            for n in noun_parses:
                if a.tag.case != n.tag.case or a.tag.number != n.tag.number:
                    continue
                if n.tag.number == "sing" and a.tag.gender and n.tag.gender and a.tag.gender != n.tag.gender:
                    continue
                return True
        return False

    @lru_cache(maxsize=100_000)
    def phrase_form(self, adjectives: tuple[str, ...], noun: str) -> str:
        """Начальная форма именной группы: «нейронных сетей» → «нейронная сеть»."""
        noun_parse = next((p for p in self._morph.parse(noun.lower()) if p.tag.POS == "NOUN"), None)
        if noun_parse is None:
            return " ".join([*adjectives, noun]).lower()
        base = noun_parse.normal_form
        if self.info(noun).proper:
            base = base.capitalize()
        gender = noun_parse.tag.gender
        plural_only = "Pltm" in noun_parse.tag
        grammemes = {"nomn", "plur"} if plural_only else {"nomn", "sing"}
        if gender and not plural_only:
            grammemes.add(gender)
        words = []
        for adjective in adjectives:
            parse = next((p for p in self._morph.parse(adjective.lower()) if p.tag.POS in {"ADJF", "PRTF"}), None)
            inflected = parse.inflect(grammemes) if parse else None
            words.append(inflected.word if inflected else adjective.lower())
        return " ".join([*words, base]).replace("ё", "е")

    def head_form(self, noun: str) -> str:
        """Начальная форма главного существительного: «обработки» → «обработка»."""
        return self.info(noun).lemma


class GermanMorphology:
    language = "de"

    #: окончания сильного и слабого склонения прилагательных
    ADJECTIVE_ENDINGS = ("en", "er", "es", "em", "e")

    def __init__(self) -> None:
        from nltk.stem.snowball import SnowballStemmer

        self._stemmer = SnowballStemmer("german")

    @lru_cache(maxsize=200_000)
    def stem(self, word: str) -> str:
        return self._stemmer.stem(word.lower())

    def info(self, word: str, sentence_initial: bool = False) -> WordInfo:
        term = self.stem(word)
        capitalized = word[:1].isupper()
        # существительные в немецком пишутся с заглавной буквы; в начале
        # предложения заглавная ничего не говорит — это решается по документу
        noun = capitalized and not sentence_initial
        adjective = (not capitalized and word.lower().endswith(self.ADJECTIVE_ENDINGS)
                     and len(word) > 4)
        return WordInfo(term=term, lemma=word, noun=noun, adjective=adjective)

    def adjective_base(self, word: str) -> str:
        """Прилагательное в форме при определённом артикле: «künstlichen» → «künstliche»."""
        lower = word.lower()
        for ending in ("en", "er", "es", "em"):
            if lower.endswith(ending) and len(lower) > len(ending) + 2:
                return lower[: -len(ending)] + "e"
        return lower


@lru_cache(maxsize=None)
def for_language(language: str):
    if language == "ru":
        return RussianMorphology()
    if language == "de":
        return GermanMorphology()
    raise ValueError(f"язык не поддерживается: {language}")
