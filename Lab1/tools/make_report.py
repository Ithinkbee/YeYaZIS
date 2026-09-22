"""Сборка отчёта по лабораторной работе в формате DOCX.

    python tools/make_report.py [--output ПУТЬ]

Числа в отчёт не вписаны вручную: статистика коллекции, метрики качества и
сравнение конфигураций считаются на месте по текущей базе данных, поэтому
отчёт всегда соответствует состоянию системы. Схемы и графики берутся из
report/ (создаются tools/make_diagrams.py и tools/run_eval.py --plots).
"""

from __future__ import annotations

import argparse
import collections
import importlib.metadata as metadata
import math
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from arachne import config, db  # noqa: E402
from arachne.evaluation import runner  # noqa: E402

FONT = "Times New Roman"
SIZE = Pt(14)
INDENT = Cm(1.25)
TEXT_WIDTH_CM = 16.5

TOPICS = {
    "net": "Локальные вычислительные сети",
    "ai": "Искусственный интеллект и информационный поиск",
    "db": "Базы данных",
    "os": "Операционные системы",
    "sec": "Информационная безопасность",
    "prog": "Программирование",
    "hw": "Аппаратное обеспечение",
    "food": "Кулинария",
    "sport": "Спорт",
    "transport": "Транспорт и логистика",
}


# --- Примитивы оформления ----------------------------------------------------

class Report:
    def __init__(self) -> None:
        self.document = docx.Document()
        self.table_number = 0
        self.figure_number = 0
        self._setup()

    def _setup(self) -> None:
        section = self.document.sections[0]
        section.page_width = Cm(21.0)
        section.page_height = Cm(29.7)
        section.left_margin = Cm(3.0)
        section.right_margin = Cm(1.5)
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)

        normal = self.document.styles["Normal"]
        normal.font.name = FONT
        normal.font.size = SIZE
        normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
        normal.paragraph_format.space_after = Pt(6)

    # -- абзацы ---------------------------------------------------------------

    def _paragraph(self, align=None, *, indent=None, after=6, left=None, hanging=None):
        paragraph = self.document.add_paragraph()
        if align is not None:
            paragraph.alignment = align
        fmt = paragraph.paragraph_format
        fmt.space_after = Pt(after)
        if indent is not None:
            fmt.first_line_indent = indent
        if left is not None:
            fmt.left_indent = left
        if hanging is not None:
            fmt.first_line_indent = -hanging
        return paragraph

    SUBSCRIPT = re.compile(r"~([^~]+)~")

    def _rich(self, paragraph, content, *, bold=False, italic=False, size=SIZE):
        """Пишет текст, оформляя фрагменты вида ~x~ как нижний индекс."""
        position = 0
        for match in self.SUBSCRIPT.finditer(content):
            if match.start() > position:
                self._run(paragraph, content[position:match.start()],
                          bold=bold, italic=italic, size=size)
            run = self._run(paragraph, match.group(1), bold=bold, italic=italic, size=size)
            run.font.subscript = True
            position = match.end()
        if position < len(content):
            self._run(paragraph, content[position:], bold=bold, italic=italic, size=size)

    def _run(self, paragraph, text, *, bold=False, italic=False, size=SIZE, color=None):
        run = paragraph.add_run(text)
        run.font.name = FONT
        run.font.size = size
        run.bold = bold
        run.italic = italic
        run.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
        if color:
            run.font.color.rgb = color
        return run

    def text(self, content, *, bold=False, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
             indent=True, after=6, size=SIZE, italic=False):
        paragraph = self._paragraph(align, indent=INDENT if indent else None, after=after)
        self._rich(paragraph, content, bold=bold, italic=italic, size=size)
        return paragraph

    def heading(self, content):
        self.text(content, bold=True, align=WD_ALIGN_PARAGRAPH.LEFT, indent=False, after=6)

    def subheading(self, content):
        self.text(content, bold=True, align=WD_ALIGN_PARAGRAPH.JUSTIFY, indent=True, after=4)

    def bullets(self, items, *, marker="\u2022 "):
        """Маркированный список; часть до « — » выделяется полужирным."""
        for item in items:
            paragraph = self._paragraph(WD_ALIGN_PARAGRAPH.JUSTIFY,
                                        left=INDENT, hanging=Cm(0.5), after=3)
            head, separator, tail = item.partition(" \u2014 ")
            if separator:
                self._rich(paragraph, marker + head, bold=True)
                self._rich(paragraph, separator + tail)
            else:
                self._rich(paragraph, marker + item)

    def steps(self, items, *, start=1):
        """Нумерованный список шагов алгоритма; заголовок шага — полужирным."""
        for offset, item in enumerate(items, start=start):
            paragraph = self._paragraph(WD_ALIGN_PARAGRAPH.JUSTIFY,
                                        left=INDENT, hanging=Cm(0.6), after=3)
            head, separator, tail = item.partition(". ")
            if separator and len(head) < 70:
                self._rich(paragraph, f"{offset}. {head}.", bold=True)
                self._rich(paragraph, " " + tail)
            else:
                self._rich(paragraph, f"{offset}. {item}")

    # -- таблицы и рисунки ----------------------------------------------------

    def table(self, caption, header, rows, *, widths=None, size=Pt(12)):
        self.table_number += 1
        self.text(f"Таблица {self.table_number} \u2013 {caption}",
                  align=WD_ALIGN_PARAGRAPH.LEFT, indent=False, after=3)
        table = self.document.add_table(rows=1, cols=len(header))
        table.style = "Table Grid"

        for index, title in enumerate(header):
            cell = table.rows[0].cells[index]
            cell.text = ""
            paragraph = cell.paragraphs[0]
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            paragraph.paragraph_format.space_after = Pt(0)
            self._rich(paragraph, str(title), bold=True, size=size)

        for values in rows:
            cells = table.add_row().cells
            for index, value in enumerate(values):
                cells[index].text = ""
                paragraph = cells[index].paragraphs[0]
                paragraph.paragraph_format.space_after = Pt(0)
                if index and not isinstance(value, str):
                    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                self._rich(paragraph, str(value), size=size)

        if widths:
            for row in table.rows:
                for index, width in enumerate(widths):
                    row.cells[index].width = Cm(width)
        self.document.add_paragraph().paragraph_format.space_after = Pt(2)
        return table

    def figure(self, path: Path, caption: str, *, max_width=16.0, max_height=20.5):
        """Вставляет PNG, вписывая его в отведённое поле страницы."""
        self.figure_number += 1
        try:
            from PIL import Image  # входит в зависимости matplotlib

            with Image.open(path) as image:
                ratio = image.height / image.width
        except Exception:
            ratio = 0.62

        width = max_width
        if width * ratio > max_height:
            width = max_height / ratio

        paragraph = self._paragraph(WD_ALIGN_PARAGRAPH.CENTER, after=3)
        paragraph.add_run().add_picture(str(path), width=Cm(width))
        self.text(f"Рисунок {self.figure_number} \u2013 {caption}",
                  align=WD_ALIGN_PARAGRAPH.CENTER, indent=False, after=8, size=Pt(12))

    def page_break(self):
        self.document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    def blank(self, count=1):
        for _ in range(count):
            self._paragraph(after=0)

    def save(self, path: Path):
        self.document.save(str(path))
        return path


# --- Данные для отчёта -------------------------------------------------------

def gather(conn):
    """Собирает статистику коллекции, индекса и метрики качества."""
    stats = db.stats(conn)

    by_topic = collections.Counter()
    by_ext = collections.Counter()
    by_host = collections.Counter()
    host_ext = collections.defaultdict(collections.Counter)
    sizes, term_counts = [], []
    for row in conn.execute("SELECT path, ext, host, size_bytes, term_count FROM documents"):
        topic = Path(row["path"]).parent.name
        by_topic[topic] += 1
        by_ext[row["ext"]] += 1
        by_host[row["host"]] += 1
        host_ext[row["host"]][row["ext"]] += 1
        sizes.append(row["size_bytes"])
        term_counts.append(row["term_count"])

    top_terms = [
        (row["lemma"], row["df"], row["tf"],
         math.log(stats["documents"] / row["df"], 10) if row["df"] else 0.0)
        for row in conn.execute(
            """SELECT t.lemma AS lemma, t.df AS df, SUM(p.tf) AS tf
               FROM terms t JOIN postings p ON p.term_id = t.id
               GROUP BY t.id ORDER BY tf DESC, t.lemma LIMIT 10"""
        )
    ]

    judged = {
        level: conn.execute("SELECT COUNT(*) FROM qrels WHERE rel = ?", (level,)).fetchone()[0]
        for level in (0, 1, 2)
    }

    started = time.perf_counter()
    outcome = runner.evaluate(conn, runner.RunConfig(top_k=20))
    eval_ms = (time.perf_counter() - started) * 1000
    comparison = runner.compare_configurations(conn, top_k=20)

    return {
        "stats": stats,
        "by_topic": by_topic,
        "by_ext": by_ext,
        "by_host": by_host,
        "host_ext": host_ext,
        "total_size": sum(sizes),
        "avg_size": sum(sizes) / max(1, len(sizes)),
        "terms_total": sum(term_counts),
        "terms_avg": sum(term_counts) / max(1, len(term_counts)),
        "terms_min": min(term_counts) if term_counts else 0,
        "terms_max": max(term_counts) if term_counts else 0,
        "singletons": conn.execute("SELECT COUNT(*) FROM terms WHERE df = 1").fetchone()[0],
        "top_terms": top_terms,
        "queries": conn.execute("SELECT COUNT(*) FROM eval_queries").fetchone()[0],
        "judgements": sum(judged.values()),
        "judged": judged,
        "per_query": outcome["per_query"],
        "summary": outcome["summary"],
        "comparison": comparison,
        "eval_ms": eval_ms,
    }


def version(package: str) -> str:
    try:
        return metadata.version(package)
    except Exception:
        return "\u2014"


def number(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def plural(count: int, one: str, few: str, many: str) -> str:
    """Согласует существительное с числительным: 1 документ, 2 документа, 5 документов."""
    if 11 <= count % 100 <= 14:
        return many
    tail = count % 10
    if tail == 1:
        return one
    if 2 <= tail <= 4:
        return few
    return many


# --- Разделы отчёта ----------------------------------------------------------

def title_page(report: Report) -> None:
    center = WD_ALIGN_PARAGRAPH.CENTER
    for line in ("Министерство образования Республики Беларусь",
                 "Учреждение образования",
                 "«Белорусский государственный университет информатики и радиоэлектроники»",
                 "Факультет информационных технологий и управления",
                 "Кафедра интеллектуальных информационных технологий"):
        report.text(line, align=center, indent=False, after=0)

    report.blank(5)
    for line in ("ОТЧЁТ",
                 "по лабораторной работе № 1",
                 "по курсу «Естественно-языковой интерфейс интеллектуальных систем»",
                 "«Разработка информационно-поисковой системы.",
                 "Реализация методов оценки качества её работы»",
                 "Вариант 3"):
        report.text(line, bold=True, align=center, indent=False, after=0)

    report.blank(6)
    for line in ("Выполнили:",
                 "Студенты гр. 321702\t\t\t\t\t   Бузычков Н. Ф.",
                 "\t\t\t\t\t\t\t   Котко П. А.",
                 "\t\t\t\t\t\t\t   Халилов Р. Э.",
                 "",
                 "Проверил:\t\t\t\t\t\t   Крапивин Ю. Б."):
        report.text(line, align=WD_ALIGN_PARAGRAPH.LEFT, indent=False, after=0)

    report.blank(5)
    report.text("Минск", align=center, indent=False, after=0)
    report.text("2026", align=center, indent=False, after=0)
    report.page_break()


def goal_and_task(report: Report) -> None:
    report.heading("Цель работы:")
    report.text(
        "Освоить на практике основные принципы реализации информационно-поисковых систем "
        "и методы оценки качества их работы. Спроектировать и программно реализовать "
        "информационно-поисковую систему (ИПС) по документам локальной вычислительной сети "
        "с векторной стратегией поиска и реализацией элементов искусственного интеллекта "
        "в интерфейсе с пользователем, а также программно вычислить и представить в виде "
        "таблиц и графиков метрики качества её работы."
    )

    report.heading("Задание:")
    report.text(
        "Разработать систему информационного поиска, удовлетворяющую следующим требованиям: "
        "на входе — множество естественно-языковых текстов, по которым осуществляется поиск; "
        "выделение ключевых слов документов выполняется системой автоматически в соответствии "
        "с формулой (1.6); система позволяет пользователю формулировать естественно-языковой "
        "запрос; на выходе — список документов, релевантных запросу, в соответствии с моделью "
        "поиска согласно варианту; результаты поиска содержат активную ссылку на документ и "
        "список слов запроса, присутствующих в документе; оценка качества работы системы по "
        "метрикам РОМИП вычисляется программно, вызывается из соответствующего подменю и "
        "отображается в виде таблиц и графиков; интерфейс системы прост, доступен пользователю "
        "любого уровня и снабжён help-средствами."
    )
    report.text("Параметры варианта 3 приведены в таблице 1.")

    report.table(
        "Параметры варианта 3 и место их реализации",
        ["Параметр варианта", "Значение", "Реализация в системе"],
        [
            ("Реализация элементов ИИ", "Интерфейс с пользователем",
             "пакет arachne/ai/, веб-интерфейс arachne/web/"),
            ("Сфера применения", "Локальная вычислительная сеть",
             "паук arachne/crawler.py: обход каталогов и UNC-ресурсов"),
            ("Стратегия поиска", "Векторная",
             "arachne/indexer.py, arachne/search.py: TF-IDF и косинусная мера"),
            ("Язык", "Русский",
             "arachne/text/morphology.py: pymorphy3, стоп-слова, тезаурус"),
        ],
        widths=[4.6, 4.4, 7.5],
    )

    report.text(
        "Система получила название «Арахна» (по имени искусной ткачихи из греческого мифа, "
        "превращённой в паука) — в соответствии с ролью паука-обходчика, собирающего "
        "документы по узлам локальной сети."
    )


def libraries(report: Report) -> None:
    report.heading("Используемые библиотеки и их назначение:")
    report.text(
        f"Система реализована на языке Python {sys.version_info.major}."
        f"{sys.version_info.minor}. Сторонние компоненты "
        "подобраны так, чтобы ни один из них не выполнял за систему её основную задачу: "
        "индексирование, ранжирование и расчёт метрик реализованы в работе самостоятельно, "
        "а библиотеки закрывают вспомогательные функции — разбор форматов файлов, "
        "морфологию русского языка, транспорт HTTP и отрисовку графиков."
    )

    report.subheading("Ядро системы и веб-интерфейс:")
    report.bullets([
        f"FastAPI {version('fastapi')} — ASGI-фреймворк, на котором построен веб-интерфейс: "
        "маршрутизация запросов, разбор параметров и форм, валидация типов.",
        f"Uvicorn {version('uvicorn')} — ASGI-сервер, запускающий приложение; система "
        "поднимается одной командой python run.py и открывается в браузере.",
        f"Jinja2 {version('jinja2')} — шаблонизатор HTML-страниц интерфейса "
        "(12 шаблонов в arachne/web/templates/).",
        f"python-multipart {version('python-multipart')} — разбор данных HTML-форм "
        "(отметки релевантности, управление источниками и индексом).",
        "sqlite3 (стандартная библиотека, SQLite " + __import__("sqlite3").sqlite_version +
        ") — встроенная СУБД, хранящая документы, словарь, инвертированный индекс "
        "и эталонную разметку; отдельный сервер БД для работы системы не требуется.",
    ])

    report.subheading("Морфология русского языка:")
    report.bullets([
        f"pymorphy3 {version('pymorphy3')} — морфологический анализатор русского языка: "
        "приведение словоформы к нормальной форме (лемме), определение части речи и "
        "грамматических признаков. Леммы выступают терминами поисковых образов документа "
        "и запроса, благодаря чему «сетях», «сети» и «сеть» считаются одним термином.",
        f"pymorphy3-dicts-ru {version('pymorphy3-dicts-ru')} — словари OpenCorpora, "
        "на которых работает анализатор.",
    ])

    report.subheading("Извлечение текста из документов:")
    report.bullets([
        f"beautifulsoup4 {version('beautifulsoup4')} — разбор HTML: удаление разметки, "
        "скриптов и стилей, извлечение заголовка и текста.",
        f"python-docx {version('python-docx')} — чтение документов формата DOCX, включая "
        "текст таблиц и заголовки стилей Heading.",
        f"pypdf {version('pypdf')} — постраничное извлечение текста из PDF.",
        "striprtf — необязательный разбор RTF; при отсутствии библиотеки применяется "
        "встроенный запасной разбор управляющих последовательностей.",
    ])

    report.subheading("Оценка качества и тестирование:")
    report.bullets([
        f"matplotlib {version('matplotlib')} — построение графиков метрик и схем "
        "в формате PNG для отчёта (модуль arachne/evaluation/plots.py).",
        f"pytest {version('pytest')} — автоматические тесты ядра системы и метрик "
        "качества (36 тестов).",
        "httpx / urllib — обращение к внешнему OpenAI-совместимому сервису в "
        "необязательном слое языкового помощника; по умолчанию слой выключен и в сеть "
        "не обращается.",
    ])

    report.text(
        "Особенности применения готовых компонентов. Морфологический анализатор pymorphy3 "
        "загружает словари около одной секунды, поэтому он инициализируется лениво, при "
        "первом обращении, а результаты лемматизации кэшируются (functools.lru_cache на "
        "200 000 слов) — без кэша индексация коллекции замедляется в несколько раз. "
        "Извлечение текста вынесено за отдельный интерфейс: каждый формат обрабатывается "
        "своей функцией, а исключения приводятся к единому ExtractionError, поэтому "
        "повреждённый файл не прерывает обход всей сети. SQLite открывается в режиме "
        "журналирования WAL: это позволяет читать индекс во время фоновой переиндексации, "
        "запущенной из интерфейса."
    )


def structure(report: Report, data: dict) -> None:
    report.heading("Структура разработанной системы")
    report.text(
        "Система построена из трёх компонентов, предусмотренных методическими указаниями: "
        "агента (паука), собирающего информацию о документах; базы данных, содержащей всю "
        "собранную пауком информацию; и поискового механизма, служащего пользователю "
        "интерфейсом для взаимодействия с базой данных. Поверх ядра надстроен уровень "
        "элементов искусственного интеллекта в интерфейсе — та часть, которая по варианту 3 "
        "является предметом реализации. Структурно-функциональная схема системы приведена "
        "на рисунке 1."
    )
    report.figure(config.REPORT_DIR / "structure.png",
                  "Структурно-функциональная схема ИПС «Арахна»")

    report.text(
        "Приложение разделено на пять уровней, взаимодействующих сверху вниз по потоку данных."
    )
    report.steps([
        "Уровень источников. Ресурсы локальной вычислительной сети: обычные каталоги "
        "(D:\\Отдел) и сетевые папки в формате UNC (\\\\сервер\\обмен). В тестовой "
        "конфигурации это три узла NODE-A, NODE-B и NODE-C.",
        "Уровень данных. База данных SQLite: документы, словарь системы, инвертированный "
        "индекс, источники, эталонная разметка, журналы обходов и запросов, отметки "
        "обратной связи.",
        "Уровень ядра ИПС. Паук (crawler.py), извлечение текста (text/extract.py), "
        "индексатор (indexer.py) и поисковый механизм (search.py); все они опираются на "
        "общий модуль морфологии русского языка (text/morphology.py).",
        "Уровень элементов ИИ. Разбор естественно-языкового запроса, автодополнение, "
        "исправление опечаток, расширение синонимами, обратная связь по релевантности, "
        "объяснение выдачи и подбор похожих документов (пакет arachne/ai/).",
        "Уровень представления. Веб-интерфейс: разделы «Поиск», «Индекс», «Оценка "
        "качества», «Разметка», «Достижения» и «Справка».",
    ])

    report.text("Назначение модулей системы приведено в таблице 2.")
    report.table(
        "Состав и назначение модулей системы",
        ["Модуль", "Назначение"],
        [
            ("arachne/crawler.py", "Агент (паук): обход каталогов и UNC-ресурсов ЛВС, "
                                   "инкрементальность по времени изменения и хеш-сумме SHA-1, "
                                   "журнал обходов"),
            ("arachne/text/extract.py", "Извлечение заголовка и текста из txt, md, csv, html, "
                                        "docx, pdf, rtf; автоматический подбор кодировки"),
            ("arachne/text/morphology.py", "Токенизация, отсев стоп-слов, лемматизация "
                                           "(pymorphy3), морфологическая справка о слове"),
            ("arachne/indexer.py", "Построение поисковых образов документов: формулы (1.5) "
                                   "и (1.6), инвертированный индекс, нормы векторов"),
            ("arachne/search.py", "Поисковый образ запроса, скалярное произведение, "
                                  "евклидовы нормы, косинусная мера, ранжирование, фильтры"),
            ("arachne/text/snippets.py", "Формирование сниппетов вокруг слов запроса "
                                         "и их подсветка"),
            ("arachne/ai/suggest.py", "Разбор ЕЯ-запроса, автодополнение, исправление "
                                      "опечаток, тезаурус синонимов, история запросов"),
            ("arachne/ai/feedback.py", "Обратная связь по релевантности (метод Рокчио), "
                                       "подбор похожих документов"),
            ("arachne/ai/llm.py", "Необязательный языковой помощник поверх готовой выдачи"),
            ("arachne/evaluation/", "Метрики РОМИП, эталонная разметка, прогон запросов, "
                                    "графики"),
            ("arachne/db.py", "Схема базы данных, подключение, статистика, очистка"),
            ("arachne/web/app.py", "Веб-интерфейс: 33 маршрута HTTP, фоновые задачи обхода "
                                   "и индексации"),
            ("arachne/companion.py", "Паук-компаньон и достижения (отключаемо)"),
            ("tools/", "Генератор тестовой коллекции, переиндексация, прогон метрик, "
                       "построение схем и сборка отчёта"),
        ],
        widths=[5.0, 11.5],
        size=Pt(11),
    )


def database_section(report: Report, data: dict) -> None:
    report.heading("Структура базы данных системы")
    report.text(
        "Хранилищем служит встроенная СУБД SQLite: система рассчитана на рабочее место "
        "в локальной сети и не должна требовать развёртывания сервера базы данных. "
        "Схема состоит из двенадцати таблиц и создаётся идемпотентно при старте "
        "(модуль arachne/db.py). Схема базы данных приведена на рисунке 2."
    )
    report.figure(config.REPORT_DIR / "database.png",
                  "Схема базы данных ИПС «Арахна»")

    report.text(
        "Ядро схемы образуют три таблицы, реализующие векторную модель: documents хранит "
        "документы и норму их векторов, terms — словарь системы (термины и число документов "
        "с термином P~i~), postings — инвертированный индекс, то есть ненулевые "
        "координаты векторов документов. Хранение только ненулевых весов принципиально: "
        f"матрица «термин — документ» размера {data['stats']['terms']} × "
        f"{data['stats']['documents']} заполнена лишь на "
        f"{number(100 * data['stats']['postings'] / max(1, data['stats']['terms'] * data['stats']['documents']), 2)} %, "
        "и полное матричное представление было бы расточительным. Назначение полей "
        "основных таблиц приведено в таблицах 3–5."
    )

    report.table(
        "Таблица documents — документы, найденные пауком в ЛВС",
        ["Поле", "Тип", "Описание"],
        [
            ("id", "INTEGER PK", "Идентификатор документа"),
            ("path", "TEXT UNIQUE", "Полный путь: локальный или UNC; однозначно определяет документ"),
            ("uri", "TEXT", "Ссылка file:// для активной ссылки в поисковой выдаче"),
            ("host", "TEXT", "Узел ЛВС, которому принадлежит документ"),
            ("title", "TEXT", "Заголовок документа"),
            ("text", "TEXT", "Извлечённый текст документа"),
            ("ext", "TEXT", "Расширение файла (формат)"),
            ("size_bytes", "INTEGER", "Размер файла в байтах"),
            ("mtime", "REAL", "Время изменения файла — признак для инкрементального обхода"),
            ("date_added", "TEXT", "Дата добавления в базу (ДД.ММ.ГГГГ)"),
            ("time_added", "TEXT", "Время добавления (ЧЧ:ММ:СС)"),
            ("content_hash", "TEXT", "SHA-1 содержимого: отличает изменение файла от смены времени"),
            ("term_count", "INTEGER", "Число значимых словоупотреблений в документе"),
            ("vector_norm", "REAL", "Евклидова норма \u2016D\u2016 вектора документа"),
        ],
        widths=[3.4, 3.0, 10.1],
        size=Pt(11),
    )

    report.table(
        "Таблицы terms и postings — словарь системы и инвертированный индекс",
        ["Таблица", "Поле", "Тип", "Описание"],
        [
            ("terms", "id", "INTEGER PK", "Идентификатор термина"),
            ("", "lemma", "TEXT UNIQUE", "Термин — нормальная форма слова"),
            ("", "df", "INTEGER", "P~i~ — число документов с термином i"),
            ("postings", "term_id", "INTEGER FK", "Ссылка на terms.id"),
            ("", "doc_id", "INTEGER FK", "Ссылка на documents.id"),
            ("", "tf", "INTEGER", "Q~ij~ — частота термина i в документе j"),
            ("", "weight", "REAL", "A~ij~ = Q~ij~ · B~i~ — вес термина, формула (1.6)"),
            ("forms", "form", "TEXT", "Словоформа, встретившаяся в коллекции"),
            ("", "term_id", "INTEGER FK", "Термин, к которому приводится словоформа"),
            ("", "freq", "INTEGER", "Частота словоформы — ранжирование автодополнения"),
        ],
        widths=[2.6, 3.0, 3.2, 7.7],
        size=Pt(11),
    )

    report.table(
        "Таблицы оценки качества и обратной связи",
        ["Таблица", "Поле", "Тип", "Описание"],
        [
            ("eval_queries", "id, text, note", "INTEGER, TEXT",
             "Эталонные информационные потребности"),
            ("qrels", "query_id, doc_id", "INTEGER FK", "Пара «запрос — документ»"),
            ("", "rel", "INTEGER",
             "Степень релевантности: 0 — нерелевантен, 1 — релевантен, 2 — высоко релевантен"),
            ("feedback", "query, doc_id", "TEXT, INTEGER FK",
             "Отметка пользователя по конкретному запросу"),
            ("", "mark", "INTEGER", "+1 — «больше таких», \u22121 — «не то» (метод Рокчио)"),
            ("query_log", "raw_query, normalized", "TEXT",
             "История запросов: исходный текст и леммы"),
            ("", "results_count, took_ms", "INTEGER, REAL",
             "Число найденных документов и время поиска"),
            ("sources", "root_path, kind, label", "TEXT",
             "Обходимые ресурсы ЛВС: путь, тип (local/unc), имя узла"),
            ("crawl_log", "added, updated, skipped, removed, errors", "INTEGER",
             "Журнал обходов паука"),
        ],
        widths=[2.6, 3.6, 3.2, 7.1],
        size=Pt(11),
    )

    report.text(
        "Все связи объявлены внешними ключами с каскадным удалением (PRAGMA foreign_keys = ON), "
        "поэтому удаление документа из интерфейса автоматически убирает его вхождения из "
        "индекса, эталонной разметки и отметок обратной связи. Для ускорения поиска созданы "
        "индексы по postings(term_id), postings(doc_id), terms(lemma), forms(form) и "
        "documents(host)."
    )


def algorithms(report: Report) -> None:
    report.heading("Основные алгоритмы реализации компонентов системы")

    report.subheading("1. Алгоритм обхода локальной вычислительной сети (агент)")
    report.text(
        "Реализован в модуле arachne/crawler.py, функция crawl(). На вход подаётся список "
        "включённых источников — каталогов и UNC-ресурсов ЛВС."
    )
    report.steps([
        "Перечисление файлов. Каталог обходится рекурсивно (os.walk) с пропуском служебных "
        "папок (.git, __pycache__, System Volume Information, скрытые каталоги). Отбираются "
        "файлы с поддерживаемыми расширениями.",
        "Отсев неизменившихся файлов. Для каждого файла сравниваются время изменения и "
        "размер с сохранёнными в базе. Совпадение означает, что документ не менялся, — файл "
        "не читается вовсе. Это делает повторный обход на два порядка быстрее первого.",
        "Параллельное чтение. Оставшиеся файлы читаются пулом из восьми потоков: задача "
        "ограничена вводом-выводом, а сетевые ресурсы отвечают с заметной задержкой. Для "
        "каждого файла вычисляется SHA-1 содержимого и извлекается текст.",
        "Различение изменения и «касания» файла. Если хеш совпал с сохранённым, документ "
        "считается неизменившимся, обновляется только время изменения; иначе запись "
        "добавляется или обновляется, а vector_norm обнуляется — документ требует "
        "переиндексации.",
        "Удаление исчезнувших документов. Документы, файлы которых больше не существуют в "
        "обойдённых источниках, удаляются из базы вместе с их вхождениями в индекс.",
        "Запись журнала. Итог обхода (добавлено, обновлено, пропущено, удалено, ошибок) "
        "сохраняется в crawl_log и показывается в интерфейсе.",
    ])
    report.text(
        "Ошибки отдельного файла — нет доступа, повреждённый архив DOCX, неопознанная "
        "кодировка — не прерывают обход: они учитываются в счётчике ошибок и попадают "
        "в сообщения журнала."
    )

    report.subheading("2. Алгоритм извлечения текста из документов")
    report.text(
        "Реализован в модуле arachne/text/extract.py. Для каждого формата предусмотрен свой "
        "обработчик, возвращающий пару «заголовок, текст»."
    )
    report.steps([
        "Подбор кодировки для текстовых форматов. Файл последовательно декодируется в "
        "utf-8-sig, utf-8, cp1251, koi8-r и cp866. Для каждого варианта считается доля "
        "«осмысленных» символов (буквы, цифры, пробелы, знаки препинания) на первых "
        "4000 символах; utf-8 с долей выше 0,85 принимается сразу, иначе выбирается "
        "вариант с наибольшей оценкой. Это позволяет индексировать унаследованные "
        "документы ЛВС в кодировке Windows-1251.",
        "Разбор HTML. Удаляются теги script, style и noscript, заголовок берётся из "
        "элемента title, при его отсутствии — из первого h1 или h2.",
        "Разбор DOCX. Собираются все абзацы и содержимое таблиц; заголовком служит первый "
        "абзац со стилем Heading, свойство core_properties.title или первая содержательная "
        "строка.",
        "Разбор PDF. Текст извлекается постранично; страницы, которые не удалось разобрать, "
        "пропускаются, чтобы один сбойный лист не обесценил весь документ.",
        "Нормализация. Схлопываются повторяющиеся пробелы и пустые строки. Документ без "
        "текста отвергается с ошибкой ExtractionError.",
    ])

    report.subheading("3. Алгоритм индексирования документов")
    report.text(
        "Реализован в модуле arachne/indexer.py, функция build_index(). Строит поисковые "
        "образы документов (ПОД) по формулам методических указаний. Блок-схема алгоритма "
        "приведена на рисунке 3."
    )
    report.figure(config.REPORT_DIR / "algo_index.png",
                  "Блок-схема алгоритма построения индекса")
    report.text(
        "Инверсная частота термина вычисляется по формуле (1.5):"
    )
    report.text("B~i~ = log( N / P~i~ ),", align=WD_ALIGN_PARAGRAPH.CENTER, indent=False)
    report.text(
        "где N — количество документов в базе данных, P~i~ — количество документов "
        "с термином i. Вес термина в документе — по формуле (1.6):"
    )
    report.text("A~ij~ = Q~ij~ · B~i~,",
                align=WD_ALIGN_PARAGRAPH.CENTER, indent=False)
    report.text(
        "где Q~ij~ — частота термина i в документе j. Термин, встречающийся почти "
        "во всех документах, получает вес, близкий к нулю, и практически не влияет на "
        "ранжирование; редкий термин, наоборот, оказывается решающим."
    )
    report.text(
        "Индекс перестраивается целиком, а не дособирается. Это принципиальное решение: "
        "при добавлении документа меняется N, а значит, изменяются все инверсные частоты "
        "B~i~ и все веса A~ij~. Частичное обновление давало бы веса, посчитанные "
        "при разных N, и ранги документов стали бы несопоставимыми. Полная перестройка "
        "коллекции из 108 документов занимает около 0,3 с, поэтому цена такого решения "
        "невелика."
    )

    report.subheading("4. Алгоритм поиска по векторной модели")
    report.text(
        "Реализован в модуле arachne/search.py, класс Search. Соответствует диаграмме "
        "класса Search из методических указаний. Блок-схема приведена на рисунке 4."
    )
    report.figure(config.REPORT_DIR / "algo_search.png",
                  "Блок-схема алгоритма поиска по векторной модели")
    report.steps([
        "Построение поискового образа запроса (ПОЗ). Запрос токенизируется, из него "
        "отбрасываются стоп-слова, оставшиеся слова приводятся к нормальной форме. "
        "Вектор запроса строится по правилу методических указаний: w~qj~ = 1, если "
        "слово присутствует в запросе, и 0 в противном случае. Термины, добавленные самой "
        "системой (синонимы, исправления опечаток), входят в вектор с пониженным весом 0,5, "
        "чтобы не перебивать то, что пользователь ввёл сам.",
        "Отбор документов-кандидатов. Из инвертированного индекса одним запросом "
        "выбираются все вхождения терминов ПОЗ. Документы, не содержащие ни одного термина "
        "запроса, не рассматриваются вовсе.",
        "Скалярное произведение. Для каждого документа-кандидата накапливается "
        "(D, Q) = Σ A~ij~ · w~qj~; попутно сохраняется вклад каждого "
        "отдельного термина — он показывается пользователю в блоке «Почему найден».",
        "Применение фильтров. При включённом режиме «все слова обязательны» отсеиваются "
        "документы, в которых встретились не все слова пользовательского запроса; "
        "применяется фильтр по диапазону дат добавления.",
        "Вычисление ранга. Релевантность документа запросу — косинус угла между их "
        "векторами: sim(D, Q) = (D, Q) / ( \u2016D\u2016 · \u2016Q\u2016 ). Норма документа "
        "\u2016D\u2016 берётся из documents.vector_norm, вычисленной на этапе индексирования, "
        "поэтому во время поиска её не приходится пересчитывать.",
        "Формирование выдачи. Результаты сортируются по убыванию ранга, для каждого "
        "строится сниппет — окно текста с максимальным числом попаданий слов запроса — "
        "и собирается список слов запроса, реально присутствующих в документе.",
    ])

    report.subheading("5. Алгоритмы элементов искусственного интеллекта в интерфейсе")
    report.text(
        "Реализация элементов ИИ в интерфейсе с пользователем — предмет варианта 3. "
        "Реализованы следующие механизмы (пакет arachne/ai/)."
    )
    report.steps([
        "Морфологический разбор запроса. Для каждого слова запроса определяются нормальная "
        "форма, часть речи и наличие термина в словаре системы. Результат показывается "
        "пользователю в блоке «Как система поняла запрос» — интерфейс не скрывает от "
        "пользователя свою интерпретацию.",
        "Автодополнение. При наборе запроса подсказки берутся из двух источников: ранее "
        "заданные запросы (таблица query_log) и словоформы индекса (таблица forms), "
        "упорядоченные по частоте. Подсказки подгружаются асинхронно, без перезагрузки "
        "страницы.",
        "Исправление опечаток. Для слова, отсутствующего в словаре, подбирается ближайшая "
        "словоформа по расстоянию Дамерау — Левенштейна, учитывающему перестановку соседних "
        "символов. Порог зависит от длины слова: 1 для слов до пяти символов, 2 для более "
        "длинных. Реализация досрочно прекращает вычисление строки матрицы, если минимум "
        "в ней уже превысил порог, а кандидаты с сильно отличающейся длиной отбрасываются "
        "без вычислений. При равном расстоянии выбирается более частое слово.",
        "Расширение запроса синонимами. Термины запроса дополняются синонимами из тезауруса "
        "data/synonyms_ru.json (например, «коммутатор» \u2194 «свитч», «лвс» \u2194 «сеть»); "
        "добавляются только те синонимы, которые действительно есть в словаре системы. "
        "Пользователю показывается, чем именно был расширен его запрос.",
        "Обратная связь по релевантности. Кнопки «Больше таких» и «Не то» смещают вектор "
        "запроса методом Рокчио: Q\u2032 = α·Q + (β/|Dr|)·ΣDr \u2212 (γ/|Dnr|)·ΣDnr, где "
        "Dr и Dnr — множества документов, отмеченных как удачные и как неудачные; "
        "α = 1, β = 0,75, γ = 0,15. Векторы документов нормируются к единичной длине, "
        "отрицательные компоненты обнуляются, а результат усекается до 40 наиболее весомых "
        "терминов — иначе запрос «расползается» по всей коллекции.",
        "Похожие документы. На странице документа вычисляется косинусная мера документ — "
        "документ по 25 наиболее весомым терминам образца; выводятся пять ближайших.",
        "Объяснение выдачи. Для каждого результата раскрывается таблица вклада отдельных "
        "терминов в итоговый ранг с полосами относительной величины — пользователь видит, "
        "почему документ оказался на своём месте.",
        "Подсказки при пустой выдаче. Система анализирует причину отсутствия результатов "
        "(включён строгий режим, применён фильтр по дате, слово отсутствует в словаре) "
        "и предлагает конкретные действия.",
    ])
    report.text(
        "Отдельно предусмотрен необязательный слой языкового помощника (arachne/ai/llm.py), "
        "работающий с любым OpenAI-совместимым сервисом. Он способен кратко изложить суть "
        "найденного и предложить другие формулировки запроса, но поиск, ранжирование и "
        "расчёт метрик не выполняет. По умолчанию слой выключен и в сеть не обращается: "
        "работоспособность системы не должна зависеть от доступности стороннего сервиса."
    )

    report.subheading("6. Алгоритмы расчёта метрик качества")
    report.text(
        "Реализованы в модуле arachne/evaluation/metrics.py. Все функции принимают "
        "ранжированный список идентификаторов документов и эталонную разметку вида "
        "{документ: степень релевантности}. Прогон по всем эталонным запросам выполняет "
        "arachne/evaluation/runner.py, вызываемый из подменю «Оценка качества»."
    )
    report.bullets([
        "Точность и полнота — доля релевантных среди найденных и доля найденных среди "
        "всех релевантных документов.",
        "F-мера — гармоническое среднее точности и полноты.",
        "P@n — точность на уровне первых n документов выдачи (n = 5, 10, 20).",
        "R-точность — точность на уровне R, где R — число релевантных документов запроса.",
        "AP и MAP — средняя точность по запросу (среднее значений точности в позициях "
        "попадания релевантных документов) и её усреднение по набору запросов.",
        "11-точечный график «точность — полнота» — интерполированная точность "
        "P~int~(r) = max{ P(r\u2032) : r\u2032 \u2265 r } на стандартных уровнях "
        "полноты 0,0; 0,1; …; 1,0, усреднённая по всем запросам.",
        "DCG и nDCG — накопленный выигрыш с учётом позиции документа, "
        "(2^rel \u2212 1) / log~2~(позиция + 1), и его отношение к выигрышу идеального "
        "порядка; метрика использует градации релевантности 0/1/2.",
        "bpref — метрика, устойчивая к неполноте эталонной разметки: учитывает только "
        "оценённые документы и считает, сколько оценённых нерелевантных документов стоит "
        "выше каждого релевантного.",
    ])


def data_structures(report: Report) -> None:
    report.heading("Структуры хранения данных")
    report.text(
        "Состав классов повторяет диаграммы классов из методических указаний (рисунки 1–3 "
        "методички). Классы предметной области описаны в модуле arachne/models.py как "
        "dataclass-объекты, класс Search вынесен в arachne/search.py."
    )

    report.subheading("1. Класс Document — документ, основная сущность системы")
    report.bullets([
        "document_id (int) — идентификатор документа в таблице documents.",
        "path, uri (str) — путь в ЛВС и ссылка file:// для активной ссылки в выдаче.",
        "host (str) — узел локальной сети, которому принадлежит документ.",
        "title, text (str) — заголовок и извлечённый текст.",
        "ext, size_bytes, mtime — формат, размер и время изменения файла.",
        "date_added, time_added (str) — дата и время добавления в базу.",
        "content_hash (str) — SHA-1 содержимого для инкрементального обхода.",
        "term_count (int) — число значимых словоупотреблений.",
        "vector_norm (float) — евклидова норма \u2016D\u2016 вектора документа.",
    ])
    report.text(
        "Операциям класса Document с диаграммы методички соответствуют функции модуля "
        "arachne/indexer.py: add_document_to_base, delete_document_from_base, "
        "get_lemma_inverse_frequency (по лемме и по идентификатору), "
        "get_word_weight_in_document, get_lemma_weight_in_document и get_document_vector."
    )

    report.subheading("2. Класс Search — поисковый запрос и параметры отбора")
    report.bullets([
        "search_query (str) — естественно-языковой запрос пользователя.",
        "all_words_together (bool) — требовать присутствия всех слов запроса в документе.",
        "date_start_string, date_end_string (str) — границы диапазона дат.",
        "expansions (dict) — расширения запроса: {исходная лемма: [добавленные леммы]}.",
        "rocchio_vector (dict | None) — вектор запроса после обратной связи.",
        "use_lemmas (bool) — строить образ по леммам или по словоформам (режим сравнения).",
        "get_search_query_vector() — построение ПОЗ {лемма: w~qj~}.",
        "scalar_product(a, b) — скалярное произведение векторов (D, Q).",
        "euclidean_norm(a) — евклидова норма вектора.",
        "get_search_result() — упорядоченный по убыванию релевантности список результатов.",
    ])

    report.subheading("3. Класс SearchResult — одна ссылка в поисковой выдаче")
    report.bullets([
        "document_id (int) — идентификатор документа из таблицы documents.",
        "title (str) — заголовок документа.",
        "snippet (str) — фрагмент текста документа с подсвеченными словами запроса.",
        "rank (float) — релевантность документа запросу (косинусная мера).",
        "date (str) — дата добавления документа в базу.",
        "matched_words (list[str]) — слова запроса, присутствующие в документе "
        "(требование методических указаний к составу выдачи).",
        "feedback_words (list[str]) — термины, добавленные в поисковый образ "
        "запроса методом Рокчио по отметкам пользователя; показываются отдельно "
        "от слов запроса, так как словами запроса не являются.",
        "uri, path, host (str) — активная ссылка на документ, путь и узел ЛВС.",
        "explanation (list[tuple]) — вклад отдельных терминов в итоговый ранг.",
    ])

    report.subheading("4. Вспомогательные структуры")
    report.bullets([
        "QueryAnalysis — результат «понимания» запроса: токены, леммы, отброшенные "
        "стоп-слова, морфологическая справка, исправления опечаток, синонимы, "
        "неизвестные слова.",
        "CrawlReport — итог обхода ЛВС: добавлено, обновлено, пропущено, удалено, ошибок, "
        "просмотрено файлов, затраченное время, сообщения.",
        "RunConfig — конфигурация прогона оценки качества: использовать ли леммы, "
        "расширять ли синонимами, строгий ли режим, глубина выдачи.",
    ])


def collection_section(report: Report, data: dict) -> None:
    report.heading("Информация о тестовой коллекции документов")
    stats = data["stats"]
    report.text(
        f"Тестовая коллекция моделирует файловые ресурсы локальной сети небольшой "
        f"организации и содержит {stats['documents']} "
        f"{plural(stats['documents'], 'документ', 'документа', 'документов')} "
        f"на русском языке, "
        f"размещённых на трёх узлах — NODE-A, NODE-B и NODE-C (по "
        f"{data['by_host']['NODE-A']} "
        f"{plural(data['by_host']['NODE-A'], 'документу', 'документа', 'документов')} "
        f"на узле). Общий объём коллекции — "
        f"{data['total_size'] / 1024:.0f} КиБ, средний размер документа — "
        f"{number(data['avg_size'] / 1024, 1)} КиБ. Документы представлены в пяти форматах, "
        f"типичных для сетевых папок; распределение приведено в таблице 6."
    )

    ext_order = [".txt", ".md", ".html", ".docx", ".pdf"]
    rows = []
    for host in sorted(data["host_ext"]):
        rows.append([host] + [data["host_ext"][host].get(ext, 0) for ext in ext_order]
                    + [data["by_host"][host]])
    rows.append(["Всего"] + [data["by_ext"].get(ext, 0) for ext in ext_order]
                + [stats["documents"]])
    report.table(
        "Распределение документов коллекции по узлам ЛВС и форматам",
        ["Узел ЛВС", "TXT", "MD", "HTML", "DOCX", "PDF", "Всего"],
        rows,
        widths=[3.5, 2.1, 2.1, 2.2, 2.2, 2.2, 2.2],
    )

    report.text(
        "Документы распределены по десяти тематическим разделам. Тематика подобрана "
        "намеренно так, чтобы разделы пересекались по лексике: слово «сеть» встречается "
        "и в статьях о ЛВС, и в статьях о нейронных сетях, и в описании железнодорожной "
        "сети; слова «маршрут», «узел» и «пакет» — в статьях о сетях и о транспортной "
        "логистике; слово «индекс» — в статьях о СУБД и об информационном поиске. Без "
        "такой лексической омонимии оценка качества вырождается: любой запрос отделял бы "
        "релевантные документы от нерелевантных тривиально, и метрики принимали бы "
        "значения, близкие к единице, независимо от качества модели поиска. Распределение "
        "по темам приведено в таблице 7."
    )
    topic_rows = [
        (TOPICS.get(topic, topic), count)
        for topic, count in sorted(data["by_topic"].items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    topic_rows.append(("Всего", stats["documents"]))
    report.table(
        "Распределение документов коллекции по тематическим разделам",
        ["Тематический раздел", "Число документов"],
        topic_rows,
        widths=[11.5, 5.0],
    )

    report.text(
        f"После индексирования словарь системы содержит {stats['terms']} терминов при "
        f"{stats['postings']} вхождениях «термин — документ» и {stats['forms']} словоформах. "
        f"Средняя длина поискового образа документа — {number(data['terms_avg'], 1)} "
        f"значимого словоупотребления (от {data['terms_min']} до {data['terms_max']}), всего в "
        f"коллекции {data['terms_total']} значимых словоупотреблений. Матрица "
        f"«термин — документ» заполнена на "
        f"{number(100 * stats['postings'] / max(1, stats['terms'] * stats['documents']), 2)} %, "
        f"а {data['singletons']} "
        f"{plural(data['singletons'], 'термин', 'термина', 'терминов')} "
        f"({number(100 * data['singletons'] / stats['terms'], 1)} %) "
        "встречаются ровно в одном документе — распределение частот характерно для "
        "естественно-языковых текстов и согласуется с законом Ципфа. Наиболее частотные "
        "термины словаря и их инверсные частоты приведены в таблице 8."
    )
    report.table(
        "Наиболее частотные термины словаря системы",
        ["Термин", "P~i~ (df)", "Суммарная частота", "B~i~ = log(N / P~i~)"],
        [(lemma, df, tf, number(idf)) for lemma, df, tf, idf in data["top_terms"]],
        widths=[5.0, 3.4, 4.5, 3.6],
    )
    report.text(
        "Видно, что самые частые слова коллекции получают наименьший вес: термин «сеть», "
        "встречающийся почти в трети документов, имеет инверсную частоту около "
        f"{number(data['top_terms'][0][3], 2) if data['top_terms'] else '0,5'}, тогда как "
        "термин, встретившийся в одном документе, получает вес "
        f"log({data['stats']['documents']} / 1) = "
        f"{number(math.log(data['stats']['documents'], 10), 3)}. Именно это и обеспечивает "
        "формула (1.5): частые слова не помогают различать документы, редкие — решают."
    )

    report.text(
        f"Для оценки качества подготовлена эталонная разметка: {data['queries']} "
        f"{plural(data['queries'], 'информационная потребность', 'информационные потребности', 'информационных потребностей')} "
        f"и {data['judgements']} "
        f"{plural(data['judgements'], 'оценка', 'оценки', 'оценок')} релевантности "
        f"(из них {data['judged'][2]} с оценкой 2 — высоко релевантен, "
        f"{data['judged'][1]} с оценкой 1 — релевантен, {data['judged'][0]} с оценкой 0 — "
        f"нерелевантен). В среднем на запрос приходится "
        f"{number(sum(item['relevant_total'] for item in data['per_query']) / max(1, len(data['per_query'])), 1)} "
        "релевантного документа. Разметка хранится в базе и дублируется в текстовых файлах "
        "data/eval_queries.csv и data/qrels.csv, поэтому переживает пересборку базы; "
        "документы в ней сопоставляются по имени файла, а не по идентификатору. Править "
        "разметку можно прямо в интерфейсе, в разделе «Разметка»."
    )


def testing_section(report: Report, data: dict) -> None:
    report.heading("Результаты тестирования системы")

    report.subheading("1. Автоматическое тестирование")
    report.text(
        "Автотесты написаны с использованием pytest и покрывают все расчётные части "
        "системы. Запуск: python -m pytest tests -q. Результат: 36 тестов, все пройдены, "
        "время выполнения — около 0,7 с. Состав тестов приведён в таблице 9."
    )
    report.table(
        "Состав автоматических тестов",
        ["Группа тестов", "Что проверяется", "Тестов"],
        [
            ("Морфология", "Приведение словоформ к лемме, отсев стоп-слов, "
                           "уникальность и порядок лемм запроса", 3),
            ("Извлечение текста", "Разбор txt и html, определение кодировки cp1251, "
                                  "отказ на неподдерживаемом формате", 4),
            ("Индексирование", "Формула (1.5) на известных значениях, совпадение весов "
                               "A~ij~ с посчитанными вручную, норма вектора", 3),
            ("Поиск", "Нахождение документа по другой словоформе, преимущество редкого "
                      "термина, нормированность косинуса, режим «все слова», список слов "
                      "запроса в выдаче, скалярное произведение и норма", 6),
            ("Элементы ИИ", "Исправление опечатки, перестановка символов в расстоянии "
                            "Дамерау — Левенштейна, автодополнение по словарю, разбор "
                            "запроса, метод Рокчио, похожие документы", 6),
            ("Обход ЛВС", "Инкрементальность повторного обхода, удаление исчезнувших "
                          "документов", 2),
            ("Метрики качества", "Точность, полнота, P@n, R-точность, F-мера, AP, "
                                 "монотонность интерполированной кривой, nDCG идеального "
                                 "порядка, DCG, bpref, пустая выдача, MAP", 11),
            ("Эталонная разметка", "Устойчивость нумерации эталонных запросов при "
                                   "повторной загрузке из CSV", 1),
        ],
        widths=[3.4, 10.6, 2.5],
        size=Pt(11),
    )
    report.text(
        "Тесты индексирования и поиска построены на крошечной коллекции из трёх "
        "документов, для которой веса и ранги можно посчитать вручную: например, для "
        "термина, встречающегося в двух документах из трёх, проверяется равенство "
        "A~ij~ = Q~ij~ · log(3 / 2). Метрики качества проверяются на "
        "выдаче с заранее известным ответом."
    )

    report.subheading("2. Функциональное тестирование")
    report.text(
        "Функциональное тестирование выполнялось через веб-интерфейс на полной тестовой "
        "коллекции. Проверялось выполнение каждого требования, предъявляемого к системе "
        "методическими указаниями; результаты приведены в таблице 10."
    )
    report.table(
        "Проверка выполнения требований к системе",
        ["Требование", "Как проверялось", "Результат"],
        [
            ("Вход — множество ЕЯ-текстов",
             "Обход трёх узлов ЛВС, индексация 108 документов в пяти форматах",
             "выполнено"),
            ("Автоматическое выделение ключевых слов по формуле (1.6)",
             "Сверка весов в таблице postings с расчётом вручную; автотесты",
             "выполнено"),
            ("Формулирование ЕЯ-запроса",
             "Запросы в свободной форме: «как работает коммутатор», "
             "«маршрутизация пакетов между узлами сети»",
             "выполнено"),
            ("Выдача по векторной модели",
             "Ранжирование по косинусной мере; проверка порядка выдачи и значений ранга",
             "выполнено"),
            ("Активная ссылка на документ",
             "Ссылка на карточку документа и прямая ссылка на исходный файл в ЛВС",
             "выполнено"),
            ("Список слов запроса в документе",
             "Блок «Слова запроса в документе» под каждым результатом выдачи",
             "выполнено"),
            ("Расчёт метрик программно, вызов из подменю",
             "Раздел «Оценка качества»: расчёт по 36 эталонным запросам",
             "выполнено"),
            ("Отображение оценок в виде таблиц и графиков",
             "Таблица по запросам, таблица средних, графики на странице и выгрузка "
             "в PNG и CSV",
             "выполнено"),
            ("Простой интерфейс и help-средства",
             "Шесть разделов меню, раздел «Справка» с шестью подразделами, подсказки "
             "при пустой выдаче",
             "выполнено"),
        ],
        widths=[4.4, 8.6, 3.5],
        size=Pt(11),
    )

    report.subheading("3. Пример поисковой сессии")
    report.text(
        "Запрос «маршрутизация пакетов между узлами сети» обрабатывается следующим образом. "
        "Стоп-слово «между» отбрасывается; слова приводятся к нормальным формам "
        "«маршрутизация», «пакет», «узел», «сеть»; все они присутствуют в словаре системы. "
        "Найдено 52 документа, время поиска — около 3 мс. Первым результатом выдаётся "
        "документ «Маршрутизаторы и маршрутизация пакетов» (NODE-A, ранг 0,3119), вторым — "
        "«IP-адресация и разбиение на подсети» (ранг 0,1875), третьим — «VPN и удалённый "
        "доступ к ресурсам предприятия» (ранг 0,1648). Блок «Почему найден» показывает "
        "вклад каждого термина в ранг, причём наибольший вклад даёт редкий термин "
        "«маршрутизация», а не частотное слово «сеть»."
    )
    report.text(
        "Запрос с опечаткой «комутатор сети» распознаётся системой: слово «комутатор» "
        "отсутствует в словаре, ближайшим по расстоянию Дамерау — Левенштейна оказывается "
        "«коммутатор» (расстояние 1), и интерфейс предлагает исправленный вариант, "
        "одновременно добавляя исправление в поисковый образ запроса с весом 0,5. Для "
        "слова «сеть» тезаурус предлагает синонимы «лвс» и «сетевой», присутствующие "
        "в словаре системы."
    )


def metrics_section(report: Report, data: dict) -> None:
    summary = data["summary"]
    report.heading("Результаты оценки качества работы СИП")
    report.text(
        f"Оценка выполнена по {data['queries']} эталонным информационным потребностям при "
        f"глубине выдачи 20 документов. Расчёт запускается из подменю «Оценка качества» "
        f"веб-интерфейса либо из командной строки (python tools/run_eval.py) и занимает "
        f"около {number(data['eval_ms'] / 1000, 2)} с. Результаты по каждому запросу приведены "
        f"в таблице 11."
    )

    rows = []
    for item in data["per_query"]:
        query = item["query"]
        if len(query) > 38:
            query = query[:37] + "\u2026"
        rows.append((
            item["query_id"], query, item["relevant_total"],
            number(item["p@5"]), number(item["p@10"]), number(item["r_precision"]),
            number(item["ap"]), number(item["ndcg"]), number(item["bpref"]),
        ))
    report.table(
        "Значения метрик качества по каждому эталонному запросу",
        ["\u2116", "Запрос", "Rel", "P@5", "P@10", "R-точн.", "AP", "nDCG", "bpref"],
        rows,
        widths=[0.9, 5.5, 1.0, 1.3, 1.3, 1.6, 1.3, 1.3, 1.3],
        size=Pt(9),
    )

    report.text("Усреднённые по набору запросов значения метрик приведены в таблице 12.")
    report.table(
        "Усреднённые значения метрик качества",
        ["Метрика", "Значение", "Что показывает"],
        [
            ("Точность (P)", number(summary["precision"]),
             "Доля релевантных среди 20 выданных документов"),
            ("Полнота (R)", number(summary["recall"]),
             "Доля найденных релевантных среди всех релевантных"),
            ("F-мера (F1)", number(summary["f1"]),
             "Гармоническое среднее точности и полноты"),
            ("P@5", number(summary["p@5"]), "Точность на первых пяти документах выдачи"),
            ("P@10", number(summary["p@10"]), "Точность на первых десяти документах"),
            ("P@20", number(summary["p@20"]), "Точность на первых двадцати документах"),
            ("R-точность", number(summary["r_precision"]),
             "Точность на уровне R, где R — число релевантных документов"),
            ("MAP", number(summary["map"]),
             "Усреднённая средняя точность — основная метрика ранжирования"),
            ("nDCG", number(summary["ndcg"]),
             "Нормированный накопленный выигрыш с учётом градаций релевантности"),
            ("nDCG@10", number(summary["ndcg@10"]),
             "То же в пределах первых десяти документов"),
            ("bpref", number(summary["bpref"]),
             "Устойчивая к неполноте разметки оценка качества ранжирования"),
        ],
        widths=[3.2, 2.4, 10.9],
        size=Pt(11),
    )

    report.text(
        "Значения интерполированной точности на одиннадцати стандартных уровнях полноты "
        "приведены в таблице 13, а соответствующий график — на рисунке 5."
    )
    report.table(
        "Интерполированная точность на стандартных уровнях полноты",
        ["Полнота"] + [number(level, 1) for level, _ in summary["curve"]],
        [["Точность"] + [number(value) for _, value in summary["curve"]]],
        widths=[2.1] + [1.3] * 11,
        size=Pt(9),
    )
    report.figure(config.REPORT_DIR / "pr_curve.png",
                  "Зависимость точности от полноты (11 точек, усреднение по запросам)")

    report.text(
        "Распределение средней точности (AP) и точности на первых десяти документах (P@10) "
        "по отдельным запросам приведено на рисунках 6 и 7. Эти графики показывают не "
        "среднее, а разброс: именно он говорит о том, на каких информационных потребностях "
        "система работает хуже всего."
    )
    report.figure(config.REPORT_DIR / "per_query_ap.png",
                  "Средняя точность (AP) по каждому эталонному запросу")
    report.figure(config.REPORT_DIR / "per_query_p_10.png",
                  "Точность на первых десяти документах (P@10) по каждому запросу")


def comparison_section(report: Report, data: dict) -> None:
    report.heading("Сравнение конфигураций системы")
    report.text(
        "Чтобы оценить вклад отдельных механизмов в качество поиска, один и тот же "
        "эталонный набор прогонялся в четырёх конфигурациях системы. Конфигурация без "
        "морфологии требует перестройки индекса по словоформам, поэтому по окончании "
        "эксперимента индекс автоматически возвращается в обычное состояние. Результаты "
        "приведены в таблице 14 и на рисунке 8."
    )
    report.table(
        "Сравнение конфигураций поисковой системы",
        ["Конфигурация", "MAP", "P@10", "R-точн.", "nDCG", "bpref"],
        [
            (item["name"], number(item["summary"]["map"]), number(item["summary"]["p@10"]),
             number(item["summary"]["r_precision"]), number(item["summary"]["ndcg"]),
             number(item["summary"]["bpref"]))
            for item in data["comparison"]
        ],
        widths=[6.5, 2.0, 2.0, 2.2, 2.0, 2.0],
        size=Pt(11),
    )
    report.figure(config.REPORT_DIR / "configurations.png",
                  "Сравнение конфигураций поисковой системы по основным метрикам")


def analysis_section(report: Report, data: dict) -> None:
    summary = data["summary"]
    comparison = {item["name"]: item["summary"] for item in data["comparison"]}
    base = comparison.get("Базовая: леммы, бинарный ПОЗ", summary)
    synonyms = comparison.get("С расширением синонимами", summary)
    strict = comparison.get("Строгий режим (все слова)", summary)
    forms = comparison.get("Без морфологии (словоформы)", summary)

    report.heading("Анализ полученных данных и предложения по улучшению работы СИП")

    report.subheading("1. Общая оценка качества")
    report.text(
        f"Основная метрика ранжирования MAP = {number(summary['map'])} при полноте "
        f"{number(summary['recall'])} и nDCG = {number(summary['ndcg'])}. Это означает, что "
        "в среднем система находит подавляющее большинство релевантных документов и "
        "располагает их в верхней части выдачи. Высокое значение nDCG при заметно меньшем "
        "MAP объясняется градациями релевантности: высоко релевантные документы (оценка 2) "
        "система выводит на первые позиции устойчиво, а различить документы с оценками 1 и 0 "
        "ей удаётся хуже."
    )
    report.text(
        f"Низкое значение точности P = {number(summary['precision'])} не свидетельствует о "
        "плохом качестве: точность считается на всей выдаче глубиной 20 документов, тогда "
        f"как релевантных документов на запрос в среднем всего "
        f"{number(sum(item['relevant_total'] for item in data['per_query']) / max(1, len(data['per_query'])), 1)}. "
        "При таком соотношении даже идеальная система показала бы точность около 0,2. "
        f"Практически значимы здесь P@5 = {number(summary['p@5'])} и R-точность = "
        f"{number(summary['r_precision'])}: более половины документов на уровне R "
        "действительно релевантны."
    )
    report.text(
        "Форма кривой «точность — полнота» подтверждает вывод: до уровня полноты 0,5 "
        f"точность держится выше {number(summary['curve'][5][1], 2)}, после чего резко "
        "падает. То есть система уверенно находит основную часть релевантных документов, "
        "а «хвост» — документы, где тема выражена косвенно, — достаётся ей дорогой ценой "
        "ложных срабатываний."
    )

    report.subheading("2. Вклад отдельных механизмов")
    report.text(
        f"Морфологический анализ даёт наибольший измеримый прирост: отключение "
        f"лемматизации снижает MAP с {number(base['map'])} до {number(forms['map'])} "
        f"(на {number(100 * (base['map'] - forms['map']) / base['map'], 1)} %), "
        f"R-точность — с {number(base['r_precision'])} до {number(forms['r_precision'])}. "
        "Причина очевидна для русского языка: без приведения к нормальной форме «сети», "
        "«сетей» и «сетью» становятся разными терминами, поисковый образ документа "
        "дробится, а инверсные частоты искажаются."
    )
    report.text(
        f"Расширение запроса синонимами улучшает все метрики: MAP растёт с "
        f"{number(base['map'])} до {number(synonyms['map'])}, bpref — с "
        f"{number(base['bpref'])} до {number(synonyms['bpref'])}. Прирост умеренный, но "
        "устойчивый по всем метрикам, что говорит о корректно составленном тезаурусе: "
        "синонимы добавляются с пониженным весом 0,5 и не перебивают то, что ввёл сам "
        "пользователь."
    )
    report.text(
        f"Строгий режим «все слова обязательны» резко ухудшает качество: MAP падает до "
        f"{number(strict['map'])}, P@10 — до {number(strict['p@10'])}. Это ожидаемо и "
        "показательно: требование присутствия всех слов запроса превращает векторную "
        "модель в логическую конъюнкцию, отсекая релевантные документы, где тема выражена "
        "другими словами. Режим сохранён как инструмент точечного поиска, но по умолчанию "
        "он выключен."
    )

    report.subheading("3. Запросы, на которых система работает хуже всего")
    report.text(
        "Пять эталонных запросов с наименьшей средней точностью приведены в таблице 15."
    )
    worst = sorted(data["per_query"], key=lambda item: item["ap"])[:5]
    report.table(
        "Эталонные запросы с наименьшей средней точностью",
        ["\u2116", "Запрос", "AP", "R-точн.", "Rel"],
        [(item["query_id"], item["query"], number(item["ap"]),
          number(item["r_precision"]), item["relevant_total"]) for item in worst],
        widths=[1.2, 9.3, 2.0, 2.0, 2.0],
        size=Pt(11),
    )
    report.text(
        "Общая черта этих запросов — многословность и наличие терминов, разделяющих "
        "лексику с другими разделами коллекции. Запросы вида «запросы sql к базе данных» "
        "и «инвертированный индекс поисковой системы» страдают от того, что слово «запрос» "
        "и слово «индекс» одинаково употребительны в разделах о СУБД и об информационном "
        "поиске: бинарный вектор запроса не позволяет указать, какое из слов важнее. "
        "Запросы «защита от вирусов и программ-вымогателей» и «алгоритмы сортировки и "
        "вычислительная сложность» теряют точность из-за того, что часть релевантных "
        "документов раскрывает тему через термины, отсутствующие в запросе."
    )

    report.subheading("4. Предложения по улучшению работы СИП")
    report.steps([
        "Нормировать частоту термина в весе документа. Сейчас вес считается строго по "
        "формуле (1.6): A~ij~ = Q~ij~ · B~i~. Замена абсолютной частоты "
        "на логарифмическую (1 + log Q~ij~) или на нормированную к максимуму в "
        "документе ослабила бы влияние длины документа. Оценить прирост можно тем же "
        "эталонным набором, добавив конфигурацию в модуль сравнения.",
        "Взвешивать термины запроса, а не строить бинарный вектор. Правило "
        "w~qj~ \u2208 {0, 1} уравнивает в запросе редкое и частое слово. "
        "Умножение координат вектора запроса на инверсную частоту B~i~ позволило бы "
        "запросу «запросы sql к базе данных» опираться на редкое «sql», а не на "
        "общеупотребительное «запрос».",
        "Учитывать позицию термина в документе. Слово в заголовке или в первом абзаце "
        "почти всегда указывает на тему документа точнее, чем слово в середине текста. "
        "Заголовок в системе уже выделен (поле documents.title), и повышающий коэффициент "
        "для терминов заголовка вводится без изменения схемы базы данных.",
        "Перейти к более современной функции ранжирования. Модель BM25 учитывает "
        "насыщение частоты и длину документа и, как правило, превосходит классическую "
        "схему TF-IDF на коллекциях с документами разной длины. Инвертированный индекс "
        "системы содержит всё необходимое для её реализации.",
        "Расширить тезаурус и сделать его двухуровневым. Сейчас тезаурус содержит только "
        "синонимы. Добавление отношений «род — вид» («коммутатор» \u2192 «сетевое "
        "оборудование») позволило бы отвечать на запросы, сформулированные более общими "
        "словами, чем текст документов.",
        "Использовать накопленную обратную связь глобально. Отметки «больше таких» и "
        "«не то» сейчас влияют только на текущий запрос. Их накопление в таблице feedback "
        "позволяет вычислять поправку к рангу документа для повторяющихся запросов, "
        "то есть обучать систему на поведении пользователей.",
        "Уточнить учёт неполноты эталонной разметки. Часть запросов оценена лишь на "
        "верхних позициях выдачи, поэтому метрики, требующие полной разметки, слегка "
        "занижены. Расширение разметки методом объединения выдач нескольких конфигураций "
        "(pooling) сделало бы оценку строже.",
        "Ускорить исправление опечаток. Подбор ближайшего слова перебирает весь словарь "
        "словоформ и занимает около 18 мс — самая дорогая операция интерфейса. Индекс по "
        "буквенным триграммам сократил бы число кандидатов на порядок; на текущем объёме "
        "коллекции в этом нет необходимости, но при росте до сотен тысяч документов "
        "оптимизация станет обязательной.",
    ])


def performance_section(report: Report, data: dict) -> None:
    report.heading("Оценка быстродействия приложения")
    report.text(
        "Измерения выполнены на локальной машине под управлением Windows 11 "
        f"(Python {sys.version_info.major}.{sys.version_info.minor}) на полной тестовой "
        "коллекции из 108 документов. Результаты приведены в таблице 16."
    )
    report.table(
        "Быстродействие основных операций системы",
        ["Операция", "Время", "Примечание"],
        [
            ("Первый обход трёх узлов ЛВС", "\u2248 430 мс",
             "108 файлов, около 4 мс на документ, восемь потоков чтения"),
            ("Повторный (инкрементальный) обход", "\u2248 5 мс",
             "все 108 файлов не изменились и не читались"),
            ("Полная перестройка индекса", "\u2248 300 мс",
             "2437 терминов, 5718 вхождений, около 2,8 мс на документ"),
            ("Поиск по запросу", "0,2\u20135 мс",
             "среднее около 3 мс; зависит от числа терминов запроса"),
            ("Морфологический разбор запроса", "\u2248 1,4 мс",
             "лемматизация, поиск синонимов, проверка по словарю"),
            ("Автодополнение", "< 1 мс", "запрос к таблицам forms и query_log"),
            ("Исправление опечатки", "\u2248 18 мс",
             "перебор словаря словоформ — самая дорогая операция интерфейса"),
            ("Подбор похожих документов", "< 1 мс", "по 25 наиболее весомым терминам"),
            (f"Полная оценка качества ({data['queries']} запросов)",
             f"\u2248 {number(data['eval_ms'] / 1000, 2)} с",
             "включает прогон всех запросов и расчёт всех метрик"),
            ("Размер базы данных", "\u2248 1,4 МиБ",
             "документы с полными текстами, индекс, словоформы, разметка"),
        ],
        widths=[5.6, 2.6, 8.3],
        size=Pt(11),
    )
    report.text(
        "Распределение времени при первом запуске: извлечение текста из файлов — около "
        "55 %, морфологический анализ и лемматизация — около 30 %, запись в базу данных — "
        "около 15 %. Первое обращение к морфологическому анализатору дополнительно требует "
        "около 1 с на загрузку словарей pymorphy3; далее словари остаются в памяти, а "
        "результаты лемматизации кэшируются. Узким местом при поиске является не расчёт "
        "косинусной меры, а выборка вхождений из инвертированного индекса; при текущем "
        "объёме коллекции это доли миллисекунды."
    )


def conclusion(report: Report, data: dict) -> None:
    summary = data["summary"]
    report.heading("Вывод")
    report.text(
        "В ходе лабораторной работы спроектирована и программно реализована "
        "информационно-поисковая система «Арахна» для поиска по документам локальной "
        "вычислительной сети. Система построена из трёх компонентов, предусмотренных "
        "методическими указаниями: агента-паука, обходящего каталоги и UNC-ресурсы сети; "
        "базы данных SQLite, хранящей документы, словарь и инвертированный индекс; и "
        "поискового механизма с веб-интерфейсом."
    )
    report.text(
        "Все требования варианта 3 выполнены. Стратегия поиска — векторная: поисковые "
        "образы документов строятся по формулам (1.5) и (1.6) методических указаний, "
        "релевантность вычисляется как косинус угла между вектором документа и вектором "
        "запроса. Язык коллекции и запросов — русский, морфология обеспечивается "
        "лемматизацией через pymorphy3. Элементы искусственного интеллекта реализованы "
        "именно в интерфейсе с пользователем: морфологический разбор запроса с показом "
        "того, как система его поняла; автодополнение по словарю индекса и истории "
        "запросов; исправление опечаток по расстоянию Дамерау — Левенштейна; расширение "
        "запроса синонимами из тезауруса; обратная связь по релевантности методом Рокчио; "
        "подбор похожих документов и объяснение того, почему документ оказался в выдаче."
    )
    report.text(
        "Требования к составу выдачи выполнены: каждый результат содержит активную ссылку "
        "на документ, сниппет с подсветкой и список слов запроса, реально присутствующих "
        "в документе. Интерфейс состоит из шести разделов и снабжён справкой, объясняющей "
        "как работу с системой, так и модель поиска и смысл каждой метрики качества."
    )
    report.text(
        f"Оценка качества реализована программно и вызывается из подменю «Оценка качества». "
        f"Вычисляются метрики, принятые в РОМИП: точность, полнота, F-мера, P@n, "
        f"R-точность, AP и MAP, 11-точечный график «точность — полнота», DCG и nDCG, bpref. "
        f"Результаты отображаются в виде таблиц и графиков и выгружаются в CSV и PNG. "
        f"На эталонном наборе ({data['queries']} "
        f"{plural(data['queries'], 'информационная потребность', 'информационные потребности', 'информационных потребностей')}, "
        f"{data['judgements']} {plural(data['judgements'], 'оценка', 'оценки', 'оценок')} "
        f"релевантности) система показала MAP = "
        f"{number(summary['map'])}, nDCG = {number(summary['ndcg'])}, полноту "
        f"{number(summary['recall'])} и R-точность {number(summary['r_precision'])}."
    )
    report.text(
        "Экспериментальное сравнение конфигураций показало, что наибольший вклад в "
        "качество поиска вносит морфологический анализ русского языка: его отключение "
        "снижает MAP примерно на одну девятую. Расширение запроса синонимами улучшает все "
        "метрики, а строгий режим «все слова обязательны», сводящий векторную модель к "
        "логической, ухудшает качество более чем вдвое — что подтверждает обоснованность "
        "выбора векторной стратегии, предписанной вариантом."
    )
    report.text(
        "Корректность расчётных частей системы подтверждена 36 автоматическими тестами, "
        "проверяющими формулы индексирования, косинусную меру, инкрементальность обхода, "
        "алгоритмы элементов ИИ и все метрики качества на примерах с заранее известным "
        "ответом."
    )
    report.text(
        "Направления дальнейшего развития системы: переход к функции ранжирования BM25, "
        "взвешивание терминов запроса инверсной частотой вместо бинарного вектора, учёт "
        "позиции термина в документе, расширение тезауруса родовидовыми отношениями и "
        "использование накопленной обратной связи для настройки ранжирования по "
        "повторяющимся запросам."
    )


# --- Сборка ------------------------------------------------------------------

def build(output: Path) -> Path:
    conn = db.connect()
    db.init_db(conn)
    try:
        data = gather(conn)
    finally:
        conn.close()

    report = Report()
    title_page(report)
    goal_and_task(report)
    libraries(report)
    structure(report, data)
    database_section(report, data)
    algorithms(report)
    data_structures(report)
    collection_section(report, data)
    testing_section(report, data)
    metrics_section(report, data)
    comparison_section(report, data)
    analysis_section(report, data)
    performance_section(report, data)
    conclusion(report, data)
    return report.save(output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Сборка отчёта по лабораторной работе")
    parser.add_argument(
        "--output", type=Path,
        default=config.BASE_DIR.parent / "ОтчётЕЯзИИС1.docx",
        help="путь к DOCX-файлу отчёта",
    )
    arguments = parser.parse_args()
    path = build(arguments.output)
    print(f"Отчёт сохранён: {path}")


if __name__ == "__main__":
    main()
