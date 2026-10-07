"""Текст из файлов и веб-страниц: TXT, Markdown, HTML, PDF, DOCX, адрес сайта.

Научная статья приходит не только набранной: её открывают из PDF,
сохраняют страницей, присылают в Word. Здесь из всего этого достаётся
текст, пригодный для чтения вслух:

* HTML — только содержательная часть: <article> или <main>, если они
  есть; меню, сценарии, подвал и боковые колонки отбрасываются; заголовки
  становятся строками «# …», абзацы разделяются пустой строкой;
* PDF (пакет pypdf) — текст страниц; переносы по слогам в конце строки
  («Über-\\nsetzer») склеиваются, строки внутри абзаца соединяются;
* DOCX — абзацы из word/document.xml, без дополнительных пакетов;
* адрес сайта — страница скачивается (до 5 МБ, 15 секунд) и разбирается
  как HTML.
"""

from __future__ import annotations

import io
import re
import urllib.parse
import urllib.request
import zipfile
from html import unescape
from html.parser import HTMLParser

MAX_DOWNLOAD = 5 * 1024 * 1024

_SKIP = {"head", "title", "script", "style", "noscript", "nav", "header", "footer", "aside", "form", "button", "svg", "template",
         "iframe", "select", "sup", "figure"}
_BLOCK = {"p", "div", "section", "article", "main", "li", "dd", "dt", "blockquote", "pre", "td", "th", "tr",
          "figcaption", "caption", "br", "table", "ul", "ol", "dl"}
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class ExtractError(ValueError):
    pass


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.parts: list[str] = []
        self.heading = False
        self.title = ""
        self._in_title = False
        #: открытые элементы, внутри которых текст не читается
        self.skipping: list[str] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        style = (attributes.get("style") or "").replace(" ", "")
        hidden = "hidden" in attributes or "display:none" in style
        if tag in _SKIP or hidden or attributes.get("role") in {"navigation", "banner", "contentinfo"}:
            self.skipping.append(tag)
            self.skip += 1
            return
        if tag == "title":
            self._in_title = True
        if self.skip:
            return
        if tag in _HEADINGS:
            self.parts.append("\n\n# ")
            self.heading = True
        elif tag in _BLOCK:
            self.parts.append("\n\n" if tag not in {"br", "td", "th"} else "\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if self.skipping and self.skipping[-1] == tag:
            self.skipping.pop()
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag in _HEADINGS:
            self.parts.append("\n\n")
            self.heading = False
        elif tag in _BLOCK:
            self.parts.append("\n\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self.skip:
            return
        self.parts.append(data.replace("\n", " ") if self.heading else data)

    def text(self) -> str:
        return "".join(self.parts)


def _main_part(html: str) -> str:
    """<article> или <main>, если они есть, — там текст статьи."""
    for tag in ("article", "main"):
        match = re.search(rf"<{tag}\b[^>]*>(.*)</{tag}>", html, re.S | re.I)
        if match and len(re.sub(r"<[^>]+>", "", match.group(1))) > 400:
            return match.group(1)
    match = re.search(r'<div[^>]+id="mw-content-text"[^>]*>(.*)', html, re.S | re.I)   # Википедия
    if match:
        return match.group(1)
    return html


def tidy_text(text: str) -> str:
    """Пробелы, переносы по слогам, пустые строки."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("­", "").replace("\xa0", " ")
    # перенос по слогам в конце строки: «Über-\nsetzer» -> «Übersetzer»
    text = re.sub(r"([a-zäöüß])-\n\s*([a-zäöüß])", r"\1\2", text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # ссылки Википедии вида «[1]» и «[Bearbeiten | Quelltext bearbeiten]»
    text = re.sub(r"\[(?:Bearbeiten|Quelltext bearbeiten)[^\]]*\]", "", text)
    return text.strip()


def from_html(html: str) -> tuple[str, str]:
    """HTML -> (заголовок, текст)."""
    parser = _Text()
    parser.feed(_main_part(html))
    title = ""
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    if match:
        title = unescape(re.sub(r"\s+", " ", match.group(1))).strip()
    text = tidy_text(parser.text())
    text = re.sub(r"(?m)^# \s*$\n?", "", text)
    return title, text


def from_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as problem:
        raise ExtractError("для PDF нужен пакет pypdf: pip install pypdf") from problem
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as problem:            # noqa: BLE001 — повреждённый PDF
        raise ExtractError(f"PDF не прочитан: {problem}") from problem
    text = "\n\n".join(pages)
    if not text.strip():
        raise ExtractError("в PDF нет текстового слоя — это скан; его сначала нужно распознать")
    return tidy_text(text)


def from_docx(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as packed:
            xml = packed.read("word/document.xml").decode("utf-8")
    except (KeyError, zipfile.BadZipFile) as problem:
        raise ExtractError("это не документ Word (DOCX)") from problem
    paragraphs = []
    for paragraph in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
        text = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", paragraph, re.S))
        heading = re.search(r'<w:pStyle w:val="(?:Heading|berschrift)\d', paragraph)
        text = unescape(text).strip()
        if text:
            paragraphs.append(("# " if heading else "") + text)
    return "\n\n".join(paragraphs)


def _decode(data: bytes, declared: str | None = None) -> str:
    for encoding in filter(None, [declared, "utf-8", "cp1252", "latin-1"]):
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")


def from_file(name: str, data: bytes) -> tuple[str, str]:
    """Файл -> (заголовок, текст)."""
    suffix = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    title = name.rsplit(".", 1)[0]
    if suffix == "pdf" or data[:5] == b"%PDF-":
        return title, from_pdf(data)
    if suffix == "docx":
        return title, from_docx(data)
    text = _decode(data)
    if suffix in {"html", "htm", "xhtml"} or re.match(r"\s*<(!doctype|html)", text[:200], re.I):
        page_title, body = from_html(text)
        return page_title or title, body
    if suffix == "md":
        text = re.sub(r"(?m)^#{1,6}\s+", "# ", text)
        text = re.sub(r"[*_`]{1,3}([^*_`]+)[*_`]{1,3}", r"\1", text)
        text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return title, tidy_text(text)


def from_url(url: str) -> tuple[str, str]:
    """Страница по адресу -> (заголовок, текст)."""
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ExtractError("нужен адрес, начинающийся с http:// или https://")
    request = urllib.request.Request(url, headers={"User-Agent": "Glashatai/1.0 (Lab 8 TTS)",
                                                   "Accept-Language": "de,en;q=0.5"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = response.read(MAX_DOWNLOAD + 1)
            kind = response.headers.get_content_type()
            charset = response.headers.get_content_charset()
    except Exception as problem:            # noqa: BLE001 — любые сетевые ошибки
        raise ExtractError(f"страница не открылась: {problem}") from problem
    if len(data) > MAX_DOWNLOAD:
        raise ExtractError("страница больше 5 МБ")
    if kind == "application/pdf" or data[:5] == b"%PDF-":
        return parsed.path.rsplit("/", 1)[-1] or parsed.netloc, from_pdf(data)
    title, text = from_html(_decode(data, charset))
    if not text:
        raise ExtractError("на странице не нашлось текста")
    return title or parsed.netloc, text
