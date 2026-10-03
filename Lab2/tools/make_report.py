"""Подготовка материалов для отчёта: таблицы, выгрузки и графики.

    python tools/make_report.py              — всё сразу
    python tools/make_report.py --no-charts  — без графиков
    python tools/make_report.py --quick      — без опытов по длине и смеси

Результат складывается в каталог `report`: выгрузки в трёх форматах и графики
в формате PNG, пригодные для вставки в пояснительную записку.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tolmach import config, console, corpus, evaluation, experiments, export  # noqa: E402
from tolmach.methods import METHOD_CODES, METHOD_REGISTRY  # noqa: E402
from tolmach.recognizer import Recognizer  # noqa: E402

console.setup()

#: цвет для каждого метода — один и тот же на всех графиках
COLORS = {"ngram": "#7a5c3e", "alphabet": "#a8552f", "neural": "#3a6383"}


def _titles() -> dict[str, str]:
    return {code: METHOD_REGISTRY[code].title for code in METHOD_CODES}


def draw_charts(report, length_study, mixture_study) -> list[Path]:
    """Строит графики для отчёта. Без matplotlib молча пропускается."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  matplotlib не установлен — графики пропущены")
        return []

    plt.rcParams.update({
        "font.size": 10,
        "figure.dpi": 130,
        "axes.grid": True,
        "grid.alpha": 0.25,
        "axes.spines.top": False,
        "axes.spines.right": False,
    })
    titles = _titles()
    produced: list[Path] = []

    # --- точность и время на полных документах -------------------------------
    figure, (left, right) = plt.subplots(1, 2, figsize=(10, 3.8))
    codes = list(METHOD_CODES)
    names = [titles[code].replace(" метод", "").replace("Метод ", "") for code in codes]

    left.bar(names, [report.scores[code].accuracy * 100 for code in codes],
             color=[COLORS[code] for code in codes])
    left.set_ylim(0, 105)
    left.set_ylabel("точность, %")
    left.set_title("Точность на тестовой коллекции")
    for index, code in enumerate(codes):
        left.text(index, report.scores[code].accuracy * 100 + 2,
                  f"{report.scores[code].accuracy:.0%}", ha="center", fontsize=9)

    times = [report.scores[code].mean_ms for code in codes]
    right.bar(names, times, color=[COLORS[code] for code in codes])
    right.set_ylim(0, max(times) * 1.15)  # запас сверху, иначе подпись упирается в рамку
    right.set_ylabel("мс на документ")
    right.set_title("Время распознавания одного документа")
    for index, value in enumerate(times):
        right.text(index, value + max(times) * 0.025, f"{value:.2f}", ha="center", fontsize=9)

    figure.tight_layout()
    path = config.REPORT_DIR / "accuracy_speed.png"
    figure.savefig(path)
    plt.close(figure)
    produced.append(path)

    # --- точность от длины входа ---------------------------------------------
    if length_study is not None:
        figure, (left, right) = plt.subplots(1, 2, figsize=(10, 3.8))
        for code in codes:
            points = length_study.curve(code)
            left.plot([x for x, _ in points], [y * 100 for _, y in points],
                      marker="o", color=COLORS[code], label=titles[code])
            row = length_study.points[code]
            right.plot(
                list(length_study.lengths),
                [row[length].mean_ms for length in length_study.lengths],
                marker="o", color=COLORS[code], label=titles[code],
            )
        left.set_xscale("log")
        left.set_xlabel("длина фрагмента, символов")
        left.set_ylabel("точность, %")
        left.set_ylim(40, 105)
        left.set_title("Точность и длина входного текста")
        left.legend(fontsize=8)

        right.set_xscale("log")
        right.set_yscale("log")
        right.set_xlabel("длина фрагмента, символов")
        right.set_ylabel("мс на фрагмент")
        right.set_title("Время и длина входного текста")
        right.legend(fontsize=8)

        figure.tight_layout()
        path = config.REPORT_DIR / "length_study.png"
        figure.savefig(path)
        plt.close(figure)
        produced.append(path)

    # --- поведение на смешанном тексте ---------------------------------------
    if mixture_study is not None:
        figure, axis = plt.subplots(figsize=(6.4, 3.8))
        for code in codes:
            row = mixture_study.shares[code]
            axis.plot([r * 100 for r in mixture_study.ratios],
                      [row[r] * 100 for r in mixture_study.ratios],
                      marker="o", color=COLORS[code], label=titles[code])
        axis.axvline(50, color="#999", linestyle="--", linewidth=1)
        axis.axhline(50, color="#999", linestyle=":", linewidth=1)
        axis.set_xlabel("доля немецкого текста в смеси, %")
        axis.set_ylabel("отнесено к немецкому, %")
        axis.set_title("Граница решения на смешанном тексте")
        axis.legend(fontsize=8)
        figure.tight_layout()
        path = config.REPORT_DIR / "mixture_study.png"
        figure.savefig(path)
        plt.close(figure)
        produced.append(path)

    # --- объём обучающего корпуса --------------------------------------------
    stats = corpus.corpus_stats()
    figure, axis = plt.subplots(figsize=(6.4, 3.2))
    languages = [config.language_name(code) for code in stats]
    axis.barh(languages, [item.kilobytes for item in stats.values()], color="#7a5c3e")
    axis.axvline(config.TRAIN_MIN_BYTES / 1024, color="#a83a34", linestyle="--", linewidth=1)
    axis.axvline(config.TRAIN_MAX_BYTES / 1024, color="#a83a34", linestyle="--", linewidth=1)
    axis.set_xlabel("объём корпуса, Кб")
    axis.set_title("Обучающий корпус и границы методички (20–120 Кб)")
    for index, item in enumerate(stats.values()):
        axis.text(item.kilobytes + 1.5, index, f"{item.kilobytes:.1f} Кб", va="center", fontsize=9)
    figure.tight_layout()
    path = config.REPORT_DIR / "corpus.png"
    figure.savefig(path)
    plt.close(figure)
    produced.append(path)

    return produced


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-charts", action="store_true", help="не строить графики")
    parser.add_argument("--quick", action="store_true", help="без опытов по длине и смеси")
    arguments = parser.parse_args()

    config.ensure_dirs()

    print("Подготовка профилей…")
    recognizer = Recognizer()
    try:
        from_disk = recognizer.load_or_fit()
    except (FileNotFoundError, ValueError) as problem:
        print(f"ОШИБКА: {problem}")
        return 1
    print(f"  профили {'прочитаны с диска' if from_disk else 'построены заново'}")

    print("\nПрогон тестовой коллекции…")
    documents = corpus.load_collection()
    if not documents:
        print(f"ОШИБКА: коллекция пуста ({config.COLLECTION_DIR})")
        return 1
    started = time.perf_counter()
    verdicts = recognizer.recognize_all(documents)
    report = evaluation.build_report(verdicts, METHOD_CODES)
    print(f"  {len(documents)} документов за {(time.perf_counter() - started) * 1000:.0f} мс")
    for line in evaluation.summary_lines(report):
        print(f"  {line}")

    length_study = mixture_study = None
    if not arguments.quick:
        print("\nОпыт: зависимость точности от длины входа…")
        length_study = experiments.run_length_study(recognizer, documents)
        for line in experiments.summary_lines(length_study):
            print(f"  {line}")

        print("\nОпыт: смешанный текст…")
        mixture_study = experiments.run_mixture_study(recognizer, documents)
        for line in experiments.mixture_lines(mixture_study):
            print(f"  {line}")

    print("\nВыгрузки:")
    titles = _titles()
    for fmt in export.FORMATS:
        path = config.REPORT_DIR / f"results.{export.FORMATS[fmt][0]}"
        path.write_text(export.render(report, fmt, titles), encoding="utf-8")
        print(f"  {path.name:16} {path.stat().st_size / 1024:6.1f} Кб")

    if not arguments.no_charts:
        print("\nГрафики:")
        for path in draw_charts(report, length_study, mixture_study):
            print(f"  {path.name}")

    print(f"\nГотово. Каталог отчёта: {config.REPORT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
