"""Извлечение текста из загружаемых файлов: TXT, MD, HTML, DOCX, PDF.

Результат — текст, в котором абзацы разделены пустой строкой, а заголовки
отмечены знаком «# » (так же хранятся документы коллекции).
"""

from __future__ import annotations

import io
import re
from pathlib import Path


class ExtractError(ValueError):
    pass


def decode(data: bytes) -> str:
    """Текстовый файл: UTF-8 (с BOM или без), иначе Windows-1251."""
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def from_html(data: bytes) -> str:
    html = decode(data)
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "template", "head", "svg", "nav", "footer"]):
            tag.decompose()
        blocks = []
        for element in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote"]):
            text = " ".join(element.get_text(" ").split())
            if not text:
                continue
            blocks.append(("# " + text) if element.name.startswith("h") else text)
        if blocks:
            return "\n\n".join(blocks)
        return soup.get_text("\n")
    except ImportError:
        text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
        text = re.sub(r"(?i)</(p|div|h\d|li)>", "\n\n", text)
        return re.sub(r"<[^>]+>", " ", text)


def from_docx(data: bytes) -> str:
    import docx

    document = docx.Document(io.BytesIO(data))
    blocks = []
    for paragraph in document.paragraphs:
        text = " ".join(paragraph.text.split())
        if not text:
            continue
        style = (paragraph.style.name or "").lower() if paragraph.style is not None else ""
        blocks.append(("# " + text) if style.startswith(("heading", "заголовок", "title")) else text)
    return "\n\n".join(blocks)


def from_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n".join(pages)
    # перенос слова на стыке строк и строки внутри абзаца
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = re.sub(r"(?<![.!?:…])\n(?=[a-zа-яäöüß])", " ", text)
    return text


def extract(filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    try:
        if suffix in {".txt", ".md", ""}:
            return decode(data)
        if suffix in {".html", ".htm"}:
            return from_html(data)
        if suffix == ".docx":
            return from_docx(data)
        if suffix == ".pdf":
            return from_pdf(data)
    except ExtractError:
        raise
    except Exception as problem:  # noqa: BLE001 — повреждённый файл не должен ронять сервер
        raise ExtractError(f"не удалось прочитать файл {filename}: {problem}") from problem
    raise ExtractError(f"формат {suffix} не поддерживается")
