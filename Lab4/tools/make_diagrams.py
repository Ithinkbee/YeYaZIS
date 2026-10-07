"""Схемы для отчёта.

Методичка требует описать структуру системы и основные алгоритмы. Сценарий
строит четыре схемы:

    structure.png  — структура системы и связи между модулями;
    algorithm.png  — блок-схема перевода с трансфером;
    fields.png     — трансфер порядка слов: английское дерево → поля немецкого предложения;
    game_flow.png  — тир Пафнутия: от переведённого текста к волнам и обратно к документу.

    python tools/make_diagrams.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dragoman import config, console  # noqa: E402

console.setup()

INK = "#221d17"
MUTED = "#7a7166"
LINE = "#b7aea2"
FILL = "#ffffff"
ACCENT = "#f4e6e1"
ACCENT_LINE = "#8a3b2e"
DATA = "#f3efe6"
BLUE = "#e3eef6"
BLUE_LINE = "#3a6383"
GREEN = "#eef5e9"
GREEN_LINE = "#4f6b3a"
GOLD = "#fbf3dc"
GOLD_LINE = "#9a7420"


def _plt():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 9, "figure.dpi": 150, "font.family": "DejaVu Sans"})
    return plt


def canvas(plt, width, height, xmax=100, ymax=100):
    figure, axis = plt.subplots(figsize=(width, height))
    axis.set_xlim(0, xmax)
    axis.set_ylim(0, ymax)
    axis.axis("off")
    return figure, axis


def box(ax, x, y, w, h, text, *, fill=FILL, edge=LINE, bold=False, size=8.5, align="center", radius=1.2):
    from matplotlib.patches import FancyBboxPatch

    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0.25,rounding_size={radius}",
                                linewidth=1.1, edgecolor=edge, facecolor=fill))
    if align == "center":
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=size, color=INK,
                fontweight="bold" if bold else "normal", linespacing=1.4)
    else:
        ax.text(x + 1.2, y + h - 1.2, text, ha="left", va="top", fontsize=size, color=INK,
                fontweight="bold" if bold else "normal", linespacing=1.4)


def frame(ax, x, y, w, h, title, *, fill, edge):
    from matplotlib.patches import FancyBboxPatch

    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.3,rounding_size=1.8",
                                linewidth=1.3, edgecolor=edge, facecolor=fill))
    ax.text(x + 1.2, y + h - 0.8, title, ha="left", va="top", fontsize=9.5, color=edge, fontweight="bold")


def diamond(ax, cx, cy, w, h, text, size=8):
    from matplotlib.patches import Polygon

    ax.add_patch(Polygon([(cx, cy + h / 2), (cx + w / 2, cy), (cx, cy - h / 2), (cx - w / 2, cy)],
                         closed=True, linewidth=1.1, edgecolor=ACCENT_LINE, facecolor=ACCENT))
    ax.text(cx, cy, text, ha="center", va="center", fontsize=size, color=INK, linespacing=1.3)


def terminal(ax, cx, cy, w, h, text, size=8.5):
    from matplotlib.patches import FancyBboxPatch

    ax.add_patch(FancyBboxPatch((cx - w / 2, cy - h / 2), w, h, boxstyle=f"round,pad=0.2,rounding_size={h / 2}",
                                linewidth=1.2, edgecolor=ACCENT_LINE, facecolor=ACCENT))
    ax.text(cx, cy, text, ha="center", va="center", fontsize=size, color=INK, fontweight="bold")


def arrow(ax, start, end, text="", *, color=MUTED, dashed=False, both=False, size=7.3, offset=(0, 0.8),
          ha="center", width=1.0, rad=0.0):
    from matplotlib.patches import FancyArrowPatch

    ax.add_patch(FancyArrowPatch(start, end, arrowstyle="<|-|>" if both else "-|>", mutation_scale=10,
                                 linewidth=width, color=color, linestyle="--" if dashed else "-",
                                 shrinkA=1, shrinkB=1, connectionstyle=f"arc3,rad={rad}"))
    if text:
        ax.text((start[0] + end[0]) / 2 + offset[0], (start[1] + end[1]) / 2 + offset[1], text,
                ha=ha, va="bottom", fontsize=size, color=MUTED, linespacing=1.3)


def save(figure, name: str) -> Path:
    config.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = config.REPORT_DIR / name
    figure.savefig(path, bbox_inches="tight", facecolor="white", pad_inches=0.15)
    return path


# --- структура системы -------------------------------------------------------------

def draw_structure(plt) -> Path:
    fig, ax = canvas(plt, 11, 9.4)
    ax.set_ylim(-2, 104)
    ax.text(50, 103, "Структура системы «Драгоман»", ha="center", va="top", fontsize=12.5,
            fontweight="bold", color=INK)

    box(ax, 38, 92.5, 24, 5.2, "Пользователь (браузер)", fill=ACCENT, edge=ACCENT_LINE, bold=True)

    frame(ax, 2, 68, 96, 21.5, "Уровень интерфейса — dragoman/web", fill="#fbf8f3", edge=ACCENT_LINE)
    box(ax, 4, 70, 22, 14.5,
        "Ввод текста\nполе или файл: TXT, MD,\nHTML, DOCX, PDF\n(text/extract.py)", size=8)
    box(ax, 28, 70, 25, 14.5,
        "Результат (FastAPI + Jinja2)\nперевод, статистика;\n1 — частотный список,\n2 — дерево разбора,\n"
        "3 — сравнение способов", size=8)
    box(ax, 55, 70, 20, 14.5,
        "Сохранение и печать\nTXT в Unicode\n(UTF-16 / UTF-8)\nexport.py", size=8)
    box(ax, 77, 70, 19, 14.5,
        "Словарь: правка,\nпополнение,\nимпорт / экспорт;\nоценка; справка", size=8)

    frame(ax, 2, 28, 47, 36.5, "Перевод — dragoman/english, translate, german", fill=GREEN, edge=GREEN_LINE)
    box(ax, 4, 53, 43, 7.5,
        "text/segment.py — абзацы, заголовки, предложения, слова;\nenglish/ — теггер, лемматизатор, анализатор "
        "зависимостей", size=7.8)
    box(ax, 4, 43.5, 43, 7.5,
        "translate/transfer.py — трансфер: роли, согласование,\nпадежи, время и залог, порядок слов (поля)", size=7.8)
    box(ax, 4, 34, 43, 7.5,
        "german/ — синтез форм: спряжение, склонение,\nсложные слова; translate/output.py — сборка текста",
        size=7.8)
    box(ax, 4, 29.5, 20.5, 3.4, "direct.py — пословный", size=7.4)
    box(ax, 26.5, 29.5, 20.5, 3.4, "trees.py — деревья SVG", size=7.4)

    frame(ax, 51, 28, 47, 36.5, "Словарь — dragoman/lexicon", fill=BLUE, edge=BLUE_LINE)
    box(ax, 53, 53, 43, 7.5,
        "db.py — таблица словаря в SQLite (≈ 4 тыс. записей):\nчасть речи, род, мн. ч., управление, область",
        size=7.8)
    box(ax, 53, 43.5, 43, 7.5,
        "translate/lexical.py — выбор перевода: область (CS,\nлитература, общая), часть речи, обороты", size=7.8)
    box(ax, 53, 34, 43, 7.5,
        "guess.py — правила словообразования;\nding.py — подсказки словаря Ding (TU Chemnitz)", size=7.8)
    box(ax, 53, 29.5, 43, 3.4, "журнал неизвестных слов → пополнение словаря", size=7.4)

    frame(ax, 2, 3, 30, 21, "Данные — data/, models/", fill=DATA, edge=MUTED)
    box(ax, 4, 4.5, 26, 15,
        "collection/ — 12 текстов (CS, лит.);\nreference/ — 120 эталонов;\nlexicon/*.tsv — исходный словарь;\n"
        "models/ — теггер, анализатор\n(обучены на UD EWT, GUM,\nLinES, ParTUT — tools/train.py)", size=7.4)

    frame(ax, 35, 3, 28, 21, "Оценка и статистика", fill="#fbf8f3", edge=MUTED)
    box(ax, 37, 4.5, 24, 15,
        "pipeline.py — число слов,\nпереведённых слов, частотный\nсписок с грамматикой;\n"
        "evaluation.py — BLEU, chrF,\nвремя; tools/evaluate.py", size=7.4)

    frame(ax, 66, 3, 32, 21, "Тир Пафнутия (доп. функционал)", fill=GOLD, edge=GOLD_LINE)
    box(ax, 68, 12.5, 28, 7.5, "game.py — план волн из слов\nпереведённого текста", size=7.6)
    box(ax, 68, 4.5, 28, 6.5, "static/shooter.js — 3D (three.js);\nshooter_rules.js — правила боя",
        size=7.4)

    arrow(ax, (50, 92.3), (50, 90.2), both=True)
    arrow(ax, (25, 67.8), (25, 64.9), "текст", ha="right", offset=(-1.2, -1.6))
    arrow(ax, (74.5, 67.8), (74.5, 64.9), "правка словаря", ha="right", offset=(-1.2, -1.6))
    arrow(ax, (49.2, 47.2), (52.8, 47.2), both=True)
    arrow(ax, (17, 24.2), (17, 27.8), color=MUTED)
    arrow(ax, (40, 27.8), (45, 24.2), color=MUTED, dashed=True)
    arrow(ax, (70, 24.2), (44, 27.8), "перевод текста", color=MUTED, dashed=True, ha="left", offset=(3, -0.6))
    return save(fig, "structure.png")


# --- алгоритм перевода с трансфером ---------------------------------------------------

def draw_algorithm(plt) -> Path:
    fig, ax = canvas(plt, 9.8, 13.4, 100, 138)
    ax.text(50, 137, "Алгоритм перевода с трансфером (системы второго поколения)", ha="center", va="top",
            fontsize=12, fontweight="bold", color=INK)
    terminal(ax, 50, 130, 34, 4.6, "Начало: английский текст")
    steps = [
        (121.5, "1. Разбиение на абзацы, заголовки, предложения и слова\n(сокращения, числа, «don't» → do + n't)",
         FILL, LINE),
        (112.5, "2. Морфологический анализ: тег Penn Treebank (перцептрон),\nлемма (правила окончаний + исключения)",
         FILL, LINE),
        (103.5, "3. Синтаксический анализ: дерево зависимостей\n(arc-hybrid, перцептрон) и отношения UD", FILL, LINE),
        (94.5, "4. Исправление типичных ошибок разбора: корень, композиты,\nвопросы с do, инфинитив при "
               "прилагательном", FILL, LINE),
        (85.5, "5. Лексический трансфер: обороты из словаря (operating system,\ndepend on), перевод слова "
               "по области и части речи", GREEN, GREEN_LINE),
    ]
    for y, text, fill, edge in steps:
        box(ax, 12, y - 3.6, 76, 7.2, text, size=8, fill=fill, edge=edge)
    for top, bottom in ((127.6, 125.3), (117.7, 116.3), (108.7, 107.3), (99.7, 98.3), (90.7, 89.3)):
        arrow(ax, (50, top), (50, bottom))

    diamond(ax, 50, 75, 40, 8.5, "Слово есть\nв словаре?", size=8)
    arrow(ax, (50, 81.7), (50, 79.4))
    box(ax, 74, 70.8, 24, 8.4, "нет: правила слово-\nобразования (-ization →\n-isierung), иначе слово\n"
                               "остаётся и идёт в журнал", size=7.2)
    arrow(ax, (70, 75), (73.6, 75), "нет", offset=(0, 0.5))

    box(ax, 4, 52, 44, 14.5,
        "6. Структурный трансфер предложения:\nподлежащее и согласование глагола;\nвремя, залог, модальность → "
        "группа глагола\n(hat … gelernt, wurde … kompiliert);\nпадеж каждой группы по роли и предлогу;\n"
        "of → Genitiv, отрицание → kein / nicht", size=7.8, fill=GREEN, edge=GREEN_LINE)
    box(ax, 52, 52, 44, 14.5,
        "7. Порядок слов по полям:\nглавное — V2 (Vorfeld, глагол, Mittelfeld,\nправая скобка);"
        " придаточное — глагол\nв конце; zu-/um-zu-оборот; вопрос — глагол\nпервым; отделяемая приставка в конец",
        size=7.8, fill=GREEN, edge=GREEN_LINE)
    arrow(ax, (50, 70.7), (26, 66.8), "да", ha="right", offset=(-2, -2))
    arrow(ax, (86, 70.6), (74, 66.8))
    arrow(ax, (48.3, 59.3), (51.7, 59.3))

    box(ax, 12, 38.5, 76, 9.5,
        "8. Синтез форм: спряжение (сильные глаголы, приставки), склонение\nсуществительных и прилагательных "
        "(сильное / слабое / смешанное),\nартикли, сложные слова (Quell + Code → Quellcode), слияния (in dem → im)",
        size=7.8, fill=BLUE, edge=BLUE_LINE)
    arrow(ax, (74, 51.7), (60, 48.3))
    box(ax, 12, 27, 76, 7.5,
        "9. Сборка текста: пунктуация, кавычки „…“, прописные буквы;\nслова, которым не нашлось места "
        "(ошибка разбора), — в конец предложения", size=7.8)
    arrow(ax, (50, 38.2), (50, 34.8))
    box(ax, 12, 15.5, 76, 7.5,
        "10. Статистика: слов в тексте, переведено (по словарю, по правилам),\nимена и числа, без перевода; "
        "частотный список с грамматикой", size=7.8, fill=ACCENT, edge=ACCENT_LINE)
    arrow(ax, (50, 26.7), (50, 23.3))
    terminal(ax, 50, 7, 54, 5, "Конец: перевод, список слов, деревья, файл TXT")
    arrow(ax, (50, 15.2), (50, 9.7))
    return save(fig, "algorithm.png")


# --- поля немецкого предложения ------------------------------------------------------------

def draw_fields(plt) -> Path:
    fig, ax = canvas(plt, 11, 6.6, 100, 64)
    ax.text(50, 63, "Структурный трансфер: роли английского предложения → поля немецкого", ha="center", va="top",
            fontsize=12, fontweight="bold", color=INK)

    english = [("Yesterday", "advmod"), ("the compiler", "nsubj"), ("has", "aux"), ("translated", "root"),
               ("the program", "obj"), ("into machine code", "obl")]
    x = 3
    ax.text(3, 55, "Английское предложение и роли (дерево зависимостей):", fontsize=8.8, color=MUTED, va="center")
    positions = {}
    for text, role in english:
        width = 3 + len(text) * 1.02
        box(ax, x, 45, width, 6, text, size=8.5, fill=FILL, edge=LINE)
        ax.text(x + width / 2, 43.2, role, ha="center", va="top", fontsize=7.4, color=BLUE_LINE)
        positions[role] = x + width / 2
        x += width + 1.8

    fields = [("Vorfeld", "Gestern", 3, 15, GOLD, GOLD_LINE),
              ("финитный глагол", "hat", 20, 11, ACCENT, ACCENT_LINE),
              ("Mittelfeld", "der Compiler  das Programm  in Maschinencode", 33, 42, GREEN, GREEN_LINE),
              ("правая скобка", "übersetzt", 77, 14, ACCENT, ACCENT_LINE)]
    ax.text(3, 31, "Немецкое предложение по полям (главное предложение, глагол на втором месте):", fontsize=8.8,
            color=MUTED, va="center")
    centers = {}
    for title, text, fx, fw, fill, edge in fields:
        box(ax, fx, 18, fw, 8, text, size=9, fill=fill, edge=edge, bold=title != "Mittelfeld")
        ax.text(fx + fw / 2, 27.6, title, ha="center", va="bottom", fontsize=7.6, color=edge, fontweight="bold")
        centers[title] = fx + fw / 2

    links = [("advmod", "Vorfeld", 0), ("aux", "финитный глагол", 0), ("nsubj", "Mittelfeld", -10),
             ("obj", "Mittelfeld", 2), ("obl", "Mittelfeld", 14), ("root", "правая скобка", 0)]
    for role, field, shift in links:
        arrow(ax, (positions[role], 42), (centers[field] + shift, 28.6), color=MUTED, width=0.9)

    notes = ("• обстоятельство заняло Vorfeld — подлежащее уходит за глагол (инверсия);\n"
             "• has + translated → hat … übersetzt: рамочная конструкция, причастие в конце;\n"
             "• в Mittelfeld: подлежащее, дополнения (местоимения раньше), обстоятельства по правилу «время — "
             "причина — образ — место»;\n"
             "• в придаточном («…, dass der Compiler das Programm übersetzt hat») финитный глагол уходит "
             "в конец, Vorfeld нет.")
    ax.text(3, 13.5, notes, fontsize=8, color=INK, va="top", linespacing=1.55)
    return save(fig, "fields.png")


# --- тир Пафнутия ------------------------------------------------------------------------------

def draw_game(plt) -> Path:
    fig, ax = canvas(plt, 11, 6.4, 100, 62)
    ax.text(50, 61, "Тир Пафнутия: слова текста идут волнами", ha="center", va="top", fontsize=12.5,
            fontweight="bold", color=INK)
    box(ax, 2, 40, 21, 13, "Текст: свой или\nиз коллекции;\nчисло волн N (1–10),\nсложность", fill=ACCENT,
        edge=ACCENT_LINE, size=8)
    box(ax, 27, 40, 22, 13, "Перевод с трансфером:\nу каждого разного слова —\nего немецкий перевод\nиз "
                            "перевода текста", fill=GREEN, edge=GREEN_LINE, size=8)
    box(ax, 53, 40, 45, 13,
        "План волн (game.py):\n• мини-боссы — N самых длинных слов:\n  волна 1 — N-е по длине, …, "
        "волна N — самое длинное;\n• остальные слова — по волнам в отношении\n  1 : 2 : … : N, от коротких "
        "к длинным", fill=GOLD, edge=GOLD_LINE, size=7.6, align="left")
    arrow(ax, (23.4, 46.5), (26.6, 46.5))
    arrow(ax, (49.4, 46.5), (52.6, 46.5))

    kinds = [("мелочь", "служебные слова ≤ 4 букв:\nбыстрые, стайками"),
             ("слово", "существительные, прил.,\nнаречия, имена: кусают"),
             ("слово с пушкой", "глаголы: держат дистанцию,\nстреляют буквами"),
             ("мини-босс", "длинное слово: много\nпопаданий, очереди")]
    for k, (title, note) in enumerate(kinds):
        x = 2 + k * 24.5
        box(ax, x, 21, 22.5, 12, "\n" + note, size=7.6, fill=FILL, edge=GOLD_LINE)
        ax.text(x + 11.25, 31.4, title, ha="center", va="top", fontsize=8, color=GOLD_LINE, fontweight="bold")
    ax.text(50, 35.4, "Противники волны", ha="center", fontsize=8.5, color=GOLD_LINE, fontweight="bold")
    arrow(ax, (75, 39.7), (75, 36.8))

    box(ax, 2, 3, 30, 12, "Попадание паутиной:\nслово «переведено» —\nнад ним немецкий перевод,\nв панели "
                          "текста слово\nменяется на немецкое", size=7.8, fill=BLUE, edge=BLUE_LINE)
    box(ax, 36, 3, 28, 12, "Все волны пройдены —\nпереведены все слова\nтекста (каждое слово —\nровно один "
                           "противник)", size=7.8, fill=GREEN, edge=GREEN_LINE)
    box(ax, 68, 3, 30, 12, "Победа: полностью\nпереведённый документ;\nсохранить в TXT, открыть\nна странице "
                           "перевода", size=7.8, fill=ACCENT, edge=ACCENT_LINE, bold=False)
    arrow(ax, (17, 20.7), (17, 15.3))
    arrow(ax, (32.4, 9), (35.6, 9))
    arrow(ax, (64.4, 9), (67.6, 9))
    return save(fig, "game_flow.png")


def main() -> int:
    plt = _plt()
    for draw in (draw_structure, draw_algorithm, draw_fields, draw_game):
        path = draw(plt)
        print(f"  {path.name}")
        plt.close("all")
    return 0


if __name__ == "__main__":
    sys.exit(main())
