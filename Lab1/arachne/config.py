"""Пути, настройки системы и чтение .env."""

from __future__ import annotations

import os
from pathlib import Path

# --- Каталоги проекта -------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
COLLECTION_DIR = DATA_DIR / "collection"
REPORT_DIR = BASE_DIR / "report"
DB_PATH = DATA_DIR / "arachne.db"

STOPWORDS_PATH = DATA_DIR / "stopwords_ru.txt"
SYNONYMS_PATH = DATA_DIR / "synonyms_ru.json"
QRELS_PATH = DATA_DIR / "qrels.csv"

WEB_DIR = Path(__file__).resolve().parent / "web"
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"


def _load_dotenv(path: Path) -> None:
    """Простейший парсер .env: KEY=VALUE, строки с # игнорируются.

    Значения из окружения имеют приоритет над файлом.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "да"}


# --- Веб-сервер -------------------------------------------------------------

HOST = os.environ.get("ARACHNE_HOST", "127.0.0.1")
PORT = int(os.environ.get("ARACHNE_PORT", "8000"))

# --- Паук (обход ЛВС) -------------------------------------------------------

#: расширения, которые паук умеет разбирать
ALLOWED_EXTENSIONS = {".txt", ".md", ".html", ".htm", ".docx", ".pdf", ".rtf", ".csv"}

#: максимальный размер файла для индексации (16 МиБ)
MAX_FILE_SIZE = 16 * 1024 * 1024

#: каталоги, в которые паук не заходит
SKIP_DIRS = {
    ".git", ".svn", ".hg", "__pycache__", "node_modules", ".venv", "venv",
    "$RECYCLE.BIN", "System Volume Information", ".idea", ".vscode",
}

#: число потоков обхода (задача I/O-bound)
CRAWLER_THREADS = 8

# --- Индексирование и поиск -------------------------------------------------

#: длина сниппета в символах (требование методички — первые 300 символов)
SNIPPET_LENGTH = 300

#: сколько результатов показывать на странице выдачи
RESULTS_PER_PAGE = 10

#: вес расширенных термов (синонимы, исправления опечаток) в векторе запроса
EXPANDED_TERM_WEIGHT = 0.5

#: параметры обратной связи по релевантности (метод Рокчио)
ROCCHIO_ALPHA = 1.0
ROCCHIO_BETA = 0.75
ROCCHIO_GAMMA = 0.15

# --- Языковой помощник (любой OpenAI-совместимый сервис) ---------------------
#
# Слой не привязан к конкретному провайдеру: достаточно указать адрес,
# модель и ключ. Имена GROQ_* поддерживаются как псевдонимы для совместимости.

#: известные OpenAI-совместимые сервисы: имя -> (адрес, модель по умолчанию)
#:
#: Доступность зависит не от ключа, а от адреса выхода в сеть: Groq, Cerebras и
#: Together закрывают доступ с адресов дата-центров и VPN (ответ 403 приходит
#: ещё до проверки ключа). OpenRouter и Mistral таких ограничений не ставят.
#: Что доступно именно с вашего адреса, покажет `python tools/check_llm.py --scan`.
LLM_PROVIDERS = {
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "openrouter": ("https://openrouter.ai/api/v1", "google/gemma-4-31b-it:free"),
    "mistral": ("https://api.mistral.ai/v1", "mistral-small-latest"),
    "cerebras": ("https://api.cerebras.ai/v1", "llama-3.3-70b"),
    "together": ("https://api.together.xyz/v1", "meta-llama/Llama-3.3-70B-Instruct-Turbo"),
}

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "groq").strip().lower()
_default_url, _default_model = LLM_PROVIDERS.get(LLM_PROVIDER, LLM_PROVIDERS["groq"])

LLM_API_KEY = (
    os.environ.get("LLM_API_KEY") or os.environ.get("GROQ_API_KEY") or ""
).strip()
LLM_BASE_URL = (
    os.environ.get("LLM_BASE_URL") or os.environ.get("GROQ_BASE_URL") or _default_url
).strip().rstrip("/")
LLM_MODEL = (
    os.environ.get("LLM_MODEL") or os.environ.get("GROQ_MODEL") or _default_model
).strip()
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT") or os.environ.get("GROQ_TIMEOUT") or 20)

#: Помощник выключен по умолчанию и не обращается к сети, даже если ключ задан.
#: Причина: доступность внешнего сервиса зависит от адреса выхода в сеть (см.
#: README), а работа системы не должна от неё зависеть. Поиск, ранжирование и
#: оценка качества языковую модель не используют — она лишь необязательная
#: надстройка над готовой выдачей. Включается явно: ARACHNE_LLM=1 в .env.
LLM_ENABLED = _env_bool("ARACHNE_LLM", False) and bool(LLM_API_KEY)

# HTTP-прокси для обращения к сервису (если VPN поднят как локальный прокси).
# urllib берёт его из переменных окружения, поэтому достаточно указать в .env:
#   HTTPS_PROXY=http://127.0.0.1:8080

# --- Компаньон и геймификация ----------------------------------------------

COMPANION_ENABLED = _env_bool("ARACHNE_COMPANION", True)
COMPANION_NAME = "Пафнутий"


def ensure_dirs() -> None:
    """Создаёт рабочие каталоги, если их ещё нет."""
    for path in (DATA_DIR, COLLECTION_DIR, REPORT_DIR):
        path.mkdir(parents=True, exist_ok=True)
