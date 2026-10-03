"""Анализ документа: слова предложений, термины и их частоты в документе.

Слово участвует в расчёте весов, если оно записано алфавитом языка документа,
не является числом и не входит в список стоп-слов (методичка, шаг 1). Слова,
которые в веса не идут, всё равно сохраняются: по ним проверяется, стоят ли
два значимых слова рядом, — это нужно для поиска словосочетаний.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from izbornik.text import morphology, segment, stopwords

#: слово — буквы, возможно с дефисом или апострофом внутри: «какой-то»,
#: «Public-Key-Verfahren». Цифры в слово не входят, поэтому числа
#: отсекаются уже здесь.
WORD = re.compile(r"[^\W\d_]+(?:[-‐'’][^\W\d_]+)*")


@dataclass
class Token:
    surface: str
    term: str            # ключ термина: лемма (ru) или основа (de)
    start: int           # смещение в тексте документа D
    end: int
    counted: bool        # участвует в весах
    lemma: str = ""      # как показывать термин (ru): лемма или аббревиатура капсом
    noun: bool = False
    adjective: bool = False
    adjacent: bool = False   # от предыдущего слова отделено только пробелом
    initial: bool = False    # первое слово предложения


@dataclass
class AnalyzedDocument:
    doc_id: str
    title: str
    language: str
    layout: segment.Layout
    sentence_tokens: list[list[Token]]
    heading_tokens: list[list[Token]]
    tf: Counter                                   # tf(t, D)
    display: dict[str, str] = field(default_factory=dict)
    noun_terms: set[str] = field(default_factory=set)

    @property
    def tf_max(self) -> int:
        return max(self.tf.values()) if self.tf else 0

    @property
    def words_total(self) -> int:
        return sum(len(tokens) for tokens in self.sentence_tokens) + sum(
            len(tokens) for tokens in self.heading_tokens
        )

    @property
    def words_counted(self) -> int:
        return sum(self.tf.values())

    def show(self, term: str) -> str:
        return self.display.get(term, term)


def _tokens(text: str, base: int, language: str, stop: frozenset[str]) -> list[Token]:
    morph = morphology.for_language(language)
    tokens: list[Token] = []
    previous_end: int | None = None
    matches = list(WORD.finditer(text))
    in_phrase = stopwords.phrase_spans([m.group(0) for m in matches], language)
    for index, match in enumerate(matches):
        word = match.group(0)
        between = text[previous_end:match.start()] if previous_end is not None else ""
        adjacent = previous_end is not None and between.strip() == ""
        previous_end = match.end()

        lower = word.lower().replace("ё", "е")
        allowed = morphology.script_ok(word, language) and len(word) > 1
        if language == "ru":
            info = morph.info(word) if allowed else None
        else:
            info = morph.info(word, sentence_initial=(index == 0)) if allowed else None

        term = info.term if info else lower
        counted = (bool(info) and lower not in stop and term not in stop and len(term) > 1
                   and index not in in_phrase)
        tokens.append(
            Token(
                surface=word,
                term=term,
                start=base + match.start(),
                end=base + match.end(),
                counted=counted,
                lemma=info.lemma if info else lower,
                noun=bool(info and info.noun),
                adjective=bool(info and info.adjective),
                adjacent=adjacent,
                initial=index == 0,
            )
        )
    return tokens


def analyze(raw: str, language: str, doc_id: str = "", title: str = "") -> AnalyzedDocument:
    """Разбирает документ и считает частоты терминов tf(t, D)."""
    layout = segment.parse(raw, language)
    stop = stopwords.load(language)

    sentence_tokens = [
        _tokens(sentence.text, sentence.start, language, stop) for sentence in layout.sentences
    ]
    heading_tokens = [
        _tokens(paragraph.text, paragraph.start, language, stop)
        for paragraph in layout.paragraphs
        if paragraph.heading
    ]

    all_tokens = (*sentence_tokens, *heading_tokens)
    tf = _count(all_tokens)
    if _resolve_names(all_tokens, language, tf):
        tf = _count(all_tokens)
    forms: dict[str, Counter] = defaultdict(Counter)
    for tokens in all_tokens:
        for token in tokens:
            if token.counted:
                forms[token.term][token.surface if language == "de" else token.lemma] += 1

    # сколько раз термин написан с заглавной и со строчной в середине предложения
    capital: Counter = Counter()
    lower: Counter = Counter()
    for tokens in sentence_tokens:
        for t in tokens:
            if t.counted and not t.initial:
                (capital if t.surface[:1].isupper() else lower)[t.term] += 1

    noun_terms: set[str] = set()
    if language == "de":
        # Существительное — слово, которое в середине предложения пишется с
        # заглавной. Прилагательное тоже бывает с заглавной в составе термина
        # («Künstliche Neuronale Netze»), но чаще оно написано строчными, поэтому
        # основа считается существительным, только если заглавных вхождений в
        # середине предложения не меньше, чем строчных. Первое слово
        # предложения судится по остальным вхождениям.
        noun_terms = {term for term, count in capital.items() if count >= lower[term]}
        for tokens in (*sentence_tokens, *heading_tokens):
            for token in tokens:
                token.noun = token.counted and token.surface[:1].isupper() and token.term in noun_terms
    else:
        noun_terms = {t.term for tokens in (*sentence_tokens, *heading_tokens) for t in tokens
                      if t.counted and t.noun}

    display = {term: _display_form(term, counter, language, term in noun_terms)
               for term, counter in forms.items()}
    if language == "ru":
        # имя, которого нет в словаре pymorphy3 («Скалозуб»), узнаётся по тому,
        # что в середине предложения оно всегда написано с заглавной
        for term, count in capital.items():
            if count >= 2 and not lower[term] and display.get(term, "").islower():
                display[term] = display[term].capitalize()

    return AnalyzedDocument(
        doc_id=doc_id,
        title=title,
        language=language,
        layout=layout,
        sentence_tokens=sentence_tokens,
        heading_tokens=heading_tokens,
        tf=tf,
        display=display,
        noun_terms=noun_terms,
    )


def _count(groups) -> Counter:
    tf: Counter = Counter()
    for tokens in groups:
        for token in tokens:
            if token.counted:
                tf[token.term] += 1
    return tf


def _resolve_names(groups, language: str, tf: Counter) -> bool:
    """Уточняет термины имён собственных по документу; True, если что-то изменилось.

    * Русский: «Евгения» — либо женское имя, либо родительный падеж от
      «Евгений». Выбирается та начальная форма, которая чаще встречается в
      документе: в статье об «Онегине» это «Евгений».
    * Немецкий: притяжательная форма имени «Effis», «Goethes» сводится к
      «Effi», «Goethe», если такая форма в документе есть. Стеммер Snowball
      конечное «s» у имён не отбрасывает.
    """
    changed = False
    if language == "ru":
        morph = morphology.for_language("ru")
        for tokens in groups:
            for token in tokens:
                if not token.counted:
                    continue
                alternatives = morph.info(token.surface).alternatives
                if not alternatives:
                    continue
                best = max(alternatives, key=lambda a: (tf.get(a, 0), a == token.term))
                if best != token.term:
                    token.term, token.lemma = best, best.capitalize()
                    changed = True
    else:
        morph = morphology.for_language("de")
        surfaces = {t.surface for tokens in groups for t in tokens if t.counted}
        for tokens in groups:
            for token in tokens:
                word = token.surface
                if (token.counted and word[:1].isupper() and word.endswith("s")
                        and len(word) > 3 and word[:-1] in surfaces):
                    base = morph.stem(word[:-1])
                    if base != token.term:
                        token.term = base
                        changed = True
    return changed


def _display_form(term: str, counter: Counter, language: str, noun: bool) -> str:
    """Как показывать термин пользователю."""
    if language == "ru":
        return counter.most_common(1)[0][0]
    # немецкий: самая частая форма; при равенстве — более короткая. У
    # существительного берутся формы с заглавной буквы, у прочих — строчные.
    candidates = [(form, count) for form, count in counter.items()
                  if form[:1].isupper() == noun] or list(counter.items())
    candidates.sort(key=lambda item: (-item[1], len(item[0]), item[0]))
    form = candidates[0][0]
    return form if noun else form.lower()
