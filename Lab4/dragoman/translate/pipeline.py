"""Конвейер перевода: текст → анализ → трансфер (или прямой перевод) → синтез.

Результат перевода (Translation) содержит всё, что показывает интерфейс:

* немецкий текст по предложениям и привязку немецких слов к английским;
* статистику: сколько слов во входном тексте, сколько переведено по словарю,
  сколько — по правилам словообразования, сколько осталось без перевода;
* упорядоченный по частоте список слов текста с переводом и грамматической
  информацией — тегом части речи и его расшифровкой, родом и множественным
  числом немецкого существительного, основными формами глагола (вкладка 1);
* синтаксический разбор каждого предложения для дерева (вкладка 2).

Незнакомые слова записываются в журнал словаря — из него словарь
пополняется (раздел «Словарь»).
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from datetime import datetime

from dragoman import config
from dragoman.english import analyzer as english
from dragoman.english import tags as tagset
from dragoman.english.analyzer import AnalyzedDocument
from dragoman.german import morphology as gm
from dragoman.lexicon import db
from dragoman.lexicon.db import Entry, Lexicon, clean
from dragoman.translate import direct, transfer
from dragoman.translate.lexical import DICT, NAME, NUMBER, RULE, UNKNOWN, Lexical
from dragoman.translate.output import G, Sentence

STATUS_NAMES = {DICT: "по словарю", RULE: "по правилу словообразования", NAME: "имя собственное",
                NUMBER: "число", UNKNOWN: "нет в словаре"}

#: слова, по которым узнаётся предметная область текста
DOMAIN_MARKERS = {
    "cs": {"compiler", "program", "software", "hardware", "algorithm", "data", "network", "computer", "code",
           "memory", "processor", "system", "kernel", "database", "server", "protocol", "security", "user",
           "file", "machine", "neural", "learning", "model", "web", "internet", "programming", "language",
           "implementation", "input", "output", "process", "operating", "encryption", "ontology", "semantic"},
    "lit": {"novel", "character", "author", "play", "poem", "poet", "literature", "literary", "hero", "heroine",
            "story", "plot", "narrator", "protagonist", "tragedy", "comedy", "chapter", "writer", "reader",
            "theme", "love", "marriage", "father", "mother", "daughter", "son", "society", "monster", "creature",
            "revenge", "dream", "drama", "fiction", "sister", "wife", "husband", "soul", "death", "god"},
}


@dataclass
class ListItem:
    """Строка частотного списка: слово текста, его перевод и грамматика."""

    lemma: str
    pos: str
    count: int = 0
    forms: Counter = field(default_factory=Counter)
    tags: Counter = field(default_factory=Counter)
    german: Counter = field(default_factory=Counter)
    entry: Entry | None = None
    status: str = UNKNOWN
    first: int = 0

    @property
    def translation(self) -> str:
        if self.entry is not None:
            return self.entry.display
        if self.status in {NAME, NUMBER}:
            return self.lemma
        return ""

    @property
    def tag_text(self) -> str:
        return ", ".join(f"{tag} — {tagset.describe(tag)}" for tag, _ in self.tags.most_common())

    @property
    def pos_name(self) -> str:
        return tagset.UPOS_NAMES.get(self.pos, self.pos)

    @property
    def german_grammar(self) -> str:
        return german_grammar(self.entry) if self.entry is not None else ""


def german_grammar(entry: Entry) -> str:
    """Грамматическая информация о немецком переводе: род и мн. ч., формы глагола, степени сравнения."""
    lemma = clean(entry.de)
    if entry.pos in {"NOUN", "PROPN"}:
        if entry.gender == "pl":
            return "только мн. ч."
        parts = [f"{gm.GENDER_NAMES.get(entry.gender, entry.gender)} род"] if entry.gender else []
        if entry.plural and entry.plural != "-":
            parts.append(f"мн. ч. {entry.plural}")
        elif entry.plural == "-":
            parts.append("без мн. ч.")
        if "weak" in entry.props:
            parts.append("слабое склонение")
        return ", ".join(parts)
    if entry.pos == "VERB":
        verb = lemma.removeprefix("sich ")
        words = verb.split()
        fixed, verb = (words[:-1], words[-1]) if len(words) > 1 else ([], words[0] if words else "")
        if not verb:
            return ""
        marked = entry.de.removeprefix("sich ").split()[-1]
        present, prefix = gm.present(marked, 3, "sg")
        past, _ = gm.past(marked, 3, "sg")
        participle = gm.participle(marked)
        aux = entry.props.get("aux") or gm.auxiliary(marked)
        aux = "ist" if aux in {"sein", "s"} else "hat"
        tail = (" " + prefix) if prefix else ""
        refl = " sich" if lemma.startswith("sich ") else ""
        extra = " ".join(fixed)
        forms = f"er {present}{refl}{(' ' + extra) if extra else ''}{tail} — {past}{tail} — {aux} {participle}"
        notes = []
        if "|" in entry.de:
            notes.append("отделяемая приставка")
        if entry.props.get("prep"):
            notes.append("управление: " + entry.props["prep"].replace("+A", " + Akk.").replace("+D", " + Dat.")
                         .replace("+G", " + Gen.").replace("+N", " + Nom."))
        if entry.props.get("obj") == "D":
            notes.append("дополнение в Dativ")
        return forms + ("; " + ", ".join(notes) if notes else "")
    if entry.pos == "ADJ":
        if lemma.endswith("-") or " " in lemma:
            return "в составе слова" if lemma.endswith("-") else ""
        comp = gm.comparative(lemma)
        sup = gm.adjective_form(lemma, "sup", None, "n", "sg", "N")
        return f"{comp} — {sup}"
    if entry.pos == "ADP":
        case = entry.props.get("case", "")
        names = {"A": "Akkusativ", "D": "Dativ", "G": "Genitiv", "N": "без падежа"}
        return f"требует {names.get(case, case)}" if case else ""
    if entry.pos == "SCONJ":
        return "подчинительный союз: глагол в конце" if "sub" in entry.props else "инфинитив с «zu»"
    return ""


@dataclass
class Translation:
    uid: str
    title: str
    text: str
    domain: str
    domain_auto: bool
    mode: str
    analysis: AnalyzedDocument
    sentences: list[Sentence]
    statuses: list[dict[int, str]]
    words: list[ListItem]
    stats: dict
    timings: dict
    created: str = field(default_factory=lambda: datetime.now().strftime("%d.%m.%Y %H:%M"))
    source: str = ""

    @property
    def paragraphs(self) -> list[tuple[bool, list[Sentence]]]:
        """Абзацы перевода: (заголовок ли, предложения)."""
        result: list[tuple[bool, list[Sentence]]] = []
        current = None
        for english_sentence, german in zip(self.analysis.sentences, self.sentences):
            if current is None or english_sentence.paragraph != current:
                result.append((english_sentence.heading, []))
                current = english_sentence.paragraph
            result[-1][1].append(german)
        return result

    @property
    def german_text(self) -> str:
        blocks = []
        for heading, sentences in self.paragraphs:
            text = " ".join(s.text for s in sentences)
            blocks.append(text)
        return "\n\n".join(blocks)

    @property
    def english_paragraphs(self) -> list[tuple[bool, list]]:
        result: list[tuple[bool, list]] = []
        current = None
        for sentence in self.analysis.sentences:
            if current is None or sentence.paragraph != current:
                result.append((sentence.heading, []))
                current = sentence.paragraph
            result[-1][1].append(sentence)
        return result

    def german_for(self, sentence: int, word_index: int) -> list[str]:
        """Немецкие слова, полученные из данного английского слова."""
        return [t.text for t in self.sentences[sentence].tokens if word_index in t.src and t.kind != "punct"]

    def word_translation(self, lower: str, dictionary_first: bool = False) -> str:
        """Перевод слова текста для игры: форма из перевода или словарная."""
        for item in self.words:
            if lower in {f.lower() for f in item.forms}:
                if dictionary_first and item.entry is not None:
                    return clean(item.entry.de).split("/")[0]
                if item.german:
                    return item.german.most_common(1)[0][0]
                if item.entry is not None:
                    return clean(item.entry.de).split("/")[0]
        return ""


def detect_domain(document: AnalyzedDocument) -> str:
    scores = {code: 0 for code in config.DOMAIN_CODES}
    for w in document.words:
        lemma = w.lemma.lower()
        for code, markers in DOMAIN_MARKERS.items():
            if lemma in markers:
                scores[code] += 1
    best = max(scores, key=lambda code: (scores[code], code == "cs"))
    return best


class Translator:
    """Переводчик: держит анализатор и словарь, кэширует последние переводы."""

    def __init__(self, lexicon: Lexicon | None = None) -> None:
        self.lexicon = lexicon or db.get()
        self._cache: OrderedDict[tuple, Translation] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def analyzer(self):
        return english.get()

    def translate(self, text: str, title: str = "", domain: str = "auto", mode: str = config.DEFAULT_MODE,
                  log_unknown: bool = True, source: str = "", use_rules: bool = True) -> Translation:
        text = text.strip()
        mode = mode if mode in config.MODES else config.DEFAULT_MODE
        key = (hashlib.sha1(text.encode("utf-8")).hexdigest(), domain, mode, self.lexicon.version, use_rules)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached
        started = time.perf_counter()
        document = self.analyzer.analyze(text)
        analysis_ms = 1000 * (time.perf_counter() - started)
        domain_auto = domain not in config.DOMAIN_CODES
        chosen = detect_domain(document) if domain_auto else domain
        lexical = Lexical(self.lexicon, self.analyzer.lemmatizer, chosen, use_rules)

        t0 = time.perf_counter()
        sentences: list[Sentence] = []
        statuses: list[dict[int, str]] = []
        unknown: list[tuple[str, str, str]] = []
        if mode == "direct":
            translator = direct.DirectTranslator(lexical)
            for sentence in document.sentences:
                result, status = translator.translate(sentence)
                sentences.append(result)
                statuses.append(status)
                for w in sentence.words:
                    if status.get(w.index) == UNKNOWN:
                        unknown.append((w.lemma.lower() if w.upos != "PROPN" else w.lemma, w.upos, sentence.text))
        else:
            ctx = transfer.DocContext(lexical)
            ctx.learn_names(document.sentences)
            for sentence in document.sentences:
                result, status = transfer.translate_sentence(sentence, ctx)
                sentences.append(result)
                statuses.append(status)
            unknown = ctx.unknown
        transfer_ms = 1000 * (time.perf_counter() - t0)

        words = self._word_list(document, sentences, statuses, lexical)
        stats = self._stats(document, statuses, words)
        timings = {**document.timings, "analysis": analysis_ms, "transfer": transfer_ms,
                   "total": 1000 * (time.perf_counter() - started)}
        uid = key[0][:10]
        translation = Translation(uid, title or _title(text), text, chosen, domain_auto, mode, document, sentences,
                                  statuses, words, stats, timings, source=source)
        if log_unknown and unknown:
            try:
                self.lexicon.log_unknown(unknown)
            except Exception:  # noqa: BLE001 — журнал не должен мешать переводу
                pass
        with self._lock:
            self._cache[key] = translation
            while len(self._cache) > 40:
                self._cache.popitem(last=False)
        return translation

    # --- частотный список -----------------------------------------------------------------

    def _word_list(self, document: AnalyzedDocument, sentences: list[Sentence], statuses: list[dict[int, str]],
                   lexical: Lexical) -> list[ListItem]:
        items: dict[tuple[str, str], ListItem] = {}
        for s_index, sentence in enumerate(document.sentences):
            status = statuses[s_index]
            german_by_word: dict[int, list[str]] = {}
            for token in sentences[s_index].tokens:
                if token.kind == "punct":
                    continue
                for src in token.src:
                    german_by_word.setdefault(src, []).append(token.text)
            for w in sentence.words:
                if not w.counts:
                    continue
                lemma = w.lemma if w.upos == "PROPN" or w.lemma == "I" else w.lemma.lower()
                key = (lemma, w.upos)
                item = items.get(key)
                if item is None:
                    item = ListItem(lemma, w.upos, first=s_index)
                    choice = lexical.word(w)
                    item.entry = choice.entry
                    item.status = choice.status
                    items[key] = item
                item.count += 1
                item.forms[w.text] += 1
                item.tags[w.tag] += 1
                germans = german_by_word.get(w.index)
                if germans:
                    form = " ".join(dict.fromkeys(germans))
                    item.german[form] += 1
                word_status = status.get(w.index)
                if word_status in {DICT, RULE} and item.status == UNKNOWN:
                    item.status = word_status
        return sorted(items.values(), key=lambda item: (-item.count, item.lemma.lower()))

    @staticmethod
    def _stats(document: AnalyzedDocument, statuses: list[dict[int, str]], words: list[ListItem]) -> dict:
        counts = Counter()
        for sentence, status in zip(document.sentences, statuses):
            for w in sentence.words:
                if not w.counts:
                    continue
                counts[status.get(w.index, UNKNOWN) if status.get(w.index) != "punct" else UNKNOWN] += 1
        total = sum(counts.values())
        translated = counts[DICT] + counts[RULE]
        need = total - counts[NAME] - counts[NUMBER]
        return {
            "sentences": len(document.sentences),
            "words": total,
            "unique": len(words),
            "translated": translated,
            "dictionary": counts[DICT],
            "rule": counts[RULE],
            "names": counts[NAME],
            "numbers": counts[NUMBER],
            "unknown": counts[UNKNOWN],
            "coverage": translated / need if need else 1.0,
            "unknown_words": sorted({item.lemma for item in words if item.status == UNKNOWN}),
            "rule_words": sorted({item.lemma for item in words if item.status == RULE}),
        }


def _title(text: str) -> str:
    first = text.strip().split("\n", 1)[0].lstrip("# ").strip()
    return first[:80] if first else "Текст"


_lock = threading.Lock()
_instance: Translator | None = None


def get() -> Translator:
    global _instance
    with _lock:
        if _instance is None:
            _instance = Translator()
        return _instance


def reset() -> None:
    global _instance
    with _lock:
        _instance = None
