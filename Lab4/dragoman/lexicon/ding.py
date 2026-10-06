"""Словарь Ding (TU Chemnitz, GPL) — источник подсказок для пополнения словаря.

Ding — свободный немецко-английский словарь из ~200 тыс. статей. Строка:

    Netzwerk {n}; Netz {n} | Netzwerke {pl}; Netze {pl} :: network | networks

Значения разделены «|», синонимы — «;», в фигурных скобках — род ({m}, {f},
{n}), множественное число ({pl}), вид глагола ({vt}, {vi}, {vr}), часть речи
({adj}, {adv}). Второе значение строки — обычно множественное число первого:
по нему узнаётся форма мн. ч. немецкого существительного.

Ding не входит в систему: он скачивается по кнопке на странице «Пополнение
словаря» (7,8 МБ) в data/external и служит только для подсказок — в словарь
системы слово попадает после проверки человеком (или автоматически, если
подсказка однозначна).
"""

from __future__ import annotations

import gzip
import re
import threading
import urllib.request
from collections import defaultdict

from dragoman import config
from dragoman.lexicon.db import Entry

_lock = threading.Lock()
_lines: list[str] | None = None
_index: dict[str, list[tuple[int, int, int]]] | None = None

_TAG = re.compile(r"\{([^}]*)\}")
_NOISE = re.compile(r"\[[^\]]*\]|\([^)]*\)|<[^>]*>")
DOMAIN_TAGS = {"cs": {"comp.", "techn.", "electr.", "telco.", "math."}, "lit": {"lit.", "theat.", "art", "poet."}}


def available() -> bool:
    return config.DING_PATH.exists() and config.DING_PATH.stat().st_size > 1_000_000


def download() -> None:
    config.EXTERNAL_DIR.mkdir(parents=True, exist_ok=True)
    try:
        import requests

        response = requests.get(config.DING_URL, timeout=120)
        response.raise_for_status()
        data = response.content
    except ImportError:
        with urllib.request.urlopen(config.DING_URL, timeout=120) as response:
            data = response.read()
    config.DING_PATH.write_bytes(data)


_PLACEHOLDERS_EN = re.compile(r"(?<![\w.])(?:sth\.|sb\.|sb\./sth\.|sth\./sb\.|so\.|oneself|one's|someone|something)"
                              r"(?=\s|$)|<>")
_PLACEHOLDERS_DE = re.compile(r"(?:^|\s)(?:etw\.|jdm\.|jdn\.|jds\.|jdm\./etw\.|jdn\./etw\.|etw\./jdn\.|"
                              r"etw\./jdm\.)(?=\s|$)")


def _clean_english(text: str) -> str:
    text = _NOISE.sub("", _TAG.sub("", text))
    text = _PLACEHOLDERS_EN.sub(" ", text).strip()
    if text.startswith("to "):
        text = text[3:]
    return " ".join(text.split()).lower()


def index() -> bool:
    """Загружает словарь в память (≈ 2 с при первом обращении)."""
    global _lines, _index
    with _lock:
        if _index is not None:
            return True
        if not available():
            return False
        with gzip.open(config.DING_PATH, "rt", encoding="utf-8", errors="replace") as stream:
            lines = [line.rstrip("\n") for line in stream if line.strip() and not line.startswith("#")]
        idx: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
        for number, line in enumerate(lines):
            if " :: " not in line:
                continue
            _, english = line.split(" :: ", 1)
            for sense, part in enumerate(english.split(" | ")):
                for synonym, item in enumerate(part.split(";")):
                    key = _clean_english(item)
                    if key and len(key.split()) <= 3:
                        idx[key].append((number, sense, synonym))
        _lines, _index = lines, dict(idx)
        return True


def _german_items(line: str, sense: int) -> list[tuple[str, set[str], str]]:
    """Немецкие синонимы значения: (слово, пометки в фигурных скобках, пометки областей)."""
    german, _ = line.split(" :: ", 1)
    senses = german.split(" | ")
    if sense >= len(senses):
        return []
    result = []
    for item in senses[sense].split(";"):
        item = item.strip()
        tags = {t.strip() for t in _TAG.findall(item)}
        domains = " ".join(re.findall(r"\[([^\]]*)\]", item))
        word = _PLACEHOLDERS_DE.sub(" ", _NOISE.sub("", _TAG.sub("", item)))
        word = " ".join(word.split())
        if word:
            result.append((word, tags, domains))
    return result


def _english_count(line: str, sense: int) -> int:
    _, english = line.split(" :: ", 1)
    senses = english.split(" | ")
    return len(senses[sense].split(";")) if sense < len(senses) else 1


def _plural(line: str, sense: int, position: int) -> str:
    """Мн. ч.: следующее значение строки — те же слова с пометкой {pl}, в том же порядке."""
    german, english = line.split(" :: ", 1)
    senses = german.split(" | ")
    if sense + 1 >= len(senses):
        return ""
    items = [x.strip() for x in senses[sense + 1].split(";")]
    item = items[position] if position < len(items) else ""
    if "{pl}" not in item:
        return ""
    return " ".join(_NOISE.sub("", _TAG.sub("", item)).split())


def suggest(word: str, pos: str = "", domain: str | None = None, limit: int = 3) -> list[Entry]:
    """Варианты перевода из Ding с родом, мн. ч. и уверенностью.

    Уверенность выше у первого значения строки, у первого немецкого синонима, у значения с одним
    английским словом (оно точнее), у пометки нужной предметной области; немецкое слово, которое
    встретилось в нескольких строках, получает прибавку.
    """
    if _index is None and not index():
        return []
    hits = _index.get(word.lower(), [])
    scored: dict[str, Entry] = {}
    for number, sense, _ in hits[:80]:
        line = _lines[number]
        english_count = _english_count(line, sense)
        for position, (german, tags, domains) in enumerate(_german_items(line, sense)):
            if len(german) > 40 or "..." in german:
                continue
            gender = next((t for t in ("m", "f", "n", "pl") if t in tags), "")
            kind = "NOUN" if gender else "VERB" if tags & {"vt", "vi", "vr", "v"} else "ADJ" if "adj" in tags else                 "ADV" if "adv" in tags else ""
            if pos and kind and kind != pos and not (pos == "PROPN" and kind == "NOUN"):
                continue
            if not kind:
                kind = pos or "NOUN"
                if kind == "NOUN":
                    continue
            if kind == "VERB" and "vr" in tags and not german.startswith("sich "):
                german = "sich " + german
            confidence = 0.75 - 0.12 * sense - 0.07 * position - 0.04 * (english_count - 1)
            if domain and DOMAIN_TAGS.get(domain, set()) & set(domains.replace("[", " ").split()):
                confidence += 0.12
            if german.lower().startswith(word.lower()[:4]):
                confidence += 0.05
            key = german.lower()
            if key in scored:
                scored[key].confidence = min(0.95, max(scored[key].confidence, confidence) + 0.06)
                continue
            entry = Entry(word.lower(), kind, german, gender if kind == "NOUN" else "",
                          _plural(line, sense, position) if kind == "NOUN" and gender != "pl" else "",
                          source="ding", note=f"Ding: {line[:160]}")
            entry.confidence = max(0.05, min(0.95, confidence))
            scored[key] = entry
    result = sorted(scored.values(), key=lambda e: -e.confidence)
    return result[:limit]
