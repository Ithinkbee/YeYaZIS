"""Оценка качества и быстродействия методов на тестовой коллекции.

Методичка требует сравнить методы «по точности и затраченному времени»,
поэтому по каждому методу считаются:

    точность  — доля документов, язык которых определён верно;
    матрица ошибок — куда именно уходят ошибочные документы;
    точность и полнота по каждому языку;
    среднее время распознавания одного документа и производительность.

Отдельной строкой оценивается согласованное решение трёх методов: оно
показывает, даёт ли голосование выигрыш по сравнению с лучшим методом.
"""

from __future__ import annotations

from datetime import datetime

from . import config
from .models import MethodScore, Report, Verdict

#: имя строки сводного решения в таблицах
CONSENSUS = "consensus"
CONSENSUS_TITLE = "Согласованное решение"


def _empty_confusion() -> dict[str, dict[str, int]]:
    """Нулевая матрица ошибок: эталон -> (ответ -> количество)."""
    return {
        gold: {predicted: 0 for predicted in config.LANGUAGE_CODES}
        for gold in config.LANGUAGE_CODES
    }


def score_method(verdicts: list[Verdict], method: str) -> MethodScore:
    """Считает качество и быстродействие одного метода."""
    confusion = _empty_confusion()
    correct = total = 0
    elapsed = 0.0
    confidence = 0.0
    counted = 0

    for verdict in verdicts:
        result = verdict.results.get(method)
        if result is None:
            continue
        elapsed += result.elapsed_ms
        confidence += result.confidence
        counted += 1
        gold = verdict.document.gold
        if gold is None:
            continue
        total += 1
        confusion.setdefault(gold, {}).setdefault(result.language, 0)
        confusion[gold][result.language] += 1
        if gold == result.language:
            correct += 1

    return MethodScore(
        method=method,
        correct=correct,
        total=total,
        elapsed_ms=elapsed,
        confusion=confusion,
        confidence=confidence / counted if counted else 0.0,
    )


def score_consensus(verdicts: list[Verdict]) -> MethodScore:
    """Считает качество согласованного решения.

    Время берётся суммарным по всем методам: чтобы получить голосование,
    нужно выполнить каждый метод, и честно учитывать полную стоимость.
    """
    confusion = _empty_confusion()
    correct = total = 0
    elapsed = 0.0
    agreement = 0.0

    for verdict in verdicts:
        elapsed += verdict.elapsed_ms
        agreement += verdict.agreement
        gold = verdict.document.gold
        if gold is None:
            continue
        total += 1
        confusion.setdefault(gold, {}).setdefault(verdict.language, 0)
        confusion[gold][verdict.language] += 1
        if gold == verdict.language:
            correct += 1

    return MethodScore(
        method=CONSENSUS,
        correct=correct,
        total=total,
        elapsed_ms=elapsed,
        confusion=confusion,
        confidence=agreement / len(verdicts) if verdicts else 0.0,
    )


def build_report(verdicts: list[Verdict], method_codes: tuple[str, ...]) -> Report:
    """Собирает полный отчёт по прогону тестовой коллекции."""
    return Report(
        verdicts=verdicts,
        scores={code: score_method(verdicts, code) for code in method_codes},
        consensus=score_consensus(verdicts),
        created_at=datetime.now().isoformat(timespec="seconds"),
    )


def speed_comparison(report: Report) -> list[dict[str, object]]:
    """Сравнение методов по точности и быстродействию — таблица для отчёта.

    Колонка «относительно самого быстрого» отвечает на вопрос, во сколько раз
    метод медленнее лидера: абсолютные миллисекунды зависят от машины, а это
    отношение — нет.
    """
    rows: list[dict[str, object]] = []
    times = [score.mean_ms for score in report.scores.values() if score.mean_ms > 0]
    fastest = min(times) if times else 0.0

    for code, score in report.scores.items():
        rows.append(
            {
                "method": code,
                "accuracy": score.accuracy,
                "correct": score.correct,
                "errors": score.errors,
                "total": score.total,
                "mean_ms": score.mean_ms,
                "per_second": score.per_second,
                "slowdown": (score.mean_ms / fastest) if fastest else 0.0,
                "confidence": score.confidence,
            }
        )
    rows.sort(key=lambda row: (-float(row["accuracy"]), float(row["mean_ms"])))
    return rows


def summary_lines(report: Report) -> list[str]:
    """Короткая сводка по прогону — для консоли и шапки выгрузки."""
    counts = report.by_language()
    distribution = ", ".join(
        f"{config.language_name(code)} — {counts.get(code, 0)}"
        for code in config.LANGUAGE_CODES
    )
    lines = [
        f"Документов в коллекции: {report.size} (размечено {report.labelled})",
        f"Распределение по языкам: {distribution}",
    ]
    for code, score in report.scores.items():
        lines.append(
            f"{code}: точность {score.accuracy:.1%} "
            f"({score.correct} из {score.total}), "
            f"{score.mean_ms:.2f} мс на документ"
        )
    lines.append(
        f"{CONSENSUS}: точность {report.consensus.accuracy:.1%} "
        f"({report.consensus.correct} из {report.consensus.total}), "
        f"{report.consensus.mean_ms:.2f} мс на документ"
    )
    disagreements = report.disagreements()
    if disagreements:
        lines.append(f"Методы разошлись на документах: {len(disagreements)}")
    return lines
