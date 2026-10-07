"""Оценка качества перевода и затраченного времени; выгрузки и графики для отчёта.

    python tools/evaluate.py

Коллекция переводится двумя способами — с трансфером и пословно, —
переводы 120 предложений сравниваются с эталонными переводами
(BLEU и chrF), считаются доля переведённых слов (с правилами
словообразования и без них) и время по этапам.

Результаты:
    report/evaluation.json   все числа (их же показывает страница «Оценка»)
    report/evaluation.csv    таблица «документ × способ перевода»
    report/eval_quality.png  BLEU и chrF по областям и способам перевода
    report/eval_coverage.png доля переведённых слов по документам
    report/eval_time.png     время перевода по этапам
    report/eval_analyzer.png точность анализатора на корпусах UD (из report/analyzer.json)

Дополнительно — опыт с незнакомыми текстами: словарь составлялся под
коллекцию, поэтому на ней почти все слова находятся в словаре. Чтобы
увидеть, что дают правила словообразования на новых текстах, переводятся
10 документов тестовой части корпуса GUM (академические статьи, эссе,
учебники, биографии, рассказы), которых система не видела.
"""

from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dragoman import config, console, evaluation as ev  # noqa: E402
from dragoman.collection import Collection  # noqa: E402

console.setup()

OUT = config.REPORT_DIR
GROUPS = ["cs", "lit", "all"]
GROUP_NAMES = {"cs": "научные статьи\nпо CS", "lit": "сочинения\nпо литературе", "all": "вся\nколлекция"}
MODE_NAMES = {"transfer": "с трансфером", "direct": "пословный"}

# категориальная палитра: порядок слотов фиксирован
SERIES = {"transfer": "#2a78d6", "direct": "#eb6834", "no_rules": "#a5a39c"}
STAGES = {"segment": "#a5a39c", "tagging": "#1baf7a", "parsing": "#2a78d6", "transfer": "#eb6834"}
INK, MUTED, GRID = "#1f1d1a", "#6b6862", "#e6e3dc"


UNSEEN_GENRES = ("academic", "essay", "textbook", "bio", "fiction")


def unseen_documents() -> list[tuple[str, str]]:
    """Тексты тестовой части GUM выбранных жанров: (имя, текст)."""
    path = config.TREEBANK_DIR / "en_gum-ud-test.conllu"
    if not path.exists():
        return []
    documents: list[tuple[str, list[str]]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# newdoc id = "):
            documents.append((line.split("= ", 1)[1].strip(), []))
        elif line.startswith("# text = ") and documents:
            documents[-1][1].append(line.split("= ", 1)[1].strip())
    return [(name, " ".join(lines)) for name, lines in documents if name.split("_")[1] in UNSEEN_GENRES]


def unseen_study(translator) -> dict:
    """Доля переведённых слов на незнакомых текстах — с правилами словообразования и без них."""
    from collections import Counter

    rows, unknown = [], Counter()
    for name, text in unseen_documents():
        with_rules = translator.translate(text, name, "auto", "transfer", log_unknown=False)
        without = translator.translate(text, name, "auto", "transfer", log_unknown=False, use_rules=False)
        rows.append({"id": name, "genre": name.split("_")[1], "words": with_rules.stats["words"],
                     "domain": with_rules.domain, "coverage": with_rules.stats["coverage"],
                     "no_rules": without.stats["coverage"], "rule_words": with_rules.stats["rule_words"],
                     "unknown_words": with_rules.stats["unknown_words"]})
        unknown.update(with_rules.stats["unknown_words"])
    words = sum(r["words"] for r in rows)
    return {
        "documents": rows,
        "words": words,
        "coverage": sum(r["coverage"] * r["words"] for r in rows) / max(1, words),
        "no_rules": sum(r["no_rules"] * r["words"] for r in rows) / max(1, words),
        "rule_examples": sorted({w for r in rows for w in r["rule_words"]})[:40],
        "unknown_examples": [w for w, _ in unknown.most_common(40)],
    }


def write_csv(data: dict, path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["документ", "область", "предложений", "слов", "переведено (трансфер)",
                         "переведено без правил", "без перевода", "время трансфер, мс", "время пословно, мс"])
        for d in data["documents"]:
            writer.writerow([d["id"], d["domain"], d["sentences"], d["words"],
                             round(d["coverage"]["transfer"], 4), round(d["coverage"]["no_rules"], 4),
                             d["unknown"]["transfer"], round(d["time_ms"]["transfer"]["total"] or 0, 1),
                             round(d["time_ms"]["direct"]["total"] or 0, 1)])


def _style(ax) -> None:
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _num(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def plot_quality(data: dict, path: Path) -> None:
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), dpi=150)
    width = 0.34
    for ax, key, title in zip(axes, ("bleu", "chrf"), ("BLEU-4", "chrF")):
        for i, mode in enumerate(("transfer", "direct")):
            xs = [g + (i - 0.5) * (width + 0.02) for g in range(len(GROUPS))]
            ys = [data["groups"][g][mode][key] for g in GROUPS]
            ax.bar(xs, ys, width, color=SERIES[mode], label=f"перевод {MODE_NAMES[mode]}",
                   edgecolor="white", linewidth=1.2)
            for x, y in zip(xs, ys):
                ax.text(x, y + max(ys) * 0.015, _num(y), ha="center", va="bottom", fontsize=8, color=INK)
        ax.set_xticks(range(len(GROUPS)), [GROUP_NAMES[g] for g in GROUPS], fontsize=9)
        ax.set_title(title, fontsize=11, color=INK, loc="left")
        _style(ax)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, frameon=False, fontsize=9)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def plot_coverage(data: dict, path: Path) -> None:
    import matplotlib.pyplot as plt

    docs = data["documents"]
    fig, ax = plt.subplots(figsize=(11, 3.8), dpi=150)
    width = 0.38
    xs = range(len(docs))
    with_rules = [100 * d["coverage"]["transfer"] for d in docs]
    without = [100 * d["coverage"]["no_rules"] for d in docs]
    ax.bar([x - width / 2 for x in xs], without, width, color=SERIES["no_rules"], label="только словарь",
           edgecolor="white", linewidth=1.2)
    ax.bar([x + width / 2 for x in xs], with_rules, width, color=SERIES["transfer"],
           label="словарь и правила словообразования", edgecolor="white", linewidth=1.2)
    low = min(without + with_rules)
    ax.set_ylim(max(0, low - 4), 100.5)
    ax.set_xticks(list(xs), [d["id"].replace("-", "\n", 1) for d in docs], fontsize=8)
    ax.set_ylabel("% переведённых слов", fontsize=9, color=MUTED)
    _style(ax)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.38), ncol=2, frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def plot_time(data: dict, path: Path) -> None:
    import matplotlib.pyplot as plt

    names = {"segment": "разбиение на слова", "tagging": "теги и леммы", "parsing": "синтаксический анализ",
             "transfer": "трансфер и синтез"}
    rows = []
    for code in config.DOMAIN_CODES:
        docs = [d for d in data["documents"] if d["domain"] == code]
        values = {stage: sum((d["time_ms"]["transfer"][stage] or 0) for d in docs) / max(1, len(docs))
                  for stage in STAGES}
        words = sum(d["words"] for d in docs) / max(1, len(docs))
        rows.append((config.domain_name(code, short=True), values, words))
    fig, ax = plt.subplots(figsize=(10, 2.8), dpi=150)
    for row, (name, values, words) in enumerate(rows):
        left = 0.0
        for stage, color in STAGES.items():
            ax.barh(row, values[stage], left=left, color=color, height=0.55, edgecolor="white", linewidth=1.5,
                    label=names[stage] if row == 0 else None)
            left += values[stage]
        ax.text(left + 4, row, f"{left:.0f} мс на документ (≈ {words:.0f} слов)", va="center", fontsize=8.5,
                color=INK)
    ax.set_yticks(range(len(rows)), [r[0] for r in rows], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("мс на документ", fontsize=9, color=MUTED)
    ax.set_xlim(0, max(sum(r[1].values()) for r in rows) * 1.55)
    _style(ax)
    ax.yaxis.grid(False)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.62), ncol=4, frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def plot_analyzer(analyzer: dict, path: Path) -> None:
    import matplotlib.pyplot as plt

    names = {"en_ewt": "EWT\n(веб-тексты)", "en_gum": "GUM\n(разные жанры)", "en_lines": "LinES\n(литература)",
             "en_partut": "ParTUT\n(право, Википедия)"}
    metrics = {"tagging": ("теги", "#1baf7a"), "uas": ("UAS", "#2a78d6"), "las": ("LAS", "#eb6834")}
    banks = [b for b in names if b in analyzer["treebanks"]]
    fig, ax = plt.subplots(figsize=(10, 3.6), dpi=150)
    width = 0.25
    for i, (key, (label, color)) in enumerate(metrics.items()):
        xs, ys = [], []
        for k, bank in enumerate(banks):
            value = analyzer["treebanks"][bank].get(key)
            if value is None:
                continue
            xs.append(k + (i - 1) * (width + 0.02))
            ys.append(100 * value)
        ax.bar(xs, ys, width, color=color, label=label, edgecolor="white", linewidth=1.2)
        for x, y in zip(xs, ys):
            ax.text(x, y + 0.4, _num(y), ha="center", va="bottom", fontsize=7.5, color=INK)
    ax.set_ylim(70, 100)
    ax.set_xticks(range(len(banks)), [names[b] for b in banks], fontsize=9)
    ax.set_ylabel("%", fontsize=9, color=MUTED)
    _style(ax)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.42), ncol=3, frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def main() -> int:
    from dragoman.translate.pipeline import Translator

    collection = Collection()
    print(f"Оценка на {len(collection)} документах ({len(ev.load_references())} эталонных предложений)…")
    started = time.perf_counter()
    translator = Translator()
    data = ev.run(translator, collection)
    data["unseen"] = unseen_study(translator)
    print(f"  расчёт: {time.perf_counter() - started:.1f} с")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "evaluation.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    write_csv(data, OUT / "evaluation.csv")
    plot_quality(data, OUT / "eval_quality.png")
    plot_coverage(data, OUT / "eval_coverage.png")
    plot_time(data, OUT / "eval_time.png")
    analyzer_path = OUT / "analyzer.json"
    if analyzer_path.exists():
        plot_analyzer(json.loads(analyzer_path.read_text(encoding="utf-8")), OUT / "eval_analyzer.png")

    print("\n               BLEU (трансфер / пословно)   chrF (трансфер / пословно)")
    for group in GROUPS:
        g = data["groups"][group]
        print(f"  {group:6}       {g['transfer']['bleu']:6.2f} / {g['direct']['bleu']:6.2f}"
              f"              {g['transfer']['chrf']:6.2f} / {g['direct']['chrf']:6.2f}")
    wins = data["groups"]["all"]["wins"]
    print(f"\n  предложений лучше с трансфером: {wins['transfer']}, пословно: {wins['direct']}, "
          f"поровну: {wins['ties']}")
    c = data["coverage"]
    print(f"  переведено слов: {100 * c['transfer']:.1f} % (без правил словообразования "
          f"{100 * c['no_rules']:.1f} %, пословно {100 * c['direct']:.1f} %)")
    unseen = data["unseen"]
    if unseen["documents"]:
        print(f"  незнакомые тексты (GUM, {len(unseen['documents'])} док., {unseen['words']} слов): "
              f"{100 * unseen['coverage']:.1f} % с правилами, {100 * unseen['no_rules']:.1f} % без них")
    print(f"\nВыгрузки: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
