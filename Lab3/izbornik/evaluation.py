"""Оценка качества рефератов и затраченного времени.

Эталон берётся из источника документа и во входной текст не попадает (см.
tools/build_collection.py): у статьи КиберЛенинки — авторская аннотация и
ключевые слова, у статьи Википедии — вводный раздел.

Точность классического реферата — мера ROUGE (Lin, 2004): доля n-грамм
эталона, найденных в реферате (полнота R), доля n-грамм реферата, найденных в
эталоне (точность P), и их гармоническое среднее F. N-граммы строятся по
леммам значимых слов: русская и немецкая морфология делают совпадение
словоформ слишком строгим («нейронных сетей» и «нейронные сети» — одно и то
же), а стоп-слова совпадают всегда и только завышают меру.

Чтобы число было осмысленным, метод сравнивается с базовыми способами отбора
того же числа предложений:

* lead — первые N предложений документа;
* random — N случайных предложений (среднее по 30 попыткам);
* score — только оценка по терминам Score(Sᵢ), без учёта положения;
* position — только положение Posd(Sᵢ) · Posp(Sᵢ), без учёта терминов;
* oracle — верхняя граница: предложения, жадно подобранные по самому
  эталону. Лучше этого никакой отбор предложений не сделает.

Ключевые слова оцениваются точностью: доля ключевых слов верхнего уровня,
встречающихся в эталонном реферате, — и для статей с авторскими ключевыми
словами полнотой: доля авторских ключевых слов, покрытых списком системы.
Для сравнения то же считается для списка самых частых существительных без
учёта df — так видно, что даёт множитель log(|DB| / df).
"""

from __future__ import annotations

import random
import statistics
import time
from collections import Counter
from dataclasses import asdict, dataclass, field

from izbornik import config, weights as w
from izbornik.collection import Collection
from izbornik.summary import Result
from izbornik.text.analysis import AnalyzedDocument, analyze

METHODS = ("extraction", "score", "position", "lead", "random", "oracle")
METHOD_NAMES = {
    "extraction": "Sentence extraction (Score·Posd·Posp)",
    "score": "Только Score (термины)",
    "position": "Только Posd·Posp (положение)",
    "lead": "Первые N предложений",
    "random": "Случайные N предложений",
    "oracle": "Оракул (верхняя граница)",
}
RANDOM_TRIALS = 30


# --- ROUGE ----------------------------------------------------------------------

def _grams(sequences: list[list[str]], n: int) -> Counter:
    grams: Counter = Counter()
    for seq in sequences:
        for i in range(len(seq) - n + 1):
            grams[tuple(seq[i:i + n])] += 1
    return grams


@dataclass
class Rouge:
    p: float
    r: float
    f: float


def rouge(candidate: list[list[str]], reference: list[list[str]], n: int) -> Rouge:
    cand, ref = _grams(candidate, n), _grams(reference, n)
    overlap = sum((cand & ref).values())
    p = overlap / sum(cand.values()) if cand else 0.0
    r = overlap / sum(ref.values()) if ref else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return Rouge(p, r, f)


def sentence_terms(document: AnalyzedDocument) -> list[list[str]]:
    """Леммы значимых слов каждого предложения документа."""
    return [[t.term for t in tokens if t.counted] for tokens in document.sentence_tokens]


def reference_terms(text: str, language: str) -> list[list[str]]:
    reference = analyze(text, language)
    return sentence_terms(reference) + [
        [t.term for t in tokens if t.counted] for tokens in reference.heading_tokens
    ]


# --- отбор предложений разными способами ---------------------------------------------

def select(method: str, result: Result, count: int, reference: list[list[str]] | None = None,
           rng: random.Random | None = None) -> list[int]:
    scores = result.scores
    total = len(scores)
    if method == "extraction":
        return w.select(scores, count)
    if method == "score":
        ranked = sorted(scores, key=lambda s: (-s.score, s.index))
        return sorted(s.index for s in ranked[:count])
    if method == "position":
        ranked = sorted(scores, key=lambda s: (-(s.posd * s.posp), s.index))
        return sorted(s.index for s in ranked[:count])
    if method == "lead":
        return list(range(min(count, total)))
    if method == "random":
        return sorted((rng or random.Random(0)).sample(range(total), min(count, total)))
    if method == "oracle":
        return _oracle(sentence_terms(result.document), reference or [], count)
    raise ValueError(method)


def _oracle(sentences: list[list[str]], reference: list[list[str]], count: int) -> list[int]:
    """Жадный отбор: на каждом шаге — предложение, сильнее всего повышающее R1 + R2."""
    chosen: list[int] = []
    for _ in range(min(count, len(sentences))):
        best, best_value = None, -1.0
        for index in range(len(sentences)):
            if index in chosen:
                continue
            trial = [sentences[i] for i in sorted(chosen + [index])]
            value = rouge(trial, reference, 1).r + rouge(trial, reference, 2).r
            if value > best_value:
                best, best_value = index, value
        if best is None:
            break
        chosen.append(best)
    return sorted(chosen)


# --- ключевые слова -------------------------------------------------------------

def keyword_scores(result: Result, reference: list[list[str]], author_keywords: list[str],
                   language: str) -> dict:
    ref_terms = {t for seq in reference for t in seq}
    heads = [kw for kw in result.summary.keywords.tree]
    head_terms = [kw.terms[0] for kw in heads if kw.terms]
    precision = sum(1 for t in head_terms if t in ref_terms) / len(head_terms) if head_terms else 0.0

    # сравнение: самые частые существительные без учёта df
    document = result.document
    frequent = sorted(document.noun_terms, key=lambda t: (-document.tf[t], t))[:len(head_terms) or 10]
    precision_tf = sum(1 for t in frequent if t in ref_terms) / len(frequent) if frequent else 0.0

    recall = recall_tf = None
    if author_keywords:
        system_terms = {t for kw in result.summary.keywords.flat() for t in kw.terms}
        frequent_terms = set(sorted(document.noun_terms, key=lambda t: (-document.tf[t], t))[:len(system_terms)])
        covered = covered_tf = 0
        for phrase in author_keywords:
            lemmas = {t for seq in reference_terms(phrase, language) for t in seq}
            if not lemmas:
                continue
            covered += lemmas <= system_terms
            covered_tf += lemmas <= frequent_terms
        recall = covered / len(author_keywords)
        recall_tf = covered_tf / len(author_keywords)
    return {
        "precision": precision,
        "precision_tf": precision_tf,
        "author_recall": recall,
        "author_recall_tf": recall_tf,
        "heads": [kw.text for kw in heads],
    }


# --- прогон по коллекции -------------------------------------------------------------

@dataclass
class DocumentScore:
    doc_id: str
    title: str
    language: str
    domain: str
    chars: int
    sentences: int
    reference_chars: int
    rouge: dict = field(default_factory=dict)      # метод -> {"r1": R, "r2": R, "p1":…, "f1":…}
    keywords: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)    # этап -> мс
    selected: list[int] = field(default_factory=list)
    oracle_overlap: int = 0                        # сколько предложений совпало с оракулом


@dataclass
class Evaluation:
    count: int
    documents: list[DocumentScore]
    groups: dict = field(default_factory=dict)
    size_study: dict = field(default_factory=dict)
    scope_study: dict = field(default_factory=dict)
    ostis: dict = field(default_factory=dict)
    elapsed_ms: float = 0.0
    created: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _row(values: dict) -> dict:
    return {k: round(v, 4) if isinstance(v, float) else v for k, v in values.items()}


def evaluate_document(collection: Collection, doc_id: str, count: int) -> DocumentScore:
    entry = collection.get(doc_id)
    analysis_ms = collection.analysis_ms(doc_id)
    started = time.perf_counter()
    result = collection.summarize(doc_id, count)
    summarize_ms = (time.perf_counter() - started) * 1000
    reference = reference_terms(entry.reference_abstract, entry.language)
    sentences = sentence_terms(result.document)

    score = DocumentScore(
        doc_id=doc_id, title=entry.title, language=entry.language, domain=entry.domain,
        chars=result.document.layout.length, sentences=len(result.document.layout.sentences),
        reference_chars=len(entry.reference_abstract),
    )
    rng = random.Random(17)
    selections: dict[str, list[int]] = {}
    for method in METHODS:
        if method == "random":
            trials = [select("random", result, count, rng=rng) for _ in range(RANDOM_TRIALS)]
            values = [(rouge([sentences[i] for i in t], reference, 1),
                       rouge([sentences[i] for i in t], reference, 2)) for t in trials]
            score.rouge[method] = _row({
                "r1": statistics.mean(v[0].r for v in values), "p1": statistics.mean(v[0].p for v in values),
                "f1": statistics.mean(v[0].f for v in values), "r2": statistics.mean(v[1].r for v in values),
                "p2": statistics.mean(v[1].p for v in values), "f2": statistics.mean(v[1].f for v in values),
            })
            continue
        chosen = select(method, result, count, reference)
        selections[method] = chosen
        picked = [sentences[i] for i in chosen]
        r1, r2 = rouge(picked, reference, 1), rouge(picked, reference, 2)
        score.rouge[method] = _row({"r1": r1.r, "p1": r1.p, "f1": r1.f, "r2": r2.r, "p2": r2.p, "f2": r2.f})
    score.selected = selections["extraction"]
    score.oracle_overlap = len(set(selections["extraction"]) & set(selections["oracle"]))
    score.keywords = _row(keyword_scores(result, reference, entry.reference_keywords, entry.language))
    score.timings = _row({**result.summary.timings, "analysis": analysis_ms, "summarize_total": summarize_ms})
    return score


def aggregate(scores: list[DocumentScore]) -> dict:
    """Средние по группам: язык × область, по языкам, по областям, по всей коллекции."""
    groups: dict[str, list[DocumentScore]] = {"all": list(scores)}
    for s in scores:
        groups.setdefault(f"{s.language}-{s.domain}", []).append(s)
        groups.setdefault(s.language, []).append(s)
        groups.setdefault(s.domain, []).append(s)
    result = {}
    for name, items in groups.items():
        rouge_mean = {
            method: {key: round(statistics.mean(i.rouge[method][key] for i in items), 4)
                     for key in ("r1", "p1", "f1", "r2", "p2", "f2")}
            for method in METHODS
        }
        kw = {
            key: round(statistics.mean(v for v in (i.keywords.get(key) for i in items) if v is not None), 4)
            for key in ("precision", "precision_tf", "author_recall", "author_recall_tf")
            if any(i.keywords.get(key) is not None for i in items)
        }
        timings = {
            key: round(statistics.mean(i.timings.get(key, 0.0) for i in items), 3)
            for key in ("analysis", "term_weights", "sentences", "keywords", "summarize_total")
        }
        result[name] = {
            "documents": len(items),
            "rouge": rouge_mean,
            "keywords": kw,
            "timings": timings,
            "oracle_overlap": round(statistics.mean(i.oracle_overlap for i in items), 2),
        }
    return result


def size_study(collection: Collection, sizes=(3, 5, 10, 15, 20)) -> dict:
    """Как меняются R1 и R2 с размером реферата — для метода и для первых N предложений."""
    study: dict = {}
    for size in sizes:
        values = {"extraction": [], "lead": []}
        for entry in collection:
            result = collection.summarize(entry.id, size)
            reference = reference_terms(entry.reference_abstract, entry.language)
            sentences = sentence_terms(result.document)
            for method in values:
                picked = [sentences[i] for i in select(method, result, size)]
                values[method].append((rouge(picked, reference, 1).r, rouge(picked, reference, 2).r))
        study[str(size)] = {
            method: {"r1": round(statistics.mean(v[0] for v in items), 4),
                     "r2": round(statistics.mean(v[1] for v in items), 4)}
            for method, items in values.items()
        }
    return study


def scope_study(collection: Collection, count: int) -> dict:
    """df по документам своего языка или по всей коллекции: что лучше совпадает с эталоном."""
    study: dict = {}
    for scope in ("language", "collection"):
        r1, r2 = [], []
        for entry in collection:
            result = collection.summarize(entry.id, count, scope=scope)
            reference = reference_terms(entry.reference_abstract, entry.language)
            sentences = sentence_terms(result.document)
            picked = [sentences[i] for i in w.select(result.scores, count)]
            r1.append(rouge(picked, reference, 1).r)
            r2.append(rouge(picked, reference, 2).r)
        study[scope] = {"r1": round(statistics.mean(r1), 4), "r2": round(statistics.mean(r2), 4)}
    return study


def prime() -> None:
    """Загружает словари pymorphy3 и стеммер до замеров времени.

    Их загрузка — разовая стоимость запуска (около секунды), и без прогрева
    она целиком легла бы на первый документ каждого языка.
    """
    analyze("Проверка разбора текста. Второе предложение.", "ru")
    analyze("Eine kurze Probe des Textes. Noch ein Satz.", "de")


def run(collection: Collection, count: int = config.SUMMARY_SENTENCES, studies: bool = True) -> Evaluation:
    from datetime import datetime

    started = time.perf_counter()
    prime()
    collection.warm_up()
    scores = [evaluate_document(collection, entry.id, count) for entry in collection]
    evaluation = Evaluation(count=count, documents=scores, groups=aggregate(scores))
    if studies:
        evaluation.size_study = size_study(collection)
        evaluation.scope_study = scope_study(collection, count)
    evaluation.elapsed_ms = (time.perf_counter() - started) * 1000
    evaluation.created = datetime.now().isoformat(timespec="seconds")
    return evaluation


def load(path) -> dict | None:
    import json
    from pathlib import Path

    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
