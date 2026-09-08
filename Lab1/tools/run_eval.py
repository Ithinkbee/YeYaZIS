"""Прогон оценки качества из командной строки: таблицы, CSV и графики для отчёта.

    python tools/run_eval.py                 — метрики базовой конфигурации
    python tools/run_eval.py --compare       — сравнение конфигураций
    python tools/run_eval.py --plots         — сохранить PNG в report/
    python tools/run_eval.py --top-k 10      — другая глубина выдачи
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arachne import config, db  # noqa: E402
from arachne.evaluation import plots, qrels, runner  # noqa: E402


def print_table(per_query: list[dict], summary: dict) -> None:
    header = (
        f"{'№':>3} {'запрос':46} {'rel':>4} {'P':>6} {'R':>6} {'F1':>6} "
        f"{'P@5':>6} {'P@10':>6} {'R-pr':>6} {'AP':>6} {'nDCG':>6} {'bpref':>6}"
    )
    print(header)
    print("-" * len(header))
    for item in per_query:
        print(
            f"{item['query_id']:>3} {item['query'][:45]:46} {item['relevant_total']:>4} "
            f"{item['precision']:6.3f} {item['recall']:6.3f} {item['f1']:6.3f} "
            f"{item['p@5']:6.3f} {item['p@10']:6.3f} {item['r_precision']:6.3f} "
            f"{item['ap']:6.3f} {item['ndcg']:6.3f} {item['bpref']:6.3f}"
        )
    print("-" * len(header))
    print(
        f"{'':>3} {'СРЕДНЕЕ':46} {'':>4} "
        f"{summary['precision']:6.3f} {summary['recall']:6.3f} {summary['f1']:6.3f} "
        f"{summary['p@5']:6.3f} {summary['p@10']:6.3f} {summary['r_precision']:6.3f} "
        f"{summary['map']:6.3f} {summary['ndcg']:6.3f} {summary['bpref']:6.3f}"
    )
    print(f"\nMAP = {summary['map']:.4f}   (усреднённая средняя точность)")
    print("11-точечный график «точность — полнота»:")
    for level, value in summary["curve"]:
        bar = "█" * int(round(value * 40))
        print(f"  полнота {level:.1f} → точность {value:.3f} {bar}")


def save_csv(per_query: list[dict], summary: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "query_id", "query", "relevant_total", "relevant_retrieved", "precision",
        "recall", "f1", "p@5", "p@10", "p@20", "r_precision", "ap", "ndcg", "bpref",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(columns)
        for item in per_query:
            writer.writerow(
                [
                    item[column] if not isinstance(item.get(column), float)
                    else f"{item[column]:.4f}"
                    for column in columns
                ]
            )
        writer.writerow([])
        writer.writerow(["Средние значения"])
        for key in ("precision", "recall", "f1", "p@5", "p@10", "p@20",
                    "r_precision", "map", "ndcg", "bpref"):
            writer.writerow([key, f"{summary[key]:.4f}"])
        writer.writerow([])
        writer.writerow(["Полнота", "Интерполированная точность"])
        for level, value in summary["curve"]:
            writer.writerow([f"{level:.1f}", f"{value:.4f}"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Оценка качества работы ИПС «Арахна»")
    parser.add_argument("--top-k", type=int, default=20, help="глубина выдачи")
    parser.add_argument("--synonyms", action="store_true", help="расширять запрос синонимами")
    parser.add_argument("--compare", action="store_true", help="сравнить конфигурации")
    parser.add_argument("--plots", action="store_true", help="сохранить графики в report/")
    parser.add_argument("--load-qrels", action="store_true", help="перечитать эталон из CSV")
    parser.add_argument("--csv", type=Path, default=None, help="путь для выгрузки CSV")
    arguments = parser.parse_args()

    conn = db.connect()
    db.init_db(conn)
    try:
        if arguments.load_qrels:
            loaded = qrels.load_from_csv(conn)
            print(
                f"Загружено запросов: {loaded['queries']}, оценок: {loaded['judgements']}"
                + (f", не найдено документов: {len(loaded['missing'])}" if loaded["missing"] else "")
            )

        outcome = runner.evaluate(
            conn,
            runner.RunConfig(use_synonyms=arguments.synonyms, top_k=arguments.top_k),
        )
        if outcome.get("error"):
            print("Ошибка:", outcome["error"])
            print("Подсказка: запустите с ключом --load-qrels")
            return

        print_table(outcome["per_query"], outcome["summary"])

        csv_path = arguments.csv or (config.REPORT_DIR / "metrics.csv")
        save_csv(outcome["per_query"], outcome["summary"], csv_path)
        print(f"\nТаблица метрик сохранена: {csv_path}")

        if arguments.compare:
            print("\nСравнение конфигураций:")
            comparison = runner.compare_configurations(conn, top_k=arguments.top_k)
            print(f"{'конфигурация':38} {'MAP':>6} {'P@10':>6} {'R-pr':>6} {'nDCG':>6} {'bpref':>6}")
            for item in comparison:
                summary = item["summary"]
                print(
                    f"{item['name'][:37]:38} {summary['map']:6.3f} {summary['p@10']:6.3f} "
                    f"{summary['r_precision']:6.3f} {summary['ndcg']:6.3f} {summary['bpref']:6.3f}"
                )

        if arguments.plots:
            paths = [
                plots.precision_recall_curve(outcome["summary"]["curve"]),
                plots.per_query_bars(outcome["per_query"], "ap"),
                plots.per_query_bars(outcome["per_query"], "p@10"),
                plots.configurations_chart(
                    runner.compare_configurations(conn, top_k=arguments.top_k)
                ),
            ]
            print("\nГрафики сохранены:")
            for path in paths:
                print(f"  {path}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
