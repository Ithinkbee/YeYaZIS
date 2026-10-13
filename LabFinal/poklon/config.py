"""Настройки «Поклона»: папки, адрес сервера, допустимые записи.

Папки с музыкой и данными можно переназначить переменными окружения — так
тесты и проверки работают во временных папках и не трогают настоящие
music/ и data/.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = Path(__file__).resolve().parent / "web"
STATIC_DIR = WEB_DIR / "static"

# музыка: первая запись из этой папки (или файл, названный ключом --music)
MUSIC = Path(os.environ.get("POKLON_MUSIC", ROOT / "music"))
# слова прощания (words.json) и метки хора (cues.json)
DATA_DIR = Path(os.environ.get("POKLON_DATA", ROOT / "data"))

HOST = os.environ.get("POKLON_HOST", "127.0.0.1")
PORT = int(os.environ.get("POKLON_PORT", "8100"))

# записи, которые умеет разобрать браузер
AUDIO_TYPES = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".flac": "audio/flac",
    ".wav": "audio/wav",
}

# запись, перетащенная на страницу, сохраняется в папку с музыкой; длинная
# запись в высоком качестве занимает десятки мегабайт — больше не нужно
MAX_TRACK_BYTES = 64 * 1024 * 1024

STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def music_dir() -> Path:
    """Папка, куда сохраняются записи (если MUSIC — файл, то его папка)."""
    return MUSIC.parent if MUSIC.suffix.lower() in AUDIO_TYPES else MUSIC


def words_file() -> Path:
    return DATA_DIR / "words.json"


def cues_file() -> Path:
    return DATA_DIR / "cues.json"
