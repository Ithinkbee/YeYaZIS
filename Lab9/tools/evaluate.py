"""Проверка распознавания и реакции на озвученных фразах.

    python tools/evaluate.py              полная проверка: все фразы, все голоса, четыре уровня шума
    python tools/evaluate.py --quick      быстрая: один голос на язык, без шума и с шумом 10 дБ
    python tools/evaluate.py --no-plots   без графиков

Фразы озвучивает синтезатор речи Windows (нужны голоса немецкого и русского
языков: «Параметры» → «Время и язык» → «Речь»). Записи складываются в
data/speech и при повторном запуске берутся оттуда. Результаты —
report/evaluation.json, таблица report/evaluation.csv и графики
report/eval_*.png; их показывает страница «Проверка».
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sluhach import config, console, evaluation as ev, synth  # noqa: E402
from sluhach.essays import Collection  # noqa: E402
from sluhach.recognizer import RecognizerError, VoskEngine  # noqa: E402

console.setup()

# Цвета графиков. Язык всегда одного цвета — того же семейства, что его метка
# на страницах: немецкий синий, русский оранжевый. Пара проверена на
# различимость при нарушениях цветового зрения и на контраст с белым фоном.
SERIES = {"de": "#2a78d6", "ru": "#eb6834"}
SHADES = {"clean": "#1c5cab", "snr10": "#86b6ef"}       # один тон, два шага: до и после шума
INK = "#0b0b0b"
SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
FONT = ["Segoe UI", "DejaVu Sans"]

CONDITION_TICKS = {"clean": "без шума", "snr20": "20 дБ", "snr10": "10 дБ", "snr5": "5 дБ"}


def percent(value: float, digits: int = 0) -> str:
    return f"{100 * value:.{digits}f}".replace(".", ",") + " %"


def write_csv(data: dict, path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["язык", "вид фраз", "условие", "испытаний", "WER", "дословно", "верная реакция",
                         "замечено", "ложные срабатывания", "уверенность", "время / длительность"])
        for language in (*config.LANGUAGE_CODES, "all"):
            for kind, rows in (data["groups"].get(language) or {}).items():
                for condition, row in rows.items():
                    writer.writerow([language, ev.KIND_NAMES.get(kind, kind), ev.CONDITION_NAMES.get(condition, condition),
                                     row["trials"]] + [None if row[key] is None else round(row[key], 4) for key in
                                                       ("wer", "exact", "reaction", "detected", "false_alarm",
                                                        "confidence", "rtf")])


# --- графики ----------------------------------------------------------------------

def _style(ax, grid: str = "y") -> None:
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    (ax.yaxis if grid == "y" else ax.xaxis).grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _lines(ax, data: dict, kind: str, key: str, conditions: list[str], title: str, top: float | None) -> None:
    """Два языка по условиям; подписаны только крайние точки — остальное читается по оси."""
    values = {}
    for language in config.LANGUAGE_CODES:
        rows = (data["groups"].get(language) or {}).get(kind) or {}
        values[language] = [rows[c][key] for c in conditions if c in rows and rows[c][key] is not None]
    present = [language for language in config.LANGUAGE_CODES if len(values[language]) == len(conditions)]
    limit = top or max(0.05, max((max(values[language]) for language in present), default=0.05) * 1.25)
    xs = list(range(len(conditions)))
    for language in present:
        ax.plot(xs, values[language], color=SERIES[language], linewidth=2, marker="o", markersize=7.5,
                markeredgecolor="white", markeredgewidth=1.6, solid_capstyle="round", solid_joinstyle="round",
                label=config.language_name(language), zorder=3, clip_on=False)
    for index in (0, len(conditions) - 1):
        # у верхней линии подпись сверху, у нижней — снизу: подписи не слипаются. Если
        # нижняя точка лежит у самой оси, подписи снизу нет места — она встаёт между линиями
        order = sorted(present, key=lambda language: values[language][index])
        apart = len(order) > 1 and (values[order[-1]][index] - values[order[0]][index]) / limit >= 0.09
        for rank, language in enumerate(order):
            above = rank == len(order) - 1 or (apart and values[language][index] / limit < 0.08)
            ax.annotate(percent(values[language][index], 1 if limit <= 0.5 else 0),
                        (xs[index], values[language][index]), xytext=(0, 9 if above else -9),
                        textcoords="offset points", ha="center", va="bottom" if above else "top",
                        fontsize=8.5, color=INK)
    ax.set_xticks(xs, [CONDITION_TICKS[c] for c in conditions], fontsize=9)
    ax.set_xlim(-0.35, len(conditions) - 0.65)
    ax.set_ylim(0, limit)
    ax.yaxis.set_major_formatter(lambda value, _: percent(value))
    ax.set_title(title, fontsize=11, color=INK, loc="left", pad=12)
    _style(ax)


def _pair(data: dict, path: Path, panels: list[tuple[str, str, str, float | None]], conditions: list[str]) -> None:
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, len(panels), figsize=(5.5 * len(panels), 4.0), dpi=150)
    for ax, (kind, key, title, top) in zip(axes, panels):
        _lines(ax, data, kind, key, conditions, title, top)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=len(labels), frameon=False, fontsize=9.5, labelcolor=SECONDARY)
    fig.text(0.5, 0.105, "отношение сигнал/шум в записи", ha="center", fontsize=9, color=MUTED)
    fig.tight_layout(rect=(0, 0.13, 1, 1), w_pad=3)
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def plot_reaction(data: dict, path: Path, conditions: list[str]) -> None:
    _pair(data, path, [("command", "reaction", "Команды: верная реакция системы", 1.08),
                       ("command", "detected", "Команды: фраза замечена детектором речи", 1.08)], conditions)


def plot_wer(data: dict, path: Path, conditions: list[str]) -> None:
    _pair(data, path, [("command", "wer", "Команды: доля ошибок в словах (WER)", None),
                       ("sentence", "wer", "Предложения из сочинений: WER", None)], conditions)


def plot_voices(data: dict, path: Path) -> None:
    """Каждый голос: доля верных реакций на команды без шума и при шуме 10 дБ."""
    import matplotlib.pyplot as plt

    rows = []
    for language in config.LANGUAGE_CODES:
        genders = {voice["speaker"]: voice["gender"] for voice in data["voices"].get(language, [])}
        for speaker, by_condition in (data["by_voice"].get(language) or {}).items():
            if "clean" in by_condition and "snr10" in by_condition:
                label = f"{speaker} · {config.language_name(language)[:3]}., {genders.get(speaker, '')}".rstrip(", ")
                rows.append((label, by_condition["clean"]["reaction"], by_condition["snr10"]["reaction"]))
    if not rows:
        return
    fig, ax = plt.subplots(figsize=(8.6, 0.62 * len(rows) + 1.7), dpi=150)
    for index, (_label, clean, noisy) in enumerate(rows):
        y = len(rows) - 1 - index
        ax.plot([noisy, clean], [y, y], color=AXIS, linewidth=2, solid_capstyle="round", zorder=2)
        for value, key in ((noisy, "snr10"), (clean, "clean")):
            ax.plot(value, y, marker="o", markersize=9, color=SHADES[key], markeredgecolor="white",
                    markeredgewidth=1.6, zorder=3, linestyle="none",
                    label=ev.CONDITION_NAMES[key] if index == 0 else None)
        low, high = sorted((noisy, clean))
        ax.annotate(percent(low), (low, y), xytext=(-9, 0), textcoords="offset points", ha="right", va="center",
                    fontsize=8.5, color=INK)
        if high - low > 0.004:
            ax.annotate(percent(high), (high, y), xytext=(9, 0), textcoords="offset points", ha="left", va="center",
                        fontsize=8.5, color=INK)
    ax.set_yticks(range(len(rows)), [row[0] for row in reversed(rows)], fontsize=9.5)
    ax.tick_params(axis="y", colors=SECONDARY)
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.set_xlim(0, 1.1)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.xaxis.set_major_formatter(lambda value, _: percent(value))
    ax.set_title("Команды по голосам: верная реакция без шума и при шуме 10 дБ", fontsize=11, color=INK,
                 loc="left", pad=12)
    _style(ax, grid="x")
    ax.tick_params(axis="x", colors=MUTED)
    handles, labels = ax.get_legend_handles_labels()
    order = [labels.index(ev.CONDITION_NAMES[key]) for key in ("clean", "snr10") if ev.CONDITION_NAMES[key] in labels]
    fig.legend([handles[i] for i in order], [labels[i] for i in order], loc="lower center", ncol=2, frameon=False,
               fontsize=9.5, labelcolor=SECONDARY)
    fig.tight_layout(rect=(0, 0.09, 1, 1))
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def make_plots(data: dict, directory: Path) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    matplotlib.rcParams["font.family"] = FONT
    conditions = [name for name, _ in ev.CONDITIONS
                  if name in ((data["groups"].get("all") or {}).get("command") or {})]
    made = []
    if len(conditions) >= 2:
        plot_reaction(data, directory / "eval_reaction.png", conditions)
        plot_wer(data, directory / "eval_wer.png", conditions)
        made += ["eval_reaction.png", "eval_wer.png"]
    if "clean" in conditions and "snr10" in conditions:
        plot_voices(data, directory / "eval_voices.png")
        made.append("eval_voices.png")
    return made


# --- запуск -----------------------------------------------------------------------

def summary(data: dict) -> None:
    print("\n  язык      вид фраз                    условие        WER   верная реакция   замечено")
    for language in (*config.LANGUAGE_CODES, "all"):
        for kind in ("command", "sentence", "egg"):
            rows = (data["groups"].get(language) or {}).get(kind) or {}
            for condition, row in rows.items():
                wer = "—" if row["wer"] is None else percent(row["wer"], 1)
                print(f"  {language:8}  {ev.KIND_NAMES[kind]:26}  {ev.CONDITION_NAMES[condition]:12} {wer:>7}"
                      f" {percent(row['reaction'], 1):>12} {percent(row['detected'], 1):>12}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка распознавания на озвученных фразах")
    parser.add_argument("--quick", action="store_true", help="один голос на язык, два условия")
    parser.add_argument("--sentences", type=int, default=40, help="предложений из сочинений на язык")
    parser.add_argument("--workers", type=int, default=4, help="сколько записей распознавать одновременно")
    parser.add_argument("--no-plots", action="store_true", help="не строить графики")
    parser.add_argument("--out", default=str(config.REPORT_DIR), help="куда сохранить результаты")
    arguments = parser.parse_args()

    if not synth.available():
        print("Синтезатор речи Windows недоступен: проверка озвучивает фразы через System.Speech.")
        return 1
    engine = VoskEngine()
    missing = [code for code in config.LANGUAGE_CODES if not engine.available(code)]
    if missing:
        print("Нет моделей Vosk: " + ", ".join(config.language_name(code) for code in missing)
              + ". Скачайте их: python tools/get_models.py")
        return 1

    collection = Collection()
    phrases = ev.build_phrases(collection, per_language=arguments.sentences)
    voices = synth.voices()
    for language in config.LANGUAGE_CODES:
        names = ", ".join(voice.speaker for voice in voices[language]) or "нет"
        count = sum(1 for phrase in phrases if phrase.language == language)
        print(f"  {config.language_name(language):9} фраз: {count:4}   голоса: {names}")
    if not all(voices[language] for language in config.LANGUAGE_CODES):
        print("Не для каждого языка есть голос — установите его в параметрах Windows («Время и язык» → «Речь»).")
        return 1
    conditions = ev.CONDITIONS
    if arguments.quick:
        voices = {language: items[:1] for language, items in voices.items()}
        conditions = tuple(item for item in ev.CONDITIONS if item[0] in {"clean", "snr10"})

    started = time.perf_counter()
    items = [(phrase.text, voice) for phrase in phrases for voice in voices[phrase.language]]
    print(f"\n  озвучиваю: {len(items)} записей (готовые берутся из {config.SPEECH_DIR.name}/)…", flush=True)
    recordings = synth.synthesize(items)
    print(f"  записей на диске: {len(recordings)} из {len(items)}, {time.perf_counter() - started:.0f} с", flush=True)
    if len(recordings) < len(items):
        print(f"  не озвучено: {len(items) - len(recordings)} — эти фразы в проверку не войдут")

    def progress(done: int, total: int) -> None:
        print(f"  распознано {done} из {total}", flush=True)

    print(f"  распознаю: {len(recordings)} записей × {len(conditions)} условий…", flush=True)
    try:
        result = ev.run(engine, collection, phrases, recordings, voices, conditions, arguments.workers, progress)
    except RecognizerError as problem:
        print(f"Распознавание недоступно: {problem}")
        return 1
    data = result.to_dict()

    out = Path(arguments.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "evaluation.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    write_csv(data, out / "evaluation.csv")
    summary(data)
    print(f"\n  результаты: {out / 'evaluation.json'}, {out / 'evaluation.csv'}")
    if not arguments.no_plots:
        for name in make_plots(data, out):
            print(f"  график:     {out / name}")
    print(f"  всего: {time.perf_counter() - started:.0f} с")
    return 0


if __name__ == "__main__":
    sys.exit(main())
