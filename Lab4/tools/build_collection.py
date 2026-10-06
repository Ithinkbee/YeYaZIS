"""Сборка тестовой коллекции английских текстов.

    python tools/build_collection.py            загрузить статьи и собрать коллекцию
    python tools/build_collection.py --offline  собрать из сохранённых страниц data/sources

Коллекция — 12 текстов английской Википедии (CC BY-SA 4.0): шесть статей по
computer science и шесть литературоведческих статей о романах и пьесах. Из
статьи берутся вводная часть и разделы, близкие по жанру к варианту: для
научных статей — устройство и принципы, для литературы — темы, герои, стиль
(то, о чём пишут сочинения). Текст обрезается по границе абзаца так, чтобы
документ был около двух страниц: на нём удобно читать перевод, а в игре
Пафнутия — сражаться со всеми его словами за разумное время.

Ответы API сохраняются в data/sources/wikipedia, поэтому коллекция
пересобирается без сети.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dragoman import config, console  # noqa: E402

console.setup()

API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "Dragoman-lab/1.0 (BSUIR student lab; machine translation test collection)"
SOURCES = config.SOURCES_DIR / "wikipedia"

#: объём документа: не меньше и не больше, знаков
MIN_CHARS = 3000
MAX_CHARS = 4600

#: (идентификатор, статья, область, абзацев вводной части, разделы после неё).
#: У литературных статей берутся разделы о темах и героях — то, о чём пишут
#: сочинения, — а не пересказ сюжета.
DOCUMENTS = [
    ("cs-compiler", "Compiler", "cs", 4, ["Compiler construction", "Three-stage compiler structure"]),
    ("cs-os", "Operating system", "cs", 5, ["Kernel", "Memory management", "Concurrency"]),
    ("cs-nn", "Neural network (machine learning)", "cs", 7, ["Learning", "Neuron"]),
    ("cs-security", "Information security", "cs", 3, ["Security Goals", "Cryptography"]),
    ("cs-semweb", "Semantic Web", "cs", 3, ["Background", "Semantic Web solutions", "Challenges"]),
    ("cs-mt", "Machine translation", "cs", 3, ["Rule-based", "Transfer-based machine translation", "Interlingual",
                                               "Statistical", "Neural MT"]),
    ("lit-hamlet", "Hamlet", "lit", 2, ["Philosophical", "Religious", "Psychoanalytic"]),
    ("lit-pride", "Pride and Prejudice", "lit", 3, ["Major themes", "Self-knowledge", "Wealth"]),
    ("lit-frankenstein", "Frankenstein", "lit", 3, ["The Creature", "Modern Prometheus"]),
    ("lit-1984", "Nineteen Eighty-Four", "lit", 2, ["Censorship", "Surveillance", "Futurology"]),
    ("lit-gatsby", "The Great Gatsby", "lit", 3, ["The American Dream", "Class permanence"]),
    ("lit-janeeyre", "Jane Eyre", "lit", 3, ["Feminism", "Bildungsroman", "Social class"]),
]

#: разделы, которые в коллекцию не берутся
SKIP_SECTIONS = {"see also", "references", "notes", "further reading", "external links", "bibliography",
                 "sources", "citations", "footnotes", "works cited", "adaptations", "film adaptations",
                 "in popular culture", "editions", "publication history", "explanatory notes"}


def fetch(title: str) -> dict:
    params = {
        "action": "query", "format": "json", "formatversion": "2", "redirects": "1",
        "prop": "extracts|revisions|info", "explaintext": "1", "exsectionformat": "wiki",
        "rvprop": "ids|timestamp", "inprop": "url", "titles": title,
    }
    # requests проверяет сертификаты по своему набору certifi: у urllib на части машин
    # хранилище сертификатов устаревшее, и Википедия не открывается
    import requests

    for attempt in range(5):
        response = requests.get(API, params=params, headers={"User-Agent": USER_AGENT}, timeout=60)
        if response.status_code == 429:           # просят подождать
            time.sleep(10 * (attempt + 1))
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError(f"Википедия не отвечает на запрос статьи {title}")


def source_path(title: str) -> Path:
    safe = re.sub(r"[^\w.-]+", "_", title)
    return SOURCES / f"en-{safe}.json"


def sections(extract: str) -> list[tuple[str, list[str]]]:
    """Разделы статьи: (заголовок, абзацы); у вводной части заголовок пустой."""
    result: list[tuple[str, list[str]]] = [("", [])]
    for line in extract.split("\n"):
        line = line.strip()
        if not line:
            continue
        heading = re.fullmatch(r"(=+)\s*(.*?)\s*\1", line)
        if heading:
            result.append((heading.group(2), []))
            continue
        result[-1][1].append(line)
    return result


_IPA = re.compile(r"\s*\((?:[^()]*?(?:/[^/]+/|[ˈˌəɪʊæɒɔʃʒθðŋ])[^()]*?)\)")
_EMPTY_PARENS = re.compile(r"\s*\(\s*[;,]?\s*\)")


def clean_paragraph(text: str) -> str:
    text = _IPA.sub("", text)
    text = _EMPTY_PARENS.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    return text


def usable(paragraph: str) -> bool:
    # формулы, таблицы и списки из одного-двух слов в коллекцию не идут
    if len(paragraph) < 60 or paragraph.count(" ") < 8:
        return False
    if re.search(r"[{}\\=]{2,}|\\displaystyle", paragraph):
        return False
    return paragraph[-1:] in ".!?\"”)'"


def build_document(data: dict, lead_max: int, wanted: list[str]) -> tuple[str, list[str]]:
    page = data["query"]["pages"][0]
    parts = sections(page.get("extract", ""))
    lead = [clean_paragraph(p) for p in parts[0][1]]
    blocks: list[str] = [p for p in lead if usable(p)][:lead_max]
    used = []
    total = sum(len(p) + 2 for p in blocks)
    by_title = {title.lower(): paragraphs for title, paragraphs in parts[1:]}
    order = [title for title in wanted if title.lower() in by_title]
    order += [title for title, _ in parts[1:] if title not in order and title.lower() not in SKIP_SECTIONS]
    for title in order:
        if total >= MIN_CHARS:
            break
        paragraphs = [clean_paragraph(p) for p in by_title.get(title.lower(), [])]
        paragraphs = [p for p in paragraphs if usable(p)]
        if not paragraphs:
            continue
        heading = "# " + title
        added = False
        for paragraph in paragraphs:
            if total + len(paragraph) > MAX_CHARS and total >= MIN_CHARS * 0.8:
                break
            if not added:
                blocks.append(heading)
                total += len(heading) + 2
                added = True
            blocks.append(paragraph)
            total += len(paragraph) + 2
        if added:
            used.append(title)
    # вводная часть слишком длинная — обрезается по абзацам
    while sum(len(b) + 2 for b in blocks) > MAX_CHARS and len(blocks) > 2:
        blocks.pop()
        if blocks[-1].startswith("# "):
            blocks.pop()
    return "\n\n".join(blocks), used


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="не загружать, собрать из data/sources")
    arguments = parser.parse_args()
    config.ensure_dirs()
    SOURCES.mkdir(parents=True, exist_ok=True)

    catalog = []
    for doc_id, title, domain, lead_max, wanted in DOCUMENTS:
        path = source_path(title)
        if not arguments.offline and not path.exists():
            print(f"  загрузка: {title}")
            path.write_text(json.dumps(fetch(title), ensure_ascii=False, indent=1), encoding="utf-8")
            time.sleep(3.0)
        data = json.loads(path.read_text(encoding="utf-8"))
        page = data["query"]["pages"][0]
        text, used = build_document(data, lead_max, wanted)
        (config.COLLECTION_DIR / f"{doc_id}.txt").write_text(text + "\n", encoding="utf-8")
        revision = page.get("revisions", [{}])[0]
        words = len(re.findall(r"[A-Za-z]+(?:[-'][A-Za-z]+)*", text))
        catalog.append({
            "id": doc_id, "file": f"{doc_id}.txt", "title": page["title"], "domain": domain,
            "chars": len(text), "words": words, "sections": used,
            "source": {
                "site": "en.wikipedia.org", "url": page.get("fullurl", ""),
                "revision": revision.get("revid"), "timestamp": revision.get("timestamp"),
                "license": "CC BY-SA 4.0",
            },
        })
        print(f"  {doc_id:18} {len(text):5} знаков, {words:4} слов; разделы: {', '.join(used) or '—'}")
    config.CATALOG_PATH.write_text(json.dumps({"documents": catalog}, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    print(f"Каталог: {config.CATALOG_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
