"""Пути, языки, предметные области и параметры перевода."""

from __future__ import annotations

import os
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "да"}


# --- Каталоги проекта -------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

#: тестовая коллекция: data/collection/<идентификатор>.txt и catalog.json
COLLECTION_DIR = DATA_DIR / "collection"
CATALOG_PATH = DATA_DIR / "catalog.json"

#: исходные страницы, из которых собрана коллекция (для воспроизводимости)
SOURCES_DIR = DATA_DIR / "sources"

#: исходный словарь в виде текстовых таблиц: data/lexicon/*.tsv
LEXICON_DIR = DATA_DIR / "lexicon"

#: эталонные переводы для оценки качества: data/reference/*.tsv
REFERENCE_DIR = DATA_DIR / "reference"

#: размеченные корпуса Universal Dependencies (скачиваются tools/train.py)
TREEBANK_DIR = DATA_DIR / "treebank"

#: внешний словарь Ding для автоматического пополнения (скачивается по запросу)
EXTERNAL_DIR = DATA_DIR / "external"

#: рабочая база данных словаря (строится из data/lexicon при первом запуске)
DICTIONARY_DB = Path(os.environ.get("DRAGOMAN_DB", str(DATA_DIR / "dictionary.sqlite")))

#: обученные модели теггера, анализатора и лемматизатора
MODELS_DIR = BASE_DIR / "models"

#: оценка, графики и схемы для отчёта
REPORT_DIR = BASE_DIR / "report"

WEB_DIR = Path(__file__).resolve().parent / "web"
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

# --- Веб-сервер -------------------------------------------------------------

HOST = os.environ.get("DRAGOMAN_HOST", "127.0.0.1")
PORT = int(os.environ.get("DRAGOMAN_PORT", "8040"))

# --- Направление перевода и предметные области варианта 4 ----------------------

SOURCE_LANGUAGE = "en"
TARGET_LANGUAGE = "de"
LANGUAGES: dict[str, str] = {"en": "английский", "de": "немецкий"}

#: код области -> (название, краткое название)
DOMAINS: dict[str, tuple[str, str]] = {
    "cs": ("Научные статьи по computer science", "computer science"),
    "lit": ("Сочинения по литературе", "литература"),
}
DOMAIN_CODES: tuple[str, ...] = ("cs", "lit")
#: «общая лексика» — запись словаря, не привязанная к области
GENERAL_DOMAIN = "gen"


def domain_name(code: str, short: bool = False) -> str:
    entry = DOMAINS.get(code)
    if not entry:
        return "общая лексика" if code == GENERAL_DOMAIN else code
    return entry[1] if short else entry[0]


# --- Перевод ----------------------------------------------------------------------

#: способы перевода: прямой (пословный) и с трансфером
MODES: dict[str, str] = {
    "transfer": "с трансфером",
    "direct": "прямой (пословный)",
}
DEFAULT_MODE = "transfer"

# --- Загрузка своих текстов -------------------------------------------------------

UPLOAD_EXTENSIONS = {".txt", ".md", ".html", ".htm", ".docx", ".pdf"}
MAX_UPLOAD_SIZE = 8 * 1024 * 1024
#: самый длинный текст, который принимается к переводу, знаков
MAX_TEXT_CHARS = 60_000

# --- Обучение анализатора ---------------------------------------------------------

#: корпуса Universal Dependencies: имя -> адрес каталога в репозитории.
#: EWT и GUM размечены тегами Penn Treebank — на них учатся все три модели.
TREEBANKS: dict[str, str] = {
    "en_ewt": "https://raw.githubusercontent.com/UniversalDependencies/UD_English-EWT/master",
    "en_gum": "https://raw.githubusercontent.com/UniversalDependencies/UD_English-GUM/master",
}
#: LinES (художественная литература) и ParTUT (Википедия, тексты законов) размечены своими тегами,
#: поэтому на них учится только синтаксический анализатор — с тегами, которые расставил наш теггер
PARSER_TREEBANKS: dict[str, str] = {
    "en_lines": "https://raw.githubusercontent.com/UniversalDependencies/UD_English-LinES/master",
    "en_partut": "https://raw.githubusercontent.com/UniversalDependencies/UD_English-ParTUT/master",
}
RANDOM_SEED = 4
TAGGER_EPOCHS = 6
PARSER_EPOCHS = 15
LABELER_EPOCHS = 6
#: сколько частей при перекрёстной разметке обучающего корпуса для анализатора
JACKKNIFE_FOLDS = 5

# --- Внешний словарь Ding -----------------------------------------------------------

DING_URL = "https://ftp.tu-chemnitz.de/pub/Local/urz/ding/de-en/de-en.txt.gz"
DING_PATH = EXTERNAL_DIR / "de-en.txt.gz"

# --- Паук Пафнутий -----------------------------------------------------------------
#
# Паук из прошлых работ сидит в углу страницы и подаёт реплики по разделу, а на
# своей странице воюет: в трёхмерном тире английские слова текста идут на него
# волнами, и каждое попадание паутиной переводит слово на немецкий. При
# DRAGOMAN_COMPANION=0 он исчезает вместе с игрой; на перевод не влияет.

COMPANION_ENABLED = _env_bool("DRAGOMAN_COMPANION", True)
COMPANION_NAME = "Пафнутий"

#: волны в игре: по умолчанию, наименьшее и наибольшее число
SHOOTER_WAVES = 5
SHOOTER_WAVES_RANGE = (1, 10)


def ensure_dirs() -> None:
    """Создаёт рабочие каталоги, если их ещё нет."""
    for path in (DATA_DIR, COLLECTION_DIR, SOURCES_DIR, LEXICON_DIR, REFERENCE_DIR, MODELS_DIR, REPORT_DIR):
        path.mkdir(parents=True, exist_ok=True)
