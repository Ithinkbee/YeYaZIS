"""Проверка системы синтеза: нормализация, произношение, разборчивость, настройки, скорость.

    python tools/evaluate.py              полная проверка (≈ 10 минут)
    python tools/evaluate.py --quick      по 3 предложения из статьи, без темпов (≈ 2 минуты)
    python tools/evaluate.py --no-plots   без графиков
    python tools/evaluate.py --plots-only только перерисовать графики из report/evaluation.json

Нужны голоса Piper и модель Vosk: python tools/get_voices.py --vosk.
Результаты — report/evaluation.json, таблица report/evaluation.csv и графики
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

from glashatai import config, console, evaluation as ev  # noqa: E402
from glashatai.articles import Collection  # noqa: E402
from glashatai.asr import Recognizer  # noqa: E402
from glashatai.engines import split_voice  # noqa: E402
from glashatai.speaker import Speaker  # noqa: E402

console.setup()

# цвета: движок — один цвет; пара «до / после» — светлый и тёмный тон одного цвета
ENGINE_COLORS = {"piper": "#2a78d6", "formant": "#9b2f2f", "sapi": "#3f7a44"}
BEFORE, AFTER = "#c9c4bb", "#2a78d6"
INK = "#0b0b0b"
SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"


def voice_title(speaker: Speaker, voice_id: str) -> str:
    found = speaker.voice(voice_id)
    title = found.title if found else voice_id
    engine = split_voice(voice_id)[0]
    return {"piper": f"{title} (Piper)", "formant": f"{title} (свой)", "sapi": f"{title} (Windows)"}.get(engine, title)


def percent(value: float, digits: int = 0) -> str:
    return f"{100 * value:.{digits}f}".replace(".", ",") + " %"


def _style(ax, grid: str = "y") -> None:
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    (ax.yaxis if grid == "y" else ax.xaxis).grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def plot_intelligibility(data: dict, speaker: Speaker, path: Path) -> None:
    import matplotlib.pyplot as plt

    rows = sorted(data["intelligibility"].items(), key=lambda item: item[1]["wer"])
    labels = [voice_title(speaker, voice) for voice, _ in rows]
    colors = [ENGINE_COLORS.get(split_voice(voice)[0], MUTED) for voice, _ in rows]
    fig, axes = plt.subplots(1, 2, figsize=(11, 0.45 * len(rows) + 1.8), dpi=150, sharey=True)
    for ax, key, title, fmt in ((axes[0], "wer", "Доля ошибок распознавания в словах (WER)", lambda v: percent(v, 1)),
                                (axes[1], "rtf", "Время синтеза / длительность звука", lambda v: f"{v:.3f}".replace(".", ","))):
        values = [row[key] for _, row in rows]
        bars = ax.barh(range(len(rows)), values, color=colors, height=0.62)
        for bar, value in zip(bars, values):
            ax.text(bar.get_width(), bar.get_y() + bar.get_height() / 2, "  " + fmt(value), va="center",
                    fontsize=8.5, color=INK)
        ax.set_yticks(range(len(rows)), labels, fontsize=9)
        ax.invert_yaxis()
        ax.set_title(title, fontsize=10.5, loc="left", color=INK, pad=10)
        ax.set_xlim(0, max(values) * 1.28 if values else 1)
        _style(ax, "x")
    axes[0].xaxis.set_major_formatter(lambda v, _: percent(v))
    fig.tight_layout(w_pad=2.5)
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def plot_tempo(data: dict, speaker: Speaker, path: Path) -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7.2, 4.4), dpi=150)
    palette = ["#2a78d6", "#86b6ef", "#9b2f2f", "#d98a8a", "#3f7a44"]
    for index, (voice, rows) in enumerate(data["tempo"].items()):
        rates = sorted(rows, key=float)
        xs = [float(r) for r in rates]
        ys = [rows[r] for r in rates]
        ax.plot(xs, ys, marker="o", color=palette[index % len(palette)], linewidth=2, markersize=6.5,
                markeredgecolor="white", markeredgewidth=1.4, label=voice_title(speaker, voice))
        ax.annotate(percent(ys[-1]), (xs[-1], ys[-1]), xytext=(6, 0), textcoords="offset points", va="center",
                    fontsize=8.5, color=INK)
    ax.set_xticks([float(r) for r in sorted(next(iter(data["tempo"].values())), key=float)])
    ax.xaxis.set_major_formatter(lambda v, _: "×" + f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ","))
    ax.yaxis.set_major_formatter(lambda v, _: percent(v))
    ax.set_ylim(0, 1.05)
    ax.set_title("Разборчивость при разном темпе (WER, меньше — лучше)", fontsize=10.5, loc="left", color=INK, pad=10)
    ax.set_xlabel("темп", fontsize=9, color=MUTED)
    ax.legend(frameon=False, fontsize=8.5, labelcolor=SECONDARY, loc="upper center", bbox_to_anchor=(0.5, -0.16),
              ncol=3)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def plot_normalization(data: dict, path: Path) -> None:
    import matplotlib.pyplot as plt

    categories = [(k, v) for k, v in data["normalization"]["categories"].items() if "raw_exact" in v]
    ear = data.get("by_ear", {}).get("categories", {})
    panels = 2 if ear else 1
    fig, axes = plt.subplots(1, panels, figsize=(6.2 * panels, 4.8), dpi=150)
    axes = axes if panels > 1 else [axes]
    ax = axes[0]
    names = [v["name"] for _, v in categories]
    raw = [v["raw_exact"] for _, v in categories]
    ours = [v["accuracy"] for _, v in categories]
    xs = range(len(names))
    ax.barh([x + 0.2 for x in xs], raw, height=0.38, color=BEFORE, label="eSpeak NG сам")
    ax.barh([x - 0.2 for x in xs], ours, height=0.38, color=AFTER, label="с нормализацией «Глашатая»")
    ax.set_yticks(list(xs), names, fontsize=9)
    ax.invert_yaxis()
    ax.xaxis.set_major_formatter(lambda v, _: percent(v))
    ax.set_xlim(0, 1.05)
    ax.set_title("Трудные места, прочитанные верно", fontsize=10.5, loc="left", color=INK, pad=10)
    ax.legend(frameon=False, fontsize=8.5, labelcolor=SECONDARY, loc="upper center", bbox_to_anchor=(0.45, -0.07),
              ncol=2)
    _style(ax, "x")
    if ear:
        ax = axes[1]
        rows = list(ear.values())
        xs = range(len(rows))
        ax.barh([x + 0.2 for x in xs], [r["raw"] for r in rows], height=0.38, color=BEFORE, label="текст как есть")
        ax.barh([x - 0.2 for x in xs], [r["ours"] for r in rows], height=0.38, color=AFTER, label="после нормализации")
        ax.set_yticks(list(xs), [r["name"] for r in rows], fontsize=9)
        ax.invert_yaxis()
        ax.xaxis.set_major_formatter(lambda v, _: percent(v))
        ax.set_title("Thorsten (Piper) на слух: WER распознавания", fontsize=10.5, loc="left", color=INK, pad=10)
        ax.legend(frameon=False, fontsize=8.5, labelcolor=SECONDARY, loc="upper center", bbox_to_anchor=(0.45, -0.07),
                  ncol=2)
        _style(ax, "x")
    fig.tight_layout(w_pad=2.5)
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def plot_settings(data: dict, speaker: Speaker, path: Path) -> None:
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.0), dpi=150)
    palette = ["#2a78d6", "#9b2f2f", "#3f7a44", "#b88a22", "#5b3d8a"]
    voices = data["settings"]["voices"]
    for index, (voice, rows) in enumerate(voices.items()):
        color = palette[index % len(palette)]
        tempo = sorted(((float(k), v) for k, v in rows["tempo"].items()), key=lambda item: item[0])
        axes[0].plot([1.0] + [t for t, _ in tempo], [1.0] + [v for _, v in tempo], marker="o", color=color,
                     linewidth=1.8, markersize=5.5, label=voice_title(speaker, voice))
        pitch = sorted(((float(k), v) for k, v in rows["pitch"].items() if v is not None), key=lambda item: item[0])
        axes[1].plot([0.0] + [p for p, _ in pitch], [0.0] + [v for _, v in pitch], marker="o", color=color,
                     linewidth=1.8, markersize=5.5, label=voice_title(speaker, voice))
    axes[0].plot([0.5, 2.0], [0.5, 2.0], color=MUTED, linestyle=":", linewidth=1)
    axes[1].plot([-6, 6], [-6, 6], color=MUTED, linestyle=":", linewidth=1)
    axes[0].set_title("Темп: задано и измерено по длительности", fontsize=10.5, loc="left", color=INK, pad=10)
    axes[1].set_title("Высота: задано и измерено по тону, полутоны", fontsize=10.5, loc="left", color=INK, pad=10)
    axes[0].set_xlabel("задано", fontsize=9, color=MUTED)
    axes[1].set_xlabel("задано", fontsize=9, color=MUTED)
    for ax in axes:
        _style(ax)
    axes[0].legend(frameon=False, fontsize=8, labelcolor=SECONDARY)
    fig.tight_layout(w_pad=3)
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def plot_effects(data: dict, path: Path) -> None:
    import matplotlib.pyplot as plt

    rows = list(data["effects"].items())
    fig, ax = plt.subplots(figsize=(7.2, 3.4), dpi=150)
    colors = [BEFORE if key == "none" else "#5b3d8a" for key, _ in rows]
    values = [row["wer"] for _, row in rows]
    bars = ax.bar(range(len(rows)), values, color=colors, width=0.62)
    for bar, (_, row) in zip(bars, rows):
        shift = row["shift"]
        label = percent(row["wer"])
        if shift is not None:
            label += f"\n{shift:+.1f} пт".replace(".", ",").replace("-", "−")
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), label, ha="center", va="bottom", fontsize=8.5,
                color=INK)
    ax.set_xticks(range(len(rows)), [row["name"] for _, row in rows], fontsize=9)
    ax.yaxis.set_major_formatter(lambda v, _: percent(v))
    ax.set_ylim(0, max(values) * 1.4 if values else 1)
    ax.set_title("Голоса Пафнутия: WER распознавания и сдвиг тона", fontsize=10.5, loc="left", color=INK, pad=10)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def write_csv(data: dict, speaker: Speaker, path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["раздел", "показатель", "значение"])
        for voice, row in data["intelligibility"].items():
            writer.writerow(["разборчивость", voice_title(speaker, voice) + " — WER", round(row["wer"], 4)])
            writer.writerow(["скорость", voice_title(speaker, voice) + " — RTF", round(row["rtf"], 4)])
        for voice, rows in data.get("tempo", {}).items():
            for rate, value in rows.items():
                writer.writerow(["темп", f"{voice_title(speaker, voice)} ×{rate} — WER", round(value, 4)])
        for name, row in data["normalization"]["categories"].items():
            writer.writerow(["нормализация", row["name"] + " — верно", round(row["accuracy"], 4)])
            if "raw_exact" in row:
                writer.writerow(["нормализация", row["name"] + " — eSpeak сам верно", round(row["raw_exact"], 4)])
        if data.get("g2p"):
            for key in ("per", "per_plain", "exact", "exact_plain", "stress"):
                writer.writerow(["произношение", key, round(data["g2p"][key], 4)])


def plots(data: dict, speaker: Speaker) -> None:
    plot_intelligibility(data, speaker, config.REPORT_DIR / "eval_intelligibility.png")
    plot_normalization(data, config.REPORT_DIR / "eval_normalization.png")
    plot_settings(data, speaker, config.REPORT_DIR / "eval_settings.png")
    if data.get("tempo"):
        plot_tempo(data, speaker, config.REPORT_DIR / "eval_tempo.png")
    if data.get("effects"):
        plot_effects(data, config.REPORT_DIR / "eval_effects.png")


def main() -> None:
    parser = argparse.ArgumentParser(description="Проверка «Глашатая»")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--no-plots", action="store_true")
    parser.add_argument("--plots-only", action="store_true")
    arguments = parser.parse_args()

    speaker = Speaker()
    if arguments.plots_only:
        data = json.loads((config.REPORT_DIR / "evaluation.json").read_text(encoding="utf-8"))
        plots(data, speaker)
        print("Графики перерисованы: report/eval_*.png")
        return
    reader = speaker.reader
    collection = Collection()
    recognizer = Recognizer()
    if not recognizer.available():
        print("Нет модели Vosk: python tools/get_voices.py --vosk")
        sys.exit(1)
    piper = speaker.piper if speaker.piper.models() else None
    config.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    started = time.time()
    data: dict = {"date": time.strftime("%Y-%m-%d %H:%M"), "quick": arguments.quick}

    print("1. Нормализация по эталонному набору…", flush=True)
    data["normalization"] = ev.normalization(reader, piper)
    s = data["normalization"]["summary"]
    print(f"   верно {percent(s['accuracy'], 1)} из {s['cases']}" +
          (f"; eSpeak NG сам — {percent(s['raw_exact'], 1)}" if "raw_exact" in s else ""))

    print("   что остаётся после нормализации в статьях…", flush=True)
    data["leftovers"] = ev.leftovers(reader, collection)
    print(f"   цифр и знаков, которые синтезатор прочёл бы сам: {data['leftovers']['left']} "
          f"из {data['leftovers']['tokens']} токенов")

    if piper is not None:
        print("2. Правила произношения против eSpeak NG…", flush=True)
        data["g2p"] = ev.g2p(collection, reader, piper)
        g = data["g2p"]
        print(f"   {g['words']} слов: PER {percent(g['per'], 1)} (без долготы {percent(g['per_plain'], 1)}), "
              f"совпали целиком {percent(g['exact'], 1)}, ударение {percent(g['stress'], 1)}")

    voices = ev.evaluation_voices(speaker)
    sentences = ev.test_sentences(reader, collection, per_article=3 if arguments.quick else 10)
    print(f"3. Разборчивость: {len(voices)} голосов × {len(sentences)} предложений…", flush=True)
    done = [0]
    total = len(voices) * len(sentences)

    def tick() -> None:
        done[0] += 1
        if done[0] % 25 == 0 or done[0] == total:
            print(f"   {done[0]} из {total}", flush=True)

    data["intelligibility"] = ev.intelligibility(speaker, recognizer, voices, sentences, progress=tick)
    data["sentences"] = len(sentences)
    for voice, row in sorted(data["intelligibility"].items(), key=lambda item: item[1]["wer"]):
        print(f"   {voice_title(speaker, voice):32} WER {percent(row['wer'], 1):>8}   RTF {row['rtf']:.3f}")

    tempo_voices = [v for v in ("piper:de_DE-thorsten-medium", "piper:de_DE-kerstin-low", "formant:karl") if v in voices]
    if not arguments.quick and tempo_voices:
        subset = sentences[::2]
        rates = [0.75, 1.0, 1.5, 2.0]
        print(f"   темп: {len(tempo_voices)} голоса × {len(rates)} темпа × {len(subset)} предложений…", flush=True)
        data["tempo"] = ev.tempo(speaker, recognizer, tempo_voices, subset, rates)

    if piper is not None and "piper:de_DE-thorsten-medium" in voices:
        print("   трудные фразы на слух: с нормализацией и без…", flush=True)
        data["by_ear"] = ev.normalization_by_ear(speaker, recognizer, "piper:de_DE-thorsten-medium")
        print(f"   WER без нормализации {percent(data['by_ear']['raw'], 1)}, с ней {percent(data['by_ear']['ours'], 1)}")

    print("4. Точность настроек…", flush=True)
    sample = reader.sentence("Die Übersetzung eines Programms erfolgt in mehreren Phasen, die nacheinander ausgeführt werden.")
    setting_voices = [v for v in ("piper:de_DE-thorsten-medium", "formant:karl") if v in voices] + \
        [v for v in voices if v.startswith("sapi:")][:1]
    data["settings"] = ev.settings_accuracy(speaker, setting_voices, sample)

    if "piper:de_DE-thorsten-medium" in voices:
        print("5. Голоса Пафнутия…", flush=True)
        data["effects"] = ev.effects(speaker, recognizer, "piper:de_DE-thorsten-medium", sentences[: 6 if arguments.quick else 15])

    data["voices"] = {voice: voice_title(speaker, voice) for voice in voices}
    data["seconds"] = round(time.time() - started)
    (config.REPORT_DIR / "evaluation.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    write_csv(data, speaker, config.REPORT_DIR / "evaluation.csv")
    if not arguments.no_plots:
        plots(data, speaker)
    print(f"Готово за {data['seconds']} с: report/evaluation.json, report/evaluation.csv, report/eval_*.png")
    speaker.sapi.close()


if __name__ == "__main__":
    main()
