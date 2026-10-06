"""Сохранение результатов перевода в текстовый файл в кодировке Unicode.

Методичка требует сохранять результаты перевода и частотный список слов с
переводами и грамматической информацией в файл TXT «кодировки Unicode». В
Windows «Юникодом» называют UTF-16 с меткой порядка байтов — так файл
сохраняет Блокнот, — поэтому это кодировка по умолчанию; по выбору — UTF-8 с
меткой (её тоже понимают все редакторы). Строки разделяются CR LF.

В файле: сведения о документе, статистика, перевод, исходный текст (по
желанию), частотный список слов и расшифровка тегов, которые в нём встретились.
"""

from __future__ import annotations

import re
from collections import Counter

from dragoman import APP_NAME, LAB_NUMBER, VARIANT, VERSION, config
from dragoman.english import tags as tagset
from dragoman.translate.lexical import UNKNOWN
from dragoman.translate.pipeline import STATUS_NAMES, Translation

ENCODINGS = {"utf-16": ("Unicode (UTF-16 LE)", "utf-16"), "utf-8": ("UTF-8", "utf-8-sig")}
PARTS = {"all": "перевод и список слов", "translation": "только перевод", "words": "только список слов"}


def _num(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _pct(value: float) -> str:
    return f"{100 * value:.1f}".replace(".", ",") + " %"


def _wrap(text: str, width: int = 100, indent: str = "") -> list[str]:
    lines, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            lines.append(indent + line)
            line = word
        else:
            line = f"{line} {word}" if line else word
    if line:
        lines.append(indent + line)
    return lines or [indent]


def _table(rows: list[list[str]], header: list[str], widths: list[int]) -> list[str]:
    def cut(text: str, width: int) -> str:
        text = text.replace("\n", " ")
        return text if len(text) <= width else text[: width - 1] + "…"

    out = [" | ".join(h.ljust(w) for h, w in zip(header, widths)).rstrip()]
    out.append("-+-".join("-" * w for w in widths))
    for row in rows:
        out.append(" | ".join(cut(c, w).ljust(w) for c, w in zip(row, widths)).rstrip())
    return out


def render_text(t: Translation, parts: str = "all", with_source: bool = True) -> str:
    stats = t.stats
    lines = [
        f"«{APP_NAME}» {VERSION} — автоматический машинный перевод, английский → немецкий",
        "=" * 100,
        f"Документ:              {t.title}",
        f"Источник:              {t.source or 'текст, введённый пользователем'}",
        f"Предметная область:    {config.domain_name(t.domain)}{' (определена автоматически)' if t.domain_auto else ''}",
        f"Способ перевода:       {config.MODES.get(t.mode, t.mode)}",
        f"Дата:                  {t.created}",
        "",
        "СТАТИСТИКА",
        "-" * 100,
        f"  Предложений:                           {_num(stats['sentences'])}",
        f"  Слов во входном тексте:                {_num(stats['words'])} (разных слов: {_num(stats['unique'])})",
        f"  Переведено слов:                       {_num(stats['translated'])} — по словарю {_num(stats['dictionary'])}, "
        f"по правилам словообразования {_num(stats['rule'])}",
        f"  Имена собственные и числа:             {_num(stats['names'] + stats['numbers'])} (перевода не требуют)",
        f"  Без перевода:                          {_num(stats['unknown'])}",
        f"  Доля переведённых слов:                {_pct(stats['coverage'])}",
    ]
    if stats["unknown_words"]:
        lines += _wrap("Нет в словаре: " + ", ".join(stats["unknown_words"]), 96, "  ")
    lines.append("")

    if parts in {"all", "translation"}:
        lines += ["ПЕРЕВОД (DE)", "-" * 100]
        for heading, sentences in t.paragraphs:
            text = " ".join(s.text for s in sentences)
            if heading:
                lines += ["", text.upper(), ""]
            else:
                lines += _wrap(text, 100) + [""]
        if with_source:
            lines += ["", "ИСХОДНЫЙ ТЕКСТ (EN)", "-" * 100]
            for heading, sentences in t.english_paragraphs:
                text = " ".join(s.text for s in sentences)
                if heading:
                    lines += ["", text.upper(), ""]
                else:
                    lines += _wrap(text, 100) + [""]
        lines.append("")

    if parts in {"all", "words"}:
        lines += ["ЧАСТОТНЫЙ СПИСОК СЛОВ С ПЕРЕВОДОМ И ГРАММАТИЧЕСКОЙ ИНФОРМАЦИЕЙ", "-" * 100,
                  "Слова упорядочены по частоте встречаемости в тексте. Тег — часть речи по Penn Treebank "
                  "(расшифровка — в конце файла).", ""]
        rows = []
        for n, item in enumerate(t.words, start=1):
            forms = ", ".join(f for f, _ in item.forms.most_common(4))
            tags = ", ".join(tag for tag, _ in item.tags.most_common())
            german = item.translation or ("—" if item.status == UNKNOWN else item.lemma)
            used = ", ".join(g for g, _ in item.german.most_common(3))
            rows.append([str(n), item.lemma, forms, str(item.count), tags, item.pos_name, german,
                         item.german_grammar, used, STATUS_NAMES.get(item.status, item.status)])
        lines += _table(rows, ["№", "Слово", "Формы в тексте", "Част.", "Тег", "Часть речи", "Перевод",
                               "Грамматика (нем.)", "В переводе", "Как переведено"],
                        [4, 18, 22, 5, 9, 16, 30, 40, 26, 22])
        lines.append("")
        used_tags = Counter(tag for item in t.words for tag in item.tags)
        lines += ["ОБОЗНАЧЕНИЯ ТЕГОВ", "-" * 100]
        for tag, _ in sorted(used_tags.items()):
            lines.append(f"  {tag:6} {tagset.describe(tag)}")
        lines.append("")
    lines.append(f"Сохранено системой «{APP_NAME}». Лабораторная работа № {LAB_NUMBER}, вариант {VARIANT}.")
    return "\r\n".join(lines) + "\r\n"


def encode(text: str, encoding: str) -> bytes:
    codec = ENCODINGS.get(encoding, ENCODINGS["utf-16"])[1]
    return text.encode(codec)


def filename(t: Translation, encoding: str) -> str:
    base = re.sub(r"[^\w\-]+", "_", t.title, flags=re.UNICODE).strip("_")[:50] or "translation"
    return f"dragoman-{base}.txt"
