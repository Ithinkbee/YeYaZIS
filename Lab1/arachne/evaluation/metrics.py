"""Метрики качества информационного поиска (по материалам РОМИП).

Все функции работают с ранжированным списком идентификаторов документов
(в порядке выдачи) и с эталонной разметкой релевантности rel_map вида
{doc_id: степень релевантности}, где 0 — нерелевантен.
"""

from __future__ import annotations

import math

#: уровни полноты для усреднённого графика «точность — полнота»
RECALL_LEVELS = [round(0.1 * i, 1) for i in range(11)]


def _relevant_set(rel_map: dict[int, int]) -> set[int]:
    return {doc_id for doc_id, rel in rel_map.items() if rel > 0}


def precision(ranked: list[int], rel_map: dict[int, int]) -> float:
    """Точность: доля релевантных среди найденных."""
    if not ranked:
        return 0.0
    relevant = _relevant_set(rel_map)
    return sum(1 for doc_id in ranked if doc_id in relevant) / len(ranked)


def recall(ranked: list[int], rel_map: dict[int, int]) -> float:
    """Полнота: доля найденных релевантных среди всех релевантных."""
    relevant = _relevant_set(rel_map)
    if not relevant:
        return 0.0
    return sum(1 for doc_id in ranked if doc_id in relevant) / len(relevant)


def f_measure(p: float, r: float, beta: float = 1.0) -> float:
    """F-мера — гармоническое среднее точности и полноты."""
    if p <= 0 or r <= 0:
        return 0.0
    b2 = beta * beta
    return (1 + b2) * p * r / (b2 * p + r)


def precision_at_k(ranked: list[int], rel_map: dict[int, int], k: int) -> float:
    """Точность на уровне первых k документов выдачи."""
    if k <= 0:
        return 0.0
    relevant = _relevant_set(rel_map)
    top = ranked[:k]
    return sum(1 for doc_id in top if doc_id in relevant) / k


def r_precision(ranked: list[int], rel_map: dict[int, int]) -> float:
    """R-точность: точность на уровне R, где R — число релевантных документов."""
    relevant = _relevant_set(rel_map)
    if not relevant:
        return 0.0
    return precision_at_k(ranked, rel_map, len(relevant))


def average_precision(ranked: list[int], rel_map: dict[int, int]) -> float:
    """Средняя точность по запросу: среднее точностей в точках попадания."""
    relevant = _relevant_set(rel_map)
    if not relevant:
        return 0.0
    hits = 0
    total = 0.0
    for position, doc_id in enumerate(ranked, 1):
        if doc_id in relevant:
            hits += 1
            total += hits / position
    return total / len(relevant)


def precision_recall_points(
    ranked: list[int], rel_map: dict[int, int]
) -> list[tuple[float, float]]:
    """Точки (полнота, точность) в позициях, где найден релевантный документ."""
    relevant = _relevant_set(rel_map)
    if not relevant:
        return []
    points = []
    hits = 0
    for position, doc_id in enumerate(ranked, 1):
        if doc_id in relevant:
            hits += 1
            points.append((hits / len(relevant), hits / position))
    return points


def interpolated_precision(
    ranked: list[int], rel_map: dict[int, int]
) -> list[tuple[float, float]]:
    """Интерполированная точность на 11 стандартных уровнях полноты.

    P_int(r) = max{ P(r') : r' >= r } — классическое определение,
    используемое для построения графика «точность — полнота».
    """
    points = precision_recall_points(ranked, rel_map)
    result = []
    for level in RECALL_LEVELS:
        candidates = [p for r, p in points if r >= level - 1e-9]
        result.append((level, max(candidates) if candidates else 0.0))
    return result


def dcg(ranked: list[int], rel_map: dict[int, int], k: int | None = None) -> float:
    """Накопленный выигрыш с учётом позиции документа в выдаче."""
    top = ranked[: k or len(ranked)]
    total = 0.0
    for position, doc_id in enumerate(top, 1):
        gain = rel_map.get(doc_id, 0)
        if gain:
            total += (2 ** gain - 1) / math.log2(position + 1)
    return total


def ndcg(ranked: list[int], rel_map: dict[int, int], k: int | None = None) -> float:
    """Нормированный накопленный выигрыш: DCG выдачи к DCG идеального порядка."""
    ideal_order = sorted(
        (doc_id for doc_id, rel in rel_map.items() if rel > 0),
        key=lambda doc_id: -rel_map[doc_id],
    )
    ideal = dcg(ideal_order, rel_map, k)
    if ideal <= 0:
        return 0.0
    return dcg(ranked, rel_map, k) / ideal


def bpref(ranked: list[int], rel_map: dict[int, int]) -> float:
    """bpref — метрика, устойчивая к неполноте эталонной разметки.

    Учитывает только документы, для которых есть оценка: считает, сколько
    оценённых нерелевантных документов стоит выше каждого релевантного.
    """
    relevant = _relevant_set(rel_map)
    judged_irrelevant = {doc_id for doc_id, rel in rel_map.items() if rel == 0}
    R = len(relevant)
    N = len(judged_irrelevant)
    if R == 0:
        return 0.0
    if N == 0:
        return 1.0 if any(doc_id in relevant for doc_id in ranked) else 0.0
    total = 0.0
    seen_irrelevant = 0
    for doc_id in ranked:
        if doc_id in relevant:
            total += 1.0 - min(seen_irrelevant, R) / min(R, N)
        elif doc_id in judged_irrelevant:
            seen_irrelevant += 1
    return total / R


def evaluate_query(
    ranked: list[int],
    rel_map: dict[int, int],
    k_values: tuple[int, ...] = (5, 10, 20),
) -> dict:
    """Полный набор метрик по одному запросу."""
    relevant = _relevant_set(rel_map)
    retrieved_relevant = sum(1 for doc_id in ranked if doc_id in relevant)
    p = precision(ranked, rel_map)
    r = recall(ranked, rel_map)
    result = {
        "retrieved": len(ranked),
        "relevant_total": len(relevant),
        "relevant_retrieved": retrieved_relevant,
        "precision": p,
        "recall": r,
        "f1": f_measure(p, r),
        "r_precision": r_precision(ranked, rel_map),
        "ap": average_precision(ranked, rel_map),
        "ndcg": ndcg(ranked, rel_map),
        "ndcg@10": ndcg(ranked, rel_map, 10),
        "bpref": bpref(ranked, rel_map),
        "curve": interpolated_precision(ranked, rel_map),
    }
    for k in k_values:
        result[f"p@{k}"] = precision_at_k(ranked, rel_map, k)
    return result


def macro_average(per_query: list[dict], k_values: tuple[int, ...] = (5, 10, 20)) -> dict:
    """Усреднение метрик по набору запросов (MAP и прочие средние)."""
    if not per_query:
        return {}
    keys = ["precision", "recall", "f1", "r_precision", "ndcg", "ndcg@10", "bpref"]
    keys += [f"p@{k}" for k in k_values]
    averaged = {
        key: sum(item.get(key, 0.0) for item in per_query) / len(per_query)
        for key in keys
    }
    averaged["map"] = sum(item.get("ap", 0.0) for item in per_query) / len(per_query)
    averaged["queries"] = len(per_query)
    averaged["curve"] = averaged_curve(per_query)
    return averaged


def averaged_curve(per_query: list[dict]) -> list[tuple[float, float]]:
    """Усреднённый по запросам 11-точечный график «точность — полнота»."""
    if not per_query:
        return []
    sums = [0.0] * len(RECALL_LEVELS)
    for item in per_query:
        for index, (_, value) in enumerate(item.get("curve", [])):
            sums[index] += value
    return [
        (level, sums[index] / len(per_query))
        for index, level in enumerate(RECALL_LEVELS)
    ]
