"""Прямой (пословный) перевод — система первого поколения по методичке.

Исходный текст превращается в немецкий заменой каждого слова его словарным
соответствием; порядок слов не меняется, структура предложения не
анализируется. Учитывается только локальный контекст:

* обороты (operating system, for example, carry out) переводятся целиком;
* артикль получает род ближайшего следующего существительного;
* существительное во множественном числе (тег NNS) ставится во
  множественное число, глагол — в форму по тегу (VBZ — 3-е лицо ед. ч.,
  VBD — прошедшее время, VBN — причастие).

Падежей, рамочной конструкции, отделяемых приставок на своём месте и
порядка слов придаточного здесь нет — это и показывает, что даёт трансфер.
"""

from __future__ import annotations

from dragoman.english.analyzer import AnalyzedSentence, Word
from dragoman.german import morphology as gm
from dragoman.lexicon.db import Entry, clean
from dragoman.translate.lexical import DICT, NAME, NUMBER, RULE, UNKNOWN, Lexical, is_number
from dragoman.translate.output import G, Sentence, punct, word


class DirectTranslator:
    def __init__(self, lexical: Lexical) -> None:
        self.lex = lexical

    def _phrase(self, words: list[Word], i: int) -> tuple[Entry | None, int]:
        first = words[i].lower
        candidates = self.lex.lexicon.phrases_from(first) + self.lex.lexicon.phrases_from(words[i].lemma.lower())
        for entry in sorted(candidates, key=lambda e: -len(e.words)):
            parts = entry.en.lower().split()
            if i + len(parts) > len(words):
                continue
            ok = True
            for k, expected in enumerate(parts):
                token = words[i + k]
                if token.lower == expected:
                    continue
                if (k == len(parts) - 1 and entry.pos in {"NOUN", "PROPN"} or k == 0 and entry.pos == "VERB") \
                        and token.lemma.lower() == expected:
                    continue
                ok = False
                break
            if ok:
                return self.lex.phrase(entry.en, entry.pos) or entry, len(parts)
        return None, 0

    def _next_noun(self, words: list[Word], i: int) -> tuple[str, str]:
        """Род и число ближайшего существительного справа (до трёх слов) — локальный контекст."""
        for k in range(i + 1, min(len(words), i + 4)):
            w = words[k]
            if w.upos in {"NOUN", "PROPN"}:
                choice = self.lex.word(w, "NOUN")
                gender = choice.entry.gender if choice.entry is not None else "n"
                number = "pl" if w.tag in {"NNS", "NNPS"} or gender == "pl" else "sg"
                return (gender if gender in {"m", "f", "n"} else "n"), number
        return "n", "sg"

    def translate(self, sentence: AnalyzedSentence) -> tuple[Sentence, dict[int, str]]:
        words = sentence.words
        tokens: list[G] = []
        status: dict[int, str] = {}
        i = 0
        while i < len(words):
            w = words[i]
            entry, length = self._phrase(words, i)
            if entry is not None and length > 1:
                span = tuple(range(i, i + length))
                text = clean(entry.de)
                if entry.pos in {"NOUN", "PROPN"} and words[i + length - 1].tag in {"NNS", "NNPS"} and entry.plural_form:
                    text = " ".join(x for x in entry.de.replace("*", "").split()[:-1]) + " " + entry.plural_form
                    text = text.strip()
                if entry.pos == "VERB":
                    text = self._verb(clean(entry.de), words[i])
                tokens.append(word(text, span, noun=entry.pos in {"NOUN", "PROPN"}))
                for k in span:
                    status[k] = DICT
                i += length
                continue
            tokens.append(self._word(words, i, status))
            i += 1
        return Sentence(sentence.index, sentence.text, tokens, ["прямой перевод: слово за словом"],
                        sentence.heading), status

    def _verb(self, german: str, w: Word) -> str:
        reflexive = german.startswith("sich ")
        verb = german.removeprefix("sich ")
        words = verb.split()
        fixed, verb = (words[:-1], words[-1]) if len(words) > 1 else ([], verb)
        if w.tag == "VBZ":
            form, prefix = gm.present(verb, 3, "sg")
        elif w.tag == "VBP":
            form, prefix = gm.present(verb, 3, "pl")
        elif w.tag == "VBD":
            form, prefix = gm.past(verb, 3, "sg")
        elif w.tag == "VBN":
            form, prefix = gm.participle(verb), ""
        else:
            form, prefix = gm.infinitive(verb), ""
        parts = (["sich"] if reflexive else []) + fixed + [form] + ([prefix] if prefix else [])
        return " ".join(parts)

    def _word(self, words: list[Word], i: int, status: dict[int, str]) -> G:
        w = words[i]
        if not w.is_word:
            if is_number(w.text):
                status[i] = NUMBER
                return word(w.text, i, "number")
            status[i] = "punct"
            return punct(w.text, i)
        lower = w.lower
        if lower in {"the", "a", "an"}:
            gender, number = self._next_noun(words, i)
            status[i] = DICT
            if lower == "the":
                return word(gm.determiner("def", gender, number, "N"), i)
            text = gm.determiner("indef", gender, "sg", "N")
            return word(text or "ein", i)
        choice = self.lex.word(w)
        if choice.status == NAME:
            status[i] = NAME
            return word(w.text, i, "name", keep_case=True)
        if choice.status == NUMBER:
            status[i] = NUMBER
            return word(w.text, i, "number")
        if choice.entry is None:
            status[i] = UNKNOWN
            return word(w.text, i, "unknown")
        entry = choice.entry
        status[i] = choice.status
        kind = "rule" if choice.status == RULE else "word"
        german = clean(entry.de).split("/")[0]
        if entry.pos in {"NOUN", "PROPN"}:
            text = entry.plural_form if w.tag in {"NNS", "NNPS"} and entry.plural_form else german
            return word(text, i, kind, noun=True)
        if entry.pos == "VERB" and w.tag.startswith("VB"):
            return word(self._verb(german, w), i, kind)
        if entry.pos == "VERB" and w.tag == "MD":
            form, _ = gm.present(german, 3, "sg")
            return word(form, i, kind)
        if entry.pos == "ADJ" and w.tag == "JJR":
            return word(gm.comparative(german), i, kind)
        if entry.pos == "ADJ" and w.tag == "JJS":
            return word("am " + gm.superlative_stem(german) + "en", i, kind)
        if german.startswith("("):
            return word("", i)
        return word(german, i, kind)


def translate_sentence(sentence: AnalyzedSentence, lexical: Lexical) -> tuple[Sentence, dict[int, str]]:
    return DirectTranslator(lexical).translate(sentence)
