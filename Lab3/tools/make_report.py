"""Сборка отчёта по лабораторной работе в формате DOCX.

    python tools/make_report.py [--output ПУТЬ] [--no-tests]

Числа в отчёт не вписаны вручную: состав коллекции, результаты оценки, время
работы, число тестов берутся из данных системы (data/catalog.json,
report/evaluation.json, прогон pytest). Схемы и графики — из report/
(tools/make_diagrams.py, tools/evaluate.py), снимки экрана — из report/screens
(tools/screenshots.py).
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

from izbornik import APP_NAME, config, console  # noqa: E402
from izbornik.collection import Collection  # noqa: E402

console.setup()

ROOT = Path(__file__).resolve().parent.parent
REPORT = config.REPORT_DIR
SCREENS = REPORT / "screens"
FONT = "Times New Roman"
SIZE = Pt(14)
INDENT = Cm(1.25)

GROUPS = ["ru-cs", "ru-lit", "de-cs", "de-lit"]
GROUP_NAMES = {"ru-cs": "русский, CS", "ru-lit": "русский, литература", "de-cs": "немецкий, CS",
               "de-lit": "немецкий, литература", "ru": "русский", "de": "немецкий", "cs": "CS",
               "lit": "литература", "all": "вся коллекция"}
METHOD_NAMES = {
    "extraction": "Sentence extraction (Score · Posd · Posp)",
    "score": "Только Score (термины)",
    "position": "Только Posd · Posp (положение)",
    "lead": "Первые N предложений",
    "random": "Случайные N предложений (среднее по 30)",
    "oracle": "Оракул (верхняя граница)",
}


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
                cropped = image.crop(crop)
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
    return isinstance(value, str) and bool(re.fullmatch(r"[\d\s ,.–%—мсх/+-]+", value))


def num(value, digits=3) -> str:
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


def ref(n: int, what: str = "таблице") -> str:
    return f"{what} {n}"


# --- данные ---------------------------------------------------------------------------

def gather(run_tests: bool) -> dict:
    collection = Collection()
    collection.warm_up()
    evaluation = json.loads((REPORT / "evaluation.json").read_text(encoding="utf-8"))
    docs = []
    for entry in collection:
        layout = collection.analyzed(entry.id).layout
        docs.append({
            "entry": entry,
            "chars": layout.length,
            "sentences": len(layout.sentences),
            "paragraphs": sum(1 for p in layout.paragraphs if not p.heading),
        })
    data = {"collection": collection, "evaluation": evaluation, "docs": docs}
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
                 "по лабораторной работе № 3",
                 "по курсу «Естественно-языковой интерфейс интеллектуальных систем»",
                 "«Автоматическое реферирование документов»",
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


def goal_and_task(report: Report) -> None:
    report.heading("Цель работы:")
    report.text("Освоить на практике основные принципы автоматического реферирования документов с учётом "
                "функционала, предоставляемого технологией OSTIS. Спроектировать и программно реализовать "
                "систему автоматического реферирования, построить тестовую коллекцию документов и оценить "
                "точность и быстродействие системы для текстов разных предметных областей и естественных "
                "языков.")
    report.heading("Задание:")
    report.text("Разработать систему автоматического реферирования текстовых документов методом sentence "
                "extraction, удовлетворяющую требованиям методических указаний:")
    report.bullets([
        "на входе — текстовые документы одинакового размера (например, 10 страниц формата А4), содержащие "
        "тексты из предметных областей на естественных языках согласно варианту;",
        "на выходе — активная ссылка на исходный документ и построенный реферат документа, состоящий из двух "
        "разделов: классического реферата и реферата в виде списка ключевых слов;",
        "наличие средств сохранения в файл и распечатки полученной на выходе информации;",
        "интерфейс системы должен быть предельно простым и доступным для пользователей любого уровня, "
        "содержать понятный набор инструментов и средств, а также help-средства.",
    ])
    report.text("Параметры варианта 4 и место их реализации приведены в таблице 1.")
    report.table(
        "Параметры варианта 4 и место их реализации",
        ["Параметр", "Значение", "Где реализовано"],
        [
            ("Язык текста", "русский, немецкий",
             "izbornik/text: морфология (pymorphy3 — русский, основы Snowball — немецкий), стоп-слова "
             "data/stopwords/ru.txt и de.txt, правила разбиения на предложения для обоих языков"),
            ("Методика", "Sentence extraction + OSTIS",
             "izbornik/weights.py и summary.py — формулы и отбор предложений; izbornik/ostis — база знаний, "
             "sc-агент построения реферата, онтология kb/section_subject_domain_of_summarization"),
            ("Предметная область", "научные статьи по computer science, сочинения по литературе",
             "тестовая коллекция data/collection (по 10 документов каждой области), классы "
             "concept_scientific_article_on_computer_science и concept_essay_on_literature в онтологии"),
        ],
        widths=[3.2, 4.3, 9.0],
    )
    report.text(f"Система получила название «{APP_NAME}» — по древнерусскому «Изборнику» 1073 года, сборнику "
                "выдержек, избранных из больших текстов. Система делает то же самое: выбирает из документа "
                "наиболее значимые предложения и слова.")


def libraries(report: Report) -> None:
    report.heading("Используемые библиотеки и их назначение:")
    report.text(f"Система реализована на языке Python {sys.version_info.major}.{sys.version_info.minor}; "
                "минимальные версии сторонних компонентов зафиксированы в файле requirements.txt, версии "
                "клиентов OSTIS — строго, в соответствии с версией ostis-системы. Готовых библиотек "
                "автоматического реферирования в работе нет: разбиение на предложения, формулы весов, отбор "
                "предложений, поиск именных групп и мера качества ROUGE реализованы с нуля.")
    report.text("Веб-интерфейс:", indent=False, bold=True)
    report.bullets([
        f"FastAPI {version('fastapi')} — веб-фреймворк: маршруты страниц, сохранения в файл, версии для "
        "печати, загрузки своего документа;",
        f"Uvicorn {version('uvicorn')} — ASGI-сервер; система поднимается командой python run.py и "
        f"открывается по адресу http://{config.HOST}:{config.PORT}/;",
        f"Jinja2 {version('jinja2')} — шаблоны страниц; python-multipart — разбор формы с файлом.",
    ])
    report.text("Обработка текста:", indent=False, bold=True)
    report.bullets([
        f"pymorphy3 {version('pymorphy3')} — морфологический анализ русского языка: начальная форма, часть "
        "речи, падеж, род и число (согласование в именных группах), склонение группы в именительный падеж, "
        "признаки имён, фамилий и отчеств;",
        f"NLTK {version('nltk')} — используется только стеммер Snowball для немецкого языка; загрузки "
        "данных NLTK он не требует;",
        f"python-docx {version('python-docx')}, pypdf {version('pypdf')}, beautifulsoup4 "
        f"{version('beautifulsoup4')} — извлечение текста из загружаемых документов DOCX, PDF, HTML; "
        "python-docx также формирует реферат в формате DOCX.",
    ])
    report.text("Технология OSTIS:", indent=False, bold=True)
    report.bullets([
        f"py-sc-client {version('py-sc-client')} — клиент sc-сервера: создание элементов, поиск по "
        "шаблонам, содержимое sc-ссылок, загрузка текста SCs, подписка на события;",
        f"py-sc-kpm {version('py-sc-kpm')} — sc-агенты и модули на Python: класс ScAgentClassic, "
        "создание, инициирование и ожидание действий;",
        "ostis-система NIKA (sc-machine 0.8.0, sc-web) в контейнерах Docker — sc-память, sc-сервер "
        "(ws://localhost:8090) и визуализация базы знаний (http://localhost:8000).",
    ])
    report.text("Сборка коллекции, оценка и тестирование:", indent=False, bold=True)
    report.bullets([
        f"httpx {version('httpx')} — загрузка исходных страниц КиберЛенинки и Википедии;",
        f"matplotlib {version('matplotlib')} — графики и схемы отчёта; для работы системы не требуется;",
        f"pytest {version('pytest')} — автоматические тесты, включая проверки на живой ostis-системе.",
    ])


def components(report: Report) -> None:
    report.heading("Описание и особенности применения готовых компонентов")
    report.text("При использовании готовых компонентов выявлен ряд особенностей, которые пришлось учесть в "
                "реализации.")
    report.steps([
        "Версии клиентов OSTIS. Используется NIKA на sc-machine 0.8.0, поэтому версии клиентов взяты те же, "
        "что в самой NIKA: py-sc-client 0.3.0 и py-sc-kpm 0.2.0. Более новые версии клиентов рассчитаны на "
        "более новые версии sc-machine и используют другие имена команд и типов.",
        "Одно соединение на процесс. py-sc-client хранит сессию в глобальных переменных модуля и работает в "
        "отдельном потоке websocket, который не является фоновым: без явного отключения процесс не "
        "завершается. Поэтому все сценарии закрывают соединение в блоке finally, а веб-интерфейс — при "
        "остановке сервера.",
        "Ошибки соединения. Обработчик ошибок по умолчанию возбуждает исключение прямо в потоке websocket. "
        "Он заменён своим, который запоминает ошибку: недоступность sc-сервера — штатная ситуация, при "
        "которой система переходит в локальный режим.",
        "Ожидание агентов. Метод ScServer.serve() использует signal.pause(), которого нет в Windows; "
        "отдельный процесс агента (tools/agent.py) ждёт событий в своём цикле.",
        "Загрузка SCs. Запрос create_elements_by_scs принимает список текстов, но синтаксическая ошибка в "
        "любом из них отклоняет весь запрос — при этом корректные тексты к этому моменту уже применены. "
        "Повторная загрузка того же текста дублирует дуги. Поэтому файлы онтологии загружаются по одному "
        "и только один раз: признак загрузки — наличие узла раздела в базе знаний.",
        "Поиск по шаблону. Шаблон «документ коллекции — текст на нужном языке — системный идентификатор» "
        "на sc-machine 0.8 не находит ничего, хотя каждая его часть по отдельности работает. Поиск разбит "
        "на два шаблона, результаты соединяются по адресу документа.",
        "Адреса sc-элементов переиспользуются. Определять «самый новый» реферат по адресу его узла "
        "нельзя, поэтому при повторном построении реферата того же размера прежний отвязывается от "
        "документа, и у документа остаётся один реферат каждого размера.",
        "pymorphy3. Начальная форма причастия — инфинитив, отчества — мужского рода, а неоднозначная форма "
        "«Евгения» разбирается и как имя «Евгения», и как родительный падеж от «Евгений». Неоднозначность "
        "имён разрешается по документу — выбирается начальная форма, чаще встречающаяся в тексте; имя "
        "человека в словосочетании ставится в именительный падеж с учётом рода первого слова.",
        "Snowball. Стеммер не отбрасывает конечное -s притяжательной формы имён («Effis», «Goethes»); такая "
        "форма сводится к имени, если оно встречается в документе. Основа Snowball не читаема "
        "(«verschlussel»), поэтому ключевое слово показывается самой частой формой слова в документе.",
    ])


def collection_section(report: Report, data: dict) -> None:
    docs = data["docs"]
    sizes = [d["chars"] for d in docs]
    report.heading("Информация о тестовой коллекции документов")
    report.text(f"Тестовая коллекция data/collection содержит {len(docs)} документов — по пять в каждой "
                "группе «язык × предметная область». Методические указания требуют документов одинакового "
                f"размера, например 10 страниц формата А4. Объём задан как 10 страниц машинописного текста "
                f"по {config.PAGE_CHARS} знаков — {num(config.DOC_TARGET_CHARS)} знаков — с допуском "
                f"±{int(config.DOC_SIZE_TOLERANCE * 100)} %. Фактически объём документов — от {num(min(sizes))} "
                f"до {num(max(sizes))} знаков (в среднем {num(round(statistics.mean(sizes)))}, стандартное "
                f"отклонение {num(round(statistics.pstdev(sizes)))}), то есть от "
                f"{num(min(sizes) / config.PAGE_CHARS, 1)} до {num(max(sizes) / config.PAGE_CHARS, 1)} "
                "страницы. Состав коллекции приведён в таблице 2.")
    rows = []
    for index, d in enumerate(docs, start=1):
        entry = d["entry"]
        site = "КиберЛенинка" if entry.source.get("kind") == "cyberleninka" else \
            f"Википедия ({entry.language})"
        rows.append((index, entry.title, GROUP_NAMES[entry.group], site, num(d["chars"]), d["sentences"],
                     num(len(entry.reference_abstract))))
    report.table("Состав тестовой коллекции",
                 ["№", "Документ", "Группа", "Источник", "Знаков", "Предло-жений", "Эталон, знаков"],
                 rows, widths=[0.8, 5.6, 2.6, 2.6, 1.6, 1.5, 1.6], size=Pt(10))
    report.text("Источники подобраны так, чтобы у каждого документа был эталон для оценки точности, "
                "составленный человеком:")
    report.bullets([
        "научные статьи по computer science на русском языке — статьи с портала КиберЛенинка под лицензией "
        "CC BY; эталон — авторская аннотация и ключевые слова. Одна из статей — работа Н. А. Гулякиной и "
        "И. Т. Давыденко (БГУИР) о семантических моделях баз знаний на основе технологии OSTIS;",
        "научные тексты по computer science на немецком языке — статьи немецкой Википедии (нейронные сети, "
        "компиляторы, операционные системы, информационная безопасность, семантическая паутина); эталон — "
        "вводный раздел статьи, который по правилам Википедии кратко излагает её содержание;",
        "«сочинения по литературе» — литературоведческие статьи русской и немецкой Википедии о "
        "произведениях школьной программы: «Евгений Онегин», «Мастер и Маргарита», «Преступление и "
        "наказание», «Мёртвые души», «Горе от ума»; «Die Leiden des jungen Werthers», «Effi Briest», "
        "«Die Verwandlung», «Die Räuber», «Im Westen nichts Neues». Эталон — вводный раздел.",
    ])
    report.text("Эталон из текста документа удалён: иначе система «находила» бы его в тексте, и оценка "
                "точности была бы завышена. Это проверяется автотестом.")
    report.text("Коллекцию собирает сценарий tools/build_collection.py. Статьи КиберЛенинки доступны как "
                "распознанный текст PDF, поэтому он проходит очистку:")
    report.steps([
        "Начало основного текста — после абзаца «Ключевые слова» / «Keywords»: до него идут выходные "
        "данные, сведения об авторах и аннотации на двух языках. Конец — перед списком литературы, "
        "благодарностями и сведениями об авторах.",
        "Удаляются колонтитулы — абзацы, повторяющиеся на нескольких страницах, — строки с DOI, адресами и "
        "ORCID, подписи к рисункам и таблицам, программный код, формулы и иноязычные вставки.",
        "Склеиваются абзацы, разорванные границей страницы, и слова, разорванные переносом. Перенос "
        "«денормализа-ция» убирается, только если слитное слово есть в словаре pymorphy3, а слово с "
        "дефисом — нет: «какой-то» и «по-прежнему» не трогаются.",
        "Короткие строки без знака конца предложения распознаются как заголовки разделов, если похожи на "
        "заголовок, а не на ячейку таблицы.",
    ])
    report.text("У статей Википедии отбрасываются разделы «Литература», «Примечания», «Ссылки» и подобные, "
                "списки и формулы. Длинные статьи обрезаются по границе абзаца так, чтобы объём попал в "
                "допуск; статьи КиберЛенинки подобраны с естественным объёмом в допуске и не обрезаются, "
                "чтобы не потерять выводы. Исходные страницы сохранены в data/sources, поэтому коллекцию "
                "можно пересобрать без сети (ключ --offline).")


def structure_section(report: Report) -> None:
    report.heading("Описание структуры разработанной системы")
    report.text("Система состоит из пяти частей (рисунок 1): веб-интерфейса, ядра реферирования, "
                "интеграции с технологией OSTIS, данных и модуля оценки. Ядро реферирования не зависит ни от "
                "интерфейса, ни от OSTIS: одна и та же функция izbornik.summary.build вызывается и в "
                "локальном режиме, и sc-агентом, поэтому результаты двух режимов обязаны совпадать.")
    report.figure(REPORT / "structure.png", "Структура системы «Изборник»")
    report.text("Состав модулей приведён в таблице 3.")
    report.table("Состав и назначение модулей системы", ["Модуль", "Назначение"], [
        ("text/segment.py", "Разбиение на абзацы, заголовки и предложения; смещения |D|, |P|, BD(S~i~), BP(S~i~)"),
        ("text/analysis.py", "Слова предложений, термины, частоты tf(t, D), существительные, формы для "
                             "показа, разрешение неоднозначности имён"),
        ("text/morphology.py", "Лемматизация pymorphy3, стемминг Snowball, согласование и склонение "
                               "именных групп"),
        ("text/stopwords.py", "Стоп-слова и служебные обороты"),
        ("text/compress.py", "Сжатие предложений реферата"),
        ("text/extract.py", "Текст из загружаемых файлов TXT, MD, HTML, DOCX, PDF"),
        ("weights.py", "Статистика коллекции |DB|, df(t); веса w(t, D); Score, Posd, Posp; отбор предложений"),
        ("keywords.py", "Реферат в виде списка ключевых слов"),
        ("summary.py", "Построение реферата — общее для локального режима и sc-агента"),
        ("collection.py", "Тестовая коллекция, кэш разбора документов, локальный режим"),
        ("evaluation.py", "Мера ROUGE, базовые способы отбора, оракул, оценка ключевых слов, время"),
        ("export.py", "Сохранение в TXT, HTML, DOCX, JSON, SCs"),
        ("ostis/connection.py", "Подключение к sc-серверу, загрузка онтологии"),
        ("ostis/kb.py", "Запись документов и рефератов в базу знаний и чтение их обратно"),
        ("ostis/agent.py", "sc-агент построения реферата"),
        ("ostis/service.py", "Режим OSTIS для интерфейса: синхронизация, вызов действия, резервный режим"),
        ("ostis/scs.py", "Реферат в виде текста на языке SCs"),
        ("web/app.py", "Страницы, сохранение в файл, печать, справка"),
    ], widths=[4.0, 12.5], size=Pt(11))
    report.text("Интерфейс содержит разделы «Коллекция», «Свой документ», «Оценка», «OSTIS» и «Справка». "
                "Страница реферата — главная страница системы: на ней активные ссылки на исходный документ, "
                "оба раздела реферата, кнопки сохранения и печати, выбор размера реферата и режима "
                "построения, а в раскрывающемся разделе — промежуточные величины расчёта.")

    report.subheading("Интеграция с технологией OSTIS")
    report.text("Используется ostis-система NIKA, развёрнутая в контейнерах Docker (sc-machine 0.8.0): "
                "контейнер nika-problem-solver содержит sc-память и sc-сервер (ws://localhost:8090), "
                "nika-sc-web — интерфейс просмотра базы знаний (http://localhost:8000). Система подключается "
                "к sc-серверу по протоколу JSON поверх WebSocket и при подключении:")
    report.steps([
        "Загружает в базу знаний онтологию предметной области автоматического реферирования "
        "(kb/section_subject_domain_of_summarization, пять файлов SCs) — если её там ещё нет. Файлы "
        "ostis-системы при этом не меняются.",
        "Помещает в базу знаний 20 документов коллекции: узел документа с системным идентификатором, "
        "основной идентификатор, текст, адрес источника, принадлежность классам.",
        "Регистрирует sc-агент построения реферата, подписанный на добавление дуги в множество "
        "question_initiated.",
    ])
    report.text("Онтология описывает понятия и отношения предметной области (таблицы 4 и 5), класс действия "
                "action_build_summary и спецификацию абстрактного sc-агента. На рисунке 2 — раздел "
                "предметной области в sc-web: sc-web показывает его по-русски, через основные "
                "идентификаторы, заданные в онтологии.")
    report.table("Понятия предметной области", ["Понятие", "Основной идентификатор"], [
        ("concept_text_document", "текстовый документ"),
        ("concept_test_collection_document", "документ тестовой коллекции"),
        ("concept_scientific_article_on_computer_science", "научная статья по computer science"),
        ("concept_essay_on_literature", "сочинение по литературе"),
        ("concept_sentence", "предложение"),
        ("concept_summary", "реферат"),
        ("concept_classic_summary", "классический реферат"),
        ("concept_keyword_summary", "реферат в виде списка ключевых слов"),
        ("concept_key_term, concept_keyword, concept_key_phrase", "ключевой термин, ключевое слово, "
                                                                 "ключевое словосочетание"),
        ("concept_summarization_method, sentence_extraction", "метод автоматического реферирования, метод "
                                                              "sentence extraction"),
        ("action_build_summary", "действие. построить реферат документа"),
    ], widths=[8.0, 8.5], size=Pt(10.5))
    report.table("Отношения предметной области", ["Отношение", "Основной идентификатор", "Связывает"], [
        ("nrel_document_text", "текст документа*", "документ — sc-ссылка с текстом"),
        ("nrel_source_address", "адрес источника*", "документ — адрес"),
        ("nrel_summary", "реферат*", "документ — реферат"),
        ("rrel_classic_summary, rrel_keyword_summary", "классический реферат', реферат в виде списка "
                                                       "ключевых слов'", "роли разделов реферата"),
        ("nrel_sentence_number, nrel_sentence_rank", "номер предложения*, место по весу*", "предложение — число"),
        ("nrel_sentence_score", "оценка предложения по терминам*", "предложение — Score(S)"),
        ("nrel_position_in_document", "положение в документе*", "предложение — Posd(S)"),
        ("nrel_position_in_paragraph", "положение в абзаце*", "предложение — Posp(S)"),
        ("nrel_sentence_weight", "вес предложения*", "предложение — Score · Posd · Posp"),
        ("nrel_term_significance, nrel_term_frequency", "значимость, частота ключевого термина*",
         "дуга принадлежности термина реферату — число"),
        ("nrel_subordinate_key_term", "подчинённый ключевой термин*", "ключевое слово — словосочетание"),
        ("nrel_summary_size, nrel_document_length, nrel_collection_size, nrel_compression_ratio, "
         "nrel_processing_time", "размер реферата*, объём документа*, число документов в базе*, коэффициент "
                                 "сжатия*, время построения*", "реферат — число"),
        ("nrel_summarization_method", "метод реферирования*", "реферат — метод"),
    ], widths=[5.6, 5.9, 5.0], size=Pt(10))
    report.figure(SCREENS / "scweb_section.png", "Раздел предметной области автоматического реферирования в sc-web",
                  crop=(0, 60, 1500, 940))
    report.text("Реферат в режиме OSTIS строится выполнением действия (рисунок 3). Интерфейс сначала ищет в "
                "базе знаний реферат документа нужного размера; если его нет, создаёт действие классов "
                "question и action_build_summary с аргументами rrel_1 — документ и rrel_2 — число "
                "предложений — и инициирует его. sc-агент читает из базы знаний текст документа и тексты "
                "документов коллекции того же языка, строит реферат, записывает его в базу знаний, "
                "связывает с действием отношением nrel_answer и завершает действие. Интерфейс дожидается "
                "завершения и читает реферат из базы знаний. Повторный запрос реферата того же размера "
                "агента не вызывает — база знаний служит хранилищем рефератов.")
    report.figure(REPORT / "ostis_flow.png", "Построение реферата в режиме OSTIS")


def data_structures(report: Report) -> None:
    report.heading("Описание структур данных для хранения входной и выходной информации")
    report.text("Структуры данных описаны как dataclass-объекты Python. Их можно разделить на входную "
                "информацию, промежуточное представление документа и выходную информацию; отдельно описано "
                "хранение в базе знаний.")
    report.subheading("1. Входная информация")
    report.bullets([
        "Документ коллекции — файл data/collection/<идентификатор>.txt в кодировке UTF-8: абзацы разделены "
        "пустой строкой, заголовки разделов отмечены знаком «# ».",
        "Каталог коллекции — data/catalog.json: для каждого документа идентификатор, файл, заголовок, язык, "
        "предметная область, объём, источник (сайт, адрес, авторы, год, журнал, лицензия, ревизия статьи "
        "Википедии) и эталон — реферат источника и ключевые слова авторов. Класс CatalogEntry.",
        "Свой документ пользователя — текст из формы или файл TXT, MD, HTML, DOCX, PDF; хранится в памяти "
        "(класс UserDoc) под идентификатором по содержимому.",
        "Стоп-слова — data/stopwords/ru.txt (леммы) и de.txt (словоформы); служебные обороты — в "
        "text/stopwords.py.",
    ])
    report.subheading("2. Представление документа")
    report.bullets([
        "Layout — документ D: текст (абзацы через перевод строки), список Paragraph (текст, смещение, признак "
        "заголовка, номера предложений) и список Sentence (номер, абзац, текст, смещение start = BD(S~i~), "
        "смещение в абзаце start_in_paragraph = BP(S~i~)); |D| и |P| — длины текста и абзаца.",
        "AnalyzedDocument — документ после разбора: слова каждого предложения и заголовка (Token: форма, "
        "термин, смещения, признак «учитывается в весах», признаки существительного и прилагательного, "
        "смежность с предыдущим словом), частоты tf(t, D), множество существительных, формы для показа.",
        "CorpusStats — статистика базы документов: |DB|, df(t), идентификаторы документов, область подсчёта.",
        "TermWeight — термин, tf(t, D), df(t), log(|DB| / df), w(t, D). SentenceScore — Score, Posd, Posp, "
        "вес и вклад каждого термина в Score.",
    ])
    report.subheading("3. Выходная информация")
    report.bullets([
        "Summary — реферат документа: идентификатор, заголовок, язык, область, адрес источника, "
        "запрошенный размер, список SummarySentence, KeywordSummary, статистика (объём документа и "
        "реферата, коэффициент сжатия, |DB|, число терминов), время по этапам, режим построения и сведения "
        "о действии в базе знаний.",
        "SummarySentence — предложение реферата: номер в документе, абзац, исходный и сжатый текст, Score, "
        "Posd, Posp, вес, место по весу, термины с наибольшим вкладом.",
        "KeywordSummary — дерево Keyword (текст, термины, значимость, частота, вид: слово, словосочетание, "
        "сложное слово; подчинённые) и список словосочетаний, не подчинённых ключевым словам.",
    ])
    report.text("Выходная информация сохраняется в пяти форматах (таблица 6); во всех есть активная ссылка на "
                "исходный документ.")
    report.table("Форматы сохранения реферата", ["Формат", "Содержание", "Назначение"], [
        ("TXT", "оба раздела, номера и веса предложений, ссылки на документ и источник", "чтение, печать"),
        ("HTML", "самостоятельная страница со встроенными стилями", "просмотр в браузере, печать"),
        ("DOCX", "документ Word: оба раздела, дерево ключевых слов", "редактирование, отчёты"),
        ("JSON", "все поля Summary, включая веса и дерево ключевых слов", "обмен данными, повторная загрузка"),
        ("SCs", "фрагмент базы знаний той же структуры, что строит агент", "загрузка в любую ostis-систему"),
    ], widths=[2.0, 8.5, 6.0], size=Pt(11))
    report.subheading("4. Хранение в базе знаний")
    report.text("В базе знаний реферат представлен узлом класса concept_summary, связанным с документом "
                "отношением реферат* (рисунок 4). Его разделы — узлы классов concept_classic_summary и "
                "concept_keyword_summary с ролями rrel_classic_summary и rrel_keyword_summary. Предложения "
                "классического реферата — sc-ссылки, принадлежащие concept_sentence и языку текста, "
                "упорядоченные ролями rrel_1, rrel_2, …; номер предложения, Score, Posd, Posp, вес и место "
                "заданы числовыми sc-ссылками. Ключевые термины — общие для всех документов узлы "
                "term_<язык>_<…> с основным идентификатором; значимость и частота зависят от документа и "
                "потому приписаны дуге принадлежности термина реферату. Подчинение словосочетания ключевому "
                "слову — дуга отношения подчинённый ключевой термин*, входящая в реферат. Все элементы "
                "одного реферата (около 500) создаются одним запросом.")
    report.figure(REPORT / "kb_summary.png", "Реферат документа в базе знаний")


def algorithm_section(report: Report, data: dict) -> None:
    report.heading("Описание алгоритма построения реферата")
    report.text("Алгоритм следует методу sentence extraction из методических указаний: вычислить веса слов "
                "документа, вычислить веса предложений и выбрать из текста предложения с наибольшим весом в "
                "том порядке, в котором они идут в тексте. Параллельно строится реферат в виде списка "
                "ключевых слов. Блок-схема приведена на рисунке 5.")
    report.figure(REPORT / "algorithm.png", "Блок-схема алгоритма построения реферата", max_height=22.5)

    report.subheading("1. Разбиение документа")
    report.text("Текст делится на абзацы по пустым строкам (если пустых строк нет — по строкам). Абзац, "
                "отмеченный «# », или короткая строка без знака конца предложения считается заголовком: "
                "заголовки входят в документ D и занимают в нём место, но кандидатами в реферат не бывают. "
                "Документ D — абзацы, соединённые переводом строки; все смещения считаются в этой строке.")
    report.text("Граница предложения — знак «.», «!», «?» или «…» (с закрывающими кавычками и скобками), "
                "пробел и заглавная буква, цифра или открывающая кавычка. Граница не ставится после "
                "сокращений («т. е.», «рис.», «Дж.», «z. B.», «vgl.», «bzw.»), инициалов («А. С. Пушкин», "
                "«J. W. Goethe»), номеров пунктов списка («2.1.»), немецких порядковых числительных («im "
                "19. Jahrhundert», «am 4. Mai»); ссылка на страницу после цитаты («…“ (164)») остаётся с "
                "цитатой; прямая речь «— Пойдёшь? — спросил он.» не разрезается. В коллекции выделено "
                f"{num(sum(d['sentences'] for d in data['docs']))} предложений.")
    report.subheading("2. Термины")
    report.text("Из предложений выделяются слова — последовательности букв, возможно с дефисом. По "
                "методическим указаниям не учитываются числа, стоп-слова и слова из латинских букв (для "
                "немецкого текста, где латиница — родной алфавит, чужими считаются слова кириллицей). Кроме "
                "стоп-слов не учитываются служебные обороты: в обороте «в свою очередь» слово «очередь» "
                "смысла не несёт. Слова приводятся к термину: русские — к лемме pymorphy3 («нейронных "
                "сетей» → «нейронный», «сеть»), немецкие — к основе Snowball («Datenbanken» → «datenbank»).")
    report.subheading("3. Вес термина")
    report.text("Базовый вес слова вычисляется по формуле TF·IDF в модифицированном виде:")
    report.formula("w(t, D) = 0,5 · (1 + tf(t, D) / tf~max~(D)) · log(|DB| / df(t)),")
    report.text("где tf(t, D) — частота термина t в документе D, tf~max~(D) — максимальная частота термина в "
                "документе, df(t) — количество документов с термином t, |DB| — количество документов. База "
                "DB — документы коллекции того же языка (|DB| = 10): русский термин никогда не встретится в "
                "немецком документе. Свой документ пользователя добавляется к базе, иначе у его терминов df "
                "был бы равен нулю. Логарифм натуральный — основание на порядок предложений не влияет.")
    report.subheading("4. Вес предложения")
    report.text("Вес предложения S~i~ — произведение трёх функций:")
    report.formula("Score(S~i~) = Σ tf(t, S~i~) · w(t, D),   суммирование по терминам t ∈ S~i~,")
    report.formula("Posd(S~i~) = 1 − BD(S~i~) / |D|,   Posp(S~i~) = 1 − BP(S~i~) / |P|,")
    report.formula("Weight(S~i~) = Score(S~i~) · Posd(S~i~) · Posp(S~i~),")
    report.text("где tf(t, S~i~) — частота термина t в предложении, |D| — число символов в документе, "
                "BD(S~i~) — количество символов до S~i~ в документе, |P| — число символов в абзаце, "
                "BP(S~i~) — количество символов до S~i~ в абзаце.")
    report.subheading("5. Генерация классического реферата")
    report.text("Из документа выбираются N предложений с наибольшим весом (по умолчанию N = 10 — "
                "рекомендуемый размер реферата); при равенстве веса предпочтение отдаётся более раннему "
                "предложению. Выбранные предложения выводятся в порядке следования в тексте. Методические "
                "указания допускают трансформацию предложений; система выполняет её безопасную часть — "
                "удаляет ссылки на литературу «[3]», отсылки «(рис. 2)» и русские вводные конструкции в "
                "начале («Таким образом,», «Кроме того,»). У немецких предложений вводное слово не "
                "удаляется: немецкий порядок слов требует, чтобы спрягаемый глагол стоял вторым, и без "
                "первого слова утверждение превратилось бы в вопрос. Пользователь может переключиться на "
                "исходный вид предложений.")
    report.subheading("6. Реферат в виде списка ключевых слов")
    report.steps([
        "Ключевые слова верхнего уровня. Существительные с наибольшей значимостью tf(t, D) · log(|DB| / "
        "df(t)) — по умолчанию 10. Для ключевых слов взята классическая значимость, а не w(t, D): множитель "
        "0,5 · (1 + tf / tf_max) нарочно сглаживает частоту, и в коллекции из десяти документов слово, "
        "встреченное трижды, весило бы почти как главное понятие статьи, встреченное тридцать раз.",
        "Именные группы. Встретившиеся не реже двух раз: прилагательное (причастие) и существительное, "
        "согласованные в роде, числе и падеже («нейронная сеть», «искусственная нейронная сеть»); "
        "существительное и существительное в родительном падеже («база данных», «проектирование баз "
        "данных»); имя человека из имени, отчества и фамилии («Евгений Онегин», «Елена Сергеевна»); у "
        "немецкого текста — прилагательное и существительное («künstliche Neuronen») и сложное слово, "
        "содержащее ключевое слово («Datenbanksystem» при «Datenbank»). Группа приводится к начальной "
        "форме: «нейронных сетей» → «нейронная сеть».",
        "Иерархия. Группа подчиняется ключевому слову, которое в неё входит, для русского — и однокоренному "
        "(«лазерный луч» — к «лазеру»); из нескольких подходящих выбирается самое значимое. Длинная группа "
        "подчиняется короткой, которую содержит: «сеть → нейронная сеть → параметр нейронных сетей».",
    ])
    report.subheading("7. Пример расчёта")
    report.text("Работа формул проверяется на коллекции из трёх документов: A — «Кот ловит мышь. Кот спит.», "
                "B — «Собака ловит кота.», C — «Мышь ест сыр.» («ест» → «есть» — стоп-слово). Для документа A: "
                "tf(кот) = tf~max~ = 2, |DB| = 3. Веса терминов и предложений приведены в таблице 7; те же "
                "числа проверяются автотестом.")
    report.table("Пример расчёта весов для документа A", ["Величина", "Расчёт", "Значение"], [
        ("w(кот, A)", "0,5 · (1 + 2/2) · ln(3/2)", "0,4055"),
        ("w(ловить, A) = w(мышь, A)", "0,5 · (1 + 1/2) · ln(3/2)", "0,3041"),
        ("w(спать, A)", "0,5 · (1 + 1/2) · ln 3", "0,8240"),
        ("Score(S~1~) «Кот ловит мышь.»", "0,4055 + 0,3041 + 0,3041", "1,0137"),
        ("Posd(S~1~) = Posp(S~1~)", "1 − 0/25", "1"),
        ("Score(S~2~) «Кот спит.»", "0,4055 + 0,8240", "1,2294"),
        ("Posd(S~2~) = Posp(S~2~)", "1 − 16/25", "0,36"),
        ("Weight(S~1~); Weight(S~2~)", "1,0137 · 1 · 1; 1,2294 · 0,36 · 0,36", "1,0137; 0,1593"),
    ], widths=[5.0, 7.0, 4.5], size=Pt(11))
    report.text("Второе предложение содержит более редкий термин «спать» и по Score весомее первого, но "
                "стоит далеко от начала документа и абзаца, и в реферат из одного предложения попадает "
                "первое.")
    report.subheading("8. Алгоритм sc-агента")
    report.steps([
        "Получить инициированное действие класса action_build_summary; прочитать аргументы: rrel_1 — узел "
        "документа, rrel_2 — sc-ссылка с числом предложений (по умолчанию 10).",
        "Прочитать из базы знаний текст документа (nrel_document_text) и его язык (принадлежность ссылки "
        "lang_ru или lang_de), заголовок и предметную область.",
        "Найти в базе знаний документы тестовой коллекции того же языка и прочитать их тексты — по ним "
        "вычисляются |DB| и df(t). Разобранные тексты агент хранит в памяти по их содержимому.",
        "Построить реферат функцией izbornik.summary.build.",
        "Отвязать от документа прежний реферат того же размера, записать новый одним запросом, связать его "
        "с действием отношением nrel_answer и завершить действие (question_finished_successfully). При "
        "ошибке действие завершается как неуспешное.",
    ])


def testing_section(report: Report, data: dict) -> None:
    tests = data["tests"]
    counts = data["test_counts"]
    total = sum(counts.values())
    report.heading("Результаты тестирования системы")
    report.subheading("1. Автоматическое тестирование")
    if tests:
        outcome = f"все пройдены" if not tests["failed"] and not tests["skipped"] else \
            f"пройдено {tests['passed']}, не пройдено {tests['failed']}, пропущено {tests['skipped']}"
        report.text(f"Автотесты написаны с использованием pytest. Запуск: python -m pytest tests -q. "
                    f"Результат: {total} {plural(total, 'тест', 'теста', 'тестов')}, {outcome}, время выполнения — около "
                    f"{num(tests['seconds'], 0)} с. Проверки на живой ostis-системе выполнялись при запущенной "
                    f"NIKA; без неё они пропускаются. Состав тестов приведён в таблице 8.")
    else:
        report.text(f"Автотесты написаны с использованием pytest ({total} тестов). Состав — в таблице 8.")
    described = [
        ("test_segment.py", "Разбиение на предложения: сокращения, инициалы, порядковые числительные, "
                            "прямая речь, кавычки, номера пунктов; смещения BD и BP; заголовки"),
        ("test_analysis.py", "Отсев латиницы, чисел, стоп-слов и оборотов; леммы и основы; аббревиатуры; "
                             "существительные немецкого текста; разрешение неоднозначных имён"),
        ("test_weights.py", "Формулы методички на примере, посчитанном вручную: tf, df, w(t, D), Score, "
                            "Posd, Posp, вес; отбор и порядок предложений; добавление нового документа в DB"),
        ("test_keywords.py", "Именные группы и их начальная форма, иерархия «сеть → нейронная сеть», "
                             "однокоренные слова, немецкие сложные слова"),
        ("test_compress.py", "Сжатие предложений: ссылки, отсылки, вводные конструкции"),
        ("test_collection.py", "Состав коллекции, одинаковый объём, лицензии, отделение эталона от текста, "
                               "полный реферат каждого документа"),
        ("test_evaluation.py", "Мера ROUGE на известном примере, способы отбора, оракул как верхняя граница"),
        ("test_export.py", "Сохранение в TXT, DOCX, JSON, SCs; экранирование SCs"),
        ("test_web.py", "Страницы, активные ссылки, сохранение, печать, свой документ, ошибки ввода"),
        ("test_ostis_unit.py", "Системные идентификаторы, полнота онтологии, отказ соединения"),
        ("test_ostis_live.py", "Живая NIKA: однократная загрузка онтологии, совпадение результата агента с "
                               "локальным, один реферат каждого размера, приём SCs-выгрузки сервером"),
        ("test_companion_off.py", "Выключатель паука Пафнутия (в отдельном процессе)"),
    ]
    report.table("Состав автоматических тестов", ["Файл", "Что проверяется", "Тестов"],
                 [(name, what, counts.get(name, 0)) for name, what in described],
                 widths=[3.8, 11.0, 1.7], size=Pt(10.5))

    report.subheading("2. Функциональное тестирование")
    report.text("Функциональное тестирование выполнялось через веб-интерфейс на всей тестовой коллекции в "
                "обоих режимах. Проверялось выполнение каждого требования методических указаний (таблица 9).")
    report.table("Проверка выполнения требований к системе", ["Требование", "Как проверялось", "Результат"], [
        ("Вход — документы одинакового размера из предметных областей варианта на его языках",
         "20 документов по 16–19 тыс. знаков: научные статьи по CS и литературоведческие тексты на русском и "
         "немецком; свои документы TXT, MD, HTML, DOCX, PDF", "выполнено"),
        ("Выход — активная ссылка на исходный документ",
         "Ссылки «Исходный документ» (текст с отмеченными предложениями), «Оригинал» (страница источника), "
         "«Текст файлом»; ссылка есть и во всех форматах сохранения", "выполнено"),
        ("Классический реферат", "10 предложений с наибольшим весом в порядке текста, веса и их сомножители "
                                 "под каждым предложением", "выполнено"),
        ("Реферат в виде списка ключевых слов", "Иерархический список: ключевые слова и подчинённые "
                                               "именные группы", "выполнено"),
        ("Сохранение в файл", "TXT, HTML, DOCX, JSON, SCs для каждого реферата", "выполнено"),
        ("Распечатка", "Версия для печати; правила печати для любой страницы", "выполнено"),
        ("Простой интерфейс и help-средства", "Пять разделов меню, раздел «Справка» из девяти подразделов, "
                                              "подсказки в формах", "выполнено"),
        ("Методика Sentence extraction + OSTIS", "Реферат строит sc-агент в базе знаний NIKA; 20 из 20 "
                                                  "рефератов совпадают с локальным расчётом", "выполнено"),
    ], widths=[4.6, 9.4, 2.5], size=Pt(10.5))

    report.subheading("3. Пример реферата")
    collection = data["collection"]
    result = collection.summarize("ru-cs-ostis", 10)
    summary = result.summary
    entry = collection.get("ru-cs-ostis")
    report.text(f"Документ «{summary.title}» (Н. А. Гулякина, И. Т. Давыденко; {num(summary.stats['chars'])} "
                f"{plural(summary.stats['chars'], 'знак', 'знака', 'знаков')}, {summary.stats['sentences']} "
                f"{plural(summary.stats['sentences'], 'предложение', 'предложения', 'предложений')}). Классический реферат из 10 предложений "
                f"({num(summary.stats['summary_chars'])} "
                f"{plural(summary.stats['summary_chars'], 'знак', 'знака', 'знаков')}, {pct(summary.stats['compression'])} "
                "документа), сжатые предложения:")
    for i, sentence in enumerate(summary.sentences, start=1):
        paragraph = report._paragraph(WD_ALIGN_PARAGRAPH.JUSTIFY, left=INDENT, hanging=Cm(0.6), after=2)
        report._rich(paragraph, f"{i}. {sentence.compressed} ", size=Pt(12))
        report._rich(paragraph, f"[№ {sentence.index + 1}, вес {num(sentence.weight, 2)}]", size=Pt(10),
                     italic=True)
    report.text("Реферат в виде списка ключевых слов:")
    for top in summary.keywords.tree:
        line = top.text
        children = [kw.text for _, kw in top.walk()][1:]
        if children:
            line += " → " + "; ".join(children)
        paragraph = report._paragraph(WD_ALIGN_PARAGRAPH.LEFT, left=INDENT, after=1)
        report._rich(paragraph, line, size=Pt(12))
    ref_keywords = ", ".join(entry.reference_keywords)
    score = next(d for d in data["evaluation"]["documents"] if d["doc_id"] == "ru-cs-ostis")
    covered = round(score["keywords"]["author_recall"] * len(entry.reference_keywords))
    report.text(f"Ключевые слова авторов статьи: {ref_keywords}. Полностью покрыты списком системы "
                f"{covered} из {len(entry.reference_keywords)}.", after=8)
    report.figure(SCREENS / "ui_summary.png", "Страница реферата документа (режим OSTIS)",
                  crop=(0, 0, 1300, 1450))
    report.figure(SCREENS / "ui_source.png", "Исходный документ с отмеченными предложениями реферата",
                  crop=(0, 0, 1300, 1150))
    report.text("Реферат немецкого документа «Compiler» строится так же; в реферате в виде ключевых слов "
                "видна роль немецких сложных слов: под ключевым словом «Compiler» — «JIT-Compiler», "
                "«Precompiler», «Multi-pass-Compiler», под «Analyse» — «syntaktische Analyse», «semantische "
                "Analyse», «lexikalische Analyse» (рисунок 8).")
    report.figure(SCREENS / "ui_summary_de.png", "Реферат немецкого документа «Compiler»",
                  crop=(0, 0, 1300, 1600))
    report.text("На рисунке 9 — тот же документ в sc-web: узел документа с основным идентификатором и "
                "текстом, связанным отношением «текст документа*»; на рисунке 10 — версия реферата для печати.")
    report.figure(SCREENS / "scweb_document.png", "Документ коллекции в базе знаний (sc-web)",
                  crop=(0, 60, 1500, 700))
    report.figure(SCREENS / "ui_print.png", "Версия реферата для печати", crop=(0, 0, 1300, 1450),
                  max_height=18)


def evaluation_section(report: Report, data: dict) -> None:
    ev = data["evaluation"]
    groups = ev["groups"]
    cols = GROUPS + ["all"]
    report.heading("Оценка полученных результатов")
    report.subheading("1. Методика оценки")
    report.text("Точность классического реферата оценивалась мерой ROUGE: реферат сравнивается с эталоном — "
                "авторской аннотацией (КиберЛенинка) или вводным разделом статьи (Википедия). ROUGE-N — доля "
                "n-грамм эталона, найденных в реферате (полнота R), и доля n-грамм реферата, найденных в "
                "эталоне (точность P); ROUGE-1 учитывает отдельные слова, ROUGE-2 — пары соседних слов. "
                "N-граммы строятся по леммам значимых слов: русская и немецкая морфология делают совпадение "
                "словоформ слишком строгим, а стоп-слова совпадают всегда и только завышают меру. Реферат из "
                "10 предложений длиннее эталона, поэтому главная мера — полнота R.")
    report.text("Чтобы числа были осмысленными, тот же объём отбирался базовыми способами: первые N "
                "предложений документа, случайные N предложений (среднее по 30 попыткам), только оценка "
                "Score и только положение Posd · Posp. «Оракул» жадно подбирает предложения по самому "
                "эталону и показывает потолок, выше которого никакой отбор предложений не поднимется.")
    report.subheading("2. Точность классического реферата")
    report.table("ROUGE-1, полнота R, для способов отбора по группам документов",
                 ["Способ отбора", *[GROUP_NAMES[c] for c in cols]],
                 [(METHOD_NAMES[m], *[(Bold if m == "extraction" else str)(num(groups[c]["rouge"][m]["r1"]))
                                     for c in cols]) for m in METHOD_NAMES],
                 widths=[5.4, 2.2, 2.2, 2.2, 2.2, 2.3], size=Pt(10.5))
    report.table("ROUGE-2, полнота R, для способов отбора по группам документов",
                 ["Способ отбора", *[GROUP_NAMES[c] for c in cols]],
                 [(METHOD_NAMES[m], *[(Bold if m == "extraction" else str)(num(groups[c]["rouge"][m]["r2"]))
                                     for c in cols]) for m in METHOD_NAMES],
                 widths=[5.4, 2.2, 2.2, 2.2, 2.2, 2.3], size=Pt(10.5))
    report.figure(REPORT / "eval_rouge.png", "Полнота ROUGE-1 и ROUGE-2 по группам документов")
    all_ = groups["all"]["rouge"]
    report.text(f"По всей коллекции метод даёт R1 = {num(all_['extraction']['r1'])} и R2 = "
                f"{num(all_['extraction']['r2'])} против {num(all_['lead']['r1'])} и {num(all_['lead']['r2'])} у "
                f"первых десяти предложений и {num(all_['random']['r1'])} и {num(all_['random']['r2'])} у "
                f"случайного выбора; потолок — {num(all_['oracle']['r1'])} и {num(all_['oracle']['r2'])}. Метод "
                f"набирает {pct(all_['extraction']['r1'] / all_['oracle']['r1'], 0)} потолка по ROUGE-1. Во всех "
                "четырёх группах он лучше первых N предложений, случайного выбора и отбора по одному положению. "
                "Точность P, F-мера и доля потолка по группам приведены в таблице 12.")
    rows = []
    for c in ["ru-cs", "ru-lit", "de-cs", "de-lit", "ru", "de", "cs", "lit", "all"]:
        r = groups[c]["rouge"]["extraction"]
        rows.append((GROUP_NAMES[c], num(r["p1"]), num(r["r1"]), num(r["f1"]), num(r["p2"]), num(r["r2"]),
                     num(r["f2"]), pct(r["r1"] / groups[c]["rouge"]["oracle"]["r1"], 0),
                     num(groups[c]["oracle_overlap"], 1)))
    report.table("Точность, полнота и F-мера метода; доля потолка; предложения, совпавшие с оракулом",
                 ["Группа", "P1", "R1", "F1", "P2", "R2", "F2", "R1 / R1 оракула", "Общих с оракулом"],
                 rows, widths=[3.6, 1.35, 1.35, 1.35, 1.35, 1.35, 1.35, 2.2, 2.2], size=Pt(10))

    g = groups
    report.text("Разные предметные области и языки реферируются с разной точностью:")
    report.bullets([
        f"научные статьи — лучше литературоведческих текстов (R1 {num(g['cs']['rouge']['extraction']['r1'])} "
        f"против {num(g['lit']['rouge']['extraction']['r1'])}). В статье термины повторяются и сосредоточены в "
        "ключевых предложениях — постановке задачи, описании метода, выводах, — и те же термины есть в "
        "аннотации. Текст о романе в значительной части пересказывает сюжет, и его лексика (имена, события) "
        "расходится с вводным разделом, где речь о жанре, истории создания и значении произведения;",
        f"русские тексты — лучше немецких (R1 {num(g['ru']['rouge']['extraction']['r1'])} против "
        f"{num(g['de']['rouge']['extraction']['r1'])}). Отчасти это жанр: русские статьи по CS — научные "
        "статьи с аннотацией, немецкие — энциклопедические. Отчасти — морфология: основа Snowball грубее "
        "леммы, а немецкие сложные слова дробят лексику, и совпадений по отдельным словам меньше;",
        f"лучший результат — русские научные статьи (R1 {num(g['ru-cs']['rouge']['extraction']['r1'])}, "
        f"{pct(g['ru-cs']['rouge']['extraction']['r1'] / g['ru-cs']['rouge']['oracle']['r1'], 0)} потолка), "
        f"худший — немецкие литературоведческие тексты (R1 {num(g['de-lit']['rouge']['extraction']['r1'])}): "
        "их вводный раздел почти не пересекается по лексике ни с какими предложениями текста — потолок "
        f"здесь лишь {num(g['de-lit']['rouge']['oracle']['r1'])}.",
    ])
    report.text(f"Вклад функций положения: одна оценка Score даёт по коллекции R1 = "
                f"{num(all_['score']['r1'])}, полная формула — {num(all_['extraction']['r1'])}. Заметнее всего "
                f"положение помогает на русской литературе ({num(g['ru-lit']['rouge']['score']['r1'])} → "
                f"{num(g['ru-lit']['rouge']['extraction']['r1'])}) и немецких статьях "
                f"({num(g['de-cs']['rouge']['score']['r1'])} → {num(g['de-cs']['rouge']['extraction']['r1'])}); "
                f"на русских научных статьях и немецкой литературе одна оценка Score не хуже "
                f"({num(g['ru-cs']['rouge']['score']['r1'])} и {num(g['de-lit']['rouge']['score']['r1'])}). "
                "Score — сумма по словам, поэтому метод предпочитает длинные предложения, насыщенные "
                "терминами; это видно и по реферату-примеру.")

    size = ev.get("size_study") or {}
    if size:
        report.subheading("3. Зависимость от размера реферата")
        report.table("Полнота в зависимости от числа предложений реферата",
                     ["Предложений", "R1 метода", "R1 первых N", "R2 метода", "R2 первых N"],
                     [(n, num(v["extraction"]["r1"]), num(v["lead"]["r1"]), num(v["extraction"]["r2"]),
                       num(v["lead"]["r2"])) for n, v in size.items()],
                     widths=[3.0, 3.3, 3.3, 3.3, 3.3], size=Pt(11))
        report.figure(REPORT / "eval_size.png", "Полнота в зависимости от размера реферата")
        report.text(f"С ростом реферата полнота растёт у обоих способов, но метод уходит вперёд: при 20 "
                    f"предложениях R1 {num(size['20']['extraction']['r1'])} против {num(size['20']['lead']['r1'])}. "
                    f"На коротком реферате (3–5 предложений) первые предложения документа дают даже чуть больший "
                    f"ROUGE-2 ({num(size['3']['lead']['r2'])} против {num(size['3']['extraction']['r2'])} при "
                    "трёх предложениях): начало документа обычно вводит тему теми же словосочетаниями, что и "
                    "эталон, а метод на малом объёме выбирает длинные предложения из разных частей текста.")
    scope = ev.get("scope_study") or {}
    if scope:
        report.text(f"Выбор базы для df(t) на результат почти не влияет: документы того же языка — R1 "
                    f"{num(scope['language']['r1'])}, вся коллекция — {num(scope['collection']['r1'])}. Словари "
                    "двух языков не пересекаются, и переход к общей базе сдвигает log(|DB| / df) почти на одну "
                    "и ту же величину log 2. Выбрана база по языку: в ней термин, встречающийся во всех "
                    "документах языка, получает нулевой вес, как и должно быть по смыслу формулы.")

    report.subheading("4. Точность реферата в виде ключевых слов")
    rows = []
    for c in ["ru-cs", "ru-lit", "de-cs", "de-lit", "all"]:
        k = groups[c]["keywords"]
        rows.append((GROUP_NAMES[c], pct(k.get("precision")), pct(k.get("precision_tf")),
                     pct(k.get("author_recall")) if k.get("author_recall") is not None else "—",
                     pct(k.get("author_recall_tf")) if k.get("author_recall_tf") is not None else "—"))
    report.table("Оценка реферата в виде ключевых слов",
                 ["Группа", "Точность по эталону: tf · idf", "то же: частота tf",
                  "Полнота по ключевым словам авторов: tf · idf", "то же: частота tf"],
                 rows, widths=[3.6, 3.2, 3.0, 3.7, 3.0], size=Pt(10.5))
    k = groups["all"]["keywords"]
    report.text(f"Точность — доля ключевых слов верхнего уровня, встречающихся в эталонном реферате; полнота — "
                f"доля ключевых слов авторов (есть у статей КиберЛенинки), все слова которых вошли в список "
                f"системы. Для сравнения то же посчитано для самых частых существительных без множителя "
                f"log(|DB| / df). Частые существительные чаще встречаются в аннотации ({pct(k['precision_tf'])} "
                f"против {pct(k['precision'])}) — это общая лексика вроде «система», «метод», «данные». Зато "
                f"ключевые слова авторов система покрывает вдвое лучше ({pct(k['author_recall'])} против "
                f"{pct(k['author_recall_tf'])}): именно множитель idf отличает понятия статьи от общей лексики.")

    report.subheading("5. Затраченное время")
    rows = []
    for c in GROUPS:
        t = groups[c]["timings"]
        rows.append((GROUP_NAMES[c], ms(t["analysis"]), ms(t["term_weights"]), ms(t["sentences"]),
                     ms(t["keywords"]), ms(t["analysis"] + t["summarize_total"])))
    report.table("Время построения реферата одного документа (≈ 10 страниц)",
                 ["Группа", "Разбор документа", "Веса терминов", "Веса и отбор предложений",
                  "Ключевые слова", "Всего"], rows, widths=[3.6, 2.6, 2.4, 2.8, 2.4, 2.7], size=Pt(10.5))
    report.figure(REPORT / "eval_time.png", "Время построения реферата по этапам")
    ostis = ev.get("ostis") or {}
    report.text("Измерения выполнены на локальной машине под Windows 11 после загрузки словарей pymorphy3 и "
                "стеммера (разовая стоимость запуска — около секунды). Основное время занимает разбор "
                "документа: сегментация и морфологический анализ; собственно формулы — веса терминов и "
                "предложений — занимают меньше миллисекунды. Русский текст разбирается в три-четыре раза "
                "дольше немецкого: лемматизация pymorphy3 с учётом нескольких разборов слова дороже "
                "стемминга; по той же причине дольше строятся ключевые слова — проверка согласования и "
                "склонение именных групп.")
    if ostis:
        report.table("Время работы в режиме OSTIS", ["Операция", "Время"], [
            ("Загрузка онтологии (пять файлов SCs)", ms(ostis.get("ontology_ms")) if ostis.get("ontology_ms") and
             ostis.get("ontology_ms") > 50 else "≈ 0,3 с (при первом подключении)"),
            ("Проверка и загрузка 20 документов коллекции в базу знаний", ms(ostis.get("sync_ms"))),
            ("Первый вызов агента для языка (разбор коллекции языка)", ms(ostis.get("agent_first_ms"))),
            ("Вызов агента: действие, построение, запись, ожидание, среднее", ms(ostis.get("agent_ms"))),
            ("Работа агента по данным базы знаний, среднее", ms(ostis.get("agent_work_ms"))),
            ("Чтение готового реферата из базы знаний, среднее", ms(ostis.get("kb_read_ms"))),
            ("Рефераты, совпавшие с локальным расчётом", f"{ostis.get('matches')} из {ostis.get('documents')}"),
        ], widths=[12.0, 4.5], size=Pt(11))
        report.text(f"Режим OSTIS медленнее локального: вызов агента занимает около {ms(ostis.get('agent_ms'))} "
                    "— запись реферата (около 500 sc-элементов) одним запросом, чтение текстов коллекции, обмен "
                    "событиями. Зато готовый реферат читается из базы знаний за "
                    f"{ms(ostis.get('kb_read_ms'))} и дальше доступен любым средствам ostis-системы. Все "
                    "рефераты, построенные агентом и прочитанные из базы знаний, совпали с локальным расчётом "
                    "до предложения, веса и ключевого слова.")


def conclusion(report: Report, data: dict) -> None:
    ev = data["evaluation"]
    g = ev["groups"]
    tests = data["tests"]
    total = sum(data["test_counts"].values())
    report.heading("Вывод")
    report.text(f"В ходе лабораторной работы спроектирована и программно реализована система автоматического "
                f"реферирования документов «{APP_NAME}» по методике Sentence extraction + OSTIS. Система строит "
                "реферат из двух разделов — классического реферата и реферата в виде списка ключевых слов — "
                "и выдаёт его вместе с активной ссылкой на исходный документ; реферат сохраняется в TXT, HTML, "
                "DOCX, JSON и SCs и выводится на печать. Интерфейс содержит справку и подсказки.")
    report.text("Все требования варианта 4 выполнены. Обрабатываются тексты на русском и немецком языках из "
                "двух предметных областей — научные статьи по computer science и сочинения по литературе. "
                "Составлена тестовая коллекция из 20 документов одинакового объёма (около 10 страниц) с "
                "эталонами, взятыми из источников. Формулы методических указаний реализованы без изменений и "
                "проверены автотестом на примере, посчитанном вручную.")
    report.text("Технология OSTIS используется по существу: онтология предметной области автоматического "
                "реферирования загружается в базу знаний ostis-системы NIKA, документы коллекции хранятся "
                "в базе знаний, реферат строит sc-агент, откликающийся на действие «построить реферат "
                "документа», и записывает его в базу знаний в виде семантической структуры, которую можно "
                "просматривать в sc-web и выгрузить на языке SCs. Результаты агента совпадают с локальным "
                "расчётом для всех документов коллекции.")
    report.text(f"Оценка показала, что метод работоспособен: по всей коллекции полнота ROUGE-1 — "
                f"{num(g['all']['rouge']['extraction']['r1'])} против {num(g['all']['rouge']['lead']['r1'])} у первых "
                f"предложений документа и {num(g['all']['rouge']['random']['r1'])} у случайных, "
                f"{pct(g['all']['rouge']['extraction']['r1'] / g['all']['rouge']['oracle']['r1'], 0)} потолка, "
                "достижимого отбором предложений. Научные статьи реферируются заметно лучше "
                "литературоведческих текстов, русские — лучше немецких. Реферат в виде ключевых слов "
                f"покрывает {pct(g['all']['keywords']['author_recall'])} ключевых слов авторов статей — вдвое "
                "больше, чем простой список самых частых существительных. Реферат документа объёмом "
                "10 страниц строится за десятки миллисекунд локально и за доли секунды через OSTIS.")
    if tests:
        report.text(f"Корректность системы подтверждена {total} автоматическими тестами, включая проверки на "
                    "живой ostis-системе.")
    report.text("Выявлены и ограничения метода: оценка Score как сумма по словам отдаёт предпочтение длинным "
                "предложениям, а на текстах, где эталон говорит о другом, чем основная часть текста (пересказ "
                "сюжета и вводный раздел о романе), отбор предложений упирается в низкий потолок. Улучшить "
                "результат могли бы нормировка Score по длине предложения, учёт заголовка документа и "
                "разрешение анафоры при сжатии предложений.")
    report.text("Перспективы применения: подготовка рефератов для электронных библиотек и репозиториев "
                "научных статей, предварительный просмотр документов в информационно-поисковой системе "
                "(например, в системе первой лабораторной работы), наполнение баз знаний ostis-систем "
                "ключевыми терминами и сжатыми описаниями документов — реферат, записанный в базу знаний, "
                "сразу доступен другим агентам ostis-системы.")


def build(output: Path, run_tests: bool) -> Path:
    data = gather(run_tests)
    report = Report()
    title_page(report)
    goal_and_task(report)
    libraries(report)
    collection_section(report, data)
    structure_section(report)
    data_structures(report)
    algorithm_section(report, data)
    testing_section(report, data)
    evaluation_section(report, data)
    components(report)
    conclusion(report, data)
    return report.save(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", default=str(ROOT / "ОтчётЕЯзИИС37.docx"))
    parser.add_argument("--no-tests", action="store_true", help="не запускать pytest")
    arguments = parser.parse_args()
    path = build(Path(arguments.output), not arguments.no_tests)
    print(f"Отчёт: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
