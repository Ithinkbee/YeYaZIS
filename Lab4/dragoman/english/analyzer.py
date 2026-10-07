"""Анализ английского текста: предложения, слова, теги, леммы, дерево зависимостей.

Результат анализа — входные данные для трансфера и для списка слов. Модели
загружаются один раз при первом обращении (около секунды).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from dragoman import config
from dragoman.english import tags as tagset
from dragoman.english.lemmatizer import Lemmatizer
from dragoman.english.parser import Parser
from dragoman.english.tagger import Tagger
from dragoman.text import segment


@dataclass
class Word:
    """Слово предложения после анализа."""

    index: int                 # номер в предложении, с 0
    text: str
    lemma: str
    tag: str                   # тег Penn Treebank
    upos: str
    head: int                  # номер вершины; −1 — корень
    deprel: str
    start: int                 # смещение в тексте документа
    end: int
    space_after: bool = True
    children: list[int] = field(default_factory=list)

    @property
    def lower(self) -> str:
        return self.text.lower()

    @property
    def is_word(self) -> bool:
        """Слово, а не знак препинания и не число."""
        return any(ch.isalpha() for ch in self.text)

    @property
    def is_clitic(self) -> bool:
        """Отделённая токенизатором часть слова: «'s», «n't», «'re», «'ll»."""
        return self.text[:1] in {"'", "’"} or self.lower in {"n't", "n’t"}

    @property
    def counts(self) -> bool:
        """Считается «словом текста»: в статистике, частотном списке и в игре."""
        return self.is_word and not self.is_clitic

    @property
    def tag_description(self) -> str:
        return tagset.describe(self.tag)


@dataclass
class AnalyzedSentence:
    index: int
    paragraph: int
    text: str
    start: int
    heading: bool
    words: list[Word]

    @property
    def root(self) -> int:
        for word in self.words:
            if word.head < 0:
                return word.index
        return 0

    def children(self, i: int, deprel: str | None = None) -> list[Word]:
        result = [self.words[c] for c in self.words[i].children]
        if deprel is not None:
            result = [w for w in result if w.deprel == deprel or w.deprel.split(":")[0] == deprel]
        return result

    def subtree(self, i: int) -> list[int]:
        """Номера слов поддерева с вершиной i, по порядку."""
        stack, seen = [i], []
        while stack:
            node = stack.pop()
            seen.append(node)
            stack.extend(self.words[node].children)
        return sorted(seen)


@dataclass
class AnalyzedDocument:
    text: str
    sentences: list[AnalyzedSentence]
    timings: dict[str, float]

    @property
    def words(self) -> list[Word]:
        return [w for s in self.sentences for w in s.words]


class Analyzer:
    def __init__(self, tagger: Tagger, parser: Parser, lemmatizer: Lemmatizer) -> None:
        self.tagger = tagger
        self.parser = parser
        self.lemmatizer = lemmatizer

    @classmethod
    def load(cls) -> "Analyzer":
        directory = config.MODELS_DIR
        return cls(Tagger.load(directory), Parser.load(directory), Lemmatizer.load(directory))

    def analyze_sentence(self, tokens: list[str]) -> tuple[list[str], list[str], list[int], list[str]]:
        tags = self.tagger.tag(tokens)
        lemmas = [self.lemmatizer.lemma(t, g) for t, g in zip(tokens, tags)]
        heads, labels = self.parser.parse(tokens, tags)
        return tags, lemmas, heads, labels

    def analyze(self, text: str) -> AnalyzedDocument:
        timings = {"segment": 0.0, "tagging": 0.0, "parsing": 0.0}
        started = time.perf_counter()
        layout = segment.layout(text)
        timings["segment"] = 1000 * (time.perf_counter() - started)
        sentences = []
        for sentence in layout.sentences:
            tokens = [t.text for t in sentence.tokens]
            if not tokens:
                continue
            t0 = time.perf_counter()
            tags = self.tagger.tag(tokens)
            lemmas = [self.lemmatizer.lemma(t, g) for t, g in zip(tokens, tags)]
            t1 = time.perf_counter()
            heads, labels = self.parser.parse(tokens, tags)
            t2 = time.perf_counter()
            timings["tagging"] += 1000 * (t1 - t0)
            timings["parsing"] += 1000 * (t2 - t1)
            words = [
                Word(i, tok.text, lemmas[i], tags[i], tagset.upos(tags[i]), heads[i], labels[i],
                     sentence.start + tok.start, sentence.start + tok.end, tok.space_after)
                for i, tok in enumerate(sentence.tokens)
            ]
            for word in words:
                if word.head >= 0:
                    words[word.head].children.append(word.index)
            sentences.append(AnalyzedSentence(sentence.index, sentence.paragraph, sentence.text, sentence.start,
                                              sentence.heading, words))
        return AnalyzedDocument(layout.text, sentences, timings)


_lock = threading.Lock()
_instance: Analyzer | None = None


def get() -> Analyzer:
    """Общий анализатор процесса (модели загружаются один раз)."""
    global _instance
    with _lock:
        if _instance is None:
            _instance = Analyzer.load()
        return _instance
