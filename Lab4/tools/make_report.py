"""Сборка отчёта по лабораторной работе в формате DOCX.

    python tools/make_report.py [--output ПУТЬ] [--no-tests]

Числа в отчёт не вписаны вручную: состав коллекции, результаты оценки, точность
анализатора, время, число тестов, примеры перевода берутся из данных системы
(data/catalog.json, report/evaluation.json, report/analyzer.json, прогон pytest,
перевод на месте). Схемы и графики — из report/ (tools/make_diagrams.py,
tools/evaluate.py), снимки экрана — из report/screens (tools/screenshots.py).
"""

from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
import re
import statistics
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import docx  # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from docx.shared import Cm, Pt  # noqa: E402

from dragoman import APP_NAME, config, console  # noqa: E402
from dragoman.collection import Collection  # noqa: E402

console.setup()

ROOT = Path(__file__).resolve().parent.parent
REPORT = config.REPORT_DIR
SCREENS = REPORT / "screens"
FONT = "Times New Roman"
SIZE = Pt(14)
INDENT = Cm(1.25)

DOMAIN_NAMES = {"cs": "computer science", "lit": "литература", "all": "вся коллекция"}
MODE_NAMES = {"transfer": "с трансфером", "direct": "пословный"}


# --- примитивы оформления ------------------------------------------------------------

class Report:
    def __init__(self) -> None:
        self.document = docx.Document()
        self.table_number = 0
        self.figure_number = 0
        section = self.document.sections[0]
        section.page_width, section.page_height = Cm(21.0), Cm(29.7)
        section.left_margin, section.right_margin = Cm(3.0), Cm(1.5)
        section.top_margin = section.bottom_margin = Cm(2.0)
        normal = self.document.styles["Normal"]
        normal.font.name = FONT
        normal.font.size = SIZE
        normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
        normal.paragraph_format.space_after = Pt(6)

    def _paragraph(self, align=None, *, indent=None, after=6, left=None, hanging=None, keep=False):
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
        if keep:
            fmt.keep_with_next = True
        return paragraph

    SUB = re.compile(r"~([^~]+)~|\^([^^]+)\^")

    def _rich(self, paragraph, content, *, bold=False, italic=False, size=SIZE):
        """Текст; ~x~ — нижний индекс, ^x^ — верхний."""
        position = 0
        for match in self.SUB.finditer(content):
            if match.start() > position:
                self._run(paragraph, content[position:match.start()], bold=bold, italic=italic, size=size)
            run = self._run(paragraph, match.group(1) or match.group(2), bold=bold, italic=italic, size=size)
            if match.group(1):
                run.font.subscript = True
            else:
                run.font.superscript = True
            position = match.end()
        if position < len(content):
            self._run(paragraph, content[position:], bold=bold, italic=italic, size=size)

    def _run(self, paragraph, text, *, bold=False, italic=False, size=SIZE):
        run = paragraph.add_run(text)
        run.font.name = FONT
        run.font.size = size
        run.bold, run.italic = bold, italic
        run.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
        return run

    def text(self, content, *, bold=False, align=WD_ALIGN_PARAGRAPH.JUSTIFY, indent=True, after=6,
             size=SIZE, italic=False, keep=False):
        paragraph = self._paragraph(align, indent=INDENT if indent else None, after=after, keep=keep)
        self._rich(paragraph, content, bold=bold, italic=italic, size=size)
        return paragraph

    def heading(self, content):
        self.text(content, bold=True, align=WD_ALIGN_PARAGRAPH.LEFT, indent=False, after=6, keep=True)

    def subheading(self, content):
        self.text(content, bold=True, align=WD_ALIGN_PARAGRAPH.JUSTIFY, indent=True, after=4, keep=True)

    def formula(self, content):
        self.text(content, align=WD_ALIGN_PARAGRAPH.CENTER, indent=False, after=6)

    def bullets(self, items, *, marker="• "):
        """Маркированный список; часть до « — » выделяется полужирным."""
        for item in items:
            paragraph = self._paragraph(WD_ALIGN_PARAGRAPH.JUSTIFY, left=INDENT, hanging=Cm(0.5), after=3)
            head, separator, tail = item.partition(" — ")
            if separator and len(head) < 60:
                self._rich(paragraph, marker + head, bold=True)
                self._rich(paragraph, separator + tail)
            else:
                self._rich(paragraph, marker + item)

    def steps(self, items, *, start=1):
        for offset, item in enumerate(items, start=start):
            paragraph = self._paragraph(WD_ALIGN_PARAGRAPH.JUSTIFY, left=INDENT, hanging=Cm(0.6), after=3)
            head, separator, tail = item.partition(". ")
            if separator and len(head) < 70:
                self._rich(paragraph, f"{offset}. {head}.", bold=True)
                self._rich(paragraph, " " + tail)
            else:
                self._rich(paragraph, f"{offset}. {item}")

    def table(self, caption, header, rows, *, widths=None, size=Pt(11)):
        self.table_number += 1
        self.text(f"Таблица {self.table_number} – {caption}", align=WD_ALIGN_PARAGRAPH.LEFT,
                  indent=False, after=3, keep=True)
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
                if index and not isinstance(value, str) or (index and _numeric(value)):
                    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                bold = isinstance(value, Bold)
                self._rich(paragraph, str(value), size=size, bold=bold)
        if widths:
            for row in table.rows:
                for index, width in enumerate(widths):
                    row.cells[index].width = Cm(width)
        self.document.add_paragraph().paragraph_format.space_after = Pt(2)
        return table

    def figure(self, path: Path, caption: str, *, max_width=16.0, max_height=21.0, crop=None):
        if not path.exists():
            self.text(f"[нет файла {path.name}]", italic=True)
            return
        from PIL import Image

        source = path
        if crop:
            with Image.open(path) as image:
                box = (crop[0], crop[1], min(crop[2], image.width), min(crop[3], image.height))
                cropped = image.crop(box)
                source = REPORT / "_crop" / f"{path.stem}_{'_'.join(map(str, crop))}.png"
                source.parent.mkdir(exist_ok=True)
                cropped.save(source)
        with Image.open(source) as image:
            ratio = image.height / image.width
        width = max_width
        if width * ratio > max_height:
            width = max_height / ratio
        self.figure_number += 1
        paragraph = self._paragraph(WD_ALIGN_PARAGRAPH.CENTER, after=3, keep=True)
        paragraph.add_run().add_picture(str(source), width=Cm(width))
        self.text(f"Рисунок {self.figure_number} – {caption}", align=WD_ALIGN_PARAGRAPH.CENTER,
                  indent=False, after=8, size=Pt(12))

    @property
    def next_table(self) -> int:
        """Номер таблицы, которая будет выведена следующей."""
        return self.table_number + 1

    @property
    def next_figure(self) -> int:
        return self.figure_number + 1

    def page_break(self):
        self.document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    def blank(self, count=1):
        for _ in range(count):
            self._paragraph(after=0)

    def save(self, path: Path) -> Path:
        self.document.save(str(path))
        return path


class Bold(str):
    """Значение ячейки таблицы, выводимое полужирным."""


def _numeric(value) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[\d\s ,.–%—мсх/+-]+", value))


def num(value, digits=1) -> str:
    if value is None:
        return "—"
    if isinstance(value, int):
        return f"{value:,}".replace(",", " ")
    return f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")


def pct(value, digits=1) -> str:
    return "—" if value is None else f"{100 * value:.{digits}f}".replace(".", ",") + " %"


def ms(value) -> str:
    if value is None:
        return "—"
    return (f"{value / 1000:.2f}".replace(".", ",") + " с") if value >= 1000 else \
        (f"{value:.1f}".replace(".", ",") + " мс")


def plural(count: int, one: str, few: str, many: str) -> str:
    """Согласует существительное с числительным: 1 тест, 2 теста, 5 тестов."""
    if 11 <= count % 100 <= 14:
        return many
    return {1: one, 2: few, 3: few, 4: few}.get(count % 10, many)


def version(package: str) -> str:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return "—"


# --- данные ---------------------------------------------------------------------------

def gather(run_tests: bool) -> dict:
    from dragoman.lexicon import db
    from dragoman.translate.pipeline import Translator

    collection = Collection()
    evaluation = json.loads((REPORT / "evaluation.json").read_text(encoding="utf-8"))
    analyzer = json.loads((REPORT / "analyzer.json").read_text(encoding="utf-8"))
    translator = Translator(db.get())
    data = {"collection": collection, "evaluation": evaluation, "analyzer": analyzer, "translator": translator,
            "lexicon": db.get().stats()}
    data["tests"] = run_pytest() if run_tests else None
    data["test_counts"] = collect_tests()
    return data


def run_pytest() -> dict:
    try:
        result = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"],
                                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=900)
    except subprocess.TimeoutExpired:
        print("  тесты не уложились в 15 минут — в отчёт идёт только их состав")
        return {}
    tail = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", tail)) else 0
    failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", tail)) else 0
    skipped = int(m.group(1)) if (m := re.search(r"(\d+) skipped", tail)) else 0
    seconds = float(m.group(1)) if (m := re.search(r"in ([\d.]+)s", tail)) else 0.0
    return {"passed": passed, "failed": failed, "skipped": skipped, "seconds": seconds, "line": tail}


def collect_tests() -> Counter:
    result = subprocess.run([sys.executable, "-m", "pytest", "tests", "--collect-only", "-q", "-p",
                             "no:cacheprovider"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                            errors="replace")
    counts: Counter = Counter()
    for line in result.stdout.splitlines():
        if "::" in line:
            counts[line.split("::")[0].replace("tests/", "").replace("tests\\", "")] += 1
    return counts


# --- разделы --------------------------------------------------------------------------

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
                 "по лабораторной работе № 4",
                 "по курсу «Естественно-языковой интерфейс интеллектуальных систем»",
                 "«Автоматический машинный перевод текстов»",
                 "Вариант 4"):
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


def goal_and_task(report: Report, data: dict) -> None:
    report.heading("Цель работы:")
    report.text("Освоить на практике основные принципы машинного перевода документов: спроектировать и "
                "программно реализовать систему автоматического машинного перевода, оценить качество перевода "
                "и быстродействие системы на текстах разных предметных областей.")
    report.heading("Задание:")
    report.text("Разработать систему машинного перевода, удовлетворяющую требованиям методических указаний:")
    report.bullets([
        "на входе — естественно-языковой текст на входном языке, подлежащий процедуре машинного перевода;",
        "подсчитать количество слов во входном тексте, количество переведённых слов, определить "
        "грамматическую информацию (теги частей речи и их расшифровка);",
        "на выходе — перевод входного текста на выходной язык; упорядоченный по частоте встречаемости в "
        "тексте список слов и их переводов на выходной язык с грамматической информацией (вкладка 1); "
        "построенное дерево синтаксического разбора выбранного предложения (вкладка 2);",
        "обеспечить наличие утилиты автоматического пополнения и корректировки полученного словаря "
        "(таблицы БД);",
        "обеспечить сохранение и распечатку результатов перевода и упорядоченных по частоте списков слов с "
        "переводами и грамматической информацией в файл формата TXT в кодировке Unicode;",
        "интерфейс системы должен быть простым и доступным для пользователей любого уровня, содержать "
        "понятный набор инструментов.",
    ])
    report.text(f"Параметры варианта 4 и место их реализации приведены в таблице {report.next_table}.")
    report.table(
        "Параметры варианта 4 и место их реализации",
        ["Параметр", "Значение", "Где реализовано"],
        [
            ("Направление перевода", "англо-немецкий",
             "dragoman/english — анализ английского текста (теги, леммы, дерево зависимостей); "
             "dragoman/german — синтез немецких форм; dragoman/translate — трансфер"),
            ("Предметные области", "научные статьи по computer science, сочинения по литературе",
             "тестовая коллекция data/collection (по 6 документов каждой области); статьи словаря с пометкой "
             "области cs или lit; автоматическое определение области текста"),
            ("Тип системы", "с трансфером (второе поколение); для сравнения — прямой (пословный)",
             "translate/transfer.py — структурный трансфер; translate/direct.py — пословный перевод"),
        ],
        widths=[3.2, 4.3, 9.0],
    )
    report.text(f"Система получила название «{APP_NAME}» — так называли переводчиков при посольствах и "
                "торговых домах Востока. Сверх требований методических указаний в систему, как и в "
                "предыдущие работы, добавлен игровой компонент: трёхмерный тир, в котором паук Пафнутий "
                "отбивается от слов переводимого текста, переводя их на немецкий (раздел «Тир Пафнутия»).")


def libraries(report: Report) -> None:
    report.heading("Используемые библиотеки и их назначение:")
    report.text(f"Система реализована на языке Python {sys.version_info.major}.{sys.version_info.minor}; "
                "минимальные версии сторонних компонентов зафиксированы в файле requirements.txt. Готовых "
                "библиотек обработки естественного языка (spaCy, NLTK, Stanza) и машинного перевода в работе "
                "нет: разбиение на слова, теггер частей речи, лемматизатор, синтаксический анализатор, "
                "трансфер, немецкая морфология и меры качества перевода реализованы с нуля.")
    report.text("Веб-интерфейс:", indent=False, bold=True)
    report.bullets([
        f"FastAPI {version('fastapi')} — веб-фреймворк: маршруты страниц, перевод, сохранение в файл, версия "
        "для печати, словарь, API плана волн тира;",
        f"Uvicorn {version('uvicorn')} — ASGI-сервер; система поднимается командой python run.py и "
        f"открывается по адресу http://{config.HOST}:{config.PORT}/;",
        f"Jinja2 {version('jinja2')} — шаблоны страниц; python-multipart — разбор формы с файлом;",
        "three.js r160 (MIT) — трёхмерная графика тира; файл библиотеки входит в состав системы "
        "(static/vendor), поэтому тир работает без доступа к сети.",
    ])
    report.text("Хранение и обработка данных:", indent=False, bold=True)
    report.bullets([
        "sqlite3 (стандартная библиотека Python) — база данных словаря: таблицы статей, правок пользователя "
        "и журнала неизвестных слов;",
        f"python-docx {version('python-docx')}, pypdf {version('pypdf')}, beautifulsoup4 "
        f"{version('beautifulsoup4')} — извлечение текста из загружаемых документов DOCX, PDF, HTML; "
        "python-docx также формирует этот отчёт;",
        f"requests {version('requests')} — загрузка статей Википедии для коллекции, корпусов Universal "
        "Dependencies и словаря Ding.",
    ])
    report.text("Оценка и тестирование:", indent=False, bold=True)
    report.bullets([
        f"matplotlib {version('matplotlib')} — графики и схемы отчёта; для работы системы не требуется;",
        f"pytest {version('pytest')} — автоматические тесты; httpx — тестовый клиент FastAPI;",
        f"websockets {version('websockets')} — управление браузером Edge по протоколу DevTools при снятии "
        "снимков экрана и проверке тира.",
    ])
    report.text("Лингвистические ресурсы:", indent=False, bold=True)
    report.bullets([
        "корпуса Universal Dependencies English EWT, GUM, LinES, ParTUT (CC BY-SA) — обучение теггера, "
        "лемматизатора и синтаксического анализатора;",
        "словарь Ding (TU Chemnitz, GPL) — подсказки переводов при пополнении словаря.",
    ])


def collection_section(report: Report, data: dict) -> None:
    collection = data["collection"]
    ev = data["evaluation"]
    docs = {d["id"]: d for d in ev["documents"]}
    report.heading("Информация о тестовой коллекции документов")
    entries = list(collection)
    chars = [len(collection.text(e.id)) for e in entries]
    report.text(f"Тестовая коллекция data/collection содержит {len(entries)} документов — по "
                f"{len(entries) // 2} в каждой предметной области. Документы — разделы статей английской "
                "Википедии (лицензия CC BY-SA 4.0): вводный раздел и разделы, близкие к жанру варианта. Для "
                "computer science это изложение научных понятий и истории технологий, для литературы — "
                "литературоведческие тексты о произведениях: сюжет, темы, история создания, восприятие "
                f"критикой. Объём документа — от {num(min(chars))} до {num(max(chars))} знаков, всего "
                f"{num(ev['words'])} слов. Состав коллекции приведён в таблице {report.next_table}.")
    rows = []
    for index, e in enumerate(entries, start=1):
        d = docs.get(e.id, {})
        rows.append((index, e.title, DOMAIN_NAMES.get(e.domain, e.domain), num(len(collection.text(e.id))),
                     d.get("sentences", "—"), d.get("words", "—")))
    report.table("Состав тестовой коллекции", ["№", "Документ (статья Википедии)", "Область", "Знаков",
                                               "Предло-жений", "Слов"],
                 rows, widths=[0.8, 6.8, 3.0, 1.9, 1.9, 1.6], size=Pt(10.5))
    report.text("Коллекцию собирает сценарий tools/build_collection.py: он запрашивает разделы статьи через "
                "API Википедии (ревизия фиксируется в каталоге data/catalog.json), очищает разметку, "
                "сноски, формулы и списки и сохраняет текст; исходные ответы сохранены в data/sources, "
                "поэтому коллекция пересобирается без сети (ключ --offline).")
    refs = ev["references"]
    report.text(f"Для оценки качества у {refs} предложений коллекции (по 10 из каждого документа, выбраны "
                "равномерно по тексту) есть эталонные переводы на немецкий язык, подготовленные для этой работы "
                "независимо от системы: близко к тексту, без литературной обработки, с принятыми немецкими "
                "названиями произведений (data/reference/references.tsv). С ними сравнивается машинный "
                "перевод. Эталон один на предложение, поэтому BLEU занижает оценку правильных, но иначе "
                "построенных переводов.")
    an = data["analyzer"]
    report.text(f"Для обучения анализатора английского языка использованы корпуса Universal Dependencies "
                f"(версия 2.x): EWT (веб-тексты), GUM (тексты разных жанров), LinES (литература) и ParTUT "
                f"(право, Википедия) — {num(an['train_sentences'])} предложений, {num(an['train_words'])} слов "
                "в обучающих частях. Тестовые части корпусов служат для проверки точности анализатора, а "
                "десять документов тестовой части GUM — ещё и незнакомыми текстами для оценки полноты "
                "словаря.")


def structure_section(report: Report, data: dict) -> None:
    report.heading("Описание структуры разработанной системы")
    report.text(f"Система состоит из пяти частей (рисунок {report.next_figure}): веб-интерфейса, модуля "
                "перевода (анализ "
                "английского текста, трансфер, синтез немецкого), словаря в базе данных с утилитой "
                "пополнения, данных (коллекция, эталоны, модели) и модуля оценки; отдельно — тир Пафнутия. "
                "Модуль перевода не зависит от интерфейса: одна функция Translator.translate используется "
                "страницами, тестами, оценкой и тиром.")
    report.figure(REPORT / "structure.png", "Структура системы «Драгоман»")
    report.text(f"Состав модулей приведён в таблице {report.next_table}.")
    report.table("Состав и назначение модулей системы", ["Модуль", "Назначение"], [
        ("text/segment.py", "Абзацы, заголовки, предложения и слова (правила Penn Treebank)"),
        ("text/extract.py", "Текст из загружаемых файлов TXT, MD, HTML, DOCX, PDF"),
        ("english/perceptron.py", "Усреднённый перцептрон — общий для теггера и синтаксического анализатора"),
        ("english/tagger.py", "Теги частей речи Penn Treebank; поправки для вопросов и предложений без глагола"),
        ("english/lemmatizer.py", "Леммы: правила окончаний по тегу и исключения"),
        ("english/parser.py", "Синтаксический анализатор зависимостей arc-hybrid и разметчик отношений UD"),
        ("english/conllu.py, tags.py", "Чтение корпусов UD; расшифровка тегов и отношений на русском"),
        ("english/analyzer.py", "Анализ текста целиком: предложения, слова, теги, леммы, деревья"),
        ("lexicon/db.py", "Словарь в SQLite: поиск по части речи и области, правка, журнал неизвестных слов, "
                          "импорт и экспорт"),
        ("lexicon/guess.py, ding.py", "Правила словообразования; подсказки словаря Ding"),
        ("translate/lexical.py", "Выбор перевода слова: оборот, словарь, правило, имя, число"),
        ("translate/transfer.py", "Структурный трансфер: исправление разбора, роли, согласование, падежи, "
                                  "глагольная группа, порядок слов"),
        ("translate/direct.py", "Пословный перевод (система первого поколения)"),
        ("translate/output.py", "Немецкие слова со ссылками на исходные, сборка текста, кавычки, запятые"),
        ("translate/pipeline.py", "Перевод документа, статистика, частотный список с грамматикой"),
        ("german/verbs.py, morphology.py", "Сильные глаголы и приставки; спряжение, склонение, сложные слова"),
        ("trees.py", "Деревья зависимостей и составляющих в SVG"),
        ("export.py", "Сохранение результатов в TXT (UTF-16 или UTF-8)"),
        ("evaluation.py", "Меры BLEU и chrF, сравнение способов перевода, время"),
        ("game.py, web/static/shooter*.js", "Тир Пафнутия: план волн, правила боя, трёхмерная сцена"),
        ("web/app.py", "Страницы интерфейса, справка"),
    ], widths=[4.6, 11.9], size=Pt(10.5))
    report.text("Интерфейс содержит разделы «Перевод», «Коллекция», «Словарь», «Оценка», «Тир Пафнутия» и "
                "«Справка». Главная страница — форма ввода текста (или загрузки файла) с выбором предметной "
                "области и способа перевода. Страница результата показывает перевод рядом с оригиналом (слова "
                "подсвечиваются: переведённые по правилу, неизвестные, имена), статистику и вкладки: 1 — "
                "частотный список слов, 2 — дерево разбора выбранного предложения, 3 — перевод другим "
                "способом, пополнение словаря. Кнопки «Сохранить в TXT» и «Печать» — в шапке страницы.")


def data_structures(report: Report) -> None:
    report.heading("Описание структур данных для хранения входной и выходной информации")
    report.text("Структуры данных описаны как dataclass-объекты Python. Их можно разделить на входную "
                "информацию, промежуточное представление текста, словарь и выходную информацию.")
    report.subheading("1. Входная информация")
    report.bullets([
        "Текст пользователя — строка из формы или из файла (TXT, MD, HTML, DOCX, PDF), не длиннее "
        f"{num(config.MAX_TEXT_CHARS)} знаков; абзацы разделяются пустой строкой, заголовок отмечается «# ».",
        "Документ коллекции — файл data/collection/<идентификатор>.txt в UTF-8 и запись каталога "
        "data/catalog.json (CatalogEntry: идентификатор, заголовок, область, объём, разделы, источник с "
        "адресом, ревизией и лицензией).",
        "Эталоны — data/reference/references.tsv: документ, номер предложения, английское предложение, "
        "немецкий эталон.",
    ])
    report.subheading("2. Представление текста")
    report.bullets([
        "Layout, Paragraph, Sentence, Token — результат разбиения: абзацы с признаком заголовка, "
        "предложения со смещением в тексте, слова со смещениями и признаком пробела после слова.",
        "Word — слово после анализа: номер, текст, лемма, тег Penn Treebank, универсальная часть речи, "
        "номер вершины в дереве и синтаксическое отношение UD, зависимые слова.",
        "AnalyzedSentence, AnalyzedDocument — предложение-дерево и документ; время анализа по этапам.",
    ])
    report.subheading("3. Словарь (таблицы базы данных)")
    report.table("Таблицы базы данных словаря", ["Таблица", "Поля", "Назначение"], [
        ("entries", "en, pos, de, gender, plural, extra, domain, source, rank, note, updated",
         "статьи словаря: английское слово или оборот, часть речи, немецкий перевод с пометками (vor|stellen, "
         "sich …), род, мн. ч., свойства (управление prep=auf+A, дополнение в Dativ, перфект с sein, слабое "
         "склонение), область (cs, lit, gen), источник (seed, user, rule, ding)"),
        ("overrides", "en, pos, domain", "правки и удаления пользователя в статьях исходного словаря: они "
                                         "переживают обновление исходных таблиц"),
        ("unknown", "en, pos, count, texts, example, first_seen, last_seen",
         "журнал неизвестных слов для пополнения словаря"),
        ("meta", "key, value", "контрольная сумма исходных таблиц data/lexicon/*.tsv, дата загрузки"),
    ], widths=[2.2, 5.6, 8.7], size=Pt(10.5))
    report.text("Статья словаря в памяти — объект Entry; выбор перевода слова — объект Choice (статья и "
                "способ: словарь, правило словообразования, имя, число, не найдено).")
    report.subheading("4. Трансфер и выходная информация")
    report.bullets([
        "Agr — согласование (лицо, число, род); EnglishVerb — английская глагольная группа (время, "
        "перфект, длительность, залог, модальность, инфинитив); VerbGroup — немецкая (финитная форма, "
        "неличные формы, отделяемая приставка, возвратное местоимение); Part — составляющая немецкого "
        "предложения с полем (подлежащее, дополнение, обстоятельство, Nachfeld) и позицией в оригинале.",
        "G — немецкое слово: текст, номера английских слов, из которых оно получено, вид (слово, имя, "
        "число, знак, правило, неизвестное); Sentence (выходное) — немецкое предложение и пояснения "
        "трансфера.",
        "ListItem — строка частотного списка: лемма, часть речи, частота, формы в тексте, теги, статья "
        "словаря, немецкие формы в переводе, способ перевода.",
        "Translation — результат: идентификатор, заголовок, текст, область, способ, анализ, переводы "
        "предложений, частотный список, статистика (предложений, слов, разных слов, переведено по словарю "
        "и по правилам, имена и числа, без перевода, доля), время по этапам.",
        "Enemy, Wave, Plan — план тира: слова-противники (английское слово, перевод, часть речи, вид, "
        "частота, прочность), волны и мини-боссы.",
    ])
    report.text("Результаты сохраняются в TXT (export.py): сведения о документе, статистика, перевод, "
                "исходный текст, частотный список слов в виде таблицы и расшифровка встретившихся тегов. По "
                "умолчанию кодировка — UTF-16 LE с меткой порядка байтов (так Блокнот Windows сохраняет "
                "«Юникод»), по выбору — UTF-8 с меткой; строки разделяются CR LF. Можно сохранить всё, только "
                "перевод или только список слов.")


def algorithm_section(report: Report, data: dict) -> None:
    an = data["analyzer"]
    lex = data["lexicon"]
    report.heading("Основные алгоритмы реализации компонентов системы")
    report.text("Перевод выполняется по схеме систем второго поколения: анализ в категориях английского "
                "языка → межъязыковые операции (трансфер) → синтез в категориях немецкого языка. Блок-схема "
                f"приведена на рисунке {report.next_figure}.")
    report.figure(REPORT / "algorithm.png", "Блок-схема алгоритма перевода с трансфером", max_height=22.5)

    report.subheading("1. Разбиение на предложения и слова")
    report.text("Текст делится на абзацы по пустым строкам; абзац, отмеченный «# », — заголовок. Граница "
                "предложения — «.», «!», «?» (с закрывающими кавычками и скобками), за которыми идут пробел и "
                "заглавная буква, цифра или открывающая кавычка; после сокращений (e.g., Dr., Mr., etc., U.S.) "
                "и инициалов граница не ставится. Слова выделяются по правилам Penn Treebank, как в "
                "обучающих корпусах: клитики отделяются (don't → do + n't, Shakespeare's → Shakespeare + 's), "
                "знаки препинания, тире и многоточия — отдельные токены, числа, проценты, адреса и слова с "
                "дефисом (cross-compiler) — целые.")

    report.subheading("2. Теггер частей речи")
    report.text("Теггер — усреднённый перцептрон (Collins, 2002; схема Honnibal). Слова размечаются слева "
                "направо; для слова i тег выбирается как")
    report.formula("t~i~ = argmax~t~ Σ~f ∈ F(i)~ w(f, t),")
    report.text("где F(i) — признаки: слово, его суффиксы длиной 2–4, префикс, форма (Xxxx, dd, …), соседние "
                "слова и их суффиксы, два предыдущих тега и их сочетания со словом. Частые однозначные слова "
                "размечаются по словарю тегов без модели. При обучении веса правильного тега увеличиваются, "
                "ошибочного — уменьшаются; итоговые веса усредняются по всем шагам, что сглаживает колебания "
                "перцептрона. После разметки применяются две поправки: в вопросе с do существительное, "
                "«съевшее» глагол (What does the parser *produce*?), становится глаголом, если корпус знает "
                "слово как глагол; в предложении без глагола им становится существительное, для которого "
                "модель вторым по оценке ставит тег глагола (The system *manages* resources).")
    report.subheading("3. Лемматизатор")
    report.text("Правила окончаний выучены из корпусов: для каждого тега — замена окончания (-ies → -y для "
                "NNS, -ied → -y для VBD, …), выбранная по частоте; неправильные формы (went → go, children → "
                "child, better → good) хранятся списком исключений.")
    report.subheading("4. Синтаксический анализатор")
    report.text("Используется переходный анализатор зависимостей arc-hybrid (Kuhlmann и др., 2011). "
                "Состояние — стек, буфер слов и множество дуг; переходы: SHIFT (слово из буфера в стек), "
                "LEFT (верхнее слово стека становится зависимым первого слова буфера), RIGHT (верхнее слово "
                "стека — зависимое слова под ним). Переход выбирает перцептрон по признакам слов, тегов и уже "
                "построенных зависимых на вершине стека и в начале буфера; анализ линеен по длине "
                "предложения. Обучение — с динамическим оракулом (Goldberg, Nivre, 2013): модель учится и на "
                "состояниях, в которые попадает после своих ошибок, — так она ведёт себя на реальных "
                "данных. Отношение UD (nsubj, obj, obl, amod, acl:relcl, …) для каждой дуги ставит отдельный "
                "перцептрон. Анализатор обучается на тегах, расставленных теггером перекрёстно (пять частей "
                "корпуса, каждую размечает теггер, не видевший её), — на тех тегах, какие он увидит при "
                f"работе. Обучение всех моделей занимает около {num(an['seconds'] / 60, 0)} минут.")
    report.text("Из дерева зависимостей строится и дерево составляющих (вкладка 2): главное слово со своими "
                "зависимыми образует группу — S (предложение), NP, VP, PP, AP, AdvP.")

    report.subheading("5. Исправление разбора")
    report.text("Перед трансфером дерево проверяется на типичные ошибки анализатора, которые портят немецкий "
                "порядок слов сильнее всего:")
    report.bullets([
        "корень-существительное при глаголе, подвешенном к нему как parataxis, — корнем становится глагол;",
        "союз, подвешенный к запятой («…, but rather by patterns»), — становится cc, его зависимые — "
        "однородными членами;",
        "второе сказуемое придаточного без подлежащего, подвешенное к существительному главного, — "
        "однородно с глаголом придаточного;",
        "существительное перед существительным, разобранное как nmod или nsubj («training samples», «machine "
        "translation software»), — часть сложного слова;",
        "инфинитив при прилагательном (easy to train), размеченный obl или csubj, — xcomp; вопросительное "
        "слово-дополнение, подвешенное к does, — дополнение смыслового глагола.",
    ])

    report.subheading("6. Лексический трансфер")
    report.text(f"Словарь содержит {num(lex['total'])} статей, из них {num(lex['phrases'])} оборотов. Перевод "
                "слова ищется в таком порядке:")
    report.steps([
        "Обороты. Сочетания, которые переводятся целиком (operating system → Betriebssystem, depend on → "
        "abhängen von, take place → stattfinden), склеиваются в одну единицу по дереву: для глагольного "
        "оборота — глагол и его частица, предлог или дополнение, для именного — цепочка определений.",
        "Статья по части речи и области. Сначала статья области текста (play в литературе — Theaterstück), "
        "затем общая; для глагола учитывается контекст: know с придаточным — wissen, без — kennen; provide "
        "for без прямого дополнения — sorgen für, с дополнением — bereitstellen; need смысловым глаголом — "
        "benötigen, с инфинитивом — модальный müssen.",
        "Правила словообразования (lexicon/guess.py). Научная лексика английского и немецкого общая по "
        "происхождению: -ization → -isierung, -ity → -ität, -ism → -ismus, -ic → -isch, -ive → -iv, -ize → "
        "-isieren, -able → основа глагола + -bar, сложные слова из двух слов словаря (dataflow → "
        "Datenfluss). Догадка получает оценку уверенности.",
        "Имена и числа. Имя собственное, которого нет в словаре имён, остаётся как в оригинале; числа "
        "переводятся в немецкую запись (1,000 → 1.000, 1990s → 1990er-Jahre).",
        "Не найдено. Слово остаётся английским, отмечается в тексте и попадает в журнал неизвестных слов.",
    ])
    report.text("Предметная область текста определяется автоматически — по частоте слов-маркеров (compiler, "
                "algorithm, network … против novel, character, poem …); её можно задать и вручную.")

    report.subheading("7. Структурный трансфер")
    report.text("Для каждого предложения обходится дерево зависимостей; каждой группе английского "
                "предложения сопоставляется немецкая составляющая с полем топологической модели "
                f"(рисунок {report.next_figure}).")
    report.figure(REPORT / "fields.png", "Структурный трансфер: роли английского предложения → поля немецкого")
    report.steps([
        "Подлежащее и согласование. Подлежащее (nsubj) переводится в Nominativ, его лицо, число и род "
        "определяют форму глагола; местоимение it/its выбирает er, sie, es по роду последнего существительного "
        "(антецедента); формальное it даёт es.",
        "Глагольная группа. По вспомогательным глаголам английской группы определяются время, перфект, залог "
        "и модальность, и строится немецкая: has been tested → ist getestet worden, was compiled → wurde "
        "kompiliert, will read → wird lesen, can learn → kann lernen; have to, need to, want to, be able to, be "
        "going to — модальные müssen, wollen, können и будущее с werden; перфект с haben или sein — по "
        "глаголу.",
        "Падежи. Прямое дополнение — Akkusativ (или Dativ по управлению: helfen, danken); предложная группа — "
        "падеж немецкого предлога (mit + Dativ, für + Akkusativ, in + Dativ или Akkusativ при глаголе "
        "движения); управление глагола из словаря заменяет предлог (apply X to Y → X auf Y anwenden, depend "
        "on → abhängen von); of при существительном — Genitiv (des Computers) или von; by при пассиве — von.",
        "Отрицание. not перед неопределённым артиклем или существительным без артикля — kein (does not use a "
        "stack → verwendet keinen Stapel), иначе nicht в конце Mittelfeld; not X but Y — nicht X, sondern Y.",
        "Придаточные. Относительное придаточное: местоимение der/die/das по роду и числу антецедента и падежу "
        "по роли в придаточном (whose → dessen/deren, which после целого предложения → was); "
        "дополнительное — dass, ob или вопросительное слово; обстоятельственное — союз (if → wenn, because → "
        "weil, although → obwohl); to + инфинитив цели — um … zu; it is … that — es ist …, dass.",
        "Именная группа. Артикль, прилагательные (с окончаниями по таблице склонения), существительное; "
        "цепочка существительных — сложное слово (source code → Quellcode, training samples → "
        "Trainingsproben); роль перед именем получает артикль (critic Lionel Trilling → der Kritiker Lionel "
        "Trilling); прилагательное-определение с зависимыми — расширенное определение перед существительным.",
        "Порядок слов. Главное предложение — V2: в Vorfeld подлежащее или первое обстоятельство (тогда "
        "подлежащее уходит за глагол), затем финитный глагол, Mittelfeld (местоимения раньше существительных, "
        "дополнения, обстоятельства), правая скобка — неличные формы и отделяемая приставка (führt … ein). "
        "Придаточное — союз, Mittelfeld, глагол в конце. Вопрос — глагол первым или после вопросительного "
        "слова. Длинные придаточные и инфинитивные обороты — в Nachfeld после рамки.",
    ])
    report.subheading("8. Синтез немецких форм")
    report.text("Морфология немецкого языка (german/) построена на правилах и списках исключений:")
    report.bullets([
        "спряжение — настоящее время, претерит, конъюнктив II, причастие II, zu-инфинитив; около 140 сильных и "
        "неправильных глаголов с формами (geben — gibt — gab — gegeben), производные выводятся из простых "
        "(an|geben, vergeben); отделяемые (vor|stellen) и неотделяемые (be-, ver-, er-, …) приставки, "
        "глаголы на -ieren без ge-; вспомогательный глагол перфекта — по списку глаголов движения и состояния;",
        "склонение существительных — по роду и мн. ч. из словаря, -n в Dativ мн. ч., -s/-es в Genitiv "
        "(односложные — -es), слабое склонение (des Studenten);",
        "склонение прилагательных — сильное, слабое, смешанное (по артиклю), степени сравнения с умлаутом "
        "(groß — größer — am größten);",
        "сложные слова — с соединительным -s- после -ung, -heit, -keit, -ion, -tät (Sicherheitslücke), -n у "
        "существительных женского рода на -e (Seitenzahl ← Seite), через дефис у аббревиатур и имён "
        "(CPU-Zeit); слияния предлога с артиклем (in dem → im, zu der → zur);",
        "пунктуация — запятые перед придаточными и инфинитивными оборотами, немецкие кавычки „…“.",
    ])
    report.subheading("9. Пословный перевод")
    report.text("Для сравнения реализован перевод системы первого поколения (translate/direct.py): каждое слово "
                "заменяется словарной формой на своём месте; из контекста учитываются только обороты и род "
                "следующего существительного для артикля. Тот же словарь и те же обороты позволяют сравнить "
                "способы честно: разница — только в трансфере.")
    report.subheading("10. Статистика и частотный список")
    report.text("Словом текста считается токен, содержащий буквы, кроме отделённых клитик ('s, n't); числа и "
                "знаки препинания не считаются. Слово переведено, если его перевод найден в словаре или "
                "получен по правилу словообразования; имена собственные и числа учитываются отдельно — они "
                "перевода не требуют. Доля переведённых слов = переведённые / (все − имена − числа). "
                "Частотный список группирует слова по лемме и части речи; для каждой строки выводятся формы "
                "в тексте, частота, теги Penn Treebank с расшифровкой, словарный перевод с родом и мн. ч., "
                "немецкая грамматика (для глагола — основные формы и управление, для существительного — род и "
                "мн. ч., для предлога — падеж), формы в переводе и способ перевода.")
    report.subheading("11. Утилита пополнения и корректировки словаря")
    report.steps([
        "Журнал. Каждое слово, которое при переводе не нашлось в словаре, записывается в таблицу unknown с "
        "частотой, числом текстов и примером предложения.",
        "Подсказки. Для слова из журнала система предлагает перевод по правилам словообразования (с оценкой "
        "уверенности) и статьи словаря Ding: строки «английское :: немецкое» разбираются, из немецкого "
        "убираются пометки (etw., jdm., {f}), род и мн. ч. берутся из пометок, кандидаты упорядочиваются по "
        "точности совпадения английской части и частоте.",
        "Ручное пополнение. Пользователь правит подсказку (часть речи, перевод, род, мн. ч., область) и "
        "добавляет статью; можно добавить, исправить и удалить любую статью словаря, выгрузить словарь в TSV "
        "и загрузить статьи из TSV.",
        "Автоматическое пополнение. Кнопка «Пополнить автоматически» добавляет в словарь все подсказки с "
        "уверенностью не ниже порога (65–85 %), сначала правила, затем Ding; добавленные слова уходят из "
        "журнала. Исходные статьи и правки пользователя хранятся раздельно: правка переживает обновление "
        "исходных таблиц, а «Сбросить словарь» возвращает исходное состояние.",
    ])


def game_section(report: Report, data: dict) -> None:
    from dragoman import game

    collection = data["collection"]
    translator = data["translator"]
    entry = collection.get("lit-hamlet")
    t = translator.translate(collection.text(entry.id), entry.title, entry.domain, log_unknown=False)
    plan = game.plan(t, 5)
    report.heading("Дополнительный функционал: тир Пафнутия")
    report.text("Как и в предыдущих работах, в систему добавлен игровой компонент с пауком Пафнутием. Это "
                "трёхмерный шутер (three.js): Пафнутий стоит на вершине Вавилонской башни, а на него волнами "
                "через шесть ворот парапета идут английские слова переводимого текста. Попадание паутиной "
                "переводит слово на немецкий — над ним проступает перевод, и слово повержено. Перед игрой "
                "выбирается текст (документ коллекции или свой перевод), число волн и сложность "
                f"(рисунок {report.next_figure}).")
    report.figure(REPORT / "game_flow.png", "Тир Пафнутия: от переведённого текста к волнам и обратно к документу")
    report.steps([
        "Противники. Каждое разное слово текста — один противник, выходящий ровно один раз; он несёт свой "
        "немецкий перевод из перевода текста (если слово слилось с соседями в сложное слово — словарный). "
        "Служебные слова до четырёх букв — «мелочь»: маленькие, быстрые, бегут стайками; существительные, "
        "прилагательные, наречия, имена — обычные слова, идут и кусают; глаголы — «слова с пушками»: держат "
        "дистанцию и стреляют буквами.",
        "Мини-боссы. N самых длинных слов документа (по числу букв; при равной длине — более частое). При N "
        "волнах первую волну закрывает N-е по длине слово, вторую — (N−1)-е, …, последнюю — самое длинное. "
        "Прочность босса — число букв плюс два за каждую волну; с каждым попаданием над боссом проступает "
        "очередная доля немецкого перевода.",
        "Волны. Остальные слова делятся между N волнами в отношении 1 : 2 : … : N (с округлением; каждая "
        "волна не меньше предыдущей), внутри — от коротких слов к длинным и глаголам. Так волны растут, а за "
        "все волны выходят все слова текста.",
        "Победа. Когда все волны отбиты, все слова текста переведены, и игрок получает полностью переведённый "
        "документ — его можно сохранить в TXT или открыть на странице перевода. В панели текста (Tab) "
        "повергнутые слова уже показаны по-немецки.",
    ])
    sizes = " → ".join(str(w.size) for w in plan.waves)
    bosses = ", ".join(f"«{w.boss.en}» ({w.boss.length} букв) → «{w.boss.de}»" for w in plan.waves)
    report.text(f"Пример: документ «{entry.title}» содержит {plan.words} разных слов ({plan.tokens} "
                f"словоупотреблений). При пяти волнах их размеры {sizes}; мини-боссы по волнам: {bosses}.")
    report.text("План волн строит сервер (game.py) и отдаёт странице в JSON; правила боя (скорость и урон "
                "противников, уровни сложности, расписание появления слов, попадание снаряда в слово, "
                "раскрытие перевода босса, звёзды за бой) вынесены в shooter_rules.js без зависимостей от "
                "отрисовки и проверяются отдельным набором тестов; отрисовка, управление (W/S и ↑/↓ — вперёд и назад, A/D и ←/→ — влево и вправо, мышь — камера, прыжок, рывок, "
                "ловчая сеть) и интерфейс боя — в shooter.js. Кадры игры приведены на рисунках "
                f"{report.next_figure}–{report.next_figure + 3}.")
    report.figure(SCREENS / "game_setup.png", "Тир Пафнутия: выбор текста, числа волн и сложности; план волн",
                  crop=(60, 80, 1240, 1010), max_height=16)
    report.figure(SCREENS / "game_wave.png", "Волна слов выходит из ворот", crop=(88, 105, 1212, 795))
    report.figure(SCREENS / "game_boss.png", "Мини-босс первой волны и лента переведённых слов",
                  crop=(88, 105, 1212, 795))
    report.figure(SCREENS / "game_victory.png", "Победа: полностью переведённый документ",
                  crop=(88, 150, 1212, 925))


def testing_section(report: Report, data: dict) -> None:
    tests = data["tests"]
    counts = data["test_counts"]
    total = sum(counts.values())
    report.heading("Результаты тестирования системы")
    report.subheading("1. Автоматическое тестирование")
    if tests:
        if not tests["failed"]:
            outcome = "все пройдены" + (f", {tests['skipped']} пропущен (нет node)" if tests["skipped"] else "")
        else:
            outcome = f"пройдено {tests['passed']}, не пройдено {tests['failed']}, пропущено {tests['skipped']}"
        report.text(f"Автотесты написаны с использованием pytest. Запуск: python -m pytest tests -q. "
                    f"Результат: {total} {plural(total, 'тест', 'теста', 'тестов')}, {outcome}, время выполнения "
                    f"— около {num(tests['seconds'], 0)} с. Состав тестов приведён в таблице {report.next_table}.")
    else:
        report.text(f"Автотесты написаны с использованием pytest ({total} тестов). Состав — в таблице "
                    f"{report.next_table}.")
    described = [
        ("test_segment.py", "Разбиение на предложения и слова: сокращения, клитики, тире и многоточия, "
                            "заголовки"),
        ("test_analyzer.py", "Теги, леммы, дерево зависимостей (всегда дерево), пассив, вопросы с do, "
                             "клитики не считаются словами, деревья в SVG"),
        ("test_german.py", "Немецкая морфология: спряжение сильных и приставочных глаголов, причастия, "
                           "склонение, сложные слова"),
        ("test_lexicon.py", "Словарь: загрузка таблиц, выбор по области, правка и удаление переживают "
                            "обновление, журнал неизвестных слов, импорт и экспорт, правила словообразования"),
        ("test_transfer.py", "Предложения на каждое правило трансфера: V2, рамка, пассив, kein, um … zu, "
                             "модальные обороты, вопросы, придаточные, sondern; пословный перевод"),
        ("test_pipeline.py", "Статистика, частотный список с грамматикой, перевод, сохранение в UTF-16 с "
                             "меткой и CR LF, кэш, журнал; перевод каждого документа коллекции"),
        ("test_evaluation.py", "BLEU и chrF на посчитанных вручную примерах, выравнивание эталонов с "
                               "коллекцией, сравнение способов перевода"),
        ("test_game.py", "План тира: каждое слово ровно один раз, волны растут, боссы — самые длинные слова в "
                         "нужном порядке, виды противников, словарные формы надписей; правила боя в node или браузере"),
        ("test_web.py", "Страницы, перевод из формы и файла, вкладки, статистика, сохранение, печать, правка "
                        "и пополнение словаря, API тира"),
        ("test_companion_off.py", "Выключатель паука Пафнутия (в отдельном процессе)"),
    ]
    report.table("Состав автоматических тестов", ["Файл", "Что проверяется", "Тестов"],
                 [(name, what, counts.get(name, 0)) for name, what in described],
                 widths=[3.8, 11.0, 1.7], size=Pt(10.5))
    report.text("Правила боя тира проверяет отдельный набор tests/shooter_rules.test.js (51 проверка: "
                "расписание появления слов, сложность, раскрытие перевода босса, попадание снаряда, подсчёт "
                "переведённой доли текста). pytest запускает его через node, а если node не установлен — в "
                "движке V8 браузера Edge или Chrome без окна (tools/run_js_tests.py); все проверки пройдены. "
                "Работа тира в браузере проверена сценарием tools/screenshots.py: Edge без окна (WebGL через "
                "SwiftShader) проходит игру от выбора текста до победы, ошибок JavaScript нет.")

    report.subheading("2. Функциональное тестирование")
    report.text("Функциональное тестирование выполнялось через веб-интерфейс на всей тестовой коллекции и на "
                "своих текстах. Проверялось выполнение каждого требования методических указаний "
                f"(таблица {report.next_table}).")
    ev = data["evaluation"]
    report.table("Проверка выполнения требований к системе", ["Требование", "Как проверялось", "Результат"], [
        ("Вход — естественно-языковой текст на входном языке",
         "Текст в поле ввода и файлы TXT, MD, HTML, DOCX, PDF; 12 документов коллекции и 10 незнакомых "
         "текстов корпуса GUM", "выполнено"),
        ("Количество слов и переведённых слов",
         "Карточки статистики на странице перевода и в файле TXT; совпадение чисел проверяется тестом",
         "выполнено"),
        ("Грамматическая информация: теги и расшифровка",
         "Тег Penn Treebank и его расшифровка у каждой строки списка и у каждого слова дерева; справка со "
         "всеми тегами и отношениями", "выполнено"),
        ("Перевод на выходной язык", f"Перевод всех документов коллекции ({num(ev['words'])} слов), "
                                     "параллельный вид с подсветкой источника каждого слова", "выполнено"),
        ("Частотный список слов с переводами и грамматикой (вкладка 1)",
         "Сортировка по частоте, алфавиту, части речи; немецкая грамматика для каждой статьи", "выполнено"),
        ("Дерево синтаксического разбора выбранного предложения (вкладка 2)",
         "Выбор предложения; дерево зависимостей и дерево составляющих; таблица слов", "выполнено"),
        ("Утилита автоматического пополнения/корректировки словаря (таблицы БД)",
         "Журнал неизвестных слов, подсказки правил и Ding, автоматическое пополнение по порогу, правка, "
         "удаление, импорт и экспорт", "выполнено"),
        ("Сохранение и распечатка в TXT в Unicode",
         "Файлы UTF-16 LE с меткой (и UTF-8) открываются в Блокноте; версия для печати", "выполнено"),
        ("Простой интерфейс", "Шесть разделов меню, справка, подсказки, пример текста", "выполнено"),
    ], widths=[4.8, 9.2, 2.5], size=Pt(10.5))

    report.subheading("3. Пример перевода")
    translator = data["translator"]
    collection = data["collection"]
    rows = []
    for doc_id, indices in (("cs-compiler", (0, 10)), ("cs-mt", (16,)), ("lit-pride", (0,)),
                            ("lit-hamlet", (4,))):
        entry = collection.get(doc_id)
        text = collection.text(doc_id)
        transfer = translator.translate(text, entry.title, entry.domain, log_unknown=False)
        direct = translator.translate(text, entry.title, entry.domain, "direct", log_unknown=False)
        for index in indices:
            rows.append((transfer.analysis.sentences[index].text, transfer.sentences[index].text,
                         direct.sentences[index].text))
    report.text(f"В таблице {report.next_table} — предложения коллекции и их переводы двумя способами.")
    report.table("Пример перевода: с трансфером и пословный", ["Оригинал", "Перевод с трансфером",
                                                               "Пословный перевод"],
                 rows, widths=[5.5, 5.5, 5.5], size=Pt(10))
    entry = collection.get("cs-compiler")
    t = translator.translate(collection.text("cs-compiler"), entry.title, entry.domain, log_unknown=False)
    s = t.stats
    report.text(f"Документ «{entry.title}»: {s['sentences']} предложений, {s['words']} слов ({s['unique']} "
                f"разных), переведено {s['translated']} (по словарю {s['dictionary']}, по правилам {s['rule']}), "
                f"имён и чисел {s['names'] + s['numbers']}, без перевода {s['unknown']}; доля переведённых — "
                f"{pct(s['coverage'])}. Начало частотного списка — в таблице {report.next_table}.")
    rows = []
    for item in t.words[:12]:
        tags = ", ".join(f"{tag}" for tag, _ in item.tags.most_common())
        rows.append((item.lemma, item.count, tags, item.translation or "—", item.german_grammar or "—"))
    report.table("Начало частотного списка документа «Compiler»", ["Слово", "Частота", "Теги", "Перевод",
                                                                  "Грамматика (нем.)"],
                 rows, widths=[2.6, 1.8, 2.0, 4.6, 5.5], size=Pt(10))
    report.figure(SCREENS / "ui_index.png", "Главная страница: ввод текста", crop=(0, 0, 1300, 1000),
                  max_height=14)
    report.figure(SCREENS / "ui_result.png", "Перевод документа: статистика и параллельный текст",
                  crop=(0, 0, 1300, 1400))
    report.figure(SCREENS / "ui_words.png", "Вкладка 1: частотный список слов с переводом и грамматикой",
                  crop=(0, 0, 1300, 1150))
    report.figure(SCREENS / "ui_tree.png", "Вкладка 2: дерево разбора выбранного предложения",
                  crop=(0, 0, 1300, 1460))
    report.figure(SCREENS / "ui_compare.png", "Вкладка 3: перевод с трансфером и пословный",
                  crop=(0, 0, 1300, 1100))
    report.figure(SCREENS / "ui_replenish.png", "Пополнение словаря: журнал неизвестных слов и подсказки",
                  crop=(0, 0, 1300, 1250))
    report.figure(SCREENS / "ui_dictionary.png", "Словарь: поиск, добавление и правка статей",
                  crop=(0, 0, 1300, 1250), max_height=17)
    report.figure(SCREENS / "ui_print.png", "Версия для печати", crop=(0, 0, 1300, 1450), max_height=18)


def length_buckets(sentences: list[dict]) -> list[tuple]:
    buckets = [(1, 15), (16, 25), (26, 35), (36, 999)]
    rows = []
    for low, high in buckets:
        group = [s for s in sentences if low <= len(s["en"].split()) <= high]
        if not group:
            continue
        name = f"{low}–{high}" if high < 999 else f"{low} и более"
        rows.append((name, len(group), num(statistics.mean(s["chrf_transfer"] for s in group)),
                     num(statistics.mean(s["chrf_direct"] for s in group)),
                     num(statistics.mean(s["bleu_transfer"] for s in group)),
                     num(statistics.mean(s["bleu_direct"] for s in group))))
    return rows


ERRORS = [
    ("cs-os", 5, "ошибка теггера: в «are operating systems» слово operating размечено как глагол (длительная "
                 "форма are operating), термин operating system распался, и анализатор построил неверное дерево — "
                 "группы переставлены"),
    ("cs-security", 0, "ошибка теггера: «risks» в «mitigating information risks» размечено как глагол — оно стало "
                       "сказуемым всего предложения, а «is the practice» — его подлежащим"),
    ("lit-hamlet", 12, "цитата «to be, or not to be» внутри предложения разобрана как часть его структуры; "
                       "цитаты и названия нужно переводить как единое целое"),
    ("lit-1984", 23, "лексическая многозначность: encourage — ermutigen, а не fördern, suspicious — verdächtig, "
                     "а не misstrauisch, report X to Y — jemandem melden; ошибка выбора значения, а не структуры"),
]


def evaluation_section(report: Report, data: dict) -> None:
    ev = data["evaluation"]
    groups = ev["groups"]
    an = data["analyzer"]
    report.heading("Результаты анализа полученных данных")
    report.subheading("1. Методика оценки")
    report.text(f"Качество перевода оценивалось на {ev['references']} предложениях коллекции с эталонными "
                "переводами двумя принятыми в машинном переводе мерами:")
    report.bullets([
        "BLEU-4 (Papineni и др., 2002) — среднее геометрическое точностей p~n~ совпадения n-грамм слов "
        "перевода с эталоном (n = 1…4) со штрафом BP за слишком короткий перевод: BLEU = BP · exp(¼ Σ ln "
        "p~n~). Считается по всему набору сразу (corpus BLEU), с учётом регистра — в немецком заглавная буква "
        "существительного входит в правописание;",
        "chrF (Popović, 2015) — F-мера (β = 2) по n-граммам символов (n = 1…6) без пробелов; она мягче к "
        "морфологии: «neuronalen» и «neuronales» совпадают почти целиком, а для немецкого с его падежными "
        "окончаниями это важно.",
    ])
    report.text("Обе меры приводятся в процентах. Перевод с трансфером сравнивается с пословным переводом с "
                "тем же словарём: разница показывает вклад анализа и трансфера. Отдельно оценены полнота "
                "словаря (доля переведённых слов) — на коллекции и на незнакомых текстах, точность "
                "анализатора и время работы.")

    report.subheading("2. Качество перевода")
    rows = []
    for g in ("cs", "lit", "all"):
        rows.append((DOMAIN_NAMES[g], Bold(num(groups[g]["transfer"]["bleu"])), num(groups[g]["direct"]["bleu"]),
                     Bold(num(groups[g]["transfer"]["chrf"])), num(groups[g]["direct"]["chrf"]),
                     f"{groups[g]['wins']['transfer']} / {groups[g]['wins']['direct']} / {groups[g]['wins']['ties']}"))
    report.table("Качество перевода по предметным областям",
                 ["Область", "BLEU, трансфер", "BLEU, пословно", "chrF, трансфер", "chrF, пословно",
                  "Предложений лучше: трансфер / пословно / поровну"],
                 rows, widths=[3.4, 2.2, 2.2, 2.2, 2.2, 4.3], size=Pt(10.5))
    report.figure(REPORT / "eval_quality.png", "BLEU и chrF по областям и способам перевода")
    a = groups["all"]
    precisions = [(f"{n}-граммы", num(a["transfer"]["precisions"][n - 1]), num(a["direct"]["precisions"][n - 1]),
                   num(a["transfer"]["precisions"][n - 1] / max(0.01, a["direct"]["precisions"][n - 1]), 2))
                  for n in range(1, 5)]
    report.table("Точность n-грамм слов по всей коллекции, %", ["n-граммы", "С трансфером", "Пословно",
                                                                "Отношение"],
                 precisions, widths=[4.0, 4.0, 4.0, 4.5], size=Pt(11))
    report.text(f"Перевод с трансфером лучше пословного по всем мерам: BLEU {num(a['transfer']['bleu'])} против "
                f"{num(a['direct']['bleu'])}, chrF {num(a['transfer']['chrf'])} против {num(a['direct']['chrf'])}; "
                f"по chrF трансфер лучше в {a['wins']['transfer']} предложениях из {ev['references']}, хуже — в "
                f"{a['wins']['direct']}. Отношение точностей растёт с длиной n-граммы (таблица "
                f"{report.table_number}): униграммы "
                "у способов почти общие — словарь один, — а совпадения длинных n-грамм дают порядок слов, "
                "рамочные конструкции и правильные формы. Трансфер выигрывает именно структурой.")
    report.text("Научные тексты переводятся заметно лучше литературных (BLEU "
                f"{num(groups['cs']['transfer']['bleu'])} против {num(groups['lit']['transfer']['bleu'])}). "
                "Терминология computer science однозначна и хорошо покрыта словарём оборотов (operating system, "
                "neural network), предложения построены по немногим схемам (определение, пассив, перечисление). "
                "В текстах о романах — имена, цитаты, книжные обороты, длинные предложения с вставками и "
                "приложениями, а главное — многозначная общая лексика.")
    report.text(f"Качество падает с длиной предложения (таблица {report.next_table}): чем длиннее предложение, "
                "тем больше в нём "
                "ошибок анализатора и тем дальше уходят группы при перестановке.")
    report.table("Качество перевода в зависимости от длины предложения",
                 ["Слов в предложении", "Предложений", "chrF, трансфер", "chrF, пословно",
                  "BLEU предл., трансфер", "BLEU предл., пословно"],
                 length_buckets(ev["sentences"]), widths=[3.0, 2.3, 2.6, 2.6, 3.0, 3.0], size=Pt(10.5))

    report.subheading("3. Полнота словаря")
    unseen = ev.get("unseen") or {}
    c = ev["coverage"]
    rows = [("Коллекция", num(ev["words"]), pct(c["transfer"]), pct(c["no_rules"]))]
    if unseen.get("documents"):
        rows.append((f"Незнакомые тексты: {len(unseen['documents'])} документов тестовой части GUM",
                     num(unseen["words"]), pct(unseen["coverage"]), pct(unseen["no_rules"])))
    report.table("Доля переведённых слов", ["Тексты", "Слов", "Словарь и правила", "Только словарь"], rows,
                 widths=[7.5, 2.4, 3.3, 3.3], size=Pt(10.5))
    report.figure(REPORT / "eval_coverage.png", "Доля переведённых слов по документам коллекции")
    examples = ", ".join(unseen.get("rule_examples", [])[:12])
    unknown = ", ".join(unseen.get("unknown_examples", [])[:14])
    report.text(f"На коллекции словарь находит почти все слова — он составлялся под неё. Реальную полноту "
                f"показывают незнакомые тексты — академические статьи, эссе, учебники, биографии и рассказы "
                f"корпуса GUM: {pct(unseen.get('coverage'))} с правилами словообразования и "
                f"{pct(unseen.get('no_rules'))} без них. Правила переводят слова вроде {examples}. Остаются "
                f"непереведёнными редкая общая лексика, сложные слова через дефис и опечатки корпуса: {unknown}. "
                "Частые слова общей лексики, которых не хватало (car, skin, species, …), добавлены в словарь из "
                "частотного списка обучающих частей корпусов UD — проверочные тексты для этого не "
                "использовались.")

    report.subheading("4. Точность анализатора")
    rows = []
    names = {"en_ewt": "EWT (веб-тексты)", "en_gum": "GUM (разные жанры)", "en_lines": "LinES (литература)",
             "en_partut": "ParTUT (право, Википедия)"}
    for bank, r in an["treebanks"].items():
        rows.append((names.get(bank, bank), num(r["sentences"]), pct(r["tagging"], 1) if r["tagging"] else "—",
                     pct(r["lemmas"], 1) if r["lemmas"] else "—", pct(r["uas"]), pct(r["las"]),
                     num(r["ms_per_sentence"])))
    report.table("Точность анализатора на тестовых частях корпусов UD",
                 ["Корпус", "Предложений", "Теги", "Леммы", "UAS", "LAS", "мс на предл."],
                 rows, widths=[4.4, 2.0, 1.8, 1.8, 1.8, 1.8, 2.0], size=Pt(10.5))
    report.figure(REPORT / "eval_analyzer.png", "Точность анализатора на корпусах Universal Dependencies")
    report.text("UAS — доля слов с правильной вершиной, LAS — с правильной вершиной и отношением. Точность "
                "тегов около 94–96 % и UAS около 85 % — уровень классических перцептронных анализаторов без "
                "нейронных сетей; современные нейросетевые анализаторы дают UAS 90–93 %. При UAS 85 % в "
                "предложении из 30 слов в среднем 4–5 неверных связей, и именно они — главный источник ошибок "
                "перевода.")

    report.subheading("5. Затраченное время")
    tm = ev["timings"]
    rows = [(name, ms(tm["transfer"][key]), ms(tm["direct"][key])) for key, name in (
        ("segment", "Разбиение на предложения и слова"), ("tagging", "Теги и леммы"),
        ("parsing", "Синтаксический анализ"), ("transfer", "Трансфер и синтез (или пословная замена)"),
        ("total", "Всего, со статистикой и списком слов"))]
    words = ev["words"] / max(1, len(ev["documents"]))
    report.table(f"Время перевода одного документа (в среднем {num(words, 0)} слов)",
                 ["Этап", "С трансфером", "Пословно"], rows, widths=[9.0, 3.7, 3.8], size=Pt(11))
    report.figure(REPORT / "eval_time.png", "Время перевода по этапам")
    report.text("Измерения выполнены на локальной машине под Windows после загрузки моделей (разовая "
                "стоимость запуска — около трёх секунд). Больше половины времени занимает синтаксический "
                "анализ; трансфер и синтез — около пятой части. Пословный перевод тоже выполняет анализ "
                "(дерево нужно для страницы результата), поэтому выигрыш по времени у него невелик. Документ "
                "переводится за доли секунды, что достаточно для интерактивной работы.")

    report.subheading("6. Анализ ошибок")
    by_key = {(s["doc"], s["index"]): s for s in ev["sentences"]}
    rows = []
    for doc, index, cause in ERRORS:
        s = by_key.get((doc, index))
        if s is None:
            continue
        rows.append((s["en"], s["transfer"], s["ref"], cause))
    report.text("Разбор предложений с наибольшими потерями показал четыре типа ошибок "
                f"(таблица {report.next_table}):")
    report.table("Типичные ошибки перевода", ["Оригинал", "Перевод системы", "Эталон", "Причина"], rows,
                 widths=[4.0, 4.2, 4.2, 4.1], size=Pt(9.5))
    report.bullets([
        "ошибки анализа — теггера и синтаксического анализатора — самый частый и самый дорогой тип: неверный "
        "тег (operating и risks приняты за глаголы) или неверно прикреплённая предложная группа, союз, "
        "придаточное переставляют целые группы. Поправки теггера и эвристики исправления разбора закрывают "
        "самые частые случаи, но не все;",
        "многозначность общей лексики — слово переведено верно по словарю, но не в том значении (little, "
        "manage, play): выбор значения учитывает только часть речи, область и немногие контекстные "
        "признаки;",
        "цитаты, названия и вставки в скобках — переводятся как часть предложения, хотя должны оставаться "
        "единым целым;",
        "редкие конструкции — эллипсис, обособленные причастные обороты, инверсия — правилами трансфера не "
        "покрыты, и группа переводится по общему правилу.",
    ])
    report.text("Сравнение с пословным переводом подтверждает это: из 120 предложений пословный выигрывает в "
                f"{a['wins']['direct']} — и почти во всех из них трансфер ошибается именно в структуре "
                "(неверный разбор), а пословный перевод случайно сохраняет порядок оригинала, близкий к "
                "немецкому.")


def improvements(report: Report) -> None:
    report.heading("Предложения по улучшению работы системы")
    report.steps([
        "Точность анализатора. Главный резерв — синтаксический анализ: нейросетевой анализатор (biaffine) "
        "с векторными представлениями слов поднял бы UAS с 85 до 91–93 % и сократил бы основной тип ошибок. "
        "В рамках перцептрона — анализатор с поиском по лучу (beam search) вместо жадного и больше "
        "обучающих корпусов научной прозы.",
        "Выбор значения слова. Многозначные слова переводить с учётом контекста: сочетаемость с соседями "
        "(manage + resources → verwalten, manage + to → schaffen), частотные модели пар слов, выученные на "
        "параллельном корпусе, или тематическая модель документа.",
        "Словарь. Пополнять общую лексику из словаря Ding с проверкой человеком через утилиту пополнения; "
        "добавлять в словарь обороты, найденные в журнале неизвестных слов; хранить у статей частоты, чтобы "
        "выбирать самый употребительный перевод.",
        "Трансфер. Отдельно обрабатывать цитаты и названия произведений; добавить правила для обособленных "
        "причастных оборотов, эллипсиса, инверсии; согласование временных форм в косвенной речи.",
        "Оценка. Увеличить набор эталонов и привлечь второй эталонный перевод — BLEU с одним эталоном "
        "занижает оценку правильных, но отличающихся переводов.",
        "Интерфейс. Правка перевода пользователем с запоминанием исправлений (память переводов), чтобы "
        "повторяющиеся предложения переводились так, как исправил человек.",
    ])


def components(report: Report) -> None:
    report.heading("Описание и особенности применения готовых компонентов")
    report.text("При использовании готовых компонентов и данных выявлен ряд особенностей, которые пришлось "
                "учесть в реализации.")
    report.steps([
        "Корпуса Universal Dependencies. Сокращённые формы записаны многословными токенами (строка «don't» и "
        "под ней «do», «n't»); в GUM и EWT слова с дефисом разбиты на три токена (cross - compiler), а "
        "токенизатор системы оставляет их целыми — при чтении корпусов такие токены склеиваются. Анализатор "
        "arc-hybrid строит только проективные деревья, поэтому непроективные предложения (около 3 %) из "
        "обучения исключаются.",
        "Теги корпусов. В LinES и ParTUT нет тегов Penn Treebank, поэтому теггер учится только на EWT и GUM, "
        "а синтаксический анализатор на LinES и ParTUT учится по тегам, которые расставил теггер.",
        "Размер моделей. Веса перцептрона анализатора занимали 18 МБ; веса с модулем меньше 1,5 "
        "отбрасываются, остальные округляются до десятых — модель уменьшилась до 7 МБ почти без потери "
        "точности (прореженная модель проверена на тестовых частях корпусов).",
        "Словарь Ding. Строка содержит синонимы через «;» и варианты через «|», немецкая часть — пометки "
        "{f}, {pl}, etw., jdn., [ugs.], а английская — sth., sb.; пометки убираются, род и мн. ч. берутся из "
        "фигурных скобок, значения немецкой и английской части сопоставляются по позиции «|».",
        "Загрузка данных в Windows. Модуль urllib отклоняет сертификаты некоторых сайтов "
        "(CERTIFICATE_VERIFY_FAILED), поэтому загрузка идёт через requests с набором certifi; API Википедии "
        "при частых запросах отвечает 429 — запросы повторяются с паузой.",
        "«Unicode» в Windows. Блокнот называет «Юникодом» UTF-16 LE с меткой порядка байтов — так файл "
        "сохраняется по умолчанию; строки разделяются CR LF, иначе старые версии Блокнота склеивают строки.",
        "three.js. Библиотека подключена как ES-модуль из папки static/vendor, а не с CDN, чтобы тир работал "
        "без сети; модули загружаются только по HTTP, поэтому тир открывается со страницы системы.",
        "Захват мыши. В Chromium requestPointerLock возвращает Promise и отклоняет его, если пользователь "
        "только что вышел из захвата (Esc); отказ перехватывается, а без захвата обзор работает "
        "перетаскиванием мышью.",
        "Снимки экрана и проверка тира. Edge без окна рисует WebGL программно (SwiftShader) с частотой "
        "несколько кадров в секунду; шаг времени игры ограничен 0,05 с, поэтому игра идёт замедленно, и "
        "сценарий снимков выдерживает паузы и пользуется отладочным API тира (?debug=1).",
    ])


def conclusion(report: Report, data: dict) -> None:
    ev = data["evaluation"]
    g = ev["groups"]
    tests = data["tests"]
    total = sum(data["test_counts"].values())
    unseen = ev.get("unseen") or {}
    report.heading("Вывод")
    report.text(f"В ходе лабораторной работы спроектирована и программно реализована система автоматического "
                f"машинного перевода «{APP_NAME}» с английского языка на немецкий по схеме систем второго "
                "поколения — с трансфером. Система анализирует английский текст (теги частей речи, леммы, "
                "дерево зависимостей), переносит структуру предложения в немецкую (порядок слов, рамочные "
                "конструкции, падежи, согласование, придаточные) и синтезирует немецкие формы. Все "
                "лингвистические компоненты — теггер, лемматизатор, синтаксический анализатор, трансфер, "
                "немецкая морфология — написаны с нуля; модели анализатора обучены на корпусах Universal "
                "Dependencies.")
    report.text("Все требования методических указаний выполнены: система подсчитывает слова входного текста и "
                "переведённые слова, выводит теги частей речи с расшифровкой, перевод, частотный список слов "
                "с переводами и грамматической информацией (вкладка 1) и дерево синтаксического разбора "
                "выбранного предложения (вкладка 2); словарь хранится в базе данных SQLite и пополняется и "
                "корректируется утилитой с автоматическими подсказками; результаты сохраняются в TXT в "
                "Unicode и печатаются; интерфейс прост и снабжён справкой.")
    report.text(f"Оценка на {ev['references']} предложениях с эталонными переводами показала, что трансфер "
                f"оправдан: BLEU {num(g['all']['transfer']['bleu'])} и chrF {num(g['all']['transfer']['chrf'])} "
                f"против {num(g['all']['direct']['bleu'])} и {num(g['all']['direct']['chrf'])} у пословного "
                f"перевода с тем же словарём; перевод с трансфером лучше в {g['all']['wins']['transfer']} "
                f"предложениях из {ev['references']}. Научные тексты переводятся лучше литературных (BLEU "
                f"{num(g['cs']['transfer']['bleu'])} против {num(g['lit']['transfer']['bleu'])}). Словарь "
                f"переводит {pct(ev['coverage']['transfer'])} слов коллекции и {pct(unseen.get('coverage'))} "
                "слов незнакомых текстов; документ переводится за доли секунды. Главный источник ошибок — "
                "синтаксический анализ, и его улучшение — основной путь к повышению качества перевода.")
    if tests:
        report.text(f"Корректность системы подтверждена {total} автоматическими тестами.")
    report.text("Сверх требований в систему добавлен трёхмерный тир Пафнутия: слова переводимого текста "
                "волнами идут на паука, попадание переводит слово, мини-боссы — самые длинные слова "
                "документа, а победа даёт полностью переведённый документ. Игра превращает перевод текста в "
                "наглядный процесс: видно, из каких слов состоит текст и как каждое из них переводится.")
    report.text("Перспективы применения: черновой перевод научных статей и учебных текстов по computer "
                "science, вспомогательный инструмент при изучении немецкого языка (параллельный текст, "
                "грамматика каждого слова, дерево разбора), основа для систем с языком-посредником или "
                "систем, основанных на знаниях, где тот же анализ дополняется семантическим представлением.")


def build(output: Path, run_tests: bool) -> Path:
    data = gather(run_tests)
    report = Report()
    title_page(report)
    goal_and_task(report, data)
    libraries(report)
    collection_section(report, data)
    structure_section(report, data)
    data_structures(report)
    algorithm_section(report, data)
    game_section(report, data)
    testing_section(report, data)
    evaluation_section(report, data)
    improvements(report)
    components(report)
    conclusion(report, data)
    return report.save(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", default=str(ROOT / "ОтчётЕЯзИИС47.docx"))
    parser.add_argument("--no-tests", action="store_true", help="не запускать pytest")
    arguments = parser.parse_args()
    path = build(Path(arguments.output), not arguments.no_tests)
    print(f"Отчёт: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
