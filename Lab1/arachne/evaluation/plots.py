"""Построение графиков метрик в PNG — для включения в отчёт по работе."""

from __future__ import annotations

from pathlib import Path

from .. import config


def _pyplot():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.family"] = ["DejaVu Sans"]
    return plt


def precision_recall_curve(
    curve: list[tuple[float, float]], path: Path | None = None, title: str = ""
) -> Path:
    """11-точечный график «точность — полнота»."""
    plt = _pyplot()
    path = path or (config.REPORT_DIR / "pr_curve.png")
    path.parent.mkdir(parents=True, exist_ok=True)

    figure, axes = plt.subplots(figsize=(7, 4.5))
    axes.plot(
        [r for r, _ in curve], [p for _, p in curve],
        marker="o", color="#3f6f4f", linewidth=2,
    )
    axes.set_xlabel("Полнота")
    axes.set_ylabel("Точность")
    axes.set_title(title or "Зависимость точности от полноты (11 точек)")
    axes.set_xlim(-0.02, 1.02)
    axes.set_ylim(0, 1.05)
    axes.grid(True, alpha=0.3)
    figure.tight_layout()
    figure.savefig(path, dpi=130)
    plt.close(figure)
    return path


def per_query_bars(
    per_query: list[dict], metric: str = "ap", path: Path | None = None
) -> Path:
    """Столбчатая диаграмма значения метрики по каждому эталонному запросу."""
    plt = _pyplot()
    path = path or (config.REPORT_DIR / f"per_query_{metric.replace('@', '_')}.png")
    path.parent.mkdir(parents=True, exist_ok=True)

    labels = [f"{item['query_id']}" for item in per_query]
    values = [item.get(metric, 0.0) for item in per_query]

    figure, axes = plt.subplots(figsize=(max(7, len(labels) * 0.45), 4.2))
    axes.bar(labels, values, color="#5b8c6a")
    average = sum(values) / len(values) if values else 0
    axes.axhline(average, color="#b4553f", linestyle="--", linewidth=1.2,
                 label=f"среднее = {average:.3f}")
    axes.set_xlabel("Номер эталонного запроса")
    axes.set_ylabel(metric.upper())
    axes.set_ylim(0, 1.05)
    axes.legend()
    axes.grid(True, axis="y", alpha=0.3)
    figure.tight_layout()
    figure.savefig(path, dpi=130)
    plt.close(figure)
    return path


def configurations_chart(comparison: list[dict], path: Path | None = None) -> Path:
    """Сравнение конфигураций системы по основным метрикам."""
    plt = _pyplot()
    path = path or (config.REPORT_DIR / "configurations.png")
    path.parent.mkdir(parents=True, exist_ok=True)

    names = [item["name"] for item in comparison]
    shown = [("MAP", "map"), ("P@10", "p@10"), ("R-точность", "r_precision"), ("nDCG", "ndcg")]

    figure, axes = plt.subplots(figsize=(9, 4.6))
    width = 0.8 / len(shown)
    positions = range(len(names))
    palette = ["#3f6f4f", "#5b8c6a", "#8fb08c", "#b4553f"]
    for index, (label, key) in enumerate(shown):
        values = [item["summary"].get(key, 0.0) for item in comparison]
        axes.bar(
            [p + index * width for p in positions], values, width=width,
            label=label, color=palette[index % len(palette)],
        )
    axes.set_xticks([p + width * (len(shown) - 1) / 2 for p in positions])
    axes.set_xticklabels(names, fontsize=8.5, rotation=8)
    axes.set_ylim(0, 1.05)
    axes.set_ylabel("Значение метрики")
    axes.set_title("Сравнение конфигураций поисковой системы")
    axes.legend()
    axes.grid(True, axis="y", alpha=0.3)
    figure.tight_layout()
    figure.savefig(path, dpi=130)
    plt.close(figure)
    return path
