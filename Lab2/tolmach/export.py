"""Сохранение результатов в файл.

Методичка требует средств сохранения и распечатки выходной информации.
Распечатку обеспечивает интерфейс (страница `/print` с правилами @media print),
а за сохранение отвечает этот модуль: три формата на разные задачи.

    CSV  — таблица «документ — язык» для переноса в отчёт или таблицу;
    JSON — полные данные прогона, включая расстояния до каждого языка;
    TXT  — готовый к печати текстовый протокол.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path

from . import config, evaluation
from .models import Report

#: поддерживаемые форматы выгрузки: код -> (расширение, MIME-тип, название)
FORMATS: dict[str, tuple[str, str, str]] = {
    "csv": ("csv", "text/csv; charset=utf-8", "Таблица CSV"),
    "json": ("json", "application/json; charset=utf-8", "Полные данные JSON"),
    "txt": ("txt", "text/plain; charset=utf-8", "Текстовый протокол"),
}


def to_csv(report: Report) -> str:
    """Таблица результатов: по строке на документ, по колонке на метод."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    method_codes = list(report.scores)
    header = ["file", "title", "letters", "words", "gold"]
    for code in method_codes:
        header += [f"{code}_language", f"{code}_distance_ru", f"{code}_distance_de", f"{code}_ms"]
    header += ["consensus", "agreement", "correct"]
    writer.writerow(header)

    for verdict in report.verdicts:
        document = verdict.document
        row: list[object] = [
            document.doc_id,
            document.title,
            document.letters,
            document.words,
            document.gold or "",
        ]
        for code in method_codes:
            result = verdict.results.get(code)
            if result is None:
                row += ["", "", "", ""]
                continue
            row += [
                result.language,
                f"{result.distances.get('ru', 0.0):.6f}",
                f"{result.distances.get('de', 0.0):.6f}",
                f"{result.elapsed_ms:.3f}",
            ]
        correct = verdict.correct
        row += [
            verdict.language,
            f"{verdict.agreement:.2f}",
            "" if correct is None else ("да" if correct else "нет"),
        ]
        writer.writerow(row)

    # сводка по методам отделена пустой строкой — так её видно и в Excel
    writer.writerow([])
    writer.writerow(["method", "accuracy", "correct", "total", "mean_ms", "docs_per_second"])
    for code, score in report.scores.items():
        writer.writerow(
            [
                code,
                f"{score.accuracy:.4f}",
                score.correct,
                score.total,
                f"{score.mean_ms:.3f}",
                f"{score.per_second:.1f}",
            ]
        )
    consensus = report.consensus
    writer.writerow(
        [
            evaluation.CONSENSUS,
            f"{consensus.accuracy:.4f}",
            consensus.correct,
            consensus.total,
            f"{consensus.mean_ms:.3f}",
            f"{consensus.per_second:.1f}",
        ]
    )
    return buffer.getvalue()


def to_json(report: Report) -> str:
    """Полные данные прогона: расстояния, время, матрицы ошибок."""
    payload = {
        "application": "Толмач",
        "variant": 4,
        "languages": {code: config.language_name(code) for code in config.LANGUAGE_CODES},
        "created_at": report.created_at,
        "collection": {
            "size": report.size,
            "labelled": report.labelled,
            "by_language": report.by_language(),
        },
        "documents": [
            {
                "file": verdict.document.doc_id,
                "title": verdict.document.title,
                "letters": verdict.document.letters,
                "words": verdict.document.words,
                "size": verdict.document.size,
                "gold": verdict.document.gold,
                "consensus": verdict.language,
                "agreement": round(verdict.agreement, 3),
                "correct": verdict.correct,
                "methods": {
                    code: {
                        "language": result.language,
                        "distances": {
                            key: round(value, 6) for key, value in result.distances.items()
                        },
                        "confidence": round(result.confidence, 4),
                        "elapsed_ms": round(result.elapsed_ms, 3),
                    }
                    for code, result in verdict.results.items()
                },
            }
            for verdict in report.verdicts
        ],
        "scores": {
            code: {
                "accuracy": round(score.accuracy, 4),
                "correct": score.correct,
                "errors": score.errors,
                "total": score.total,
                "mean_ms": round(score.mean_ms, 3),
                "docs_per_second": round(score.per_second, 1),
                "confidence": round(score.confidence, 4),
                "confusion": score.confusion,
                "per_language": {
                    language: {
                        "precision": round(score.precision(language), 4),
                        "recall": round(score.recall(language), 4),
                        "f1": round(score.f1(language), 4),
                    }
                    for language in config.LANGUAGE_CODES
                },
            }
            for code, score in report.scores.items()
        },
        "consensus": {
            "accuracy": round(report.consensus.accuracy, 4),
            "correct": report.consensus.correct,
            "total": report.consensus.total,
            "mean_ms": round(report.consensus.mean_ms, 3),
            "confusion": report.consensus.confusion,
        },
        "speed": evaluation.speed_comparison(report),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def to_text(report: Report, method_titles: dict[str, str] | None = None) -> str:
    """Текстовый протокол прогона — то же, что печатает интерфейс."""
    titles = method_titles or {}
    width = 78
    lines: list[str] = [
        "=" * width,
        "СИСТЕМА РАСПОЗНАВАНИЯ ЯЗЫКА ТЕКСТА «ТОЛМАЧ»".center(width),
        "Лабораторная работа № 2, вариант 4".center(width),
        "русский / немецкий · формат HTML".center(width),
        "=" * width,
        f"Отчёт сформирован: {report.created_at}",
        "",
        "1. ТЕСТОВАЯ КОЛЛЕКЦИЯ",
        "-" * width,
    ]
    lines += [f"  {line}" for line in evaluation.summary_lines(report)[:2]]
    lines += ["", "2. РЕЗУЛЬТАТ ПО ДОКУМЕНТАМ", "-" * width]

    method_codes = list(report.scores)
    header = f"  {'документ':<28}{'эталон':<10}"
    for code in method_codes:
        header += f"{code:<10}"
    header += "итог"
    lines.append(header)
    lines.append("  " + "·" * (width - 2))

    for verdict in report.verdicts:
        row = f"  {verdict.document.doc_id[:27]:<28}{(verdict.document.gold or '—'):<10}"
        for code in method_codes:
            result = verdict.results.get(code)
            row += f"{(result.language if result else '—'):<10}"
        mark = "" if verdict.correct is None else ("  ✓" if verdict.correct else "  ✗")
        row += f"{verdict.language}{mark}"
        lines.append(row)

    lines += ["", "3. ТОЧНОСТЬ И БЫСТРОДЕЙСТВИЕ МЕТОДОВ", "-" * width]
    lines.append(
        f"  {'метод':<24}{'точность':>10}{'верно':>9}{'мс/док':>10}{'док/с':>10}"
    )
    lines.append("  " + "·" * (width - 2))
    for code, score in report.scores.items():
        name = titles.get(code, code)
        lines.append(
            f"  {name[:23]:<24}{score.accuracy:>9.1%}"
            f"{f'{score.correct}/{score.total}':>9}"
            f"{score.mean_ms:>10.2f}{score.per_second:>10.0f}"
        )
    consensus = report.consensus
    lines.append(
        f"  {evaluation.CONSENSUS_TITLE[:23]:<24}{consensus.accuracy:>9.1%}"
        f"{f'{consensus.correct}/{consensus.total}':>9}"
        f"{consensus.mean_ms:>10.2f}{consensus.per_second:>10.0f}"
    )

    lines += ["", "4. МАТРИЦЫ ОШИБОК", "-" * width]
    for code, score in report.scores.items():
        lines.append(f"  {titles.get(code, code)}")
        head = " " * 6 + "эталон \\ ответ"
        for predicted in config.LANGUAGE_CODES:
            head += f"{predicted:>8}"
        lines.append(head)
        for gold in config.LANGUAGE_CODES:
            row = " " * 6 + f"{gold:<14}"
            for predicted in config.LANGUAGE_CODES:
                row += f"{score.confusion.get(gold, {}).get(predicted, 0):>8}"
            lines.append(row)
        lines.append("")

    disagreements = report.disagreements()
    lines += ["5. РАЗНОГЛАСИЯ МЕТОДОВ", "-" * width]
    if not disagreements:
        lines.append("  Разногласий нет: все методы дали одинаковые ответы.")
    else:
        for verdict in disagreements:
            answers = ", ".join(
                f"{code} → {result.language}" for code, result in verdict.results.items()
            )
            lines.append(f"  {verdict.document.doc_id}: {answers}")

    lines += ["", "=" * width]
    return "\n".join(lines)


def render(report: Report, fmt: str, method_titles: dict[str, str] | None = None) -> str:
    """Формирует выгрузку в указанном формате."""
    if fmt == "csv":
        return to_csv(report)
    if fmt == "json":
        return to_json(report)
    if fmt == "txt":
        return to_text(report, method_titles)
    raise ValueError(f"неизвестный формат выгрузки: {fmt}")


def filename(fmt: str, prefix: str = "tolmach") -> str:
    """Имя файла выгрузки со штампом времени."""
    extension = FORMATS.get(fmt, (fmt, "", ""))[0]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{prefix}-{stamp}.{extension}"


def save(report: Report, fmt: str, directory: Path | None = None,
         method_titles: dict[str, str] | None = None) -> Path:
    """Сохраняет выгрузку в каталог отчёта и возвращает путь к файлу."""
    target = (directory or config.REPORT_DIR)
    target.mkdir(parents=True, exist_ok=True)
    path = target / filename(fmt)
    path.write_text(render(report, fmt, method_titles), encoding="utf-8")
    return path
