"""Схемы для отчёта.

Методичка требует описать структуру системы и алгоритм построения реферата в
текстовом и графическом виде. Сценарий строит четыре схемы:

    structure.png  — структура системы и связи между модулями;
    algorithm.png  — блок-схема построения реферата (sentence extraction);
    ostis_flow.png — взаимодействие интерфейса, базы знаний и sc-агента;
    kb_summary.png — реферат в базе знаний (в обозначениях, близких к SCg).

    python tools/make_diagrams.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from izbornik import config, console  # noqa: E402

console.setup()

INK = "#221d17"
MUTED = "#7a7166"
LINE = "#b7aea2"
FILL = "#ffffff"
ACCENT = "#f4e6e1"
ACCENT_LINE = "#8a3b2e"
DATA = "#f3efe6"
OSTIS = "#e3eef6"
OSTIS_LINE = "#3a6383"
CORE = "#eef5e9"
CORE_LINE = "#4f6b3a"


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
    fig, ax = canvas(plt, 11, 8.6)
    ax.set_ylim(-5, 100)
    ax.text(50, 99, "Структура системы «Изборник»", ha="center", va="top", fontsize=12.5,
            fontweight="bold", color=INK)

    box(ax, 38, 88.5, 24, 5.2, "Пользователь (браузер)", fill=ACCENT, edge=ACCENT_LINE, bold=True)

    frame(ax, 2, 64, 96, 21.5, "Уровень интерфейса — izbornik/web", fill="#fbf8f3", edge=ACCENT_LINE)
    box(ax, 4, 66, 30, 14.5,
        "Страницы (FastAPI + Jinja2)\n• коллекция • реферат документа\n• исходный документ • свой документ\n"
        "• оценка • OSTIS • справка", size=8)
    box(ax, 36, 66, 29, 14.5,
        "Выходная информация\nactive-ссылка на исходный документ\nсохранение: TXT, HTML, DOCX,\nJSON, SCs "
        "(export.py)\nверсия для печати", size=8)
    box(ax, 67, 66, 29, 14.5,
        "Ввод своего документа\nтекст или файл: TXT, MD, HTML,\nDOCX, PDF (text/extract.py)\n"
        "определение языка по алфавиту", size=8)

    frame(ax, 2, 22, 46, 38.5, "Ядро реферирования — izbornik", fill=CORE, edge=CORE_LINE)
    box(ax, 4, 49.5, 42, 7,
        "text/segment.py — абзацы, заголовки, предложения;\nсмещения |D|, |P|, BD(Sᵢ), BP(Sᵢ)", size=8)
    box(ax, 4, 40, 42, 7.5,
        "text/analysis.py, morphology.py, stopwords.py — слова,\nлеммы pymorphy3 / основы Snowball, стоп-слова, tf(t, D)",
        size=8)
    box(ax, 4, 31, 42, 7,
        "weights.py — df(t), |DB|, w(t, D), Score, Posd, Posp;\nsummary.py — отбор N предложений", size=8)
    box(ax, 4, 23.5, 20, 5.5, "keywords.py —\nключевые слова", size=8)
    box(ax, 26, 23.5, 20, 5.5, "text/compress.py —\nсжатие предложений", size=8)

    frame(ax, 52, 22, 46, 38.5, "Интеграция с OSTIS — izbornik/ostis", fill=OSTIS, edge=OSTIS_LINE)
    box(ax, 54, 49.5, 42, 7,
        "service.py — режим OSTIS: синхронизация коллекции,\nвызов действия, чтение реферата, локальный резерв",
        size=8)
    box(ax, 54, 40, 42, 7.5,
        "connection.py — подключение (py-sc-client 0.3.0),\nзагрузка онтологии kb/*.scs", size=8)
    box(ax, 54, 31, 42, 7, "kb.py — документы и рефераты в базе знаний:\nзапись ScConstruction, чтение ScTemplate",
        size=8)
    box(ax, 54, 23.5, 42, 5.5, "agent.py — sc-агент (py-sc-kpm 0.2.0): вызывает summary.build", size=8)

    frame(ax, 2, 1.5, 36, 17, "Данные — data/, kb/", fill=DATA, edge=MUTED)
    box(ax, 4, 3, 32, 11,
        "catalog.json, collection/*.txt — 20 документов\nи эталоны; stopwords/ru.txt, de.txt;\n"
        "kb/section_subject_domain_of_summarization\n— онтология предметной области (SCs)", size=7.8)

    frame(ax, 42, 1.5, 22, 17, "Оценка", fill="#fbf8f3", edge=MUTED)
    box(ax, 44, 3, 18, 11, "evaluation.py — ROUGE,\nбазовые способы, оракул,\nключевые слова, время;\ntools/evaluate.py",
        size=7.8)

    frame(ax, 68, 1.5, 30, 17, "ostis-система NIKA (Docker)", fill="#e9f0f6", edge=OSTIS_LINE)
    box(ax, 70, 8.5, 26, 5.8, "sc-server, sc-memory (sc-machine 0.8.0)\nws://localhost:8090", size=7.8)
    box(ax, 70, 3, 26, 4.2, "sc-web — http://localhost:8000", size=7.8)

    arrow(ax, (50, 88.3), (50, 86.2), both=True)
    arrow(ax, (25, 63.8), (25, 60.9), "локальный режим", ha="right", offset=(-1.2, -1.6))
    arrow(ax, (75, 63.8), (75, 60.9), "режим OSTIS", ha="right", offset=(-1.2, -1.6))
    arrow(ax, (48.2, 26.2), (53.6, 26.2))
    arrow(ax, (83, 21.8), (83, 18.9), "JSON / WebSocket",
          both=True, ha="right", offset=(-1.2, -1.1), size=6.8)
    arrow(ax, (20, 18.9), (20, 21.8), color=MUTED)
    arrow(ax, (50, 18.9), (44, 21.8), color=MUTED, dashed=True)
    # онтология из kb/*.scs уходит в базу знаний — по нижнему краю схемы
    ax.plot([20, 20, 90], [1.2, -2.5, -2.5], color=MUTED, linewidth=1.0, linestyle="--")
    arrow(ax, (90, -2.5), (90, 1.2), dashed=True)
    ax.text(55, -2.1, "онтология kb/*.scs и документы коллекции загружаются в базу знаний",
            ha="center", va="bottom", fontsize=6.9, color=MUTED)
    return save(fig, "structure.png")


# --- алгоритм -------------------------------------------------------------------------

def draw_algorithm(plt) -> Path:
    fig, ax = canvas(plt, 9.6, 12.6, 100, 130)
    ax.text(50, 129, "Алгоритм построения реферата методом sentence extraction", ha="center", va="top",
            fontsize=12, fontweight="bold", color=INK)

    terminal(ax, 50, 122, 34, 4.6, "Начало: документ D")
    steps = [
        (113.5, "1. Разбиение на абзацы и предложения; заголовки — не кандидаты.\n"
                "Смещения: |D|, |P|, BD(Sᵢ), BP(Sᵢ)"),
        (104.5, "2. Выделение слов. Не учитываются: числа, слова чужого алфавита\n"
                "(латиница в русском тексте), стоп-слова и служебные обороты"),
        (95.5, "3. Приведение к термину: лемма pymorphy3 (рус.), основа Snowball (нем.).\n"
               "Частоты tf(t, D) и tf_max(D)"),
    ]
    for y, text in steps:
        box(ax, 14, y - 3.6, 72, 7.2, text, size=8)
    for top, bottom in ((119.6, 117.3), (109.7, 108.3), (100.7, 99.3)):
        arrow(ax, (50, top), (50, bottom))

    diamond(ax, 50, 85, 40, 8.5, "Документ входит\nв коллекцию DB?", size=8)
    arrow(ax, (50, 91.7), (50, 89.4))
    box(ax, 74, 81.3, 22, 7.4, "нет: добавить документ\nв DB — |DB| + 1,\ndf(t) + 1 для его терминов", size=7.4)
    arrow(ax, (70, 85), (73.6, 85), "нет", offset=(0, 0.5))
    box(ax, 14, 70.4, 72, 7.2, "4. df(t) и |DB| по документам коллекции того же языка.\n"
                               "w(t, D) = 0,5 · (1 + tf(t, D) / tf_max(D)) · log(|DB| / df(t))", size=8)
    arrow(ax, (50, 80.7), (50, 77.9), "да", ha="left", offset=(1, -1.5))
    arrow(ax, (85, 81.1), (78, 77.9))

    box(ax, 4, 52.5, 46, 13.5,
        "5. Для каждого предложения Sᵢ:\nScore(Sᵢ) = Σ tf(t, Sᵢ) · w(t, D)\nPosd(Sᵢ) = 1 − BD(Sᵢ) / |D|\n"
        "Posp(Sᵢ) = 1 − BP(Sᵢ) / |P|\nWeight(Sᵢ) = Score · Posd · Posp", size=8, fill=CORE, edge=CORE_LINE)
    box(ax, 54, 52.5, 42, 13.5,
        "8. Ключевые слова: существительные\nс наибольшей значимостью tf · log(|DB| / df)\n"
        "9. Именные группы с частотой ≥ 2:\nприл. + сущ., сущ. + сущ. в род. п.,\nимена, сложные слова (нем.)",
        size=8, fill=OSTIS, edge=OSTIS_LINE)
    arrow(ax, (35, 70.2), (27, 66.4))
    arrow(ax, (65, 70.2), (75, 66.4))

    box(ax, 4, 41, 46, 7, "6. Отбор N предложений с наибольшим весом\n(при равенстве — более раннее)", size=8,
        fill=CORE, edge=CORE_LINE)
    box(ax, 54, 41, 42, 7, "10. Подчинение групп ключевым словам:\nсеть → нейронная сеть → …", size=8,
        fill=OSTIS, edge=OSTIS_LINE)
    arrow(ax, (27, 52.2), (27, 48.3))
    arrow(ax, (75, 52.2), (75, 48.3))

    box(ax, 4, 29.5, 46, 7.5, "7. Предложения в порядке следования в тексте;\n"
                              "сжатие: без ссылок [n], отсылок (рис. n),\nвводных конструкций (рус.)", size=8,
        fill=CORE, edge=CORE_LINE)
    box(ax, 54, 29.5, 42, 7.5, "Реферат в виде списка\nключевых слов", size=8.5, bold=True, fill=OSTIS, edge=OSTIS_LINE)
    arrow(ax, (27, 40.7), (27, 37.3))
    arrow(ax, (75, 40.7), (75, 37.3))

    box(ax, 4, 20, 46, 6, "Классический реферат", size=8.5, bold=True, fill=CORE, edge=CORE_LINE)
    arrow(ax, (27, 29.2), (27, 26.3))

    box(ax, 22, 8.5, 56, 7.5, "Реферат документа: активная ссылка на исходный документ,\n"
                              "классический реферат, реферат в виде ключевых слов;\nсохранение в файл, печать",
        size=8, fill=ACCENT, edge=ACCENT_LINE)
    arrow(ax, (27, 19.7), (40, 16.3))
    arrow(ax, (75, 29.2), (62, 16.3))
    terminal(ax, 50, 3, 20, 4.2, "Конец")
    arrow(ax, (50, 8.3), (50, 5.3))
    return save(fig, "algorithm.png")


# --- взаимодействие с OSTIS ----------------------------------------------------------------

def draw_ostis_flow(plt) -> Path:
    fig, ax = canvas(plt, 11, 8.2, 100, 100)
    ax.text(50, 99, "Построение реферата в режиме OSTIS", ha="center", va="top", fontsize=12.5,
            fontweight="bold", color=INK)
    lanes = [(16, "Веб-интерфейс\n(service.py)", ACCENT, ACCENT_LINE),
             (50, "sc-сервер и база знаний\n(NIKA, sc-machine 0.8.0)", OSTIS, OSTIS_LINE),
             (84, "sc-агент построения реферата\n(agent.py, py-sc-kpm)", CORE, CORE_LINE)]
    for x, title, fill, edge in lanes:
        box(ax, x - 14, 87, 28, 7, title, fill=fill, edge=edge, bold=True, size=8.5)
        ax.plot([x, x], [4, 86.5], color=LINE, linewidth=1, linestyle=(0, (4, 3)))

    msgs = [
        (82, 16, 50, "1. есть ли реферат документа doc_X размера N?\n(search_template: nrel_summary, nrel_summary_size)"),
        (74, 16, 50, "2. нет — создать действие ∈ question, action_build_summary;\nrrel_1: doc_X; rrel_2: [N] (create_elements)"),
        (67, 16, 50, "3. question_initiated → действие"),
        (60, 50, 84, "4. событие add_outgoing_edge\n(класс действия проверяется)"),
        (52, 84, 50, "5. прочитать текст doc_X и его язык;\nтексты коллекции того же языка"),
        (33, 84, 50, "7. записать реферат (≈ 500 sc-элементов\nодним create_elements); nrel_answer"),
        (26, 84, 50, "8. question_finished_successfully,\nquestion_finished"),
        (19, 50, 16, "9. событие: действие завершено"),
        (11, 16, 50, "10. прочитать реферат: предложения,\nвеса, ключевые слова (search_template, content)"),
    ]
    for y, x1, x2, text in msgs:
        arrow(ax, (x1, y), (x2, y), text, color=INK if x2 != 16 else OSTIS_LINE, size=7.2,
              offset=(0, 0.6), dashed=x2 == 16)
    box(ax, 72, 39.5, 24, 8, "6. sentence extraction:\nizbornik.summary.build —\nте же формулы, что локально",
        fill=CORE, edge=CORE_LINE, size=7.6)
    box(ax, 2, 0.5, 28, 6.0, "если реферат размера N уже есть,\nшаги 2–9 пропускаются (≈ 65 мс)",
        size=7.4, fill="#fbf8f3")
    return save(fig, "ostis_flow.png")


# --- реферат в базе знаний -------------------------------------------------------------------

def draw_kb(plt) -> Path:
    from matplotlib.patches import Circle, FancyBboxPatch

    fig, ax = canvas(plt, 11.5, 8.4, 100, 100)
    ax.text(50, 99.5, "Реферат документа в базе знаний (обозначения, близкие к SCg)", ha="center", va="top",
            fontsize=12, fontweight="bold", color=INK)

    def node(x, y, label, *, cls=False, pos="below", color=INK):
        ax.add_patch(Circle((x, y), 1.3, facecolor="white" if not cls else "#fff1d6",
                            edgecolor=color, linewidth=1.6))
        if cls:
            ax.plot([x - 0.9, x + 0.9], [y, y], color=color, linewidth=1)
            ax.plot([x, x], [y - 0.9, y + 0.9], color=color, linewidth=1)
        dy = -2.4 if pos == "below" else 2.4
        ax.text(x, y + dy, label, ha="center", va="top" if pos == "below" else "bottom", fontsize=7.4,
                color=INK)

    def link(x, y, text, w=16):
        ax.add_patch(FancyBboxPatch((x - w / 2, y - 1.8), w, 3.6, boxstyle="round,pad=0.2,rounding_size=0.4",
                                    facecolor="#f8f8f8", edgecolor="#555", linewidth=1))
        ax.text(x, y, text, ha="center", va="center", fontsize=7, color=INK)

    def common(a, b, rel, rad=0.0, dx=0, dy=0.8):
        arrow(ax, a, b, rel, color="#333", width=2.2, size=6.9, offset=(dx, dy), rad=rad)

    def member(a, b, rel="", dx=0, dy=0.6, rad=0.0):
        arrow(ax, a, b, rel, color="#555", width=0.9, size=6.9, offset=(dx, dy), rad=rad)

    node(10, 86, "concept_test_\ncollection_document", cls=True, pos="above")
    node(30, 86, "concept_scientific_article_\non_computer_science", cls=True, pos="above")
    node(20, 70, "doc_ru_cs_ostis")
    member((10, 84.6), (19.2, 71.2))
    member((30, 84.6), (20.8, 71.2))
    link(10, 56, "[текст документа]", w=13)
    common((18.8, 69.2), (11, 58), "nrel_document_\ntext", dx=-5, dy=0)
    node(3, 48, "lang_ru", cls=True)
    member((3.5, 49.3), (6, 54.2))

    node(46, 70, "реферат", pos="above")
    common((21.4, 70), (44.6, 70), "nrel_summary", dy=0.6)
    node(60, 86, "concept_summary", cls=True, pos="above")
    member((59, 85), (47, 71))
    link(66, 72, "[10]", w=6)
    common((47.4, 70.4), (63, 71.6), "nrel_summary_size", dy=0.6)
    link(84, 72, "[0.245]", w=8)
    common((47.2, 71), (80, 73.3), "nrel_compression_ratio", rad=-0.25, dy=2.2)

    node(34, 50, "классический\nреферат")
    member((45.2, 68.9), (34.9, 51.2), "rrel_classic_summary", dx=-2, dy=0)
    node(62, 50, "реферат в виде\nключевых слов")
    member((46.8, 68.9), (61.1, 51.2), "rrel_keyword_summary", dx=3, dy=0)

    link(22, 34, "[Несмотря на достигнутые успехи …]", w=28)
    member((33.2, 48.8), (24, 36), "rrel_1", dx=-1.5, dy=0)
    link(51, 37, "[Унифицированную …]", w=20)
    member((35.1, 49), (47, 39), "rrel_2", dx=1.5, dy=0)
    link(8, 18, "[17]", w=6)
    common((16, 32.2), (9, 19.9), "nrel_sentence_\nnumber", dx=-4, dy=0)
    link(22, 14, "[44.42]", w=8)
    common((21, 32.2), (22, 15.9), "nrel_sentence_\nweight", dx=4.5, dy=0)
    link(36, 12, "[0.805]", w=8)
    common((26, 32.2), (35, 13.9), "nrel_position_\nin_document", dx=5.5, dy=1)

    node(80, 40, "term_ru_ontologiya\n«онтология»")
    member((63.1, 49.2), (78.9, 41.1), "rrel_1", dx=2, dy=0.4)
    link(92, 52, "[71.4]", w=7)
    arrow(ax, (72, 45.6), (88.5, 51), "nrel_term_\nsignificance", color="#333", width=2.2, size=6.9, offset=(-1, 0.2))
    node(82, 18, "term_ru_ontologiya_\npredmetnoy_oblasti")
    common((80.3, 38.6), (81.8, 19.4), "nrel_subordinate_\nkey_term", dx=6, dy=0)
    member((61.8, 48.7), (80.9, 19.3), "", rad=0.15)
    node(96, 30, "concept_key_\nterm", cls=True, pos="below")
    member((94.9, 31), (81.2, 39.1))

    ax.text(2, 3, "● — sc-узел;  ⊕ — класс;  прямоугольник — sc-ссылка;  тонкая стрелка — дуга принадлежности"
                  " (с ролью rrel_…);  толстая стрелка — дуга неролевого отношения nrel_…",
            fontsize=7.4, color=MUTED)
    return save(fig, "kb_summary.png")


def main() -> int:
    plt = _plt()
    for draw in (draw_structure, draw_algorithm, draw_ostis_flow, draw_kb):
        path = draw(plt)
        print(f"  {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
