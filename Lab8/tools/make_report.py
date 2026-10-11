"""Сборка отчёта по лабораторной работе в формате DOCX.

    python tools/make_report.py [--output ПУТЬ] [--no-tests]

Числа в отчёт не вписаны вручную: результаты проверки, размеры словарей,
число правил и реплик, число тестов берутся из данных системы
(report/evaluation.json, data/pronunciation, модули glashatai, прогон pytest).
Схемы — из report/ (tools/make_diagrams.py), графики — tools/evaluate.py,
снимки экрана — report/screens (tools/screenshots.py).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import docx  # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from docx.shared import Cm, Pt  # noqa: E402

from glashatai import config, console, pafnuty  # noqa: E402
from glashatai.phonetics import g2p  # noqa: E402

console.setup()

ROOT = Path(__file__).resolve().parent.parent
REPORT = config.REPORT_DIR
SCREENS = REPORT / "screens"
FONT = "Times New Roman"
SIZE = Pt(14)
INDENT = Cm(1.25)

THORSTEN = "piper:de_DE-thorsten-medium"
KERSTIN = "piper:de_DE-kerstin-low"
KARL = "formant:karl"
PAFNUTY = "formant:pafnuty"
EVA = "piper:de_DE-eva_k-x_low"


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
        language = normal.element.rPr.makeelement(qn("w:lang"), {qn("w:val"): "ru-RU"})
        normal.element.rPr.append(language)

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
        # знак процента не отрывается от числа
        run = paragraph.add_run(text.replace(" %", "\u00a0%"))
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

    def heading(self, content, *, new_page=False):
        paragraph = self.text(content, bold=True, align=WD_ALIGN_PARAGRAPH.LEFT, indent=False, after=6, keep=True)
        paragraph.paragraph_format.page_break_before = new_page

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
        """Нумерованный список; первое предложение пункта выделяется полужирным."""
        for offset, item in enumerate(items, start=start):
            paragraph = self._paragraph(WD_ALIGN_PARAGRAPH.JUSTIFY, left=INDENT, hanging=Cm(0.6), after=3)
            head, separator, tail = item.partition(". ")
            if separator and len(head) < 90:
                self._rich(paragraph, f"{offset}. {head}.", bold=True)
                self._rich(paragraph, " " + tail)
            else:
                self._rich(paragraph, f"{offset}. {item}")

    def table(self, caption, header, rows, *, widths=None, size=Pt(11), center=None):
        """center: True — все столбцы, кроме первого, по центру; None — только числа."""
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
            paragraph.paragraph_format.keep_with_next = True
            self._rich(paragraph, str(title), bold=True, size=size)
        header_row = table.rows[0]._tr.get_or_add_trPr()
        header_row.append(header_row.makeelement(qn("w:tblHeader"), {}))
        for values in rows:
            cells = table.add_row().cells
            for index, value in enumerate(values):
                cells[index].text = ""
                paragraph = cells[index].paragraphs[0]
                paragraph.paragraph_format.space_after = Pt(0)
                if index and (center if center is not None else _numeric(value)):
                    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                self._rich(paragraph, str(value), size=size, bold=isinstance(value, Bold))
        if widths:
            for row in table.rows:
                for index, width in enumerate(widths):
                    row.cells[index].width = Cm(width)
        self.document.add_paragraph().paragraph_format.space_after = Pt(2)
        return table

    def figure(self, path: Path, caption: str, *, max_width=16.0, max_height=21.0):
        if not path.exists():
            self.text(f"[нет файла {path.name}]", italic=True)
            return
        from PIL import Image

        with Image.open(path) as image:
            ratio = image.height / image.width
        width = max_width
        if width * ratio > max_height:
            width = max_height / ratio
        self.figure_number += 1
        paragraph = self._paragraph(WD_ALIGN_PARAGRAPH.CENTER, after=3, keep=True)
        paragraph.add_run().add_picture(str(path), width=Cm(width))
        self.text(f"Рисунок {self.figure_number} – {caption}", align=WD_ALIGN_PARAGRAPH.CENTER,
                  indent=False, after=8, size=Pt(12))

    @property
    def next_table(self) -> int:
        """Номер таблицы, которая будет выведена следующей."""
        return self.table_number + 1

    @property
    def next_figure(self) -> int:
        return self.figure_number + 1

    def blank(self, count=1):
        for _ in range(count):
            self._paragraph(after=0)

    def save(self, path: Path) -> Path:
        self.document.save(str(path))
        return path


class Bold(str):
    """Значение ячейки таблицы, выводимое полужирным."""


def _numeric(value) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[\d\s ,.–%—мсптх×/+−-]+", value))


def pct(value, digits=1) -> str:
    return "—" if value is None else f"{100 * value:.{digits}f}".replace(".", ",") + "\u00a0%"


def dec(value, digits=2, sign=False) -> str:
    text = f"{value:+.{digits}f}" if sign else f"{value:.{digits}f}"
    return text.replace(".", ",").replace("-", "−")


def span(values) -> str:
    """Диапазон долей: «18–22 %»."""
    return f"{100 * min(values):.0f}–{pct(max(values), 0)}"


def rate(value) -> str:
    """Множитель темпа: 0.75 — «0,75», 2.0 — «2»."""
    return f"{float(value):g}".replace(".", ",")


def group(value: int) -> str:
    """Число с пробелами между разрядами: 11808 — «11 808»."""
    return f"{value:,}".replace(",", " ")


def plural(count: int, one: str, few: str, many: str) -> str:
    """Согласует существительное с числительным: 1 тест, 2 теста, 5 тестов."""
    if 11 <= count % 100 <= 14:
        return many
    return {1: one, 2: few, 3: few, 4: few}.get(count % 10, many)


# --- данные ---------------------------------------------------------------------------

def gather(run_tests: bool) -> dict:
    evaluation = json.loads((REPORT / "evaluation.json").read_text(encoding="utf-8"))
    dictionaries = {}
    for name in ("english", "acronyms", "abbreviations"):
        lines = (config.DATA_DIR / "pronunciation" / f"{name}.tsv").read_text(encoding="utf-8").splitlines()
        dictionaries[name] = sum(1 for line in lines if line.strip() and not line.lstrip().startswith("#"))
    data = {"evaluation": evaluation, "dictionaries": dictionaries,
            "g2p": {"exceptions": len(g2p.EXCEPTIONS), "stems": len(g2p.STEMS),
                    "foreign": len(g2p.FOREIGN_SUFFIXES)},
            "talk": {"occasions": len(pafnuty.TALK), "lines": sum(len(v) for v in pafnuty.TALK.values())}}
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
    center, right = WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.RIGHT
    for line in ("Министерство образования Республики Беларусь",
                 "Учреждение образования",
                 "«Белорусский государственный университет информатики и радиоэлектроники»",
                 "",
                 "Факультет информационных технологий и управления",
                 "Кафедра интеллектуальных информационных технологий"):
        report.text(line, align=center, indent=False, after=0)
    report.blank(7)
    for line in ("ОТЧЁТ",
                 "по лабораторной работе № 8",
                 "по курсу «Естественно-языковой интерфейс интеллектуальных систем»",
                 "«Разработка автоматизированной системы синтеза речи»",
                 "Вариант 3"):
        report.text(line, bold=True, align=center, indent=False, after=0)
    report.blank(7)
    for line in ("Выполнили:",
                 "Студенты гр. 321702 Бузычков Н. Ф.",
                 "Котко П. А.",
                 "Халилов Р. Э.",
                 "",
                 "Проверил: Крапивин Ю. Б."):
        report.text(line, align=right, indent=False, after=0)
    report.blank(6)
    report.text("Минск 2026", align=center, indent=False, after=0)


def goal_and_task(report: Report, data: dict) -> None:
    words = data["dictionaries"]
    report.heading("Цель работы:", new_page=True)
    report.text("Освоить на практике основные принципы создания систем синтеза речи; закрепить навыки "
                "программирования на языке высокого уровня.")
    report.heading("Задание:")
    report.text("Разработать систему синтеза речи, которая обеспечивает: ввод текста, или копирование через "
                "буфер обмена, или поддержку указателя мыши в любом другом приложении (например, на "
                "html-странице); воспроизведение сгенерированного речевого сигнала для введённого текста; "
                "настройку (выбор) голоса диктора, темпа, громкости и других параметров чтения. Параметры "
                f"варианта 3 и места, где выполнены требования, приведены в таблице {report.next_table}.")
    report.table("Параметры варианта 3 и требования методических указаний",
                 ["Параметр / требование", "Где реализовано"],
                 [["Система синтеза речи",
                   "разбор текста, нормализация, правила произношения; четыре вида голосов: нейросетевые "
                   "Piper, собственный формантный синтезатор, голоса Windows и голос браузера"],
                  ["Язык: немецкий",
                   "немецкие голоса Piper (Thorsten, Kerstin, Eva K и Thorsten с восемью манерами), немецкие "
                   "числительные, сокращения и правила произношения; интерфейс — на русском"],
                  ["Предметная область: научные статьи по computer science",
                   "пять статей немецкой Википедии по информатике; словари: "
                   f"{words['english']} английских терминов, {words['acronyms']} аббревиатур и имён, "
                   f"{words['abbreviations']} сокращения; чтение формул, единиц, версий, ссылок на источники "
                   "и адресов"],
                  ["Ввод текста, копирование через буфер, указатель мыши в другом приложении",
                   "«Чтец»: поле ввода, кнопка «Из буфера обмена», файлы TXT, HTML, PDF, DOCX, адрес "
                   "страницы; всё скопированное в любой программе Windows читается само; Ctrl+Alt+R читает "
                   "выделенное мышью в любой программе; закладка «Глашатай, читай» читает абзац под "
                   "указателем мыши на любой веб-странице; в «Статьях» — чтение предложения под указателем"],
                  ["Воспроизведение сгенерированного речевого сигнала",
                   "чтение по предложениям с подсветкой звучащего; пауза и продолжение с того же места, "
                   "переход к предыдущему и следующему, щелчок по предложению — читать с него; сохранение "
                   "всего текста в WAV"],
                  ["Настройки голоса диктора, темпа, громкости и других параметров",
                   "11 нейросетевых голосов, 3 собственных, голоса Windows и браузера; темп ×0,5–×2, "
                   "громкость 0–100 %, высота ±8 полутонов, живость интонации, паузы после предложения и "
                   "абзаца; правила чтения включаются по одному; словарь произношения пользователя"]],
                 widths=[5.0, 11.5])
    report.text("Система названа «Глашатай» — так называли того, кто громко и внятно объявлял указы на "
                "площади, читая написанное за тех, кто прочесть не мог. Название продолжает ряд «Арахна», "
                "«Толмач», «Изборник», «Драгоман», «Слухач». Как и в прошлых работах, в систему встроена "
                "игра с пауком Пафнутием — вкладка «Мой говорящий Пафнутий» по образцу игры «Мой говорящий "
                "Том».")


def technologies(report: Report) -> None:
    report.heading("Используемые технологии:")
    report.bullets([
        "Python 3, FastAPI, uvicorn, Jinja2 — сервер и страницы; поток событий сервера (Server-Sent Events) "
        "приносит на страницу текст из других программ;",
        "piper-tts (проект Rhasspy) — нейросетевой синтез: модели VITS в формате ONNX (ONNX Runtime), фонемы "
        "для них строит eSpeak NG; голоса de_DE-thorsten-medium, de_DE-kerstin-low, de_DE-eva_k-x_low, "
        "de_DE-thorsten_emotional-medium; работает без сети;",
        "NumPy, SciPy — собственный формантный синтезатор (цифровые резонаторы) и обработка звука: уровень, "
        "WSOLA, сдвиг тона, линейное предсказание (LPC);",
        "Microsoft Speech API — голоса Windows (System.Speech через PowerShell); Win32 API через ctypes "
        "(user32.dll, kernel32.dll) — буфер обмена, горячие клавиши, нажатие Ctrl+C; winsound — звук без "
        "браузера;",
        "Web Audio API, Web Speech API, CSS Custom Highlight API — воспроизведение и громкость, захват "
        "микрофона (AudioWorklet), голос браузера, подсветка звучащего слова;",
        "pypdf — текст из PDF; Vosk (Kaldi, модель vosk-model-small-de-0.15), matplotlib, pytest, httpx — "
        "проверка разборчивости, графики, тесты.",
    ])
    report.text("Готовыми взяты только нейросеть синтеза и встроенный в Piper eSpeak NG. Деление на "
                "предложения, нормализация текста, словари, правила произношения, просодия, формантный "
                "синтезатор, WSOLA, сдвиг тона, LPC-эффекты, калибровка темпа Piper, работа с буфером обмена "
                "и горячими клавишами, закладка для веб-страниц, игра и модель паука написаны с нуля.")


def structure_section(report: Report) -> None:
    report.heading("Описание структуры разработанной системы")
    report.text(f"Система — веб-приложение (рисунок {report.next_figure}). Сервер на FastAPI разбирает текст и "
                "синтезирует звук, браузер показывает текст, воспроизводит его по предложениям и подсвечивает "
                "звучащее. Текст проходит путь: абзацы и предложения (text/segment.py) → токены и нормализация "
                "(text/normalize.py со словарями lexicon.py, числительными numbers.py, аббревиатурами "
                "acronyms.py, единицами units.py) → произношение (phonetics/g2p.py) → синтезатор (engines/) → "
                "обработка звука (dsp.py) → WAV. Диктор (speaker.py) выбирает движок по голосу, хранит "
                "готовые предложения в памяти (до 96 МБ звука) и, если выбранный голос недоступен, читает "
                "голосом по умолчанию.")
    report.figure(REPORT / "structure.png", "Структура системы «Глашатай»", max_height=14)
    report.text("Модуль desktop.py следит за буфером обмена Windows и горячими клавишами; взятый текст "
                "уходит на страницу «Чтец» по потоку событий, а если она закрыта, звучит прямо из колонок. "
                "Модуль extract.py достаёт текст из HTML, PDF, DOCX и по адресу страницы, talking.py и "
                "voicefx.py — голос паука и эффекты для игры, evaluation.py и asr.py — проверка. Страницы "
                "интерфейса: «Чтец», «Статьи», «Из других программ», «Словарь», «Проверка», «Мой говорящий "
                f"Пафнутий», «Справка». Основные структуры данных приведены в таблице {report.next_table}.")
    report.table("Структуры данных системы", ["Структура", "Назначение"], [
        ["Token", "кусок текста: место в тексте, как написан, запись словами, произношение, вид"],
        ["Sentence, Paragraph, Document", "предложение (с токенами и видом: утверждение, вопрос, "
                                          "восклицание), абзац, разобранный текст"],
        ["ReadingOptions", "какие правила чтения включены"],
        ["Abbreviation, Entry, Lexicon, UserLexicon", "сокращение, запись словаря произношения, все словари, "
                                                      "словарь пользователя"],
        ["Syllable, Pronunciation", "слог (фонемы, ударение), произношение слова"],
        ["Phone, Score", "звук партитуры (длительность, мелодия), партитура предложения"],
        ["FormantVoice", "голос собственного синтезатора: тон, длина речевого тракта, форма импульса"],
        ["Voice, Settings, Audio, Spoken", "голос любого движка, настройки чтения, звук, синтезированное "
                                           "предложение"],
        ["DesktopState, Desktop", "состояние буфера обмена и горячих клавиш"],
        ["GoldCase", "случай эталонного набора нормализации"],
    ], widths=[5.5, 11.0])


def algorithm_section(report: Report, data: dict) -> None:
    words = data["dictionaries"]
    rules = data["g2p"]
    report.heading("Основные алгоритмы и принципы реализации")

    report.subheading("1. Подготовка текста")
    report.text("Синтезатор получает не исходный текст, а предложение, записанное так, как его прочёл бы "
                f"немецкий докладчик (рисунок {report.next_figure}). Сначала текст делится на абзацы: пустая "
                "строка разделяет их всегда, одиночный перевод строки — только после точки, у заголовка или "
                "пункта списка, иначе это перенос внутри абзаца, как в тексте из PDF. Точка в научном тексте "
                "часто не кончает предложение: «z. B.», «vgl. Abb. 3», «im 19. Jahrhundert», «J. von "
                "Neumann», «1.2. Abschnitt». Поэтому граница ставится, только если после знака конца идут "
                "пробел и заглавная буква, цифра или кавычка, а точка не принадлежит сокращению, порядковому "
                "числу, инициалу или номеру раздела. Сокращение («usw.») или порядковое число может кончать "
                "предложение, если следующее слово — из тех, с которых начинаются фразы («Die», «Danach», "
                "«Es»). Предложение длиннее 400 знаков делится на части по «;», «:» и запятым ближе к "
                "середине.")
    report.text("Затем предложение разбирается одним регулярным выражением на 25 видов токенов: адрес, "
                "почта, ссылка на источник, дата, время, сокращение, десятилетие, диапазон, номер версии, "
                "порядковое, дробь, степень, число с единицей, буквы с цифрами, аббревиатура, слово, знаки. "
                "Каждый токен помнит место в исходном тексте — по нему подсвечивается прочитанное. Для "
                f"каждого токена строится запись словами (таблица {report.next_table}). Правила, которым нужны "
                "соседи, — второй проход: окончание порядкового по слову перед ним («im 19.» — «im "
                "neunzehnten», «die 2.» — «die zweite»), «ein / eine / einem» по роду единицы и предлогу.")
    report.figure(REPORT / "algo_text.png", "Блок-схема подготовки текста к синтезу", max_height=20.5)
    report.table("Примеры нормализации", ["Что", "Написано", "Читается"], [
        ["год (1100–1999 без единицы)", "1954", "neunzehnhundertvierundfünfzig"],
        ["десятилетие", "1950er-Jahren", "neunzehnhundertfünfziger Jahren"],
        ["порядковое", "vom 12. bis 14. Juni", "vom zwölften bis vierzehnten Juni"],
        ["дробь, проценты, версия", "3,5 % · Python 3.11", "drei Komma fünf Prozent · Python drei Punkt elf"],
        ["число с единицей", "1 Sekunde · 12 GB · 100 Mbit/s",
         "eine Sekunde · zwölf Gigabyte · hundert Megabit pro Sekunde"],
        ["дата, время", "am 12.03.2021 · 14:30 Uhr",
         "am zwölften März zweitausendeinundzwanzig · vierzehn Uhr dreißig"],
        [f"сокращение ({words['abbreviations']} в словаре)", "z. B. · vgl. Abb. 3 · S. 12 f.",
         "zum Beispiel · vergleiche Abbildung drei · Seite zwölf folgende"],
        ["аббревиатура по буквам", "CPU · HTTP", "Zeh Peh Uh · Hah Teh Teh Peh"],
        ["аббревиатура как слово", "DARPA · NEPOMUK", "Darpa · Nepomuk"],
        [f"аббревиатура по словарю ({words['acronyms']})", "RAM · JSON · C++", "Ramm · Dschäison · Zeh plus plus"],
        ["буквы с цифрами", "IPv6 · x86", "Ih Peh Fau sechs · Iks sechsundachtzig"],
        ["формула", "O(n log n) · x ≥ 0 · n²", "Oh von Enn log Enn · Iks größer gleich null · Enn Quadrat"],
        [f"английский термин ({words['english']})", "Deep Learning · Softwareentwicklung",
         "Diep Lörning · Softwär-entwicklung"],
        ["адрес, ссылка на источник", "info@x.de · [12]", "info at x Punkt Deh Eh · (пропускается)"],
    ], widths=[4.6, 4.9, 7.0], size=Pt(10.5), center=False)
    report.text("Аббревиатура читается по буквам, если в ней меньше четырёх букв или согласные стоят так, как в "
                "немецком слове не бывает («HTML», «DSGVO»), иначе — как слово. Английские термины записаны в "
                "словаре немецкими буквами с апострофом перед ударным слогом («Fräimwörk», «Mä'schien "
                "'Lörning») и узнаются внутри сложных слов — в начале («Softwareentwicklung») и в конце "
                "(«Quellcode»). Каждое правило выключается в настройках — так слышно, как читал бы синтезатор "
                f"без него. Что и как будет прочитано, показывает вкладка «Как прочтёт» (рисунок "
                f"{report.next_figure}).")
    report.figure(SCREENS / "ui_reader_spoken.png", "Вкладка «Как прочтёт»: места, переписанные нормализацией")

    report.subheading("2. Правила произношения")
    report.text("Собственному синтезатору нужны фонемы; ими же Piper получает слова из словарей. Немецкая "
                "орфография почти однозначна, и произношение выводится правилами (phonetics/g2p.py):")
    report.bullets([
        f"исключения — {rules['exceptions']} служебных и частых слов с непредсказуемым ударением или долготой "
        "(«System», «Programm», «Methode»);",
        f"состав слова — сложное слово делится по {rules['stems']} известным основам («Betriebs|system», "
        "«Sicherheits|maßnahmen»), отделяются безударные (be-, ge-, ver-) и ударные (an-, auf-, zusammen-) "
        "приставки и суффиксы (-heit, -keit, -lich); главное ударение — на первой части;",
        "буквы в звуки — длинными сочетаниями вперёд («tsch», «sch», «ch», «ei», «ie»); гласная долгая перед "
        "«h», в «ie», в открытом слоге, краткая — перед двойной согласной и скоплением; «ch» после a, o, u — [x], "
        "иначе [ç]; «r» после гласной — [ɐ̯]; b, d, g на конце слога оглушаются; «st», «sp» в начале основы — "
        "[ʃt], [ʃp];",
        "слоги и ударение — слог начинается с наибольшего допустимого сочетания согласных и не переходит "
        f"границу частей слова; ударение на первом слоге основы, {rules['foreign']} иноязычных окончаний "
        "(-ion, -ität, -ieren, -ie) переносят его на себя.",
    ])
    report.text("Для Piper слова из словарей переводятся в обозначения eSpeak NG и передаются готовыми фонемами "
                "в скобках [[…]]: сам eSpeak прочёл бы «Cloud» как [klˈuːt], а «Machine Learning» — как "
                "[maxˈiːnə lˈeːaɾnɪŋ].")

    report.subheading("3. Синтез и чтение по предложениям")
    report.text(f"Чтение устроено по схеме на рисунке {report.next_figure}. Страница запрашивает звук "
                "предложения и двух следующих; пока звучит одно, следующие уже синтезируются, поэтому пауз на "
                "синтез нет. Диктор проверяет кэш и передаёт предложение движку выбранного голоса:")
    report.bullets([
        "Piper — нейросеть VITS превращает фонемы сразу в звук, без отдельного вокодера. Темп модели "
        "нелинеен: length_scale 0,5 ускоряет речь лишь в 1,5 раза, а быстрее ×1,4 модель почти не говорит. "
        "Поэтому длина берётся по таблице калибровки, а остаток темпа досчитывает WSOLA. «Живость» — разброс "
        "тембра и длительностей в модели (noise_scale, noise_w);",
        "собственный формантный синтезатор — см. п. 4;",
        "голоса Windows — один процесс PowerShell живёт всё время работы и получает задания построчно: первое "
        "предложение ждёт около секунды, следующие — десятки миллисекунд; темп задаёт сама Windows;",
        "голос браузера — Web Speech API получает уже нормализованное предложение и сообщает о каждом слове; "
        "звучащее слово подсвечивается.",
    ])
    report.text("Готовый звук обрезается по тишине, его уровень L — средняя мощность громких кадров по 20 мс — "
                "приводится к −18 дБ умножением на k, края плавно нарастают и затухают за 6 мс:")
    report.formula("L = 10 · lg((P~1~ + … + P~M~) / M),   k = 10^(−18 − L) / 20^,")
    report.text("где P~i~ — мощность i-го громкого кадра, M — их число. Темп без изменения высоты меняет WSOLA: окна Ханна по 40 мс накладываются с перекрытием в "
                "половину, и каждое следующее окно ищется в пределах ±10 мс там, где оно сильнее всего "
                "коррелирует с естественным продолжением предыдущего. Высоту на s полутонов сдвигает "
                "растяжение WSOLA в r = 2^s / 12^ раз и передискретизация обратно к исходной длине. "
                "Громкость p — усилитель в звуковом потоке браузера: звук умножается на p, то есть "
                "становится тише на 20\u00a0·\u00a0lg\u00a0p дБ, меняется на ходу и не требует нового синтеза. "
                f"Чтение показано на рисунке {report.next_figure + 1}.")
    report.figure(REPORT / "algo_speak.png", "Блок-схема чтения текста по предложениям", max_height=20.5)
    report.figure(SCREENS / "ui_reader_reading.png", "«Чтец»: чтение с подсветкой звучащего предложения")

    report.subheading("4. Собственный формантный синтезатор")
    report.text("Так работали первые синтезаторы — MITalk, DECtalk — и так устроен eSpeak: речь строится не "
                "из записей, а из модели «источник — фильтр» (engines/formant.py, рисунок "
                f"{report.next_figure}). По фонемам строится партитура (phonetics/prosody.py): у каждой "
                "фонемы собственная длительность (долгая гласная 135 мс, краткая 80, шва 50, «s» 100), "
                "ударный слог длиннее (×1,15), безударный короче (×0,75), последний слог перед паузой "
                "растягивается (×1,4). Тон снижается за предложение от 1,12 до 0,92 среднего, на ударном "
                "слоге знаменательных слов поднимается; в конце утверждения падает, вопроса — поднимается.")
    report.text("Каждые 5 мс задаются цели: форманты F1–F3 гласной (24 качества немецких гласных) или "
                "«локуса» согласной — куда тянутся форманты соседних гласных, громкости голоса, шума и "
                "придыхания, спектр шума. Цели сглаживаются (форманты — окном 35 мс): так получаются "
                "переходы, по которым слух узнаёт согласные. Источник голоса — импульсы Розенберга с "
                "частотой основного тона, источник шума — белый шум. Голос с придыханием проходит каскад "
                "резонаторов, шум щелевых — параллельную ветвь с собственными усилителями (у «s» энергия "
                "около 6 кГц, у «ʃ» — 2,5–4, у «x» — 1–2). Каждый резонатор — фильтр второго порядка с "
                "частотой форманты f и её полосой b (T = 1/22 050 с — шаг дискретизации):")
    report.formula("y[n] = A·x[n] + B·y[n−1] + C·y[n−2],")
    report.formula("C = −e^−2πbT^,   B = 2e^−πbT^·cos(2πfT),   A = 1 − B − C.")
    report.figure(REPORT / "algo_formant.png", "Блок-схема формантного синтеза", max_height=20.5)
    report.text("Голоса: Карл (112 Гц), Клара (205 Гц, речевой тракт на 14 % короче) и Пафнутий (255 Гц, на "
                "24 % короче). Первая версия говорила почти без согласных: глухие щелевые были на 39–49 дБ тише "
                "гласных. Усиления шумовой ветви подобраны так, чтобы «s», «ʃ», «f», «ç», «x», «h» были тише "
                "гласных на 11, 11, 22, 15, 17 и 20 дБ, как в живой речи, — после этого доля ошибок "
                "распознавания на наборе для настройки упала с 91 до 80 %. Транскрипцию и партитуру "
                f"показывает вкладка «Транскрипция» (рисунок {report.next_figure}).")
    report.figure(SCREENS / "ui_settings.png", "Транскрипция слов, партитура предложения и настройки чтения")

    report.subheading("5. Чтение из других программ")
    report.text(f"Страница «Из других программ» (рисунок {report.next_figure}) включает три способа взять "
                "текст вне «Чтеца»:")
    report.bullets([
        "буфер обмена — система трижды в секунду спрашивает у Windows номер версии буфера "
        "(GetClipboardSequenceNumber) и, когда он меняется, читает текст (CF_UNICODETEXT);",
        "горячие клавиши — RegisterHotKey в отдельном потоке с очередью сообщений. По Ctrl+Alt+R система ждёт, "
        "пока отпустят Ctrl и Alt, сама нажимает Ctrl+C в активной программе, забирает выделенное и "
        "возвращает в буфер прежнее содержимое; Ctrl+Alt+S — замолчать;",
        "закладка «Глашатай, читай» — добавляет на любую веб-страницу сценарий pointer.js: панель в теневом "
        "DOM (стили сайта её не задевают), подсветка абзаца под указателем мыши, чтение по щелчку; звук "
        "страница запрашивает как обычный файл /api/say.wav?text=…, следующий кусок загружается, пока "
        f"звучит текущий (рисунок {report.next_figure + 1}).",
    ])
    report.text("Если открыт «Чтец», текст приходит туда по потоку событий и читается с подсветкой; если нет — "
                "звучит прямо из колонок, причём синтез идёт на предложение впереди звука. В «Статьях» "
                "предложение читается, если задержать на нём указатель мыши на 0,7 с (рисунок "
                f"{report.next_figure + 2}).")
    report.figure(SCREENS / "ui_elsewhere.png", "Страница «Из других программ»")
    report.figure(SCREENS / "ui_bookmarklet.png", "Закладка на «чужой» странице: абзац под указателем читается")
    report.figure(SCREENS / "ui_article_pointer.png", "Статья: чтение предложения под указателем мыши")

    report.subheading("6. Дополнительные возможности")
    talk = data["talk"]
    report.text("Как и в прошлых работах, система снабжена отключаемой надстройкой (GLASHATAI_COMPANION=0) — "
                "пауком Пафнутием, который здесь в роли кота из «Моего говорящего Тома»:")
    report.bullets([
        f"повтор за игроком (рисунок {report.next_figure}) — начало и конец фразы находит детектор по "
        "громкости. Пока игрок молчит, отслеживается шум комнаты N ← N + α·(L − N), α = 0,02 вверх и 0,2 "
        "вниз; фраза начинается, когда три кадра по 20 мс из пяти громче max(N + 12, −48) дБ, и кончается "
        "после 700 мс тише max(N + 7, −52) дБ или через 8 с. Запись (16 кГц, с 300 мс до начала фразы) "
        "сервер возвращает смешным голосом: писк (+7 полутонов), бас (−5), робот и шёпот (фильтр речевого "
        "тракта по LPC, 18 коэффициентов, возбуждённый импульсами 120 Гц или шумом), эхо (+3 полутона и три "
        "затухающих повтора через 190 мс);",
        f"реплики — {talk['lines']} {plural(talk['lines'], 'немецкая реплика', 'немецкие реплики', 'немецких реплик')} "
        f"на {talk['occasions']} {plural(talk['occasions'], 'повод', 'повода', 'поводов')} с переводом в облачке; "
        "каждую говорит Thorsten с подходящей манерой (удивлённо, сердито, шёпотом), поднятый на шесть "
        "полутонов;",
        "тычки — голова, глаза, брюшко, любая из восьми ног (паук поджимает именно её), нить; поглаживание; "
        "раскачивание на нити — маятник θ″ = −(g / L)·sin θ − трение; семь тычков за 6 с — обида;",
        "уход — муха, тарелки, торт, паутина, свет (сон) и «почитай» (фраза из научной статьи); сытость, "
        "бодрость и настроение убывают и пока вкладка закрыта; забота даёт опыт, девять уровней открывают "
        "гардероб;",
        "словарь произношения — пользователь записывает, как читать трудное слово (GitLab — «Gitt 'Läbb»), "
        "и запись сразу действует везде, важнее любого правила.",
    ])
    report.figure(REPORT / "algo_echo.png", "Блок-схема повтора за игроком", max_height=19)
    report.figure(SCREENS / "talk_listening.png", "«Мой говорящий Пафнутий»: паук слушает игрока")
    report.figure(SCREENS / "talk_leg.png", "Тычок в ногу: паук поджимает её и жалуется по-немецки")


def testing_section(report: Report, data: dict) -> None:
    ev = data["evaluation"]
    norm = ev["normalization"]
    categories = norm["categories"]
    text_cases = sum(row["cases"] for key, row in categories.items() if key != "satz")
    report.heading("Результаты тестирования")

    report.subheading("1. Автоматические тесты")
    tests = data["tests"]
    total = sum(data["test_counts"].values())
    browser = data["test_counts"].get("test_browser.py", 0)
    if tests and tests.get("passed"):
        outcome = (f"Все {tests['passed']} {plural(tests['passed'], 'тест', 'теста', 'тестов')} проходят "
                   f"({tests['seconds']:.0f} с)" if not tests["failed"] else
                   f"Проходят {tests['passed']} из {total}, не проходят {tests['failed']}")
    else:
        outcome = f"Тестов {total}"
    report.text(f"{outcome}; из них {browser} — в браузере без окна (Edge, протокол DevTools). Тесты проверяют "
                "числительные; нормализацию — весь эталонный набор, падежи порядковых, род и число единиц, места "
                "токенов в тексте, выключение правил, словарь пользователя; деление на абзацы и предложения; "
                "правила произношения; партитуру; формантный синтезатор — тон голосов, форманты гласных по "
                "LPC, уровни шумных согласных; обработку звука — WAV, WSOLA, сдвиг тона, громкость, эффекты "
                "Пафнутия; движки и калибровку темпа; извлечение текста из HTML, DOCX, PDF; буфер обмена и "
                "горячие клавиши; веб-интерфейс. В браузере «Чтец» читает, подсвечивает, ставит на паузу и "
                "продолжает, статья читает предложение под указателем, закладка на «чужой» странице читает "
                "абзац по щелчку, паук различает голову, брюшко, глаз и нить и помнит опыт после перезагрузки.")

    report.subheading("2. Методика проверки")
    report.text("Разборчивость синтезированной речи обычно измеряют на людях. Здесь слушает распознаватель "
                "речи Vosk (малая немецкая модель): синтезированная фраза распознаётся, и считается доля "
                "ошибок в словах относительно текста, который синтезатор должен был сказать:")
    report.formula("WER = (S + D + I) / N,")
    report.text("где S, D, I — замены, пропуски и вставки слов (по расстоянию Левенштейна между "
                "последовательностями слов), N — число слов эталона. Распознаватель строже человека — он не "
                "знает тему текста, — поэтому WER даёт нижнюю оценку разборчивости, зато её можно повторить и "
                "сравнить голоса, темпы и эффекты между собой. Скорость синтеза — RTF, время синтеза, "
                f"делённое на длительность звука. Проверка заняла {ev['seconds'] // 60} мин "
                "(python tools/evaluate.py).")

    report.subheading("3. Нормализация")
    report.text(f"Эталонный набор — {text_cases} трудных мест научного текста по 13 видам с чтением, записанным "
                f"вручную, и {categories['satz']['cases']} случаев деления на предложения. Для сравнения тот же "
                "текст без нормализации отдан eSpeak NG — он строит фонемы для голосов Piper и сам умеет "
                "читать цифры и кое-какие сокращения; «верно» для него — его фонемы совпали с фонемами "
                f"эталонного чтения (таблица {report.next_table}).")
    rows = []
    for key, row in categories.items():
        if key == "satz":
            continue
        rows.append([row["name"], str(row["cases"]), pct(row["accuracy"], 0), pct(row["raw_exact"], 0)])
    summary = norm["summary"]
    rows.append([Bold("все"), Bold(str(text_cases)), Bold(pct(summary["ours_exact"], 0)),
                 Bold(pct(summary["raw_exact"], 0))])
    rows.append([categories["satz"]["name"], str(categories["satz"]["cases"]),
                 pct(categories["satz"]["accuracy"], 0), "—"])
    report.table("Трудные места, прочитанные верно", ["Что", "Случаев", "«Глашатай»", "eSpeak NG сам"], rows,
                 widths=[6.5, 2.8, 3.6, 3.6])
    left = ev["leftovers"]
    by_ear = ev["by_ear"]
    phrases = sum(1 for _ in by_ear["categories"])
    report.text("Набор составлялся вместе с системой и потому служит регрессионным: сто процентов на нём "
                "значат, что правила делают задуманное, а не что они безошибочны. Независимых мер две. В пяти "
                f"статьях {group(left['tokens'])} токенов, нормализация переписала {left['changed']}; ни в одном из "
                "оставшихся нет цифр и знаков, которые синтезатор читал бы по своему усмотрению. Кроме того, "
                f"трудные фразы {phrases} видов голос Thorsten прочитал как есть и после нормализации, а "
                "распознаватель записал услышанное (таблица "
                f"{report.next_table}, рисунок {report.next_figure}).")
    order = sorted(by_ear["categories"].values(), key=lambda row: row["ours"] - row["raw"])
    rows = [[row["name"], pct(row["raw"]), pct(row["ours"])] for row in order]
    rows.append([Bold("все"), Bold(pct(by_ear["raw"])), Bold(pct(by_ear["ours"]))])
    report.table("Доля ошибок в словах на трудных фразах (голос Thorsten)",
                 ["Что", "Текст как есть", "После нормализации"], rows, widths=[6.5, 5.0, 5.0])
    report.figure(REPORT / "eval_normalization.png", "Нормализация: верно прочитанные трудные места и WER на слух")

    report.subheading("4. Правила произношения")
    g = ev["g2p"]
    report.text(f"{g['words']} {plural(g['words'], 'немецкое слово', 'немецких слова', 'немецких слов')} из статей (встречаются хотя бы дважды и не входят в словари "
                f"произношения) транскрибированы правилами системы и eSpeak NG. Транскрипции расходятся в "
                f"{pct(g['per'])} фонем ({pct(g['per_plain'])} без учёта долготы); слово целиком совпало у "
                f"{pct(g['exact'])} ({pct(g['exact_plain'])} без учёта долготы), главное ударение — у "
                f"{pct(g['stress'])}. Расхождения — ошибки обеих сторон: «Digitalrechner» правила ударяют "
                "верно (digi'tal), eSpeak — нет; «Sicherheitsmanagements» и «Initialisierung» точнее у eSpeak.")

    report.subheading("5. Разборчивость и скорость голосов")
    intel = ev["intelligibility"]
    first = next(iter(intel.values()))
    report.text(f"{first['sentences']} предложений из пяти статей ({first['words']} слов) без аббревиатур и "
                "английских терминов — их по буквам распознаватель не знает — прочитаны каждым голосом в "
                f"обычном темпе (таблица {report.next_table}, рисунок {report.next_figure}).")
    rows = []
    best = min(intel.values(), key=lambda row: row["wer"])
    for voice, row in sorted(intel.items(), key=lambda item: item[1]["wer"]):
        name = ev["voices"].get(voice, voice).replace(" (свой)", " (собственный)")
        wer = Bold(pct(row["wer"])) if row is best else pct(row["wer"])
        rows.append([name, wer, dec(row["rtf"], 3), f"{row['ms']:.0f} мс"])
    report.table("Разборчивость и скорость голосов", ["Голос", "WER", "RTF", "Синтез предложения"], rows,
                 widths=[7.0, 3.0, 3.0, 3.5])
    report.figure(REPORT / "eval_intelligibility.png", "Разборчивость (WER) и скорость синтеза (RTF) голосов")
    example = common_example(intel, [EVA, THORSTEN, PAFNUTY])
    if example:
        report.text(f"Пример — одно предложение разными голосами (таблица {report.next_table}).")
        rows = [["(сказано)", example["text"]]]
        for voice in (EVA, THORSTEN, PAFNUTY):
            rows.append([ev["voices"][voice].split(" (")[0], example["heard"][voice]])
        report.table("Распознанное предложение", ["Голос", "Распознано"], rows, widths=[3.0, 13.5], size=Pt(10.5))

    report.subheading("6. Темп и другие настройки")
    tempo = ev["tempo"]
    rates = sorted(next(iter(tempo.values())), key=float)
    report.text(f"Доля ошибок в словах на {(first['sentences'] + 1) // 2} предложениях при разном темпе "
                f"приведена в таблице {report.next_table} и на рисунке {report.next_figure}.")
    rows = [[ev["voices"][voice].split(" (")[0]] + [pct(values[rate]) for rate in rates]
            for voice, values in tempo.items()]
    report.table("Разборчивость при разном темпе (WER)", ["Голос"] + ["×" + rate(r) for r in rates], rows,
                 widths=[4.5, 3.0, 3.0, 3.0, 3.0])
    report.figure(REPORT / "eval_tempo.png", "Разборчивость при разном темпе", max_width=13)
    settings = ev["settings"]
    volume = settings["volume"]
    report.text("Темп и высота, которые задаёт пользователь, проверены измерением: темп — по длительности "
                "звука, высота — по основному тону (автокорреляция) относительно тона без сдвига (таблица "
                f"{report.next_table}, рисунок {report.next_figure}). Громкость 75, 50 и 25 % делает звук "
                f"тише на {dec(-volume['75'], 1)}, {dec(-volume['50'], 1)} и {dec(-volume['25'], 1)} дБ — "
                "ровно 20\u00a0·\u00a0lg\u00a0p.")
    tempo_keys = sorted(settings["voices"][THORSTEN]["tempo"], key=float)
    pitch_keys = sorted(settings["voices"][THORSTEN]["pitch"], key=float)
    rows = []
    for voice in (THORSTEN, KARL):
        name = ev["voices"][voice].split(" (")[0]
        rows.append([f"темп, {name}"] + ["×" + dec(settings["voices"][voice]["tempo"][k]) for k in tempo_keys])
    header = ["Задано"] + ["×" + rate(k) for k in tempo_keys]
    report.table("Настройки: задано и измерено", header, rows, widths=[4.5, 2.4, 2.4, 2.4, 2.4, 2.4])
    rows = []
    for voice in (THORSTEN, KARL):
        name = ev["voices"][voice].split(" (")[0]
        rows.append([f"высота, {name}"] + [dec(settings["voices"][voice]["pitch"][k], sign=True) + " пт"
                                           for k in pitch_keys])
    header = ["Задано"] + [dec(float(k), 0, sign=True) + " пт" for k in pitch_keys]
    report.table("Высота голоса: задано и измерено", header, rows, widths=[4.5, 3.0, 3.0, 3.0, 3.0])
    report.figure(REPORT / "eval_settings.png", "Темп и высота: задано и измерено")

    report.subheading("7. Голоса Пафнутия")
    effects = ev["effects"]
    parts = []
    for key, row in effects.items():
        shift = "" if row["shift"] is None or key in ("none", "robot") else \
            f", сдвиг тона {dec(row['shift'], 1, sign=True)} пт"
        parts.append(f"{row['name']} — {pct(row['wer'], 0)}{shift}")
    report.text("Предложения, прочитанные голосом Thorsten, пропущены через эффекты повтора за игроком; доля "
                f"ошибок распознавания и измеренный сдвиг тона (рисунок {report.next_figure}): "
                + "; ".join(parts) + ". Робот говорит ровным тоном 120 Гц.")
    report.figure(REPORT / "eval_effects.png", "Голоса Пафнутия: WER распознавания и сдвиг тона", max_width=13)


def common_example(intel: dict, voices: list[str]) -> dict | None:
    """Предложение, которое есть в примерах у всех голосов, — с тем, что распознано у каждого."""
    texts = None
    for voice in voices:
        if voice not in intel:
            return None
        found = {row["text"]: row["heard"] for row in intel[voice]["examples"]}
        texts = found if texts is None else {k: v for k, v in texts.items() if k in found}
    if not texts:
        return None
    text = next(iter(texts))
    return {"text": text, "heard": {voice: next(row["heard"] for row in intel[voice]["examples"]
                                                if row["text"] == text) for voice in voices}}


def analysis(report: Report, data: dict) -> None:
    ev = data["evaluation"]
    norm = ev["normalization"]["summary"]
    by_ear = ev["by_ear"]
    abk = by_ear["categories"]["abk"]
    intel = ev["intelligibility"]
    piper = [row["wer"] for voice, row in intel.items() if voice.startswith("piper")]
    formant = [row["wer"] for voice, row in intel.items() if voice.startswith("formant")]
    rtf = [row["rtf"] for row in intel.values()]
    tempo = ev["tempo"]
    report.heading("Анализ полученных данных")
    report.steps([
        "Нормализация — главное, что система добавляет к синтезатору. Сам eSpeak NG правильно читает лишь "
        f"{pct(norm['raw_exact'], 0)} трудных мест: «1954» — как количество («eintausend neunhundert…»), "
        "«z. B.» — как две фразы, «12 GB» — как «Ge Be», «am 3. Mai» и «12:30 Uhr» — как набор чисел. На "
        f"слух доля ошибок на таких фразах падает с {pct(by_ear['raw'], 0)} до {pct(by_ear['ours'], 0)}, на "
        f"сокращениях — с {pct(abk['raw'], 0)} до {pct(abk['ours'], 0)}.",
        "Оставшиеся ошибки на слух — во многом ошибки распознавателя. Он пишет «neunzehnhundert "
        "vierundfünfzig» двумя словами, а эталон — одним, и это две ошибки (поэтому у годов WER "
        f"{pct(by_ear['categories']['jahr']['ours'], 0)}); так же «syntax baums» вместо «Syntaxbaums». "
        "Заметная часть ошибок голосов Piper — разбиение сложных слов и редкие термины («Parser» — «pasa»).",
        f"Нейросетевые голоса разборчивее собственного вчетверо ({span(piper)} против {span(formant)}). Собственный синтезатор строит речь из "
        "правил, без единой записи голоса, и звучит как робот: распознаватель, обученный на живой речи, "
        "улавливает служебные слова и основы, но путает согласные. Из трёх его голосов разборчивее высокий "
        "и быстрый «Пафнутий».",
        f"Все голоса быстрее речи в {1 / max(rtf):.0f}–{1 / min(rtf):.0f} раз (RTF {dec(min(rtf))}–"
        f"{dec(max(rtf))}). Предложение готово за 0,4–0,6 с, а пока оно звучит, синтезируются следующие — "
        "чтение идёт без пауз на синтез.",
        "Настройки работают как обещано. Темп Piper нелинеен и упирается примерно в ×1,4; после калибровки и "
        "досчёта WSOLA измеренный темп совпадает с заданным до сотых. Громкость точна. Высоту собственный "
        "синтезатор меняет точно (±0,1 полутона); у Piper сдвиг вверх на 10–15 % меньше заданного: на ровном "
        "тоне обработка точна (это проверяет тест), на речи — нет; вероятная причина — растяжение WSOLA "
        "окнами по 40 мс речи с меняющимся тоном.",
        f"Быстрая речь теряет разборчивость. Темп ×1,5 Kerstin выдерживает ({pct(tempo[KERSTIN]['1.5'], 0)}), "
        f"Thorsten — хуже ({pct(tempo[THORSTEN]['1.5'], 0)}); на ×2 ошибок у обоих вдвое-втрое больше: "
        "Thorsten на ×2 — это его предел ×1,4 и растяжение WSOLA поверх, двойная обработка слышна.",
        "Голоса Пафнутия смешные и в основном понятные. Писк и робот почти не мешают распознаванию, бас и эхо "
        "мешают (низкий медленный голос и повторы), что для игры и задумано.",
    ])
    report.text("Разборчивость измерена распознавателем, а не людьми: он не знает тему текста, не догадывается "
                "по смыслу и считает ошибкой каждое иначе разделённое сложное слово, — это нижняя оценка. "
                "Эталон нормализации составлен автором системы. Интерфейс проверен в браузере без окна, "
                "микрофон «Говорящего Пафнутия» заменял искусственный звук — с живым микрофоном и на слух "
                "людьми система не проверялась.")


def improvements(report: Report) -> None:
    report.heading("Предложения по улучшению работы системы")
    report.bullets([
        "собственный синтезатор — параметры фонем, извлечённые из записей, а не из таблиц, уравнения локусов "
        "для переходов взрывных, обучаемые длительности или переход к конкатенации дифонов;",
        "правила произношения — морфологический словарь для деления сложных слов и ударения неотделяемых "
        "приставок («über'setzen»), долгота в производных («Er'gebnis»);",
        "нормализация — согласование числительных по падежу и роду по морфологическому анализу, а не по "
        "окончаниям; различение года и количества по смыслу («1500 Einträge»);",
        "английские слова вне словаря — определение языка слова и английские правила чтения;",
        "Piper — модель thorsten-high, сдвиг тона без изменения формант (PSOLA, вокодер WORLD), синтез по "
        "частям внутри длинного предложения;",
        "закладка — расширение браузера: его не останавливает политика безопасности сайтов;",
        "оценка — слушатели (MOS, тест на разборчивость) и распознаватель побольше (Whisper): малая модель "
        "Vosk строже человека.",
    ])


def conclusion(report: Report, data: dict) -> None:
    ev = data["evaluation"]
    intel = ev["intelligibility"]
    tests = data["tests"] or {}
    total = tests.get("passed") or sum(data["test_counts"].values())
    rtf = [row["rtf"] for row in intel.values()]
    report.heading("Вывод")
    report.text("В ходе лабораторной работы разработана система синтеза немецкой речи «Глашатай» для научных "
                "статей по информатике. Система принимает текст с клавиатуры, из буфера обмена, из файла или "
                "по адресу, берёт его из любой программы Windows (всё скопированное и выделенное по Ctrl+Alt+R) "
                "и с любой веб-страницы — по указателю мыши через закладку. Перед синтезом она делит текст на "
                "предложения, переписывает словами числа, годы, единицы, сокращения, аббревиатуры, формулы, "
                "адреса и английские термины и читает выбранным голосом с настраиваемыми темпом, громкостью, "
                "высотой, живостью интонации и паузами, подсвечивая звучащее предложение. Голосов четыре вида: "
                "нейросетевые Piper, собственный формантный синтезатор, написанный с нуля по схеме Клатта, "
                "голоса Windows и голос браузера. Игра «Мой говорящий Пафнутий» повторяет сказанное в "
                "микрофон смешными голосами и отвечает на заботу по-немецки.")
    report.text(f"Проверка показала, что нормализация правильно читает все {ev['normalization']['summary']['cases'] - ev['normalization']['categories']['satz']['cases']} "
                f"трудных мест эталона против {pct(ev['normalization']['summary']['raw_exact'], 0)} у eSpeak NG и "
                f"снижает долю ошибок на слух с {pct(ev['by_ear']['raw'], 0)} до {pct(ev['by_ear']['ours'], 0)}; "
                f"лучший голос, Thorsten, распознаётся с WER {pct(intel[THORSTEN]['wer'])}, собственный "
                f"синтезатор — с {pct(min(r['wer'] for v, r in intel.items() if v.startswith('formant')), 0)}; "
                f"все голоса синтезируют речь в {1 / max(rtf):.0f}–{1 / min(rtf):.0f} раз быстрее её звучания, а заданные "
                "темп и громкость "
                f"совпадают с измеренными. {total} {plural(total, 'автоматический тест', 'автоматических теста', 'автоматических тестов')} "
                "проходят. Главное направление улучшения — собственный синтезатор с параметрами, извлечёнными "
                "из записей, и проверка разборчивости на слушателях.")


# --- сборка ---------------------------------------------------------------------------

def build(output: Path, run_tests: bool) -> Path:
    print("Сбор данных" + (" и прогон тестов (≈ 2 минуты)…" if run_tests else "…"), flush=True)
    data = gather(run_tests)
    report = Report()
    title_page(report)
    goal_and_task(report, data)
    technologies(report)
    structure_section(report)
    algorithm_section(report, data)
    testing_section(report, data)
    analysis(report, data)
    improvements(report)
    conclusion(report, data)
    return report.save(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", default=str(ROOT / "ОтчётЕЯзИИС87.docx"))
    parser.add_argument("--no-tests", action="store_true", help="не запускать pytest")
    arguments = parser.parse_args()
    path = build(Path(arguments.output), not arguments.no_tests)
    print(f"Отчёт: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
