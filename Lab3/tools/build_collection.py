"""Сборка тестовой коллекции документов.

    python tools/build_collection.py                 собрать коллекцию по списку источников
    python tools/build_collection.py --offline       только из сохранённых страниц data/sources
    python tools/build_collection.py candidates cl "запрос"      подобрать статьи КиберЛенинки
    python tools/build_collection.py candidates wiki de "Titel"  проверить статью Википедии

Коллекция состоит из документов четырёх групп «язык × предметная область»:

* научные статьи по computer science на русском — КиберЛенинка, только статьи
  под лицензией CC BY;
* научные тексты по computer science на немецком — немецкая Википедия;
* литературоведческие тексты («сочинения по литературе») на русском и
  немецком — русская и немецкая Википедия.

Эталон для оценки точности берётся из самого источника и из входного текста
удаляется: у статей КиберЛенинки это авторская аннотация и ключевые слова, у
статей Википедии — вводный раздел, который по правилам Википедии и есть
краткое изложение статьи. Иначе система «находила» бы эталон в тексте, и оценка
была бы завышена.

Все документы приводятся к одинаковому объёму — 10 страниц машинописного
текста (18 000 знаков) с допуском ±10 %. Исходные страницы сохраняются в
data/sources, поэтому коллекцию можно пересобрать без сети (--offline).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from izbornik import config, console  # noqa: E402

console.setup()

USER_AGENT = (
    "Izbornik/1.0 (BSUIR student lab: automatic summarization; "
    "contact khalilovrusel@gmail.com) python-httpx"
)
REQUEST_PAUSE = 1.0

# --- Список источников --------------------------------------------------------
#
# Статьи КиберЛенинки подобраны командой `candidates` из выдачи по темам:
# лицензия CC BY, есть русская аннотация и ключевые слова, после очистки
# объём основного текста укладывается в допуск. Статьи Википедии — длинные
# статьи, у которых после вводного раздела достаточно связного текста.

def _cl(doc_id: str, slug: str, title: str) -> dict:
    return {"id": doc_id, "kind": "cyberleninka", "language": "ru", "domain": "cs",
            "link": f"/article/n/{slug}", "title": title}


def _wiki(doc_id: str, language: str, domain: str, title: str) -> dict:
    return {"id": doc_id, "kind": "wikipedia", "language": language, "domain": domain, "title": title}


SOURCES: list[dict] = [
    # --- русский, computer science (КиберЛенинка, CC BY) ---
    _cl("ru-cs-neuro",
        "metod-avtomaticheskogo-poiska-struktury-i-parametrov-neyronnyh-setey-dlya-resheniya-zadach-obrabotki-informatsii",
        "Метод автоматического поиска структуры и параметров нейронных сетей "
        "для решения задач обработки информации"),
    _cl("ru-cs-antipatterns", "antipatterny-v-proektirovanii-baz-dannyh",
        "Антипаттерны в проектировании баз данных"),
    _cl("ru-cs-crypto", "parallelnyy-modul-dlya-kriptograficheskoy-zaschity-faylov",
        "Параллельный модуль для криптографической защиты файлов"),
    _cl("ru-cs-ostis", "semanticheskie-modeli-i-metod-soglasovannoy-razrabotki-baz-znaniy",
        "Семантические модели и метод согласованной разработки баз знаний"),
    _cl("ru-cs-vision",
        "analiz-metodov-kompyuternogo-zreniya-perspektivnyh-dlya-primeneniya-v-agropromyshlennom-komplekse",
        "Анализ методов компьютерного зрения, перспективных для применения "
        "в агропромышленном комплексе"),
    # --- немецкий, computer science (de.wikipedia.org, CC BY-SA) ---
    _wiki("de-cs-nn", "de", "cs", "Künstliches neuronales Netz"),
    _wiki("de-cs-compiler", "de", "cs", "Compiler"),
    _wiki("de-cs-os", "de", "cs", "Betriebssystem"),
    _wiki("de-cs-security", "de", "cs", "Informationssicherheit"),
    _wiki("de-cs-semweb", "de", "cs", "Semantic Web"),
    # --- русский, литература (ru.wikipedia.org, CC BY-SA) ---
    _wiki("ru-lit-onegin", "ru", "lit", "Евгений Онегин"),
    _wiki("ru-lit-master", "ru", "lit", "Мастер и Маргарита"),
    _wiki("ru-lit-crime", "ru", "lit", "Преступление и наказание"),
    _wiki("ru-lit-souls", "ru", "lit", "Мёртвые души"),
    _wiki("ru-lit-woe", "ru", "lit", "Горе от ума"),
    # --- немецкий, литература (de.wikipedia.org, CC BY-SA) ---
    _wiki("de-lit-werther", "de", "lit", "Die Leiden des jungen Werthers"),
    _wiki("de-lit-effi", "de", "lit", "Effi Briest"),
    _wiki("de-lit-verwandlung", "de", "lit", "Die Verwandlung"),
    _wiki("de-lit-raeuber", "de", "lit", "Die Räuber"),
    _wiki("de-lit-westen", "de", "lit", "Im Westen nichts Neues"),
]


# --- Загрузка с кэшем -----------------------------------------------------------

_last_request = 0.0


def _client():
    import httpx

    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=40,
        follow_redirects=True,
    )


def _polite_get(client, url: str, **kwargs):
    global _last_request
    delay = REQUEST_PAUSE - (time.monotonic() - _last_request)
    if delay > 0:
        time.sleep(delay)
    response = client.get(url, **kwargs)
    _last_request = time.monotonic()
    response.raise_for_status()
    return response


def _cached(path: Path, fetch, offline: bool) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    if offline:
        raise FileNotFoundError(f"нет сохранённой страницы {path.name}, а сеть запрещена (--offline)")
    text = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


# --- Общая нормализация текста ----------------------------------------------------

_SPACES = re.compile(r"[ \t    ]+")
_INVISIBLE = dict.fromkeys(map(ord, "﻿​‌‍⁠­"), None)
TERMINAL = ".!?…"
CLOSERS = "»“”\"')]"


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text).translate(_INVISIBLE)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # перенос слова на стыке строк: «информа-\nционный» -> «информационный»
    text = re.sub(r"(\w)-\n(\w)", lambda m: m.group(1) + m.group(2) if m.group(2).islower() else m.group(0), text)
    text = text.replace("\n", " ")
    return _SPACES.sub(" ", text).strip()


def ends_sentence(text: str) -> bool:
    stripped = text.rstrip(CLOSERS + " ")
    return bool(stripped) and stripped[-1] in TERMINAL


def letter_share(text: str, predicate) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for ch in letters if predicate(ch)) / len(letters)


def is_cyrillic(ch: str) -> bool:
    return "Ѐ" <= ch <= "ӿ"


def is_latin(ch: str) -> bool:
    return ch.isascii() or ch in "äöüÄÖÜßéèàáâçëïôû"


# --- Документ коллекции -------------------------------------------------------

@dataclass
class Built:
    doc_id: str
    language: str
    domain: str
    title: str
    paragraphs: list[str]            # абзацы; заголовки начинаются с «# »
    abstract: str                    # эталонный реферат
    keywords: list[str] = field(default_factory=list)   # эталонные ключевые слова
    source: dict = field(default_factory=dict)

    @property
    def chars(self) -> int:
        return len(body_text(self.paragraphs))


def body_text(paragraphs: list[str]) -> str:
    """Текст документа так, как его видит система: абзацы через перевод строки."""
    return "\n".join(p[2:] if p.startswith("# ") else p for p in paragraphs)


def fit_size(paragraphs: list[str], target: int, tolerance: float) -> list[str]:
    """Берёт абзацы по порядку, пока объём не достигнет целевого.

    Документ, объём которого уже в допуске, не обрезается: у научной статьи
    в конце стоят выводы, и отрезать их ради ровного счёта не следует.
    Длинный документ обрывается на границе абзаца, а не посреди предложения,
    и заголовок без единого абзаца под ним в конце не остаётся.
    """
    if target * (1 - tolerance) <= len(body_text(paragraphs)) <= target * (1 + tolerance):
        return list(paragraphs)
    upper = target * (1 + tolerance / 2)
    result: list[str] = []
    for paragraph in paragraphs:
        candidate = body_text(result + [paragraph])
        if len(candidate) > upper and len(body_text(result)) >= target * (1 - tolerance):
            break
        if len(candidate) > target * (1 + tolerance):
            # абзац слишком длинный, чтобы добавить его целиком, — ищем меньший
            continue
        result.append(paragraph)
        if len(candidate) >= target:
            break
    while result and result[-1].startswith("# "):
        result.pop()
    return result


# --- КиберЛенинка ---------------------------------------------------------------

CL_BASE = "https://cyberleninka.ru"

_CL_KEYWORDS = re.compile(r"^(ключевые\s+слова|keywords|key\s+words)\b", re.I)
_CL_END = re.compile(
    r"^(список\s+(использованной\s+|цитируемой\s+|использованных\s+)?(литературы|источников)"
    r"|литература|библиографический\s+список|библиография|references|источники(\s+и\s+литература)?"
    r"|благодарност|финансирование|сведения\s+об\s+авторах|информация\s+об\s+авторах"
    r"|об\s+авторах|поступила\s+в\s+редакцию|статья\s+поступила)\b[\s.:]*",
    re.I,
)
_CL_CAPTION = re.compile(r"^(рис\.|рисунок|табл\.|таблица|fig\.|figure|схема|листинг)\s*\d", re.I)
_CL_NOISE = re.compile(r"(doi\.org|https?:|www\.|issn|e-mail|©|orcid|удк\s*\d)", re.I)
_CL_THANKS = re.compile(
    r"^(работа\s+выполнена\s+при|исследование\s+выполнено\s+(при|за\s+сч[её]т)|статья\s+подготовлена\s+при"
    r"|благодарност|авторы\s+благодарят|финансирование)", re.I)
_CL_BULLET = re.compile(r"^[•▪●◦·]\s*|^[-–]\s+(?=[А-ЯЁа-яё])")
#: нумерация раздела: «2.», «2.1.», «3.3 » — но не просто «3 » (это ячейка таблицы)
_CL_NUMBERING = re.compile(r"^(?:\d+\.)+\d*\s+|^\d+(?:\.\d+)+\s+")
_CL_HYPHEN = re.compile(r"\b([А-ЯЁа-яё]{2,})\s?-\s?([а-яё]{2,})\b")
_CL_INITIALS = re.compile(r"\b[А-ЯЁA-Z]\.\s?[А-ЯЁA-Z]\.")
_CL_BAD_HEADING_CHARS = set("^*/\\|<>~=+«»\"[]{}@#$%&_№")
STANDARD_HEADINGS = {
    "введение", "заключение", "выводы", "результаты", "обсуждение", "методы", "материалы",
    "аннотация", "постановка задачи", "материалы и методы", "результаты и обсуждение",
    "основная часть", "обзор литературы", "методология", "эксперимент", "эксперименты",
}


_morph = None


def dehyphenate(text: str) -> str:
    """Убирает переносы, оставшиеся от вёрстки: «денормализа-ция» -> «денормализация».

    Дефис убирается, только если слитное слово есть в словаре pymorphy3, а
    слово с дефисом — нет: «какой-то», «по-прежнему», «из-за» не трогаются.
    """
    global _morph
    if _morph is None:
        import pymorphy3

        _morph = pymorphy3.MorphAnalyzer()

    def repl(match: re.Match) -> str:
        left, right = match.group(1), match.group(2)
        joined = left + right
        if _morph.word_is_known(joined.lower()) and not _morph.word_is_known(f"{left}-{right}".lower()):
            return joined
        return match.group(0)

    return _CL_HYPHEN.sub(repl, text)


def _valid_heading(text: str) -> bool:
    """Отличает заголовок раздела от обрывка таблицы или подписи к рисунку."""
    if len(text) > 90 or len(text.split()) > 12:
        return False
    if any(ch in _CL_BAD_HEADING_CHARS for ch in text) or _CL_INITIALS.search(text):
        return False
    if re.search(r"[-–—]\s*[-–—]", text) or text.rstrip().endswith(("-", "–", "—")):
        return False
    core = _CL_NUMBERING.sub("", text).strip(" .:")
    if not core or any(ch.isdigit() for ch in core):
        return False
    if letter_share(core, is_cyrillic) < 0.9:
        return False
    words = core.split()
    if not any(len(word) >= 4 for word in words):
        return False
    if len(words) == 1 and core.lower() not in STANDARD_HEADINGS and not _CL_NUMBERING.match(text):
        return False
    return True


def cl_search(query: str, size: int = 20, offset: int = 0) -> list[dict]:
    with _client() as client:
        response = client.post(
            f"{CL_BASE}/api/search",
            json={"mode": "articles", "q": query, "size": size, "from": offset},
            headers={"Content-Type": "application/json", "Referer": f"{CL_BASE}/search"},
        )
        response.raise_for_status()
        return response.json().get("articles", [])


def cl_fetch(link: str, offline: bool) -> str:
    slug = link.rstrip("/").rsplit("/", 1)[-1]
    path = config.SOURCES_DIR / "cyberleninka" / f"{slug}.html"

    def fetch() -> str:
        with _client() as client:
            return _polite_get(client, CL_BASE + link).text

    return _cached(path, fetch, offline)


@dataclass
class ClArticle:
    title: str
    authors: list[str]
    year: str
    journal: str
    category: str
    license: str
    abstract: str
    keywords: list[str]
    paragraphs: list[str]
    rejected: str = ""


def _cl_paragraphs(ocr) -> list[str]:
    return [normalize(p.get_text("\n")) for p in ocr.find_all("p")]


def cl_parse(html: str) -> ClArticle:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    def meta(name: str) -> list[str]:
        return [m.get("content", "").strip() for m in soup.find_all("meta", attrs={"name": name})]

    title = (meta("citation_title") or [""])[0]
    authors = [a for a in meta("citation_author") if a]
    year = (meta("citation_publication_date") or [""])[0][:4]
    journal = (meta("citation_journal_title") or [""])[0]

    h1 = soup.select_one("h1")
    category = ""
    if h1:
        match = re.search(r"по специальности\s*«\s*(.+?)\s*»", h1.get_text(" ", strip=True))
        category = match.group(1) if match else ""

    cc = soup.select_one(".label-cc")
    license_ = cc.get_text(strip=True) if cc else ""

    abstract = ""
    for p in soup.select("div.abstract p"):
        text = normalize(p.get_text(" "))
        if letter_share(text, is_cyrillic) > 0.7:
            abstract = text
            break

    keywords = []
    for span in soup.select("div.keywords span"):
        text = normalize(span.get_text(" "))
        if text and letter_share(text, is_cyrillic) > 0.7 and text not in keywords:
            keywords.append(text)

    article = ClArticle(title, authors, year, journal, category, license_, abstract, keywords, [])

    ocr = soup.select_one("div.ocr")
    if ocr is None:
        article.rejected = "нет полного текста"
        return article
    article.paragraphs = cl_clean(_cl_paragraphs(ocr), abstract)
    if not article.paragraphs:
        article.rejected = "не найдено начало основного текста"
    return article


def cl_clean(raw: list[str], abstract: str = "") -> list[str]:
    """Выделяет основной текст статьи из распознанных страниц.

    1. Начало — после последнего абзаца «Ключевые слова» / «Keywords» в первой
       трети страницы: до него идут выходные данные, сведения об авторах,
       аннотации на двух языках.
    2. Конец — перед списком литературы, благодарностями, сведениями об авторах.
    3. Колонтитулы — абзацы, повторяющиеся на нескольких страницах.
    4. Абзацы, разорванные границей страницы, склеиваются.
    5. Отбрасываются подписи к рисункам и таблицам, программный код, формулы,
       иноязычные вставки.
    """
    raw = [p for p in raw if p]
    if not raw:
        return []

    head_zone = max(12, len(raw) // 3)
    start = None
    for index, paragraph in enumerate(raw[:head_zone]):
        if _CL_KEYWORDS.match(paragraph):
            start = index + 1
    if start is None:
        return []

    end = len(raw)
    for index in range(start, len(raw)):
        if _CL_END.match(raw[index]) and len(raw[index]) < 120:
            end = index
            break
    body = raw[start:end]

    # колонтитулы повторяются почти дословно — отличаются только номера
    def key(text: str) -> str:
        return re.sub(r"[\d\s]+", " ", text.lower()).strip()

    counts: dict[str, int] = {}
    for paragraph in body:
        counts[key(paragraph)] = counts.get(key(paragraph), 0) + 1
    body = [p for p in body if not (counts[key(p)] > 1 and len(p) < 250)]

    body = [p for p in body if not (_CL_NOISE.search(p) and len(p) < 300)]
    body = [p for p in body if not re.fullmatch(r"[\d\s\-–—.,]+", p)]
    if abstract:
        head = abstract[:80]
        body = [p for p in body if not p.startswith(head)]
    body = [p for p in body if not re.match(r"^(аннотация|abstract)\b", p, re.I)]
    body = [p for p in body if not _CL_THANKS.match(p)]
    body = [_CL_BULLET.sub("", p) for p in body]
    body = [p for p in body if p]

    # склейка абзацев, разорванных границей страницы или строки
    merged: list[str] = []
    for paragraph in body:
        if merged and not ends_sentence(merged[-1]) and paragraph[0].islower():
            previous = merged[-1]
            if previous.endswith("-") and previous[-2:-1].isalpha():
                merged[-1] = previous[:-1] + paragraph
            else:
                merged[-1] = previous + " " + paragraph
            continue
        merged.append(paragraph)

    result: list[str] = []
    for paragraph in merged:
        if _CL_CAPTION.match(paragraph):
            continue
        letters = sum(ch.isalpha() for ch in paragraph)
        if letters < 0.55 * len(paragraph):
            continue                                   # формулы, таблицы из чисел
        if letter_share(paragraph, is_latin) > 0.35:
            continue                                   # код, английский текст
        code_marks = sum(paragraph.count(ch) for ch in "=(){}[]<>_;#")
        if code_marks > 0.04 * len(paragraph) and code_marks > 3:
            continue
        paragraph = dehyphenate(paragraph)
        # нумерованный подзаголовок с точкой в конце: «2.1. Ложная абстракция.»;
        # пункт списка «4. Сначала преобразовать кадр, …» заголовком не считается
        two_level = re.match(r"^\d+\.\d+", paragraph)
        short_item = len(paragraph.split()) <= 10 and "," not in paragraph
        if _CL_NUMBERING.match(paragraph) and (two_level or short_item) \
                and _valid_heading(paragraph.rstrip(".")):
            result.append("# " + paragraph.rstrip(".:"))
            continue
        if ends_sentence(paragraph) or paragraph.endswith(":"):
            if len(paragraph) >= 40:
                result.append(paragraph)
            continue
        # короткий абзац без знака конца предложения — заголовок раздела,
        # если он похож на заголовок, а не на ячейку таблицы
        if (paragraph[0].isupper() or _CL_NUMBERING.match(paragraph)) and _valid_heading(paragraph):
            result.append("# " + paragraph.rstrip(".:"))
        continue
    # подряд идущие заголовки — остаётся последний
    cleaned: list[str] = []
    for paragraph in result:
        if cleaned and cleaned[-1].startswith("# ") and paragraph.startswith("# "):
            cleaned[-1] = paragraph
        else:
            cleaned.append(paragraph)
    while cleaned and cleaned[-1].startswith("# "):
        cleaned.pop()
    return cleaned


# --- Википедия ------------------------------------------------------------------

WIKI_SKIP = {
    "ru": {
        "примечания", "литература", "ссылки", "см. также", "источники", "библиография",
        "комментарии", "сноски", "издания", "экранизации", "постановки", "переводы",
        "адаптации", "в культуре", "в массовой культуре", "фильмография", "издания на русском языке",
        "аудиокниги", "театральные постановки", "киноадаптации", "иллюстрации",
    },
    "de": {
        "einzelnachweise", "literatur", "weblinks", "siehe auch", "anmerkungen", "quellen",
        "ausgaben", "sekundärliteratur", "primärliteratur", "hörbücher", "hörspiele",
        "verfilmungen", "vertonungen", "adaptionen", "übersetzungen", "textausgaben",
        "filme", "bearbeitungen", "inszenierungen", "hörbuch", "hörspiel", "verfilmung",
        "ausgaben (auswahl)", "literatur (auswahl)", "rezensionen",
    },
}


def wiki_fetch(language: str, title: str, offline: bool) -> dict:
    safe = re.sub(r"[^\w\-]+", "_", title, flags=re.UNICODE).strip("_")
    path = config.SOURCES_DIR / "wikipedia" / f"{language}-{safe}.json"

    def fetch() -> str:
        with _client() as client:
            response = _polite_get(
                client,
                f"https://{language}.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "prop": "extracts|info|revisions",
                    "explaintext": "1",
                    "exsectionformat": "wiki",
                    "inprop": "url",
                    "rvprop": "ids|timestamp",
                    "titles": title,
                    "redirects": "1",
                    "format": "json",
                    "formatversion": "2",
                },
            )
            return json.dumps(response.json(), ensure_ascii=False, indent=1)

    data = json.loads(_cached(path, fetch, offline))
    page = data["query"]["pages"][0]
    if page.get("missing"):
        raise LookupError(f"в {language}.wikipedia.org нет статьи «{title}»")
    return page


_HEADING = re.compile(r"^(=+)\s*(.+?)\s*\1$")


def _wiki_paragraph_ok(text: str) -> bool:
    if len(text) < 60 or not ends_sentence(text):
        return False
    if "displaystyle" in text or "\\" in text:
        return False
    return True


def wiki_parse(page: dict, language: str) -> tuple[str, list[str], str]:
    """Возвращает (вводный раздел, абзацы основного текста, адрес статьи)."""
    lines = [normalize(line) for line in page.get("extract", "").split("\n")]
    lead: list[str] = []
    body: list[str] = []
    skip_level: int | None = None
    in_lead = True
    pending_heading: str | None = None

    for line in lines:
        if not line:
            continue
        heading = _HEADING.match(line)
        if heading:
            in_lead = False
            level = len(heading.group(1))
            name = heading.group(2).strip()
            if skip_level is not None and level > skip_level:
                continue
            skip_level = None
            if name.lower() in WIKI_SKIP[language]:
                skip_level = level
                continue
            pending_heading = name
            continue
        if skip_level is not None:
            continue
        if not _wiki_paragraph_ok(line):
            continue
        if in_lead:
            lead.append(line)
            continue
        if pending_heading:
            body.append("# " + pending_heading)
            pending_heading = None
        body.append(line)
    return " ".join(lead), body, page.get("fullurl", "")


# --- Сборка -------------------------------------------------------------------

def build_one(entry: dict, offline: bool) -> Built:
    kind = entry["kind"]
    target = config.DOC_TARGET_CHARS
    tolerance = config.DOC_SIZE_TOLERANCE

    if kind == "cyberleninka":
        article = cl_parse(cl_fetch(entry["link"], offline))
        if article.rejected:
            raise ValueError(f"{entry['id']}: {article.rejected}")
        paragraphs = fit_size(article.paragraphs, target, tolerance)
        return Built(
            doc_id=entry["id"],
            language=entry["language"],
            domain=entry["domain"],
            title=entry.get("title") or _title_case(article.title),
            paragraphs=paragraphs,
            abstract=article.abstract,
            keywords=[k.lower() if k.isupper() else k for k in article.keywords],
            source={
                "kind": "cyberleninka",
                "site": "КиберЛенинка",
                "url": CL_BASE + entry["link"],
                "authors": article.authors,
                "year": article.year,
                "journal": article.journal,
                "license": article.license or "CC BY",
                "reference": "авторская аннотация и ключевые слова",
            },
        )

    if kind == "wikipedia":
        page = wiki_fetch(entry["language"], entry["title"], offline)
        lead, body, url = wiki_parse(page, entry["language"])
        paragraphs = fit_size(body, target, tolerance)
        revision = (page.get("revisions") or [{}])[0]
        host = f"{entry['language']}.wikipedia.org"
        return Built(
            doc_id=entry["id"],
            language=entry["language"],
            domain=entry["domain"],
            title=page.get("title", entry["title"]),
            paragraphs=paragraphs,
            abstract=lead,
            keywords=[],
            source={
                "kind": "wikipedia",
                "site": f"Википедия ({host})",
                "url": url,
                "revision": revision.get("revid"),
                "timestamp": revision.get("timestamp"),
                "license": "CC BY-SA 4.0",
                "reference": "вводный раздел статьи",
            },
        )

    raise ValueError(f"неизвестный вид источника: {kind}")


def _title_case(title: str) -> str:
    """Заголовки на КиберЛенинке часто набраны капсом — приводим к обычному виду."""
    if title.isupper():
        return title[:1] + title[1:].lower()
    return title


def write_collection(documents: list[Built]) -> None:
    config.COLLECTION_DIR.mkdir(parents=True, exist_ok=True)
    for stale in config.COLLECTION_DIR.glob("*.txt"):
        if stale.stem not in {doc.doc_id for doc in documents}:
            stale.unlink()

    catalog = []
    for doc in documents:
        path = config.COLLECTION_DIR / f"{doc.doc_id}.txt"
        path.write_text("\n\n".join(doc.paragraphs) + "\n", encoding="utf-8")
        catalog.append(
            {
                "id": doc.doc_id,
                "file": path.name,
                "title": doc.title,
                "language": doc.language,
                "domain": doc.domain,
                "chars": doc.chars,
                "paragraphs": sum(1 for p in doc.paragraphs if not p.startswith("# ")),
                "source": doc.source,
                "reference": {"abstract": doc.abstract, "keywords": doc.keywords},
            }
        )
    config.CATALOG_PATH.write_text(
        json.dumps({"target_chars": config.DOC_TARGET_CHARS,
                    "tolerance": config.DOC_SIZE_TOLERANCE,
                    "documents": catalog},
                   ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build(offline: bool) -> int:
    config.ensure_dirs()
    documents: list[Built] = []
    problems = 0
    target = config.DOC_TARGET_CHARS
    low, high = target * (1 - config.DOC_SIZE_TOLERANCE), target * (1 + config.DOC_SIZE_TOLERANCE)
    for entry in SOURCES:
        try:
            doc = build_one(entry, offline)
        except Exception as problem:  # noqa: BLE001 — одна плохая страница не должна рушить сборку
            print(f"  ✗ {entry['id']}: {problem}")
            problems += 1
            continue
        flag = "✓" if low <= doc.chars <= high else "!"
        if flag == "!":
            problems += 1
        print(f"  {flag} {doc.doc_id:14} {doc.chars:6} знаков, "
              f"эталон {len(doc.abstract):5} знаков, {len(doc.keywords)} ключ. слов — {doc.title[:60]}")
        documents.append(doc)
    write_collection(documents)
    print(f"\nСобрано документов: {len(documents)}; допуск объёма {low:.0f}–{high:.0f} знаков.")
    print(f"Каталог: {config.CATALOG_PATH}")
    return 1 if problems else 0


# --- Подбор кандидатов ------------------------------------------------------------

def candidates_cl(query: str, size: int, offset: int) -> None:
    target = config.DOC_TARGET_CHARS
    for item in cl_search(query, size, offset):
        link = item["link"]
        try:
            article = cl_parse(cl_fetch(link, offline=False))
        except Exception as problem:  # noqa: BLE001
            print(f"  ✗ {link}: {problem}")
            continue
        body = len(body_text(article.paragraphs))
        mark = "✓" if (article.license.startswith("CC BY") and article.abstract and article.keywords
                       and not article.rejected and body >= target * 0.9) else " "
        print(f"{mark} {body:6} {article.license:10} kw={len(article.keywords)} "
              f"abs={len(article.abstract):4} [{article.category[:30]}] {link}  {article.rejected}")


def candidates_wiki(language: str, title: str) -> None:
    page = wiki_fetch(language, title, offline=False)
    lead, body, url = wiki_parse(page, language)
    print(f"{url}\n  вводный раздел: {len(lead)} знаков, основной текст: {len(body_text(body))} знаков, "
          f"абзацев: {sum(1 for p in body if not p.startswith('# '))}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="не обращаться к сети")
    sub = parser.add_subparsers(dest="command")
    cand = sub.add_parser("candidates", help="подбор источников")
    cand.add_argument("kind", choices=["cl", "wiki"])
    cand.add_argument("args", nargs="+")
    cand.add_argument("--size", type=int, default=20)
    cand.add_argument("--offset", type=int, default=0)
    arguments = parser.parse_args()

    if arguments.command == "candidates":
        if arguments.kind == "cl":
            candidates_cl(" ".join(arguments.args), arguments.size, arguments.offset)
        else:
            candidates_wiki(arguments.args[0], " ".join(arguments.args[1:]))
        return 0
    return build(arguments.offline)


if __name__ == "__main__":
    sys.exit(main())
