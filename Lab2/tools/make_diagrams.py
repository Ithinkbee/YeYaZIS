"""Схемы для пояснительной записки.

Методичка требует описать алгоритм определения языка в текстовом и в
графическом виде, а также структуру системы. Сценарий строит три схемы:

    structure.png  — структура системы и связи между модулями;
    algorithm.png  — блок-схема распознавания (три шага методички);
    profiles.png   — построение поисковых образов языка и документа.

    python tools/make_diagrams.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tolmach import config, console  # noqa: E402

console.setup()

INK = "#23201c"
MUTED = "#7b756c"
LINE = "#b9b2a8"
FILL = "#ffffff"
ACCENT = "#f0e8de"
ACCENT_LINE = "#7a5c3e"
RU = "#f7e6de"
DE = "#e0ebf3"


def _setup():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 9, "figure.dpi": 150})
    return plt


def box(axis, x, y, width, height, text, *, fill=FILL, edge=LINE, bold=False, size=9):
    """Прямоугольник со скруглением и подписью по центру."""
    from matplotlib.patches import FancyBboxPatch

    axis.add_patch(
        FancyBboxPatch(
            (x, y), width, height,
            boxstyle="round,pad=0.012,rounding_size=0.02",
            linewidth=1.1, edgecolor=edge, facecolor=fill,
        )
    )
    axis.text(
        x + width / 2, y + height / 2, text,
        ha="center", va="center", fontsize=size, color=INK,
        fontweight="bold" if bold else "normal", linespacing=1.45,
    )


def diamond(axis, x, y, width, height, text, size=8.5):
    """Ромб — условие в блок-схеме."""
    from matplotlib.patches import Polygon

    cx, cy = x + width / 2, y + height / 2
    axis.add_patch(
        Polygon(
            [(cx, y + height), (x + width, cy), (cx, y), (x, cy)],
            closed=True, linewidth=1.1, edgecolor=ACCENT_LINE, facecolor=ACCENT,
        )
    )
    axis.text(cx, cy, text, ha="center", va="center", fontsize=size, color=INK, linespacing=1.4)


def arrow(axis, start, end, *, text="", dashed=False, color=MUTED):
    """Стрелка между блоками с необязательной подписью."""
    from matplotlib.patches import FancyArrowPatch

    axis.add_patch(
        FancyArrowPatch(
            start, end,
            arrowstyle="-|>", mutation_scale=11,
            linewidth=1.0, color=color,
            linestyle="--" if dashed else "-",
            shrinkA=2, shrinkB=2,
        )
    )
    if text:
        axis.text(
            (start[0] + end[0]) / 2, (start[1] + end[1]) / 2 + 0.012, text,
            ha="center", va="bottom", fontsize=7.5, color=MUTED,
        )


def canvas(plt, width, height):
    figure, axis = plt.subplots(figsize=(width, height))
    axis.set_xlim(0, 1)
    axis.set_ylim(0, 1)
    axis.axis("off")
    return figure, axis


def save(figure, name: str) -> Path:
    path = config.REPORT_DIR / name
    figure.savefig(path, bbox_inches="tight", facecolor="white")
    return path


# --- структура системы -------------------------------------------------------


def draw_structure(plt) -> Path:
    figure, axis = canvas(plt, 9.5, 6.4)

    axis.text(0.5, 0.975, "Структура системы «Толмач»", ha="center",
              fontsize=12, fontweight="bold", color=INK)

    # источники данных
    box(axis, 0.015, 0.775, 0.20, 0.105,
        "Обучающий корпус\ndata/train/ru, de\n20–120 Кб на язык", fill=RU, size=8.0)
    box(axis, 0.015, 0.625, 0.20, 0.105,
        "Тестовая коллекция\ndata/collection/*.html\n+ labels.csv", fill=DE, size=8.0)

    # ядро: единая вертикальная цепочка обработки
    box(axis, 0.285, 0.795, 0.24, 0.085, "preprocess\nHTML → текст → нормализация", bold=True, size=8.3)
    box(axis, 0.285, 0.655, 0.24, 0.085, "corpus\nчтение корпуса и коллекции", bold=True, size=8.3)
    box(axis, 0.285, 0.405, 0.24, 0.19,
        "methods\n\nngram · alphabet · neural\n\nfit / profile / distance",
        fill=ACCENT, edge=ACCENT_LINE, bold=True, size=8.5)
    box(axis, 0.285, 0.265, 0.24, 0.085, "recognizer\nоркестратор и голосование", bold=True, size=8.3)
    box(axis, 0.285, 0.125, 0.24, 0.085, "evaluation · experiments\nточность, время, опыты", bold=True, size=8.3)

    # хранилище профилей и выгрузки
    box(axis, 0.585, 0.445, 0.175, 0.105, "models/*.json\nпрофили языков", fill=ACCENT, size=8.1)
    box(axis, 0.585, 0.120, 0.175, 0.115, "export\nCSV · JSON · TXT\n→ report/", size=8.1)

    box(axis, 0.795, 0.395, 0.19, 0.345,
        "web\n\nFastAPI + Jinja2\n\nколлекция\nсравнение методов\nпрофили языков\nсвой текст\nсправка\nпечать",
        bold=True, size=8.1)

    # источники → ядро
    arrow(axis, (0.215, 0.828), (0.285, 0.836))
    arrow(axis, (0.215, 0.678), (0.285, 0.697))

    # вертикальная цепочка
    arrow(axis, (0.405, 0.795), (0.405, 0.740))
    arrow(axis, (0.405, 0.655), (0.405, 0.595))
    arrow(axis, (0.405, 0.405), (0.405, 0.350))
    arrow(axis, (0.405, 0.265), (0.405, 0.210))

    # профили: сохранение после обучения и чтение при запуске
    arrow(axis, (0.525, 0.520), (0.585, 0.520))
    arrow(axis, (0.585, 0.478), (0.525, 0.478), dashed=True)
    axis.text(0.673, 0.428, "сохранение и чтение профилей",
              ha="center", va="top", fontsize=7.2, color=MUTED, style="italic")

    # выгрузка и интерфейс
    arrow(axis, (0.525, 0.172), (0.585, 0.178))
    arrow(axis, (0.525, 0.300), (0.795, 0.425))
    arrow(axis, (0.735, 0.235), (0.826, 0.395))

    axis.text(0.5, 0.030,
              "Методы подключаются через общий интерфейс Method: новый метод "
              "добавляется правкой одного реестра",
              ha="center", fontsize=7.8, color=MUTED, style="italic")

    return save(figure, "structure.png")


# --- блок-схема алгоритма ----------------------------------------------------


def draw_algorithm(plt) -> Path:
    figure, axis = canvas(plt, 8.2, 8.6)

    axis.text(0.5, 0.982, "Алгоритм определения языка документа", ha="center",
              fontsize=12, fontweight="bold", color=INK)

    left = 0.28
    width = 0.44

    box(axis, left, 0.905, width, 0.052, "Входной HTML-документ", fill=DE, bold=True)

    axis.text(0.045, 0.845, "Шаг 1", fontsize=9, fontweight="bold", color=ACCENT_LINE)
    axis.text(0.045, 0.825, "предварительная\nобработка", fontsize=7.6, color=MUTED, va="top")
    box(axis, left, 0.828, width, 0.052, "Удалить теги, script, style;\nраскрыть HTML-сущности", size=8.3)
    box(axis, left, 0.751, width, 0.052, "Привести к строчным буквам;\nне-буквы → пробел (ä ö ü ß сохранить)", size=8.3)

    axis.text(0.045, 0.706, "Шаг 2", fontsize=9, fontweight="bold", color=ACCENT_LINE)
    axis.text(0.045, 0.688, "сравнение\nпрофилей", fontsize=7.6, color=MUTED, va="top")
    box(axis, left, 0.664, width, 0.052, "Построить профиль документа (ПОД)\nпо правилу метода", bold=True, size=8.3)

    # три метода рядом
    box(axis, 0.055, 0.487, 0.27, 0.13,
        "Метод N-грамм\n\nN-граммы длиной 1–5\nиз «_слово_»,\nтоп-300 по частоте",
        fill=ACCENT, edge=ACCENT_LINE, size=7.9)
    box(axis, 0.365, 0.487, 0.27, 0.13,
        "Алфавитный метод\n\nвектор относительных\nчастот букв\nалфавита",
        fill=ACCENT, edge=ACCENT_LINE, size=7.9)
    box(axis, 0.675, 0.487, 0.27, 0.13,
        "Нейросетевой метод\n\nвектор частот 400\nсимвольных N-грамм\n(длина 1–3)",
        fill=ACCENT, edge=ACCENT_LINE, size=7.9)

    box(axis, 0.055, 0.352, 0.27, 0.105,
        "Мера несовпадения\nпозиций (out-of-place):\nΣ|ранг_д − ранг_я|,\nштраф за отсутствие", size=7.9)
    box(axis, 0.365, 0.352, 0.27, 0.105,
        "Манхэттенское\nрасстояние\nΣ|p − q| / 2", size=7.9)
    box(axis, 0.675, 0.352, 0.27, 0.105,
        "Прямой проход сети,\nsoftmax;\nрасстояние = 1 − P(язык)", size=7.9)

    box(axis, left, 0.262, width, 0.052, "Расстояние до каждого ПОЯ\n(профиля языка)", size=8.3)

    axis.text(0.045, 0.192, "Шаг 3", fontsize=9, fontweight="bold", color=ACCENT_LINE)
    axis.text(0.045, 0.172, "выбор языка", fontsize=7.6, color=MUTED, va="top")
    diamond(axis, 0.325, 0.135, 0.35, 0.088, "Какое расстояние\nнаименьшее?")

    box(axis, 0.085, 0.045, 0.24, 0.05, "Русский", fill=RU, bold=True)
    box(axis, 0.675, 0.045, 0.24, 0.05, "Немецкий", fill=DE, bold=True)

    # поток
    arrow(axis, (0.5, 0.905), (0.5, 0.880))
    arrow(axis, (0.5, 0.828), (0.5, 0.803))
    arrow(axis, (0.5, 0.751), (0.5, 0.716))
    arrow(axis, (0.5, 0.664), (0.5, 0.617))

    for x in (0.19, 0.5, 0.81):
        arrow(axis, (x, 0.487), (x, 0.457))
    # боковые ветви сводятся внутрь: расстояние считается одним и тем же блоком
    arrow(axis, (0.19, 0.352), (0.33, 0.316))
    arrow(axis, (0.50, 0.352), (0.50, 0.316))
    arrow(axis, (0.81, 0.352), (0.67, 0.316))
    arrow(axis, (0.5, 0.262), (0.5, 0.223))

    arrow(axis, (0.325, 0.179), (0.205, 0.095), text="до русского")
    arrow(axis, (0.675, 0.179), (0.795, 0.095), text="до немецкого")

    # профили языков: отдельный вход в блок расчёта расстояния, справа от него
    box(axis, 0.735, 0.245, 0.235, 0.086,
        "ПОЯ — профили языков\nиз обучающего корпуса\n(models/*.json)", fill=RU, size=7.9)
    arrow(axis, (0.735, 0.288), (0.72, 0.288), dashed=True)

    axis.text(0.5, 0.012,
              "Итоговый ответ системы — голосование трёх методов; "
              "при равенстве голосов побеждает метод с наибольшим отрывом",
              ha="center", fontsize=7.8, color=MUTED, style="italic")

    return save(figure, "algorithm.png")


# --- построение профилей -----------------------------------------------------


def draw_profiles(plt) -> Path:
    figure, axis = canvas(plt, 9.2, 4.6)

    axis.text(0.5, 0.965, "Построение поисковых образов и их сравнение",
              ha="center", fontsize=12, fontweight="bold", color=INK)

    # верхняя ветвь — язык
    box(axis, 0.02, 0.70, 0.18, 0.115, "Обучающий корпус\nязыка (20–120 Кб)", fill=RU, size=8.3)
    box(axis, 0.24, 0.70, 0.17, 0.115, "Нормализация\nтекста", size=8.3)
    box(axis, 0.45, 0.70, 0.19, 0.115, "Подсчёт частот\nпризнаков", size=8.3)
    box(axis, 0.655, 0.70, 0.235, 0.115,
        "Сортировка по частоте,\nранги = ПОЯ", fill=ACCENT, edge=ACCENT_LINE, bold=True, size=8.3)

    # нижняя ветвь — документ
    box(axis, 0.02, 0.24, 0.18, 0.115, "Входной документ\nHTML", fill=DE, size=8.3)
    box(axis, 0.24, 0.24, 0.17, 0.115, "Удаление разметки\n+ нормализация", size=8.3)
    box(axis, 0.45, 0.24, 0.19, 0.115, "Подсчёт частот\nтех же признаков", size=8.3)
    box(axis, 0.655, 0.24, 0.235, 0.115,
        "Сортировка по частоте,\nранги = ПОД", fill=ACCENT, edge=ACCENT_LINE, bold=True, size=8.3)

    for y in (0.7575, 0.2975):
        arrow(axis, (0.20, y), (0.24, y))
        arrow(axis, (0.41, y), (0.45, y))
        arrow(axis, (0.64, y), (0.655, y))

    # сравнение
    box(axis, 0.655, 0.475, 0.235, 0.105,
        "Метрика расстояния\nПОД ↔ ПОЯ", fill=ACCENT, edge=ACCENT_LINE, bold=True, size=8.5)
    arrow(axis, (0.7725, 0.70), (0.7725, 0.58))
    arrow(axis, (0.7725, 0.355), (0.7725, 0.475))

    axis.text(0.30, 0.525,
              "Оба образа строятся по одному и тому же правилу —\n"
              "иначе их ранги были бы несопоставимы",
              ha="center", fontsize=8.2, color=MUTED, style="italic", linespacing=1.5)

    axis.text(0.5, 0.055,
              "Профили языков строятся один раз и сохраняются в models/*.json; "
              "профиль документа — при каждом распознавании",
              ha="center", fontsize=7.8, color=MUTED, style="italic")

    return save(figure, "profiles.png")


def main() -> int:
    config.ensure_dirs()
    try:
        plt = _setup()
    except ImportError:
        print("ОШИБКА: не установлен matplotlib (pip install matplotlib)")
        return 1

    print("Построение схем…")
    for draw in (draw_structure, draw_algorithm, draw_profiles):
        path = draw(plt)
        plt.close("all")
        print(f"  {path.name:16} {path.stat().st_size / 1024:6.0f} Кб")
    print(f"\nГотово. Каталог отчёта: {config.REPORT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
