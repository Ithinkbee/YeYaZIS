"""Оценка качества перевода.

Для 120 предложений тестовой коллекции (по 10 из каждого документа) есть
эталонные переводы, подготовленные независимо от системы
(data/reference/references.tsv).
Машинный перевод сравнивается с эталоном двумя принятыми в машинном переводе
мерами:

* **BLEU** (Papineni и др., 2002) — доля совпавших с эталоном n-грамм слов
  (n = 1…4), среднее геометрическое, со штрафом за слишком короткий перевод.
  Считается по всему набору сразу (corpus BLEU), с учётом регистра — в
  немецком заглавная буква существительного входит в правописание;
* **chrF** (Popović, 2015) — F-мера по n-граммам символов (n = 1…6), β = 2.
  Она мягче к морфологии: «neuronalen» и «neuronales» совпадают почти целиком,
  а для немецкого с его падежными окончаниями это важно.

Сравниваются два способа перевода — пословный (системы первого поколения) и
с трансфером, — а также доля переведённых слов со словообразовательными
правилами и без них и время работы по этапам.
"""

from __future__ import annotations

import math
import re
import statistics
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from dragoman import config
from dragoman.collection import Collection

REFERENCES = config.REFERENCE_DIR / "references.tsv"
MODES = ("transfer", "direct")

_TOKEN = re.compile(r"\w+(?:[-'’]\w+)*|[^\w\s]", re.UNICODE)


def tokens(text: str) -> list[str]:
    text = text.replace("„", '"').replace("“", '"').replace("”", '"').replace("‚", "'").replace("‘", "'")
    return _TOKEN.findall(text)


def ngrams(items: list[str], n: int) -> Counter:
    return Counter(tuple(items[i:i + n]) for i in range(len(items) - n + 1))


def bleu(hypotheses: list[str], references: list[str], max_n: int = 4) -> dict:
    """Corpus BLEU-4 с одним эталоном."""
    matches = [0] * max_n
    totals = [0] * max_n
    hyp_len = ref_len = 0
    for hyp, ref in zip(hypotheses, references):
        h, r = tokens(hyp), tokens(ref)
        hyp_len += len(h)
        ref_len += len(r)
        for n in range(1, max_n + 1):
            hn, rn = ngrams(h, n), ngrams(r, n)
            matches[n - 1] += sum(min(count, rn[g]) for g, count in hn.items())
            totals[n - 1] += max(0, len(h) - n + 1)
    precisions = [(m / t) if t else 0.0 for m, t in zip(matches, totals)]
    if min(precisions) == 0:
        score = 0.0
    else:
        score = math.exp(sum(math.log(p) for p in precisions) / max_n)
    bp = 1.0 if hyp_len > ref_len else math.exp(1 - ref_len / max(1, hyp_len))
    return {"bleu": 100 * score * bp, "precisions": [100 * p for p in precisions], "bp": bp,
            "ratio": hyp_len / max(1, ref_len), "hyp_len": hyp_len, "ref_len": ref_len}


def sentence_bleu(hypothesis: str, reference: str) -> float:
    """BLEU предложения со сглаживанием (+1 к числителю и знаменателю для n > 1)."""
    h, r = tokens(hypothesis), tokens(reference)
    if not h:
        return 0.0
    logs = []
    for n in range(1, 5):
        hn, rn = ngrams(h, n), ngrams(r, n)
        match = sum(min(count, rn[g]) for g, count in hn.items())
        total = max(0, len(h) - n + 1)
        if n > 1:
            match, total = match + 1, total + 1
        logs.append(math.log(match / total) if match and total else math.log(1e-9))
    bp = 1.0 if len(h) > len(r) else math.exp(1 - len(r) / len(h))
    return 100 * bp * math.exp(sum(logs) / 4)


def chrf(hypothesis: str, reference: str, n_max: int = 6, beta: float = 2.0) -> float:
    """chrF: F-мера по n-граммам символов без пробелов, усреднение по n."""
    h = re.sub(r"\s+", "", hypothesis)
    r = re.sub(r"\s+", "", reference)
    precisions, recalls = [], []
    for n in range(1, n_max + 1):
        hn = Counter(h[i:i + n] for i in range(len(h) - n + 1))
        rn = Counter(r[i:i + n] for i in range(len(r) - n + 1))
        if not hn or not rn:
            continue
        match = sum(min(count, rn[g]) for g, count in hn.items())
        precisions.append(match / sum(hn.values()))
        recalls.append(match / sum(rn.values()))
    if not precisions:
        return 0.0
    p, rcl = statistics.mean(precisions), statistics.mean(recalls)
    if p + rcl == 0:
        return 0.0
    return 100 * (1 + beta ** 2) * p * rcl / (beta ** 2 * p + rcl)


def corpus_chrf(hypotheses: list[str], references: list[str]) -> float:
    return statistics.mean(chrf(h, r) for h, r in zip(hypotheses, references)) if hypotheses else 0.0


def load_references(path: Path = REFERENCES) -> list[dict]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        doc, index, english, german = line.split("\t")
        rows.append({"doc": doc, "index": int(index), "en": english, "ref": german})
    return rows


def run(translator, collection: Collection | None = None, references: Path = REFERENCES) -> dict:
    """Переводит коллекцию обоими способами и считает меры качества, долю перевода и время."""
    collection = collection or Collection()
    refs = load_references(references)
    by_doc: dict[str, list[dict]] = {}
    for row in refs:
        by_doc.setdefault(row["doc"], []).append(row)

    documents = []
    sentences = []
    translator.analyzer.analyze("Warm up.")      # модели загружаются один раз — не в замер первого документа
    for entry in collection:
        text = collection.text(entry.id)
        record = {"id": entry.id, "title": entry.title, "domain": entry.domain, "coverage": {}, "time_ms": {},
                  "unknown": {}, "words": 0}
        results = {}
        for mode in MODES:
            started = time.perf_counter()
            t = translator.translate(text, entry.title, entry.domain, mode, log_unknown=False, source=entry.source_url)
            elapsed = 1000 * (time.perf_counter() - started)
            results[mode] = t
            record["coverage"][mode] = t.stats["coverage"]
            record["unknown"][mode] = t.stats["unknown"]
            record["words"] = t.stats["words"]
            record["sentences"] = t.stats["sentences"]
            record["time_ms"][mode] = {"total": t.timings.get("total", elapsed), "segment": t.timings.get("segment"),
                                       "tagging": t.timings.get("tagging"), "parsing": t.timings.get("parsing"),
                                       "transfer": t.timings.get("transfer")}
        no_rules = translator.translate(text, entry.title, entry.domain, "transfer", log_unknown=False,
                                        use_rules=False)
        record["coverage"]["no_rules"] = no_rules.stats["coverage"]
        record["rule_words"] = results["transfer"].stats["rule_words"]
        record["unknown_words"] = results["transfer"].stats["unknown_words"]
        for row in by_doc.get(entry.id, []):
            item = {**row, "domain": entry.domain}
            for mode in MODES:
                hyp = results[mode].sentences[row["index"]].text
                item[mode] = hyp
                item[f"chrf_{mode}"] = chrf(hyp, row["ref"])
                item[f"bleu_{mode}"] = sentence_bleu(hyp, row["ref"])
            sentences.append(item)
        documents.append(record)

    def scores(rows: list[dict]) -> dict:
        result = {}
        for mode in MODES:
            hyps = [r[mode] for r in rows]
            refs_ = [r["ref"] for r in rows]
            b = bleu(hyps, refs_)
            result[mode] = {"bleu": b["bleu"], "precisions": b["precisions"], "bp": b["bp"], "ratio": b["ratio"],
                            "chrf": corpus_chrf(hyps, refs_), "sentences": len(rows)}
        wins = sum(1 for r in rows if r["chrf_transfer"] > r["chrf_direct"] + 0.5)
        losses = sum(1 for r in rows if r["chrf_transfer"] < r["chrf_direct"] - 0.5)
        result["wins"] = {"transfer": wins, "direct": losses, "ties": len(rows) - wins - losses}
        return result

    groups = {"all": scores(sentences)}
    for code in config.DOMAIN_CODES:
        groups[code] = scores([r for r in sentences if r["domain"] == code])

    def mean(values):
        values = [v for v in values if v is not None]
        return statistics.mean(values) if values else None

    timings = {}
    for mode in MODES:
        timings[mode] = {
            "total": mean(d["time_ms"][mode]["total"] for d in documents),
            "segment": mean(d["time_ms"][mode]["segment"] for d in documents),
            "tagging": mean(d["time_ms"][mode]["tagging"] for d in documents),
            "parsing": mean(d["time_ms"][mode]["parsing"] for d in documents),
            "transfer": mean(d["time_ms"][mode]["transfer"] for d in documents),
        }
    words = sum(d["words"] for d in documents)
    coverage = {mode: sum(d["coverage"][mode] * d["words"] for d in documents) / max(1, words)
                for mode in ("transfer", "direct", "no_rules")}
    return {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "references": len(sentences),
        "documents": documents,
        "sentences": sentences,
        "groups": groups,
        "timings": timings,
        "coverage": coverage,
        "words": words,
        "lexicon": translator.lexicon.stats(),
    }
