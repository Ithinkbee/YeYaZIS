"""Лексический трансфер: какая словарная статья переводит данное слово.

Слово ищется в словаре по лемме и части речи; если не найдено — по запасным
леммам («using» → use, «duped» → dupe), по форме слова как прилагательного
(«hidden», «distributed»), по прилагательному для наречия на -ly. Последнее
средство — правила словообразования (guess.py). Слово, которое не удалось
перевести ничем, остаётся в переводе по-английски и попадает в журнал
неизвестных слов — оттуда его можно добавить в словарь.
"""

from __future__ import annotations

import re

from dataclasses import dataclass

from dragoman.english.analyzer import Word
from dragoman.english.lemmatizer import Lemmatizer
from dragoman.lexicon.db import Entry, Lexicon
from dragoman.lexicon import guess

#: статусы перевода слова
DICT, RULE, NAME, NUMBER, UNKNOWN, PUNCT = "dict", "rule", "name", "number", "unknown", "punct"


@dataclass
class Choice:
    entry: Entry | None
    status: str
    lemma: str

    @property
    def de(self) -> str:
        return self.entry.de if self.entry else ""


def is_number(text: str) -> bool:
    stripped = text.replace(",", "").replace(".", "").replace("%", "")
    return bool(stripped) and stripped[0].isdigit() and not any(ch.isalpha() for ch in stripped.rstrip("stndrdh"))


class Lexical:
    def __init__(self, lexicon: Lexicon, lemmatizer: Lemmatizer | None, domain: str | None,
                 use_rules: bool = True) -> None:
        self.lexicon = lexicon
        self.lemmatizer = lemmatizer
        self.domain = domain
        #: переводить ли незнакомые слова правилами словообразования
        self.use_rules = use_rules

    def _candidates(self, w: Word) -> list[str]:
        result = [w.lemma.lower() if w.upos != "PROPN" else w.lemma]
        if self.lemmatizer is not None:
            for candidate in self.lemmatizer.candidates(w.text, w.tag):
                if candidate not in result:
                    result.append(candidate)
        if w.lower not in result:
            result.append(w.lower)
        return result

    def lookup(self, text: str, pos: str, strict: bool = False) -> Entry | None:
        return self.lexicon.best(text, pos, self.domain, strict=strict)

    def word(self, w: Word, pos: str | None = None) -> Choice:
        """Перевод слова вне оборотов; pos — какой частью речи слово выступает в немецком."""
        if not w.is_word:
            if is_number(w.text):
                return Choice(None, NUMBER, w.text)
            return Choice(None, PUNCT, w.text)
        if w.tag == "CD" and is_number(w.text):
            return Choice(None, NUMBER, w.text)
        # «iPadOS», «macOS», «eBay» — название: строчная буква в начале, прописная внутри;
        # «NNs», «CPUs», «GPUs» — аббревиатура во мн. ч. — тоже без перевода
        if re.match(r"^[a-z]+[A-Z]", w.text) or re.fullmatch(r"[A-Z]{2,}s", w.text):
            return Choice(None, NAME, w.text)
        pos = pos or w.upos
        if w.tag in {"VBN", "VBG"} and pos == "ADJ":
            entry = self.lookup(w.lower, "ADJ", strict=True)
            if entry:
                return Choice(entry, DICT, w.lower)
        if w.tag in {"MD"}:
            entry = self.lookup(w.lower, "VERB", strict=True)
            if entry:
                return Choice(entry, DICT, w.lower)
        if pos in {"PRON", "DET", "ADP", "SCONJ", "CCONJ", "PART"} or w.tag in {"IN", "TO", "RP", "DT", "PRP",
                                                                             "PRP$", "WDT", "WP", "WP$", "WRB"}:
            entry = self.lookup(w.lower, pos) or self.lookup(w.lemma.lower(), pos)
            if entry:
                return Choice(entry, DICT, w.lower)
        if pos == "ADJ" and w.tag in {"NNP", "NNPS", "JJ"}:
            entry = self.lookup(w.lower, "ADJ", strict=True)
            if entry:
                return Choice(entry, DICT, w.lower)
        if pos == "PROPN" or w.tag in {"NNP", "NNPS"}:
            entry = self.lookup(w.text, "PROPN", strict=True) or self.lookup(w.lemma, "PROPN", strict=True)
            if entry:
                return Choice(entry, DICT, w.lemma)
            return Choice(None, NAME, w.text)

        lookup_pos = {"AUX": "VERB"}.get(pos, pos)
        for candidate in self._candidates(w):
            entry = self.lookup(candidate, lookup_pos, strict=lookup_pos in {"NOUN", "VERB", "ADJ"})
            if entry and "modal" in entry.props and w.tag != "MD":
                # «need» смысловым глаголом — «benötigen», модальным («need not») — «müssen»
                entry = next((e for e in self.lexicon.lookup(candidate, "VERB", self.domain, strict=True)
                              if "modal" not in e.props), entry)
            if entry:
                return Choice(entry, DICT, candidate)
        # причастие в роли прилагательного и прилагательное, образованное от глагола
        if lookup_pos == "ADJ":
            entry = self.lookup(w.lower, "ADJ")
            if entry:
                return Choice(entry, DICT, w.lower)
            if w.lower.endswith(("ed", "ing")):
                for candidate in self._candidates(w):
                    verb = self.lookup(candidate, "VERB", strict=True)
                    if verb:
                        return Choice(verb, DICT, candidate)
        if lookup_pos == "VERB" and w.tag in {"VBN", "VBG", "JJ"}:
            entry = self.lookup(w.lower, "ADJ", strict=True)
            if entry:
                return Choice(entry, DICT, w.lower)
        if lookup_pos == "NOUN":
            for candidate in self._candidates(w):
                entry = self.lookup(candidate, "NOUN")
                if entry:
                    return Choice(entry, DICT, candidate)
        if lookup_pos == "ADV":
            entry = self.lookup(w.lower, "ADV") or self.lookup(w.lower, "ADJ", strict=True)
            if entry:
                return Choice(entry, DICT, w.lower)
        # теггер мог ошибиться с частью речи: «well» как существительное — всё равно «gut»,
        # «scholar» как прилагательное — всё равно «Wissenschaftler»
        for candidate in (w.lower, w.lemma.lower()):
            allowed = {"VERB"} if lookup_pos == "VERB" else {"ADV", "ADJ", "NOUN", "VERB", "ADP", "PRON"}
            alternatives = [e for e in self.lexicon.any_pos(candidate, self.domain)
                            if e.pos in allowed and " " not in e.en]
            if alternatives:
                preferred = [e for e in alternatives if e.pos == lookup_pos] or alternatives
                return Choice(preferred[0], DICT, candidate)
        # правила словообразования
        for candidate in (self._candidates(w)[:2] if self.use_rules else []):
            rule = guess.guess(candidate if lookup_pos != "ADV" else w.lower, lookup_pos, self.lexicon, self.domain)
            if rule:
                return Choice(rule, RULE, candidate)
        if lookup_pos == "NOUN" and w.text[:1].isupper() and w.index > 0:
            return Choice(None, NAME, w.text)
        return Choice(None, UNKNOWN, w.lemma)

    def phrase(self, en: str, pos: str) -> Entry | None:
        return self.lexicon.best(en, pos, self.domain, strict=True)
