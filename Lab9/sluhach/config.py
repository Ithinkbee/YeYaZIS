"""Пути, языки и параметры распознавания."""

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

#: сочинения по литературе: data/essays/<идентификатор>.txt
ESSAYS_DIR = DATA_DIR / "essays"

#: сведения о сочинениях: заголовок, язык, автор произведения, источник
CATALOG_PATH = DATA_DIR / "catalog.json"

#: то, что меняется во время работы: список операций, заданный пользователем,
#: фразы-пасхалки администратора и надиктованные сочинения. Тесты уводят этот
#: каталог во временный, чтобы не трогать настоящие настройки.
STATE_DIR = Path(os.environ.get("SLUHACH_STATE_DIR") or DATA_DIR)
OPERATIONS_PATH = STATE_DIR / "operations.json"
EGGS_PATH = STATE_DIR / "eggs.json"
DICTATED_PATH = STATE_DIR / "dictated.json"

#: акустические модели Vosk: models/<название модели>/
MODELS_DIR = Path(os.environ.get("SLUHACH_MODELS_DIR") or BASE_DIR / "models")

#: фразы, озвученные синтезатором для проверки распознавания (tools/evaluate.py)
SPEECH_DIR = DATA_DIR / "speech"

#: результаты проверки и графики
REPORT_DIR = BASE_DIR / "report"

WEB_DIR = Path(__file__).resolve().parent / "web"
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

# --- Веб-сервер -------------------------------------------------------------

HOST = os.environ.get("SLUHACH_HOST", "127.0.0.1")
#: 8000 и 8090 заняты sc-web и sc-server, 8010 и 8030 — прошлыми работами.
#: Микрофон браузер отдаёт только защищённым страницам; адреса 127.0.0.1 и
#: localhost считаются защищёнными и без HTTPS.
PORT = int(os.environ.get("SLUHACH_PORT", "8097"))

# --- Языки варианта 7 ---------------------------------------------------------

#: код языка -> (название по-русски, самоназвание, метка языка для браузера)
LANGUAGES: dict[str, tuple[str, str, str]] = {
    "de": ("немецкий", "Deutsch", "de-DE"),
    "ru": ("русский", "Русский", "ru-RU"),
}
#: немецкий — язык варианта, поэтому он первый и выбран по умолчанию
LANGUAGE_CODES: tuple[str, ...] = ("de", "ru")
DEFAULT_LANGUAGE = os.environ.get("SLUHACH_LANGUAGE", "de").strip().lower()
if DEFAULT_LANGUAGE not in LANGUAGES:
    DEFAULT_LANGUAGE = "de"


def language_name(code: str) -> str:
    entry = LANGUAGES.get(code)
    return entry[0] if entry else code


def language_tag(code: str) -> str:
    entry = LANGUAGES.get(code)
    return entry[2] if entry else code


# --- Распознавание ------------------------------------------------------------

#: модели Vosk (Kaldi). Малые модели — около 45 МБ на язык, работают без сети
#: и на порядок быстрее реального времени; большие (1,8 ГБ) точнее, но для
#: коротких команд их точность избыточна.
VOSK_MODELS: dict[str, str] = {
    "de": "vosk-model-small-de-0.15",
    "ru": "vosk-model-small-ru-0.22",
}
VOSK_MODEL_URL = "https://alphacephei.com/vosk/models/{name}.zip"

#: способы распознавания: локальный распознаватель на сервере и распознаватель
#: браузера (Web Speech API — в Chrome и Edge, нужен интернет)
ENGINES: dict[str, str] = {
    "vosk": "Vosk — на этом компьютере, без сети",
    "browser": "браузер — Web Speech API",
}
DEFAULT_ENGINE = "vosk"

#: частота дискретизации звука, который приходит от браузера и уходит в Vosk
SAMPLE_RATE = 16000

# --- Обнаружение речи в сигнале -------------------------------------------------
#
# Сигнал режется на кадры по 20 мс, у каждого считается уровень в дБ
# относительно полной шкалы. Речь начинается, когда уровень заметно выше шума
# комнаты, и кончается, когда он надолго возвращается к шуму.

FRAME_MS = 20
#: на сколько дБ кадр должен быть громче шума, чтобы считаться началом речи
VAD_START_MARGIN_DB = 9.0
#: внутри фразы порог ниже: затухающий конец слова — ещё речь
VAD_END_MARGIN_DB = 5.0
#: тише этого уровня речью не считается ничего, как бы тихо ни было в комнате
VAD_MIN_LEVEL_DB = -50.0
#: речь началась, если из последних VAD_START_WINDOW кадров громких — не меньше
#: VAD_START_FRAMES: одиночный щелчок фразу не открывает
VAD_START_FRAMES = 3
VAD_START_WINDOW = 5
#: пауза, после которой фраза считается законченной, мс
VAD_END_SILENCE_MS = 700
#: сколько звука перед началом речи отдаётся распознавателю: первый согласный
#: тише порога и иначе пропал бы
VAD_PREROLL_MS = 300
#: фраза длиннее этого завершается принудительно (например, играет музыка)
VAD_MAX_UTTERANCE_MS = 15000
#: всплеск короче этого — не фраза
VAD_MIN_SPEECH_MS = 160

# --- Сопоставление фразы с операциями ---------------------------------------------

#: насколько распознанная фраза должна совпасть с шаблоном операции (0…1).
#: Мера — доля совпавших букв по расстоянию Левенштейна: «ließ vor» вместо
#: «lies vor» и «сочинении» вместо «сочинение» проходят, случайная фраза — нет.
MATCH_THRESHOLD = 0.75
#: то же для ключевых фраз-пасхалок; порог выше — фраза должна прозвучать целиком
EGG_THRESHOLD = 0.8
#: самая длинная фраза, которая принимается к разбору, знаков
MAX_PHRASE_CHARS = 300
#: сколько шаблонов можно задать операции на одном языке и какой длины
MAX_TEMPLATES = 8
MAX_TEMPLATE_CHARS = 60

# --- Чтение вслух -----------------------------------------------------------------

#: сколько знаков абзаца Пафнутий показывает в облачке, когда читает вслух:
#: абзац целиком виден на странице, в облачке хватит начала
READ_PREVIEW_CHARS = 90

# --- Диктовка ---------------------------------------------------------------------

#: самый длинный текст, который можно надиктовать, знаков (школьное сочинение — 2–4 тысячи)
MAX_DRAFT_CHARS = 20000
#: во время диктовки фраза не обрезается до MAX_PHRASE_CHARS: длинное предложение — не команда
MAX_DICTATED_PHRASE_CHARS = 2000
#: сколько последних фраз можно стереть голосом
DRAFT_UNDO = 30
#: сколько надиктованных сочинений хранится
MAX_DICTATED = 50
MAX_TITLE_CHARS = 60
#: если название не задано, им становятся первые слова текста
DICTATED_TITLE_WORDS = 5

# --- Фразы-пасхалки и администратор ---------------------------------------------------
#
# Ключевые фразы и ответы на них вписывает администратор в окне, которое
# обычному пользователю не открывается: чтобы попасть в него, нужно войти по
# имени и паролю (ссылка «Вход администратора» внизу страницы, адрес /admin,
# пять щелчков по пауку или Ctrl+Alt+P). Имя и пароль задаются при запуске.

ADMIN_LOGIN = os.environ.get("SLUHACH_ADMIN_LOGIN", "admin")
#: пароль по умолчанию годится только для своего компьютера — задайте свой
DEFAULT_ADMIN_PASSWORD = "pafnuty"
ADMIN_PASSWORD = os.environ.get("SLUHACH_ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)
#: после стольких неверных паролей подряд вход закрывается на ADMIN_LOCK_SECONDS
ADMIN_ATTEMPTS = 5
ADMIN_LOCK_SECONDS = 30
#: сколько часов действует вход администратора
ADMIN_SESSION_HOURS = 12
MAX_EGGS = 200
MAX_EGG_KEY_CHARS = 120
MAX_EGG_ANSWER_CHARS = 400

# --- Паук Пафнутий -----------------------------------------------------------------
#
# Паук из прошлых работ. Здесь он — голос системы: ответ звучит и одновременно
# появляется в его облачке, а сам он показывает, что система делает — слушает,
# думает или говорит. На своей странице он гуляет по карте, слушаясь голоса.
# При SLUHACH_COMPANION=0 он исчезает вместе с игрой; распознавание, операции
# и пасхалки работают по-прежнему, ответы остаются в журнале.

COMPANION_ENABLED = _env_bool("SLUHACH_COMPANION", True)
COMPANION_NAME = "Пафнутий"


def ensure_dirs() -> None:
    """Создаёт рабочие каталоги, если их ещё нет."""
    for path in (DATA_DIR, ESSAYS_DIR, STATE_DIR, MODELS_DIR, REPORT_DIR):
        path.mkdir(parents=True, exist_ok=True)
