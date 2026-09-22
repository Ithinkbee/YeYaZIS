"""Построение схем для отчёта: структура системы, схема БД, блок-схемы алгоритмов.

    python tools/make_diagrams.py

Сохраняет в report/: structure.png, database.png, algo_index.png, algo_search.png.
Схемы рисуются matplotlib'ом, чтобы отчёт собирался без внешних редакторов и
графики с ними были выдержаны в одном стиле.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

from arachne import config  # noqa: E402

plt.rcParams["font.family"] = ["DejaVu Sans"]

DARK = "#2f5540"
GREEN = "#3f6f4f"
MID = "#5b8c6a"
LIGHT = "#e8f0e9"
PALE = "#f4f8f4"
RUST = "#b4553f"
INK = "#1d2b22"


def _axes(width: float, height: float):
    figure, axes = plt.subplots(figsize=(width, height))
    axes.set_xlim(0, 100)
    axes.set_ylim(0, 100)
    axes.axis("off")
    return figure, axes


def _box(axes, x, y, w, h, text, *, face=LIGHT, edge=GREEN, size=8.5,
         weight="normal", color=INK, radius=1.2, lw=1.4):
    axes.add_patch(
        FancyBboxPatch(
            (x, y), w, h,
            boxstyle=f"round,pad=0,rounding_size={radius}",
            facecolor=face, edgecolor=edge, linewidth=lw,
        )
    )
    axes.text(x + w / 2, y + h / 2, text, ha="center", va="center",
              fontsize=size, weight=weight, color=color, linespacing=1.45)


def _arrow(axes, start, end, *, color=GREEN, style="-|>", lw=1.5, rad=0.0, dashed=False):
    axes.add_patch(
        FancyArrowPatch(
            start, end, arrowstyle=style, mutation_scale=11,
            color=color, linewidth=lw, shrinkA=0, shrinkB=0,
            linestyle="--" if dashed else "-",
            connectionstyle=f"arc3,rad={rad}",
        )
    )


def _label(axes, x, y, text, *, size=8, color="#5a6b5f", ha="center", style="italic"):
    axes.text(x, y, text, ha=ha, va="center", fontsize=size, color=color, style=style)


# --- Рисунок 1. Структурно-функциональная схема ------------------------------

def structure(path: Path) -> Path:
    figure, axes = plt.subplots(figsize=(11.2, 9.4))
    axes.set_xlim(0, 100)
    axes.set_ylim(0, 116)
    axes.axis("off")

    def band(top, height, title, title_x=3.4):
        axes.add_patch(
            FancyBboxPatch((1.5, top - height), 97, height,
                           boxstyle="round,pad=0,rounding_size=1",
                           facecolor=PALE, edgecolor="#c8d6cb", linewidth=1.0)
        )
        axes.text(title_x, top - 2.9, title, ha="left", va="center",
                  fontsize=8.6, weight="bold", color=DARK)

    def row(items, y, height, *, x0=4.0, x1=96.0, size=7.8, gap=1.8, **kw):
        width = (x1 - x0 - gap * (len(items) - 1)) / len(items)
        for index, text in enumerate(items):
            _box(axes, x0 + index * (width + gap), y, width, height, text,
                 face="#ffffff", size=size, **kw)

    def bar(text, y, height=4.6, size=7.6):
        _box(axes, 4.0, y, 92.0, height, text, face=LIGHT, size=size)

    band(115, 24, "УРОВЕНЬ ПРЕДСТАВЛЕНИЯ — веб-интерфейс (FastAPI + Jinja2)")
    row(["Поиск\n/, /search", "Документ\n/doc/{id}", "Индекс\n/admin",
         "Оценка качества\n/metrics", "Разметка\n/qrels"], 99.5, 9.5)
    bar("Справка /help  ·  автодополнение (AJAX)  ·  паук-компаньон и достижения", 92.5)

    band(89, 24, "УРОВЕНЬ ЭЛЕМЕНТОВ ИИ В ИНТЕРФЕЙСЕ (реализация элементов ИИ, вариант 3)")
    row(["Морфологический\nразбор запроса", "Автодополнение\nпо словарю",
         "Исправление опечаток\n(Дамерау — Левенштейн)", "Расширение\nсинонимами",
         "Обратная связь\n(Рокчио)"], 73.5, 9.5, size=7.4)
    bar("Объяснение выдачи «Почему найден»  ·  похожие документы  ·  подсказки при пустой "
        "выдаче  ·  языковой помощник (опц.)", 66.5)

    band(63, 29, "УРОВЕНЬ ЯДРА ИПС — три компонента поисковой системы")
    row(["АГЕНТ (ПАУК)\ncrawler.py\n\nобход каталогов\nи UNC-ресурсов ЛВС,\nинкрементальность",
         "ИЗВЛЕЧЕНИЕ ТЕКСТА\ntext/extract.py\n\ntxt, md, csv, html,\ndocx, pdf, rtf,\nподбор кодировки",
         "ИНДЕКСАТОР\nindexer.py\n\nПОД, формулы\n(1.5) и (1.6),\nнормы ‖D‖",
         "ПОИСКОВЫЙ МЕХАНИЗМ\nsearch.py\n\nПОЗ, косинусная\nмера, ранжирование,\nсниппеты"],
        42.0, 15.5, size=7.6, lw=1.7)
    for x in (26.6, 49.3, 72.0):
        _arrow(axes, (x - 1.1, 49.7), (x + 1.1, 49.7))
    bar("МОРФОЛОГИЯ РУССКОГО ЯЗЫКА  ·  text/morphology.py  ·  токенизация → отсев стоп-слов → "
        "лемматизация (pymorphy3)", 36.0, height=4.4)

    band(32, 17, "УРОВЕНЬ ДАННЫХ")
    _box(axes, 22.0, 21.0, 36.0, 7.0,
         "БАЗА ДАННЫХ SQLite  ·  db.py\ndocuments · terms · postings · forms · sources",
         face="#ffffff", size=7.6, lw=1.7)
    _box(axes, 60.0, 21.0, 36.0, 7.0,
         "ОЦЕНКА КАЧЕСТВА  ·  evaluation/\neval_queries · qrels · metrics.py · plots.py",
         face="#ffffff", size=7.6, lw=1.7)
    _box(axes, 22.0, 16.4, 74.0, 3.6,
         "query_log · feedback (отметки Рокчио) · crawl_log · settings · achievements",
         face=LIGHT, size=7.4)

    band(13, 13, "ИСТОЧНИКИ — локальная вычислительная сеть", title_x=22.0)
    row(["NODE-A\n36 документов", "NODE-B\n36 документов", "NODE-C\n36 документов"],
        1.8, 6.6, x0=22.0, x1=96.0, size=7.8, edge=MID)
    _label(axes, 12.0, 5.1, "каталоги\nи UNC-ресурсы", size=7)

    # межуровневые связи
    _arrow(axes, (13.0, 8.4), (13.0, 42.0), color=MID, lw=1.6)
    _label(axes, 15.0, 25.0, "обход ЛВС", size=7, ha="left")

    _arrow(axes, (18.0, 42.0), (18.0, 28.0), style="<|-|>", color=MID)
    _arrow(axes, (84.0, 42.0), (84.0, 28.0), style="<|-|>", color=MID)
    _label(axes, 85.6, 35.0, "ПОД, веса A$_{ij}$", size=7, ha="left")

    _arrow(axes, (88.0, 57.5), (88.0, 73.5), style="<|-|>", color=MID)
    _label(axes, 89.6, 65.5, "выдача", size=7, ha="left")
    _arrow(axes, (88.0, 83.0), (88.0, 99.5), style="<|-|>", color=MID)
    _label(axes, 89.6, 91.0, "ЕЯ-запрос", size=7, ha="left")

    # раздел «Оценка качества» обращается к модулю evaluation — по правому полю,
    # чтобы линия не пересекала блоки промежуточных уровней
    axes.plot([96.0, 97.7, 97.7, 68.7, 68.7], [24.5, 24.5, 110.5, 110.5, 109.8],
              color=MID, linewidth=1.3, linestyle="--", zorder=1)
    _arrow(axes, (68.7, 110.0), (68.7, 109.0), color=MID, lw=1.3)
    _arrow(axes, (97.0, 24.5), (96.0, 24.5), color=MID, lw=1.3)
    axes.text(96.6, 66.0, "метрики и графики", rotation=90, ha="center", va="center",
              fontsize=7, color="#5a6b5f", style="italic")

    figure.tight_layout()
    figure.savefig(path, dpi=140, facecolor="white")
    plt.close(figure)
    return path


# --- Рисунок 2. Схема базы данных --------------------------------------------

HEAD_H = 4.0
ROW_H = 3.0
GAP = 4.0

#: колонки схемы: (x, ширина, [(имя таблицы, [поля])])
COLUMNS = [
    (4.0, 28.0, [
        ("terms", ["id     INTEGER PK", "lemma  TEXT UNIQUE", "df     INTEGER   P_i"]),
        ("postings", ["term_id  INTEGER FK", "doc_id   INTEGER FK",
                      "tf       INTEGER  Q_ij", "weight   REAL     A_ij"]),
        ("forms", ["form     TEXT PK", "term_id  INTEGER FK", "freq     INTEGER"]),
        ("sources", ["id          INTEGER PK", "root_path   TEXT UNIQUE",
                     "kind        TEXT local|unc", "label       TEXT",
                     "enabled     INTEGER", "last_crawl  TEXT"]),
    ]),
    (36.0, 28.0, [
        ("documents", ["id            INTEGER PK", "path          TEXT UNIQUE",
                       "uri, host     TEXT", "title, text   TEXT", "ext           TEXT",
                       "size_bytes    INTEGER", "mtime         REAL",
                       "date_added    TEXT", "time_added    TEXT",
                       "content_hash  TEXT", "term_count    INTEGER",
                       "vector_norm   REAL   ‖D‖"]),
        ("crawl_log", ["id            INTEGER PK", "started_at    TEXT",
                       "finished_at   TEXT", "added/updated INTEGER",
                       "skipped/removed  INT", "errors, details"]),
    ]),
    (70.0, 28.0, [
        ("eval_queries", ["id    INTEGER PK", "text  TEXT UNIQUE", "note  TEXT"]),
        ("qrels", ["query_id  INTEGER FK", "doc_id    INTEGER FK",
                   "rel       INTEGER 0|1|2"]),
        ("feedback", ["id      INTEGER PK", "query   TEXT", "doc_id  INTEGER FK",
                      "mark    INTEGER +1|−1", "ts      TEXT"]),
        ("query_log", ["id             INTEGER PK", "raw_query      TEXT",
                       "normalized     TEXT", "ts             TEXT",
                       "results_count  INTEGER", "took_ms        REAL"]),
    ]),
]

SMALL = [("settings", ["key    TEXT PK", "value  TEXT"]),
         ("achievements", ["code         TEXT PK", "unlocked_at  TEXT"])]


def _table(axes, x, y, w, name, fields):
    """Рисует таблицу вверх от y (y — нижняя граница). Возвращает высоту."""
    height = HEAD_H + ROW_H * len(fields)
    top = y + height
    axes.add_patch(
        FancyBboxPatch((x, y), w, height, boxstyle="round,pad=0,rounding_size=0.7",
                       facecolor="#ffffff", edgecolor=GREEN, linewidth=1.4)
    )
    axes.add_patch(
        FancyBboxPatch((x, top - HEAD_H), w, HEAD_H,
                       boxstyle="round,pad=0,rounding_size=0.7",
                       facecolor=GREEN, edgecolor=GREEN, linewidth=1.4)
    )
    axes.text(x + w / 2, top - HEAD_H / 2, name, ha="center", va="center",
              fontsize=8.4, weight="bold", color="white")
    for index, field in enumerate(fields):
        axes.text(x + 1.2, top - HEAD_H - ROW_H * (index + 0.5), field,
                  ha="left", va="center", fontsize=6.9, color=INK,
                  family="DejaVu Sans Mono")
    return height


def database(path: Path) -> Path:
    figure, axes = plt.subplots(figsize=(11.6, 9.0))
    axes.set_xlim(0, 100)
    axes.set_ylim(0, 106)
    axes.axis("off")

    top_y = 96.0
    place: dict[str, tuple[float, float, float, float]] = {}
    for x, width, tables in COLUMNS:
        cursor = top_y
        for name, fields in tables:
            height = HEAD_H + ROW_H * len(fields)
            _table(axes, x, cursor - height, width, name, fields)
            place[name] = (x, cursor - height, width, height)
            cursor -= height + GAP

    # служебные таблицы — двумя половинами под documents
    for index, (name, fields) in enumerate(SMALL):
        half = (28.0 - 2.0) / 2
        x = 36.0 + index * (half + 2.0)
        height = HEAD_H + ROW_H * len(fields)
        _table(axes, x, 16.0, half, name, fields)
        place[name] = (x, 16.0, half, height)

    for x, _, caption in ((4.0, 0, "ИНВЕРТИРОВАННЫЙ ИНДЕКС\nИ ИСТОЧНИКИ ЛВС"),
                          (36.0, 0, "ДОКУМЕНТЫ И ЖУРНАЛ ОБХОДА"),
                          (70.0, 0, "ОЦЕНКА КАЧЕСТВА,\nОБРАТНАЯ СВЯЗЬ, ЖУРНАЛЫ")):
        axes.text(x + 14, 101.5, caption, ha="center", va="center", fontsize=8,
                  weight="bold", color=DARK, linespacing=1.4)

    def fk(src, dst, *, label, dy_src=0.5, dy_dst=0.5):
        """Горизонтальная связь между соседними колонками."""
        sx, sy, sw, sh = place[src]
        dx, dy, dw, dh = place[dst]
        if dx > sx:
            start, end = (sx + sw, sy + sh * dy_src), (dx, dy + dh * dy_dst)
        else:
            start, end = (sx, sy + sh * dy_src), (dx + dw, dy + dh * dy_dst)
        _arrow(axes, start, end, color=RUST, lw=1.3)
        axes.text((start[0] + end[0]) / 2, max(start[1], end[1]) + 1.5, label,
                  ha="center", va="center", fontsize=6.6, color=RUST, style="italic")

    def fk_up(src, dst, *, label, at=0.28):
        """Вертикальная связь внутри колонки (таблицы стоят одна над другой)."""
        sx, sy, sw, sh = place[src]
        dx, dy, dw, dh = place[dst]
        x = sx + sw * at
        _arrow(axes, (x, sy + sh), (x, dy), color=RUST, lw=1.3)
        axes.text(x + 0.8, (sy + sh + dy) / 2, label, ha="left", va="center",
                  fontsize=6.6, color=RUST, style="italic")

    fk_up("postings", "terms", label="term_id → terms.id")
    fk("postings", "documents", label="doc_id", dy_src=0.45, dy_dst=0.38)
    fk_up("qrels", "eval_queries", label="query_id → eval_queries.id", at=0.3)
    fk("qrels", "documents", label="doc_id", dy_src=0.5, dy_dst=0.72)
    fk("feedback", "documents", label="doc_id", dy_src=0.62, dy_dst=0.08)

    # forms → terms: обходим postings по левому полю
    fx, fy, fw, fh = place["forms"]
    tx, ty, tw, th = place["terms"]
    axes.plot([fx, 1.6, 1.6, tx], [fy + fh * 0.5, fy + fh * 0.5, ty + th * 0.35, ty + th * 0.35],
              color=RUST, linewidth=1.3, zorder=1)
    _arrow(axes, (2.6, ty + th * 0.35), (tx, ty + th * 0.35), color=RUST, lw=1.3)
    axes.text(2.4, (fy + fh * 0.5 + ty + th * 0.35) / 2, "term_id", rotation=90,
              ha="center", va="center", fontsize=6.6, color=RUST, style="italic")

    _label(axes, 50, 9.5,
           "Стрелки — внешние ключи (ON DELETE CASCADE).  "
           "P$_i$ = terms.df,  Q$_{ij}$ = postings.tf,  A$_{ij}$ = postings.weight = Q$_{ij}$ · B$_i$,  "
           "B$_i$ = log(N / P$_i$),  ‖D‖ = documents.vector_norm", size=7.4)

    figure.tight_layout()
    figure.savefig(path, dpi=140, facecolor="white")
    plt.close(figure)
    return path


# --- Блок-схемы алгоритмов ---------------------------------------------------

def _flow(path: Path, title: str, steps: list[tuple]) -> Path:
    """Строит вертикальную блок-схему.

    Шаг задаётся кортежем (тип, текст) либо (тип, текст, метка ветви «вниз»,
    метка обходной ветви). Тип: 'io' — ввод-вывод, 'proc' — обработка,
    'dec' — условие, 'term' — начало/конец. Для условия рисуется обходная
    ветвь, пропускающая следующий блок.
    """
    total = len(steps)
    figure, axes = plt.subplots(figsize=(7.8, 0.78 * total + 0.9))
    axes.set_xlim(0, 100)
    axes.set_ylim(0, 100)
    axes.axis("off")

    axes.text(50, 97.5, title, ha="center", va="center", fontsize=9.5,
              weight="bold", color=DARK)

    faces = {"io": "#ffffff", "proc": LIGHT, "dec": "#fdf0ec", "term": GREEN}
    top, bottom = 94.0, 1.0
    height = (top - bottom) / total
    box_h = height * 0.66
    geometry = []

    for index, step in enumerate(steps):
        kind, text = step[0], step[1]
        y = top - height * (index + 1) + (height - box_h) / 2
        width = 62 if kind == "dec" else 74
        x = 50 - width / 2
        _box(axes, x, y, width, box_h, text,
             face=faces[kind],
             edge=RUST if kind == "dec" else GREEN,
             color="white" if kind == "term" else INK,
             weight="bold" if kind == "term" else "normal",
             size=8.0, radius=box_h / 2 if kind == "term" else 1.0,
             lw=1.5)
        geometry.append((x, y, width, box_h))

    for index in range(total - 1):
        _, y, _, _ = geometry[index]
        _arrow(axes, (50, y), (50, y - (height - box_h)))
        step = steps[index]
        if len(step) > 2 and step[2]:
            axes.text(51.4, y - (height - box_h) / 2, step[2], ha="left", va="center",
                      fontsize=7.2, color=RUST, style="italic")

    # обходные ветви условий: пропускают следующий блок
    for index, step in enumerate(steps):
        if step[0] != "dec" or index + 2 >= total or len(step) < 4 or not step[3]:
            continue
        dx, dy, dw, dh = geometry[index]
        tx, ty, tw, th = geometry[index + 2]
        y_from, y_to = dy + dh / 2, ty + th / 2
        axes.plot([dx + dw, 93.0, 93.0, tx + tw], [y_from, y_from, y_to, y_to],
                  color=RUST, linewidth=1.3, zorder=1)
        _arrow(axes, (tx + tw + 1.0, y_to), (tx + tw, y_to), color=RUST, lw=1.3)
        axes.text(92.0, (y_from + y_to) / 2, step[3], rotation=90, ha="center",
                  va="center", fontsize=7.2, color=RUST, style="italic")

    figure.tight_layout()
    figure.savefig(path, dpi=140, facecolor="white")
    plt.close(figure)
    return path


def algo_index(path: Path) -> Path:
    return _flow(
        path,
        "Алгоритм построения индекса (поисковых образов документов)",
        [
            ("term", "Начало: build_index()"),
            ("io", "Чтение текстов всех N документов из таблицы documents"),
            ("proc", "Для каждого документа: токенизация → отсев стоп-слов →\n"
                     "лемматизация (pymorphy3) → частоты терминов Q$_{ij}$"),
            ("proc", "Подсчёт числа документов с термином:  P$_i$ = terms.df"),
            ("io", "Очистка и запись словаря системы в таблицу terms"),
            ("proc", "Инверсная частота термина:  B$_i$ = log(N / P$_i$)          (1.5)"),
            ("proc", "Вес термина в документе:  A$_{ij}$ = Q$_{ij}$ · B$_i$              (1.6)"),
            ("proc", "Евклидова норма вектора документа:  ‖D‖ = √( Σ A$_{ij}$² )"),
            ("io", "Запись postings (term_id, doc_id, tf, weight)\nи documents.vector_norm"),
            ("io", "Запись словоформ в forms — для автодополнения\nи исправления опечаток"),
            ("term", "Конец: индекс построен"),
        ],
    )


def algo_search(path: Path) -> Path:
    return _flow(
        path,
        "Алгоритм поиска по векторной модели (стратегия варианта 3)",
        [
            ("term", "Начало: естественно-языковой запрос пользователя"),
            ("proc", "Токенизация, отсев стоп-слов, лемматизация запроса"),
            ("dec", "Все слова запроса есть в словаре системы?", "нет", "да"),
            ("proc", "Исправление опечатки (Дамерау — Левенштейн),\n"
                     "расширение синонимами из тезауруса (вес 0,5)"),
            ("proc", "Построение ПОЗ:  w$_{qj}$ = 1 для слов запроса,\n"
                     "0,5 для терминов, добавленных системой"),
            ("dec", "Есть отметки обратной связи по этому запросу?", "да", "нет"),
            ("proc", "Пересчёт вектора запроса методом Рокчио"),
            ("io", "Выборка из postings документов, содержащих термины ПОЗ"),
            ("proc", "Скалярное произведение  (D, Q) = Σ A$_{ij}$ · w$_{qj}$"),
            ("proc", "Фильтры: «все слова обязательны», диапазон дат"),
            ("proc", "Ранг документа:  sim(D, Q) = (D, Q) / ( ‖D‖ · ‖Q‖ )"),
            ("proc", "Сортировка по убыванию ранга, сниппеты и подсветка"),
            ("term", "Выдача: ссылка, ранг, слова запроса, объяснение"),
        ],
    )


def main() -> None:
    config.ensure_dirs()
    produced = [
        structure(config.REPORT_DIR / "structure.png"),
        database(config.REPORT_DIR / "database.png"),
        algo_index(config.REPORT_DIR / "algo_index.png"),
        algo_search(config.REPORT_DIR / "algo_search.png"),
    ]
    print("Схемы сохранены:")
    for item in produced:
        print(f"  {item}")


if __name__ == "__main__":
    main()
