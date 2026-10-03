"""Оценка точности и затраченного времени; выгрузки и графики для отчёта.

    python tools/evaluate.py              оценка, замеры OSTIS (если доступна), графики
    python tools/evaluate.py --no-ostis   без замеров OSTIS
    python tools/evaluate.py --quick      без опытов с размером реферата и базой df

Результаты:
    report/evaluation.json   все числа (их же показывает страница «Оценка»)
    report/evaluation.csv    таблица «документ × способ отбора»
    report/eval_rouge.png    ROUGE-1 по группам и способам отбора
    report/eval_size.png     зависимость полноты от размера реферата
    report/eval_time.png     время построения реферата по этапам

Если веб-интерфейс запущен, его sc-агент уже зарегистрирован; второй агент
обработал бы то же действие повторно. Поэтому при запущенном интерфейсе
замеры OSTIS используют его агента, а свой не регистрируется.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from izbornik import config, console, evaluation as ev  # noqa: E402
from izbornik.collection import Collection  # noqa: E402

console.setup()

OUT = config.REPORT_DIR
GROUP_ORDER = ["ru-cs", "ru-lit", "de-cs", "de-lit", "all"]
GROUP_NAMES = {"ru-cs": "рус., CS", "ru-lit": "рус., литература", "de-cs": "нем., CS",
               "de-lit": "нем., литература", "all": "вся коллекция"}
TICK_NAMES = {"ru-cs": "русский\nCS", "ru-lit": "русский\nлитература", "de-cs": "немецкий\nCS",
              "de-lit": "немецкий\nлитература", "all": "вся\nколлекция"}

# категориальная палитра: порядок слотов фиксирован, оракул — нейтральный серый
SERIES = {"extraction": "#2a78d6", "lead": "#eb6834", "random": "#1baf7a", "oracle": "#a5a39c"}
STAGES = {"analysis": "#2a78d6", "term_weights": "#eb6834", "sentences": "#1baf7a", "keywords": "#eda100"}
INK, MUTED, GRID = "#1f1d1a", "#6b6862", "#e6e3dc"


def web_running() -> bool:
    try:
        urllib.request.urlopen(f"http://{config.HOST}:{config.PORT}/help", timeout=1)
        return True
    except Exception:  # noqa: BLE001
        return False


def measure_ostis(collection: Collection) -> dict:
    """Время работы через OSTIS: вызов агента и чтение готового реферата из базы знаний."""
    from izbornik.ostis.service import Service

    external = web_running()
    service = Service(collection, mode="on", agent_mode="external" if external else "embedded")
    if not service.start():
        print(f"  OSTIS недоступна: {service.error}")
        return {}
    print(f"  OSTIS: агент {'веб-интерфейса' if external else 'этого процесса'}")
    try:
        first: dict[str, float] = {}
        agent, work, read, matches = [], [], [], 0
        for entry in collection:
            local = collection.summarize(entry.id, config.SUMMARY_SENTENCES).summary
            started = time.perf_counter()
            built = service.summarize_entry(entry, config.SUMMARY_SENTENCES, force=True)
            elapsed = (time.perf_counter() - started) * 1000
            if entry.language not in first:
                first[entry.language] = elapsed
            else:
                agent.append(elapsed)
            work.append(built.timings.get("agent", 0.0))
            started = time.perf_counter()
            again = service.summarize_entry(entry, config.SUMMARY_SENTENCES)
            read.append((time.perf_counter() - started) * 1000)
            same = ([s.index for s in again.sentences] == [s.index for s in local.sentences]
                    and [k.text for k in again.keywords.tree] == [k.text for k in local.keywords.tree])
            matches += same
            print(f"    {entry.id:20} агент {elapsed:7.0f} мс, чтение {read[-1]:5.0f} мс, "
                  f"{'совпадает' if same else 'РАСХОДИТСЯ'} с локальным расчётом")
        return {
            "documents": len(collection),
            "matches": matches,
            "agent_first_ms": round(statistics.mean(first.values()), 1),
            "agent_ms": round(statistics.mean(agent), 1) if agent else None,
            "agent_work_ms": round(statistics.mean(work), 1),
            "kb_read_ms": round(statistics.mean(read), 1),
            "sync_ms": round(service.synced.get("ms", 0.0), 1),
            "ontology_ms": round(service.ontology.elapsed_ms, 1) if service.ontology else None,
        }
    finally:
        service.stop()


def write_csv(data: dict, path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        header = ["документ", "язык", "область", "знаков", "эталон, знаков"]
        for method in ev.METHODS:
            header += [f"{method} R1", f"{method} R2"]
        header += ["точность ключ. слов", "полнота по авторским", "время, мс"]
        writer.writerow(header)
        for d in data["documents"]:
            row = [d["doc_id"], d["language"], d["domain"], d["chars"], d["reference_chars"]]
            for method in ev.METHODS:
                row += [d["rouge"][method]["r1"], d["rouge"][method]["r2"]]
            row += [d["keywords"].get("precision"), d["keywords"].get("author_recall"),
                    round(d["timings"]["analysis"] + d["timings"]["summarize_total"], 1)]
            writer.writerow(row)


# --- графики ----------------------------------------------------------------------

def _style(ax) -> None:
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def plot_rouge(data: dict, path: Path) -> None:
    import matplotlib.pyplot as plt

    methods = ["extraction", "lead", "random", "oracle"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), dpi=150)
    width = 0.19
    for ax, key, title in zip(axes, ("r1", "r2"), ("ROUGE-1, полнота", "ROUGE-2, полнота")):
        for i, method in enumerate(methods):
            xs = [g + (i - 1.5) * (width + 0.015) for g in range(len(GROUP_ORDER))]
            ys = [data["groups"][g]["rouge"][method][key] for g in GROUP_ORDER]
            ax.bar(xs, ys, width, color=SERIES[method], label=ev.METHOD_NAMES[method],
                   edgecolor="white", linewidth=1.2)
            if method == "extraction":
                for x, y in zip(xs, ys):
                    ax.text(x, y + 0.006, f"{y:.2f}".replace(".", ","), ha="center", va="bottom",
                            fontsize=7.5, color=INK)
        ax.set_xticks(range(len(GROUP_ORDER)), [TICK_NAMES[g] for g in GROUP_ORDER], fontsize=9)
        ax.set_title(title, fontsize=11, color=INK, loc="left")
        _style(ax)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=4, frameon=False, fontsize=9)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def plot_size(data: dict, path: Path) -> None:
    import matplotlib.pyplot as plt

    sizes = [int(s) for s in data["size_study"]]
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8), dpi=150)
    for ax, key, title in zip(axes, ("r1", "r2"), ("ROUGE-1, полнота", "ROUGE-2, полнота")):
        for method in ("extraction", "lead"):
            ys = [data["size_study"][str(s)][method][key] for s in sizes]
            ax.plot(sizes, ys, color=SERIES[method], linewidth=2, marker="o", markersize=5,
                    label=ev.METHOD_NAMES[method])
            ax.annotate(ev.METHOD_NAMES[method].split(" (")[0], (sizes[-1], ys[-1]),
                        xytext=(6, 0), textcoords="offset points", fontsize=8.5, color=INK, va="center")
        ax.set_xticks(sizes)
        ax.set_xlabel("предложений в реферате", fontsize=9, color=MUTED)
        ax.set_title(title, fontsize=11, color=INK, loc="left")
        ax.set_xlim(sizes[0] - 1, sizes[-1] + 6)
        _style(ax)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, frameon=False, fontsize=9)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def plot_time(data: dict, path: Path) -> None:
    import matplotlib.pyplot as plt

    names = {"analysis": "разбор документа", "term_weights": "веса терминов",
             "sentences": "веса и отбор предложений", "keywords": "ключевые слова"}
    groups = ["ru-cs", "ru-lit", "de-cs", "de-lit"]
    fig, ax = plt.subplots(figsize=(10, 3.4), dpi=150)
    for row, group in enumerate(groups):
        left = 0.0
        for stage, color in STAGES.items():
            value = data["groups"][group]["timings"][stage]
            ax.barh(row, value, left=left, color=color, height=0.55, edgecolor="white", linewidth=1.5,
                    label=names[stage] if row == 0 else None)
            left += value
        ax.text(left + 2, row, f"{left:.0f} мс", va="center", fontsize=8.5, color=INK)
    ax.set_yticks(range(len(groups)), [GROUP_NAMES[g] for g in groups], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("мс на документ (≈ 10 страниц)", fontsize=9, color=MUTED)
    _style(ax)
    ax.yaxis.grid(False)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.45), ncol=4, frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-ostis", action="store_true")
    parser.add_argument("--quick", action="store_true")
    arguments = parser.parse_args()

    collection = Collection()
    print(f"Оценка на {len(collection)} документах, реферат из {config.SUMMARY_SENTENCES} предложений…")
    result = ev.run(collection, config.SUMMARY_SENTENCES, studies=not arguments.quick)
    data = result.to_dict()
    print(f"  расчёт: {result.elapsed_ms / 1000:.1f} с")

    if not arguments.no_ostis:
        print("Замеры через OSTIS…")
        data["ostis"] = measure_ostis(collection)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "evaluation.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    write_csv(data, OUT / "evaluation.csv")
    plot_rouge(data, OUT / "eval_rouge.png")
    if data.get("size_study"):
        plot_size(data, OUT / "eval_size.png")
    plot_time(data, OUT / "eval_time.png")

    print("\nROUGE-1 / ROUGE-2 (полнота), способ отбора × группа:")
    for method in ev.METHODS:
        cells = "  ".join(f"{data['groups'][g]['rouge'][method]['r1']:.3f}/{data['groups'][g]['rouge'][method]['r2']:.3f}"
                          for g in GROUP_ORDER)
        print(f"  {ev.METHOD_NAMES[method]:40} {cells}")
    print(f"\nВыгрузки: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
