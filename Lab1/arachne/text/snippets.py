"""Формирование сниппетов выдачи и подсветка слов запроса."""

from __future__ import annotations

import html
import re

from .. import config
from .morphology import TOKEN_RE, lemma


def _hits(text: str, lemmas: set[str]) -> list[tuple[int, int, str]]:
    """Позиции словоформ, лемма которых входит в запрос: (начало, конец, лемма)."""
    found = []
    for match in TOKEN_RE.finditer(text):
        token = match.group(0).lower().replace("ё", "е")
        norm = lemma(token)
        if norm in lemmas:
            found.append((match.start(), match.end(), norm))
    return found


def matched_lemmas(text: str, lemmas: set[str]) -> list[str]:
    """Какие леммы запроса реально встретились в тексте документа."""
    seen: list[str] = []
    for _, _, norm in _hits(text, lemmas):
        if norm not in seen:
            seen.append(norm)
    return seen


def make_snippet(text: str, lemmas: set[str], length: int = None) -> str:
    """Фрагмент документа вокруг первого вхождения слов запроса.

    Если совпадений нет — первые `length` символов документа
    (поведение по умолчанию из методички).
    """
    length = length or config.SNIPPET_LENGTH
    text = re.sub(r"\s+", " ", text).strip()
    if not lemmas:
        return text[:length] + ("…" if len(text) > length else "")

    hits = _hits(text[: 20_000], lemmas)
    if not hits:
        return text[:length] + ("…" if len(text) > length else "")

    # окно с максимальным числом совпадений
    best_start, best_count = 0, 0
    for start, _, _ in hits:
        window_start = max(0, start - length // 3)
        count = sum(1 for s, _, _ in hits if window_start <= s < window_start + length)
        if count > best_count:
            best_start, best_count = window_start, count

    # выравнивание границ по словам
    if best_start > 0:
        space = text.find(" ", best_start)
        best_start = space + 1 if 0 <= space < best_start + 30 else best_start
    fragment = text[best_start : best_start + length]
    if best_start + length < len(text):
        cut = fragment.rfind(" ")
        if cut > length * 0.6:
            fragment = fragment[:cut]
        fragment += "…"
    if best_start > 0:
        fragment = "…" + fragment
    return fragment


def highlight(fragment: str, lemmas: set[str]) -> str:
    """Возвращает HTML-безопасный фрагмент с <mark> вокруг слов запроса."""
    if not fragment:
        return ""
    if not lemmas:
        return html.escape(fragment)

    out: list[str] = []
    last = 0
    for match in TOKEN_RE.finditer(fragment):
        token = match.group(0).lower().replace("ё", "е")
        if lemma(token) not in lemmas:
            continue
        out.append(html.escape(fragment[last : match.start()]))
        out.append("<mark>" + html.escape(match.group(0)) + "</mark>")
        last = match.end()
    out.append(html.escape(fragment[last:]))
    return "".join(out)
