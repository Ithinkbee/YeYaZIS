"""Пути, голоса и параметры синтеза."""

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

#: научные статьи по computer science: data/articles/<идентификатор>.txt
ARTICLES_DIR = DATA_DIR / "articles"
#: сведения о статьях: заголовок, источник, лицензия
CATALOG_PATH = DATA_DIR / "catalog.json"

#: встроенные словари произношения: английские термины, аббревиатуры
PRONUNCIATION_DIR = DATA_DIR / "pronunciation"

#: проверочные наборы: эталонное чтение трудных случаев, предложения для разборчивости
EVAL_DIR = DATA_DIR / "eval"

#: то, что меняется во время работы: словарь пользователя и настройки чтения
#: для других программ. Тесты уводят этот каталог во временный.
STATE_DIR = Path(os.environ.get("GLASHATAI_STATE_DIR") or DATA_DIR)
LEXICON_PATH = STATE_DIR / "lexicon.json"
SETTINGS_PATH = STATE_DIR / "settings.json"

#: синтезированные фразы Пафнутия и записи проверки — создаются заново, в репозиторий не входят
CACHE_DIR = Path(os.environ.get("GLASHATAI_CACHE_DIR") or DATA_DIR / "cache")

#: нейросетевые голоса Piper: voices/<голос>.onnx и .onnx.json
VOICES_DIR = Path(os.environ.get("GLASHATAI_VOICES_DIR") or BASE_DIR / "voices")

#: модель распознавания Vosk — только для проверки разборчивости (tools/evaluate.py)
MODELS_DIR = Path(os.environ.get("GLASHATAI_MODELS_DIR") or BASE_DIR / "models")
VOSK_MODEL = "vosk-model-small-de-0.15"
VOSK_MODEL_URL = "https://alphacephei.com/vosk/models/{name}.zip"

#: результаты проверки и графики
REPORT_DIR = BASE_DIR / "report"

WEB_DIR = Path(__file__).resolve().parent / "web"
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

# --- Веб-сервер -------------------------------------------------------------

HOST = os.environ.get("GLASHATAI_HOST", "127.0.0.1")
#: 8000 и 8090 заняты sc-web и sc-server, 8010–8040 и 8097 — прошлыми работами.
#: 8083: работа № 8, вариант 3. Микрофон («Мой говорящий Пафнутий») браузер даёт
#: только защищённым страницам; адреса 127.0.0.1 и localhost считаются защищёнными.
PORT = int(os.environ.get("GLASHATAI_PORT", "8083"))

# --- Язык варианта 3 ----------------------------------------------------------

LANGUAGE = "de"
LANGUAGE_TAG = "de-DE"
LANGUAGE_NAME = "немецкий"

# --- Голоса -------------------------------------------------------------------
#
# Голос задаётся строкой «движок:имя». Движки:
#   piper    — нейросетевые голоса Piper (VITS, ONNX), работают без сети;
#   formant  — собственный формантный синтезатор системы, написан с нуля;
#   sapi     — голоса Windows (Microsoft Speech API);
#   browser  — голоса браузера (Web Speech API), звучат на стороне страницы.

#: голоса Piper, которые скачивает tools/get_voices.py. Ключ — имя файла модели.
#: speakers — дикторы многоголосой модели (у Thorsten — восемь эмоций).
PIPER_VOICES: dict[str, dict] = {
    "de_DE-thorsten-medium": {
        "title": "Thorsten", "gender": "мужской", "quality": "medium",
        "path": "de/de_DE/thorsten/medium",
        "note": "основной голос: 22 кГц, ровное чтение",
    },
    "de_DE-kerstin-low": {
        "title": "Kerstin", "gender": "женский", "quality": "low",
        "path": "de/de_DE/kerstin/low",
        "note": "16 кГц",
    },
    "de_DE-eva_k-x_low": {
        "title": "Eva K", "gender": "женский", "quality": "x_low",
        "path": "de/de_DE/eva_k/x_low",
        "note": "самая лёгкая модель, 20 МБ",
    },
    "de_DE-thorsten_emotional-medium": {
        "title": "Thorsten (эмоции)", "gender": "мужской", "quality": "medium",
        "path": "de/de_DE/thorsten_emotional/medium",
        "note": "восемь манер чтения: от шёпота до гнева",
        "speakers": {
            "neutral": "спокойно", "amused": "весело", "surprised": "удивлённо", "angry": "сердито",
            "disgusted": "брезгливо", "sleepy": "сонно", "drunk": "пьяно", "whisper": "шёпотом",
        },
    },
}
PIPER_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/{path}/{name}{extension}?download=true"

#: голос по умолчанию: нейросетевой Thorsten, а без моделей Piper — собственный синтезатор
DEFAULT_VOICE = os.environ.get("GLASHATAI_VOICE", "piper:de_DE-thorsten-medium")
FALLBACK_VOICE = "formant:karl"

# --- Параметры чтения ---------------------------------------------------------

#: темп: доля обычной скорости речи (1 — как говорит голос сам)
RATE_RANGE = (0.5, 2.0)
#: высота: сдвиг основного тона в полутонах
PITCH_RANGE = (-8.0, 8.0)
#: громкость в процентах; 100 % — запись, приведённая к единому уровню
VOLUME_RANGE = (0, 100)
#: «живость» — разброс интонации и ритма (для Piper — noise_scale и noise_w)
LIVELINESS_RANGE = (0.0, 1.0)
#: паузы после предложения и после абзаца, мс
SENTENCE_PAUSE_RANGE = (0, 2000)
PARAGRAPH_PAUSE_RANGE = (0, 3000)

#: уровень, к которому приводится каждая запись перед регулировкой громкости, дБ
#: относительно полной шкалы: голоса разных движков звучат одинаково громко
TARGET_LEVEL_DB = -18.0

#: самый длинный текст, который читается за один раз, знаков (статья — 15–20 тысяч)
MAX_TEXT_CHARS = 200_000
#: самое длинное предложение, которое уходит синтезатору целиком; длиннее — делится по запятым
MAX_SENTENCE_CHARS = 400
#: самый большой файл, который можно открыть, байт
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
#: сколько синтезированных записей держать в памяти (по объёму звука), МБ
CACHE_MEMORY_MB = 96

# --- Чтение из других программ --------------------------------------------------
#
# Буфер обмена и горячая клавиша работают в Windows: система следит за буфером
# и по сочетанию клавиш копирует выделенное в любой программе. Выключаются
# ключом --no-desktop или переменной GLASHATAI_DESKTOP=0.

DESKTOP_ENABLED = _env_bool("GLASHATAI_DESKTOP", True)
#: сочетание «прочитать выделенное» и «замолчать»
HOTKEY_READ = "Ctrl+Alt+R"
HOTKEY_STOP = "Ctrl+Alt+S"
#: как часто проверяется буфер обмена, с
CLIPBOARD_POLL_SECONDS = 0.3
#: самый длинный текст из буфера, который читается, знаков
MAX_CLIPBOARD_CHARS = 20_000

# --- Паук Пафнутий -----------------------------------------------------------------
#
# Паук из прошлых работ. Здесь у него свой голос — формантный синтезатор
# системы — и своя вкладка «Мой говорящий Пафнутий», где он, как кот из
# «Говорящего Тома», повторяет сказанное писклявым голосом и отзывается на
# тычки. При GLASHATAI_COMPANION=0 он исчезает вместе с вкладкой; чтение,
# голоса и настройки работают по-прежнему.

COMPANION_ENABLED = _env_bool("GLASHATAI_COMPANION", True)
COMPANION_NAME = "Пафнутий"
#: самая длинная запись, которую Пафнутий повторяет, с
MAX_ECHO_SECONDS = 12
#: самая длинная фраза, которую можно дать ему сказать, знаков
MAX_TALK_CHARS = 300


def ensure_dirs() -> None:
    """Создаёт рабочие каталоги, если их ещё нет."""
    for path in (DATA_DIR, STATE_DIR, CACHE_DIR, VOICES_DIR, REPORT_DIR):
        path.mkdir(parents=True, exist_ok=True)
