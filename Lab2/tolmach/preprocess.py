"""Шаг 1 алгоритма — предварительная обработка входного текста.

Из HTML-документа извлекается видимый текст, который затем приводится к виду,
пригодному для построения поисковых образов: строчные буквы, слова разделены
одиночными пробелами, разметка, числа и знаки препинания удалены.

Диакритика немецкого языка (ä, ö, ü, ß) при нормализации сохраняется: без неё
немецкий профиль теряет один из своих самых заметных признаков.
"""

from __future__ import annotations

import html as html_module
import re
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

from . import config

# --- Извлечение текста из HTML ----------------------------------------------

#: теги, содержимое которых не является видимым текстом документа
_INVISIBLE_TAGS = {"script", "style", "noscript", "template", "head", "svg"}

#: теги, вокруг которых нужен разрыв строки, иначе слова склеятся
_BLOCK_TAGS = {
    "p", "div", "br", "hr", "li", "tr", "td", "th", "section", "article",
    "header", "footer", "nav", "aside", "blockquote", "pre", "figcaption",
    "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol", "dl", "dt", "dd",
}

_CHARSET_RE = re.compile(rb"""charset\s*=\s*["']?\s*([\w.-]+)""", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_WHITESPACE_RE = re.compile(r"\s+")


class _TextExtractor(HTMLParser):
    """Запасной разборщик HTML на случай, если BeautifulSoup недоступен."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _INVISIBLE_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _INVISIBLE_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self.chunks.append(data)

    def result(self) -> str:
        return "".join(self.chunks)


def detect_encoding(raw: bytes) -> str:
    """Определяет кодировку HTML по BOM или по объявлению charset."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    # charset объявляется в начале документа; дальше первого килобайта не ищем
    match = _CHARSET_RE.search(raw[:2048])
    if match:
        name = match.group(1).decode("ascii", errors="ignore").lower()
        try:
            "".encode(name)
        except LookupError:
            return config.DEFAULT_ENCODING
        return name
    return config.DEFAULT_ENCODING


def decode(raw: bytes) -> str:
    """Переводит байты документа в строку, не падая на битых символах."""
    encoding = detect_encoding(raw)
    return raw.decode(encoding, errors="replace")


def strip_html(markup: str) -> str:
    """Возвращает видимый текст HTML-документа.

    Используется BeautifulSoup, если он установлен: он устойчивее к незакрытым
    тегам. Иначе работает разборщик из стандартной библиотеки.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        parser = _TextExtractor()
        parser.feed(markup)
        parser.close()
        text = parser.result()
    else:
        soup = BeautifulSoup(markup, "html.parser")
        for tag in soup(list(_INVISIBLE_TAGS)):
            tag.decompose()
        text = soup.get_text(separator="\n")
    return html_module.unescape(text)


def extract_title(markup: str, fallback: str = "") -> str:
    """Заголовок документа из <title>; при отсутствии — переданная замена."""
    match = _TITLE_RE.search(markup)
    if not match:
        return fallback
    title = _WHITESPACE_RE.sub(" ", html_module.unescape(match.group(1))).strip()
    return title or fallback


# --- Нормализация текста ----------------------------------------------------


def _is_letter(char: str) -> bool:
    """Буква любого алфавита; цифры, знаки и пробелы буквами не считаются."""
    return unicodedata.category(char).startswith("L")


def normalize(text: str) -> str:
    """Приводит текст к каноническому виду для построения профилей.

    Буквы переводятся в нижний регистр, всё остальное заменяется пробелом,
    идущие подряд пробелы схлопываются. Результат всегда обрамлён пробелами,
    что упрощает нарезку словных N-грамм.
    """
    # NFC склеивает «u + диерезис» в одиночное «ü»: иначе одна и та же буква
    # даёт разные N-граммы в зависимости от того, как её записали.
    text = unicodedata.normalize("NFC", text).lower()
    out: list[str] = []
    space = True  # подавляем ведущие пробелы
    for char in text:
        if _is_letter(char):
            out.append(char)
            space = False
        elif not space:
            out.append(" ")
            space = True
    return "".join(out).strip()


def tokenize(normalized: str) -> list[str]:
    """Разбивает нормализованный текст на слова."""
    return normalized.split()


def count_letters(normalized: str) -> int:
    """Число букв в нормализованном тексте (пробелы не считаются)."""
    return sum(1 for char in normalized if char != " ")


# --- Единая точка входа -----------------------------------------------------


def prepare_text(source: str, *, is_html: bool = True) -> tuple[str, str]:
    """Готовит произвольный вход к распознаванию.

    Возвращает пару (видимый текст, нормализованный текст).
    """
    visible = strip_html(source) if is_html else source
    visible = _WHITESPACE_RE.sub(" ", visible).strip()
    return visible, normalize(visible)


def read_html(path: Path) -> tuple[str, str, str]:
    """Читает HTML-файл с диска.

    Возвращает тройку (заголовок, видимый текст, нормализованный текст).
    Размер файла ограничен `config.MAX_FILE_SIZE`.
    """
    raw = path.read_bytes()
    if len(raw) > config.MAX_FILE_SIZE:
        raise ValueError(f"файл {path.name} больше допустимых {config.MAX_FILE_SIZE} байт")
    markup = decode(raw)
    title = extract_title(markup, fallback=path.stem)
    visible, normalized = prepare_text(markup, is_html=True)
    return title, visible, normalized
