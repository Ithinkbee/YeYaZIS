"""Пути, языки, предметные области и параметры реферирования."""

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

#: тестовая коллекция: data/collection/<идентификатор>.txt
COLLECTION_DIR = DATA_DIR / "collection"

#: сведения о документах коллекции: заголовок, язык, область, источник,
#: лицензия, эталонный реферат и эталонные ключевые слова
CATALOG_PATH = DATA_DIR / "catalog.json"

#: исходные страницы, из которых собрана коллекция (для воспроизводимости)
SOURCES_DIR = DATA_DIR / "sources"

#: списки стоп-слов: data/stopwords/<язык>.txt
STOPWORDS_DIR = DATA_DIR / "stopwords"

#: онтология предметной области на языке SCs
KB_DIR = BASE_DIR / "kb"

#: выгрузки результатов, графики и схемы для отчёта
REPORT_DIR = BASE_DIR / "report"

WEB_DIR = Path(__file__).resolve().parent / "web"
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

# --- Веб-сервер -------------------------------------------------------------

HOST = os.environ.get("IZBORNIK_HOST", "127.0.0.1")
#: 8000 и 8090 заняты sc-web и sc-server, поэтому порт системы другой
PORT = int(os.environ.get("IZBORNIK_PORT", "8030"))

# --- Языки и предметные области варианта 4 ----------------------------------

#: код языка -> (название по-русски, самоназвание)
LANGUAGES: dict[str, tuple[str, str]] = {
    "ru": ("русский", "Русский"),
    "de": ("немецкий", "Deutsch"),
}
LANGUAGE_CODES: tuple[str, ...] = ("ru", "de")

#: код области -> (название, краткое название)
DOMAINS: dict[str, tuple[str, str]] = {
    "cs": ("Научные статьи по computer science", "computer science"),
    "lit": ("Сочинения по литературе", "литература"),
}
DOMAIN_CODES: tuple[str, ...] = ("cs", "lit")


def language_name(code: str) -> str:
    entry = LANGUAGES.get(code)
    return entry[0] if entry else code


def domain_name(code: str, short: bool = False) -> str:
    entry = DOMAINS.get(code)
    if not entry:
        return code
    return entry[1] if short else entry[0]


# --- Реферирование ----------------------------------------------------------

#: размер классического реферата; методичка рекомендует 10 предложений
SUMMARY_SENTENCES = 10

#: сколько ключевых слов верхнего уровня выводить в реферате
KEYWORDS_TOP = 10

#: сколько словосочетаний подчинять одному ключевому слову
KEYWORD_CHILDREN = 4

#: словосочетание попадает в реферат, если встретилось не реже стольких раз
PHRASE_MIN_FREQ = 2

#: по каким документам считается df(t) и |DB|.
#:
#: "language" — по документам того же языка. Русский термин никогда не
#: встретится в немецком документе, поэтому общая коллекция завысила бы вес
#: любого слова: термин, который есть во всех русских документах, получил бы
#: log(20/10) > 0, хотя он ничего не отличает. "collection" оставлен для
#: сравнения.
IDF_SCOPE = os.environ.get("IZBORNIK_IDF_SCOPE", "language")

#: удалять ли из предложений реферата вводные конструкции и ссылки на
#: литературу. Отбор предложений от этого не зависит — меняется только вид.
COMPRESS_SENTENCES = True

# --- Требования к тестовой коллекции ----------------------------------------

#: «документы одинакового размера (например, 10 страниц формата А4)».
#: Страница машинописного текста — 1800 знаков с пробелами.
PAGE_CHARS = 1800
DOC_TARGET_PAGES = 10
DOC_TARGET_CHARS = PAGE_CHARS * DOC_TARGET_PAGES
#: допустимое отклонение объёма документа от целевого
DOC_SIZE_TOLERANCE = 0.10

# --- Загрузка своих документов ----------------------------------------------

UPLOAD_EXTENSIONS = {".txt", ".md", ".html", ".htm", ".docx", ".pdf"}
#: максимальный размер загружаемого файла (8 МиБ)
MAX_UPLOAD_SIZE = 8 * 1024 * 1024
#: слишком короткий текст реферировать бессмысленно
MIN_TEXT_CHARS = 400

# --- OSTIS ------------------------------------------------------------------
#
# Система работает в двух режимах. Если sc-сервер доступен, документ
# помещается в базу знаний, реферат строит sc-агент, а интерфейс читает
# результат из базы знаний. Если нет — тот же алгоритм выполняется локально.

#: auto — работать через OSTIS, если сервер доступен; on — только через OSTIS;
#: off — только локально
OSTIS_MODE = os.environ.get("IZBORNIK_OSTIS", "auto").strip().lower()

OSTIS_URL = os.environ.get("IZBORNIK_OSTIS_URL", "ws://localhost:8090")
SC_WEB_URL = os.environ.get("IZBORNIK_SC_WEB_URL", "http://localhost:8000")

#: embedded — агент регистрируется в процессе веб-интерфейса;
#: external — агент запущен отдельно (python tools/agent.py)
AGENT_MODE = os.environ.get("IZBORNIK_AGENT", "embedded").strip().lower()

#: сколько секунд ждать завершения действия агентом
OSTIS_ACTION_TIMEOUT = float(os.environ.get("IZBORNIK_OSTIS_TIMEOUT", "60"))

# --- Паук Пафнутий -----------------------------------------------------------
#
# Паук из первых двух работ сидит в углу страницы и подаёт реплики по разделу,
# а на своих страницах играет: в сапёре он прячет на поле паучат, в бою
# выставляет их против слов из рефератов. При IZBORNIK_COMPANION=0 он исчезает
# полностью вместе с играми; на реферирование и оценку он не влияет ни в
# каком виде.

COMPANION_ENABLED = _env_bool("IZBORNIK_COMPANION", True)
COMPANION_NAME = "Пафнутий"

# --- Реферат вручную -----------------------------------------------------------
#
# Человек пишет реферат короткого отрывка, система реферирует тот же отрывок и
# сравнивает. Это задание на реферирование, а не игра паука, поэтому оно
# доступно и без Пафнутия.

#: отрывок — несколько соседних абзацев одного раздела документа
PRACTICE_MIN_CHARS = 700
PRACTICE_MAX_CHARS = 1600
PRACTICE_MIN_SENTENCES = 5
#: доля предложений отрывка в реферате системы (но от 2 до 4 предложений)
PRACTICE_SUMMARY_SHARE = 0.3
#: сколько ключевых понятий отрывка искать в реферате человека
PRACTICE_CONCEPTS = 6
#: объём реферата человека, при котором замечаний нет, — доля отрывка
PRACTICE_GOOD_LENGTH = (0.1, 0.45)
#: длиннее этого (доля отрывка) — уже пересказ, а не реферат
PRACTICE_MAX_LENGTH = 0.75
#: самый длинный реферат, который принимается к сравнению, знаков
PRACTICE_MAX_INPUT = 4000

# --- Бой с Пафнутием ---------------------------------------------------------------
#
# Поле букв, в котором спрятаны ключевые слова реферата одного документа.
# Правила самого боя (прочность, урон, скорость) — в web/static/battle.js.

BATTLE_GRID_ROWS = 8
BATTLE_GRID_COLS = 13
#: сколько слов прятать в одном поле
BATTLE_WORDS = (3, 5)
#: слово короче этого легко возникает среди случайных букв само собой
BATTLE_WORD_MIN_LEN = 4


def ensure_dirs() -> None:
    """Создаёт рабочие каталоги, если их ещё нет."""
    for path in (DATA_DIR, COLLECTION_DIR, SOURCES_DIR, STOPWORDS_DIR, REPORT_DIR):
        path.mkdir(parents=True, exist_ok=True)
