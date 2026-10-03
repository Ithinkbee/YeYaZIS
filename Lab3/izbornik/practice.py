"""Реферат вручную: человек реферирует отрывок, система сравнивает.

Отрывок — несколько соседних абзацев одного раздела документа коллекции или
своего документа пользователя: 700–1600 знаков, не меньше пяти предложений.
Человек пишет реферат как умеет — своими словами или фразами из текста.
Система реферирует тот же отрывок методом sentence extraction (df — по
коллекции того же языка, отрывок добавляется к ней, как свой документ) и
сравнивает результаты по леммам значимых слов, как при оценке по эталону:

* ключевые понятия — самые значимые существительные отрывка, прежде всего
  повторяющиеся; сколько из них упомянул человек;
* совпадение с рефератом системы — ROUGE-1 и ROUGE-2: какая доля значимых
  слов реферата системы есть у человека (полнота) и наоборот (точность);
* объём — доля отрывка; реферат длиннее трёх четвертей отрывка — пересказ;
* дословность — доля пар соседних слов человека, взятых из отрывка без
  изменений: так видно, извлекал ли человек фразы, как система, или
  пересказывал своими словами. Второго метод sentence extraction не умеет.

Оценка нарочно мягкая: человек пишет без вычислений, а реферат системы — не
эталон, а одно из мнений о главном.
"""

from __future__ import annotations

import random
import re
import time
from collections import Counter
from dataclasses import dataclass, field

from izbornik import config, summary as summary_module
from izbornik.collection import Collection, detect_language
from izbornik.evaluation import Rouge, reference_terms, rouge
from izbornik.text import morphology, segment
from izbornik.text.analysis import WORD, analyze

#: ключ отрывка: «ru-lit-master:3-5» или «mine:<uid>:3-5» (абзацы с 0)
_KEY = re.compile(r"^(?:(mine):)?([\w-]+):(\d+)-(\d+)$")

#: номер пункта в начале строки: «2.», «2.1.», «IV.»
_NUMBERED = re.compile(r"^(?:\d{1,2}(?:\.\d{1,2})*\.?|[IVX]{1,4}\.)\s")

#: абзац короче этого — подпись, пункт списка или заголовок, а не связный текст
_SHORT_PARAGRAPH = 80

#: средняя длина абзаца связного отрывка: иначе в отрывок попадает список из
#: коротких пунктов («Erzeugung neuer Prozesse…», «Verwaltung des Dateisystems…»)
_PROSE_PARAGRAPH = 180


@dataclass
class Source:
    """Документ, из которого берётся отрывок."""

    kind: str              # doc | mine
    doc_id: str
    title: str
    language: str
    domain: str | None
    text: str


@dataclass
class Excerpt:
    key: str
    source: Source
    first: int             # номера абзацев документа, с 0
    last: int
    section: str           # заголовок раздела, если он есть
    paragraphs: list[str]

    @property
    def text(self) -> str:
        return "\n\n".join(self.paragraphs)

    @property
    def chars(self) -> int:
        return sum(len(p) for p in self.paragraphs) + len(self.paragraphs) - 1

    @property
    def sentences(self) -> int:
        return len(segment.parse(self.text, self.source.language).sentences)

    @property
    def source_link(self) -> str:
        base = f"/doc/{self.source.doc_id}" if self.source.kind == "doc" else f"/mine/{self.source.doc_id}"
        return f"{base}/source"


def make_key(source: Source, first: int, last: int) -> str:
    prefix = "mine:" if source.kind == "mine" else ""
    return f"{prefix}{source.doc_id}:{first}-{last}"


def parse_key(key: str) -> tuple[str, str, int, int] | None:
    """(вид, документ, первый абзац, последний абзац) или None."""
    match = _KEY.match(key or "")
    if not match:
        return None
    mine, doc_id, first, last = match.groups()
    return ("mine" if mine else "doc"), doc_id, int(first), int(last)


def is_boundary(paragraph: segment.Paragraph) -> bool:
    """Абзац, на котором связный отрывок кончается.

    Кроме распознанных заголовков это нумерованные заголовки статей, которые
    кончаются точкой («2.1. ENUM hardcoding.») и потому считаются абзацами, и
    вообще очень короткие абзацы — подписи и пункты списков.
    """
    if paragraph.heading or paragraph.length < _SHORT_PARAGRAPH:
        return True
    return len(paragraph.sentences) <= 1 and paragraph.length <= 150 and bool(_NUMBERED.match(paragraph.text))


def windows(layout: segment.Layout) -> list[tuple[int, int]]:
    """Отрывки подходящего размера: подряд идущие абзацы одного раздела."""
    found: list[tuple[int, int]] = []
    paragraphs = layout.paragraphs
    for first, paragraph in enumerate(paragraphs):
        if is_boundary(paragraph):
            continue
        chars = sentences = 0
        for last in range(first, len(paragraphs)):
            current = paragraphs[last]
            if is_boundary(current):
                break
            chars += current.length + (1 if last > first else 0)
            sentences += len(current.sentences)
            if chars > config.PRACTICE_MAX_CHARS:
                break
            prose = chars / (last - first + 1) >= _PROSE_PARAGRAPH
            if chars >= config.PRACTICE_MIN_CHARS and sentences >= config.PRACTICE_MIN_SENTENCES and prose:
                found.append((first, last))
    return found


def excerpt(source: Source, first: int, last: int) -> Excerpt:
    """Отрывок из абзацев first–last; ValueError, если таких абзацев нет."""
    layout = segment.parse(source.text, source.language)
    paragraphs = layout.paragraphs
    if not 0 <= first <= last < len(paragraphs):
        raise ValueError("в документе нет таких абзацев")
    chosen = paragraphs[first:last + 1]
    if any(p.heading for p in chosen):
        raise ValueError("отрывок не может содержать заголовок")
    section = next((p.text for p in reversed(paragraphs[:first]) if p.heading), "")
    return Excerpt(make_key(source, first, last), source, first, last, section, [p.text for p in chosen])


def random_excerpt(sources: list[Source], rng: random.Random | None = None) -> Excerpt | None:
    """Случайный отрывок случайного документа; None — если подходящих нет."""
    rng = rng or random.Random()
    order = sources[:]
    rng.shuffle(order)
    for source in order:
        options = windows(segment.parse(source.text, source.language))
        if options:
            first, last = rng.choice(options)
            return excerpt(source, first, last)
    return None


# --- сравнение ------------------------------------------------------------------------

@dataclass
class Concept:
    text: str              # как показывать
    term: str              # лемма или основа
    freq: int              # сколько раз встречается в отрывке
    covered: bool = False


@dataclass
class Verdict:
    stars: int             # 1–5; 0 — без оценки (реферат на другом языке)
    title: str
    occasion: str          # повод для реплики Пафнутия
    notes: list[str] = field(default_factory=list)


@dataclass
class Comparison:
    excerpt: Excerpt
    text: str                          # реферат человека
    language: str                      # язык, на котором он написан
    chars: int
    words: int                         # значимых слов
    compression: float                 # доля отрывка
    concepts: list[Concept]
    coverage: float
    rouge1: Rouge                      # человек против реферата системы
    rouge2: Rouge
    copied: float                      # доля пар слов, взятых из отрывка дословно
    on_topic: float                    # доля значимых слов человека, которые есть в отрывке
    style: str                         # extract | mixed | own
    system: summary_module.Result      # реферат системы по отрывку
    system_ms: float
    seconds: float | None              # сколько писал человек
    verdict: Verdict
    #: текст человека кусками: (текст, ключевое ли это понятие)
    segments: list[tuple[str, bool]] = field(default_factory=list)


def system_size(sentences: int) -> int:
    """Сколько предложений отрывка берёт реферат системы: около трети, от 2 до 4."""
    return max(2, min(4, round(sentences * config.PRACTICE_SUMMARY_SHARE)))


def summarize_excerpt(collection: Collection, item: Excerpt) -> tuple[summary_module.Result, float]:
    """Реферат отрывка системой и время его построения, мс."""
    started = time.perf_counter()
    document = analyze(item.text, item.source.language, f"excerpt:{item.key}", item.source.title)
    count = system_size(len(document.layout.sentences))
    result = summary_module.build(document, collection.stats(item.source.language), count)
    return result, (time.perf_counter() - started) * 1000


def concepts_of(result: summary_module.Result) -> list[Concept]:
    """Ключевые понятия отрывка: ключевые слова, прежде всего повторяющиеся.

    В коротком отрывке почти всё встречается по разу, и слово, редкое в
    коллекции, попадало бы в понятия только из-за большого idf. Поэтому
    сначала берутся слова, встреченные хотя бы дважды, и лишь если их мало —
    остальные по значимости.
    """
    tree = result.summary.keywords.tree
    concepts = [kw for kw in tree if kw.freq >= 2][:config.PRACTICE_CONCEPTS]
    for keyword in tree:
        if len(concepts) >= 4:
            break
        if keyword not in concepts:
            concepts.append(keyword)
    surfaces: dict[str, Counter] = {}
    for tokens in result.document.sentence_tokens:
        for token in tokens:
            surfaces.setdefault(token.term, Counter())[token.surface] += 1
    return [Concept(_shown(kw.text, surfaces.get(kw.terms[0])), kw.terms[0], kw.freq) for kw in concepts if kw.terms]


def _shown(text: str, forms: Counter | None) -> str:
    """Как показывать понятие. Составные имена pymorphy3 склоняет неверно
    («Га-Ноцри» → «Га-ноцрь»): если такой леммы в тексте нет, показывается
    самая частая форма из текста."""
    if "-" not in text or not forms or text.lower() in {form.lower() for form in forms}:
        return text
    return forms.most_common(1)[0][0]


def excerpt_parts(result: summary_module.Result) -> list[list[tuple[str, int]]]:
    """Абзацы отрывка кусками: (текст, номер предложения в реферате системы или 0)."""
    layout = result.document.layout
    order = {index: number for number, index in enumerate(sorted(result.selected), start=1)}
    parts: list[list[tuple[str, int]]] = []
    for paragraph in layout.paragraphs:
        pieces: list[tuple[str, int]] = []
        position = 0
        for index in paragraph.sentences:
            sentence = layout.sentences[index]
            begin = sentence.start_in_paragraph
            end = begin + sentence.length
            if begin > position:
                pieces.append((paragraph.text[position:begin], 0))
            pieces.append((paragraph.text[begin:end], order.get(index, 0)))
            position = end
        if position < len(paragraph.text):
            pieces.append((paragraph.text[position:], 0))
        parts.append(pieces)
    return parts


def _surface_words(text: str) -> list[str]:
    return [m.group(0).lower().replace("ё", "е") for m in WORD.finditer(text)]


def _bigrams(words: list[str]) -> list[tuple[str, str]]:
    return list(zip(words, words[1:]))


def _segments(text: str, language: str, terms: set[str]) -> list[tuple[str, bool]]:
    """Текст человека кусками с отметкой ключевых понятий."""
    morph = morphology.for_language(language)
    parts: list[tuple[str, bool]] = []
    position = 0
    for match in WORD.finditer(text):
        word = match.group(0)
        if not morphology.script_ok(word, language) or len(word) < 2:
            continue
        info = morph.info(word) if language == "ru" else morph.info(word, sentence_initial=False)
        if info.term in terms:
            parts.append((text[position:match.start()], False))
            parts.append((word, True))
            position = match.end()
    parts.append((text[position:], False))
    return [part for part in parts if part[0]]


def compare(collection: Collection, item: Excerpt, text: str, seconds: float | None = None) -> Comparison:
    """Сравнивает реферат человека с отрывком и с рефератом системы."""
    text = text.strip()[:config.PRACTICE_MAX_INPUT]
    language = item.source.language
    system, system_ms = summarize_excerpt(collection, item)
    document = system.document

    written = detect_language(text) if text else language
    human_terms = reference_terms(text, language) if text else []
    human_set = {t for seq in human_terms for t in seq}
    human_count = sum(len(seq) for seq in human_terms)

    concepts = concepts_of(system)
    for concept in concepts:
        concept.covered = concept.term in human_set
    coverage = sum(c.covered for c in concepts) / len(concepts) if concepts else 0.0

    selected = sorted(system.selected)
    reference = [[t.term for t in document.sentence_tokens[i] if t.counted] for i in selected]
    rouge1, rouge2 = rouge(human_terms, reference, 1), rouge(human_terms, reference, 2)

    words = _surface_words(text)
    source_pairs = set(_bigrams(_surface_words(item.text)))
    pairs = _bigrams(words)
    copied = sum(1 for pair in pairs if pair in source_pairs) / len(pairs) if pairs else 0.0
    on_topic = len(human_set & set(document.tf)) / len(human_set) if human_set else 0.0
    style = "extract" if copied >= 0.6 else "mixed" if copied >= 0.25 else "own"
    compression = len(text) / item.chars if item.chars else 0.0

    verdict = judge(coverage, rouge1, human_count, compression, on_topic, written != language)
    return Comparison(
        excerpt=item, text=text, language=written, chars=len(text), words=human_count,
        compression=compression, concepts=concepts, coverage=coverage, rouge1=rouge1, rouge2=rouge2,
        copied=copied, on_topic=on_topic, style=style, system=system, system_ms=system_ms,
        seconds=seconds, verdict=verdict,
        segments=_segments(text, language, {c.term for c in concepts}) if written == language else [(text, False)],
    )


STAR_TITLES = {
    5: "Отличный реферат",
    4: "Хороший реферат",
    3: "Неплохо, но главное — не всё",
    2: "Главное упущено",
    1: "Реферат не получился",
}


def score(coverage: float, rouge1: Rouge) -> float:
    """Доля от 0 до 1: ключевые понятия и совпадение с рефератом системы.

    Полнота ROUGE-1 делится на 0,4: короткий реферат человека не может
    вместить все значимые слова реферата системы, и 40 % хватает для полного
    балла. Точность — доля слов человека, которые есть и у системы, — не даёт
    обидеть короткий, но точный реферат из одной фразы о главном.
    """
    return 0.5 * coverage + 0.3 * min(1.0, rouge1.r / 0.4) + 0.2 * min(1.0, rouge1.p / 0.5)


def stars(value: float) -> int:
    for threshold, result in ((0.7, 5), (0.5, 4), (0.3, 3), (0.15, 2)):
        if value >= threshold:
            return result
    return 1


def judge(coverage: float, rouge1: Rouge, words: int, compression: float, on_topic: float,
          other_language: bool) -> Verdict:
    """Звёзды, заголовок и замечания — с поблажками, которых заслуживает человек."""
    if other_language:
        return Verdict(0, "Без оценки", "manual_language", [
            "Реферат написан на другом языке, чем отрывок, а сравнение идёт по словам: переводить система "
            "не умеет. Напишите реферат на языке отрывка."])
    notes: list[str] = []
    value = score(coverage, rouge1)
    occasion = ""
    low, high = config.PRACTICE_GOOD_LENGTH
    if words < 3:
        value *= 0.5
        notes.append("Слишком коротко: в реферате почти нет значимых слов.")
    if compression > config.PRACTICE_MAX_LENGTH:
        value *= 0.3
        occasion = "manual_long"
        notes.append(f"Реферат занимает {round(100 * compression)} % отрывка — это пересказ, а не реферат. "
                     "Обычно реферат в несколько раз короче текста.")
    elif compression > high:
        value *= 0.85
        notes.append(f"Длинновато: {round(100 * compression)} % отрывка. Хорошему реферату хватает "
                     f"{round(100 * low)}–{round(100 * high)} %.")
    elif compression < low and words >= 3 and value >= 0.3:
        notes.append("Очень сжато — это хорошо, если главное не потерялось.")
    if words >= 3 and on_topic < 0.3:
        notes.append("Большей части слов реферата в отрывке нет — возможно, он о другом.")
    result = stars(value)
    return Verdict(result, STAR_TITLES[result], occasion or f"manual_{result}", notes)
