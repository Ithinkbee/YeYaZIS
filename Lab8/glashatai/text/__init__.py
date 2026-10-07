"""Разбор текста перед синтезом: абзацы, предложения, нормализация.

    reader = TextReader()
    document = reader.prepare("Ab 1954 kam z. B. der Begriff auf.")
    document.sentences[0].render()   # «Ab neunzehnhundertvierundfünfzig kam zum Beispiel …»
"""

from __future__ import annotations

from dataclasses import dataclass, field

from glashatai import config
from glashatai.text.lexicon import Lexicon, UserLexicon
from glashatai.text.normalize import KINDS, Normalizer, ReadingOptions, Sentence, Token
from glashatai.text.segment import Block, Segmenter, blocks

__all__ = ["Document", "KINDS", "Lexicon", "ReadingOptions", "Sentence", "TextReader", "Token", "UserLexicon"]


@dataclass
class Paragraph:
    index: int
    start: int
    end: int
    heading: bool
    sentences: list[Sentence] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"index": self.index, "start": self.start, "end": self.end, "heading": self.heading,
                "sentences": [sentence.to_dict() for sentence in self.sentences]}


@dataclass
class Document:
    text: str
    paragraphs: list[Paragraph]
    options: ReadingOptions

    @property
    def sentences(self) -> list[Sentence]:
        return [sentence for paragraph in self.paragraphs for sentence in paragraph.sentences]

    def stats(self) -> dict:
        sentences = self.sentences
        changed = [token for sentence in sentences for token in sentence.tokens if token.changed]
        kinds: dict[str, int] = {}
        for token in changed:
            kinds[token.kind] = kinds.get(token.kind, 0) + 1
        words = sum(1 for s in sentences for t in s.tokens if t.kind not in {"space", "punct", "quote", "pause"})
        return {"chars": len(self.text), "paragraphs": len(self.paragraphs), "sentences": len(sentences),
                "tokens": words, "changed": len(changed),
                "kinds": [{"kind": k, "name": KINDS.get(k, k), "count": v}
                          for k, v in sorted(kinds.items(), key=lambda item: -item[1])]}

    def to_dict(self) -> dict:
        return {"paragraphs": [paragraph.to_dict() for paragraph in self.paragraphs], "stats": self.stats(),
                "options": self.options.to_dict()}


class TextReader:
    """Всё, что делается с текстом до синтезатора."""

    def __init__(self, lexicon: Lexicon | None = None) -> None:
        self.lexicon = lexicon or Lexicon()
        self.segmenter = Segmenter(self.lexicon.abbreviations)
        self.normalizer = Normalizer(self.lexicon)

    def prepare(self, text: str, options: ReadingOptions | None = None,
                limit: int | None = config.MAX_SENTENCE_CHARS) -> Document:
        options = options or ReadingOptions()
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        paragraphs: list[Paragraph] = []
        counter = 0
        for block in blocks(text, self.segmenter, limit):
            paragraph = Paragraph(block.index, block.start, block.end, block.heading)
            for number, (start, end) in enumerate(block.sentences):
                if block.heading:
                    # «# Grundlagen»: знак разметки не читается
                    while start < end and text[start] in "# \t":
                        start += 1
                tokens = self.normalizer.tokens(text, start, end, options)
                if not any(token.say.strip() for token in tokens if token.kind not in {"space", "punct"}):
                    continue
                continued = number + 1 < len(block.sentences) and text[end - 1] not in ".!?…\"»“”)"
                sentence = Sentence(counter, block.index, start, end, text[start:end], tokens, block.heading,
                                    continued and not block.heading, options.is_raw)
                paragraph.sentences.append(sentence)
                counter += 1
            if paragraph.sentences:
                paragraph.index = len(paragraphs)
                for sentence in paragraph.sentences:
                    sentence.paragraph = paragraph.index
                paragraphs.append(paragraph)
        return Document(text, paragraphs, options)

    def sentence(self, text: str, options: ReadingOptions | None = None) -> Sentence:
        """Одно предложение (или кусок текста) целиком, без деления."""
        options = options or ReadingOptions()
        tokens = self.normalizer.tokens(text, 0, len(text), options)
        return Sentence(0, 0, 0, len(text), text, tokens, raw=options.is_raw)
