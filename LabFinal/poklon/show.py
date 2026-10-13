"""Музыка, слова и метки: всё, что странице нужно знать перед началом.

Музыка — запись, которую кладёт сам пользователь: первая по алфавиту из папки
music/ (или файл, названный при запуске). Слова прощания и этажи шахты —
data/words.json: его правят руками, без кода. Метки — когда вступает и когда
смолкает большой хор; страница находит их сама по громкости, а подправленные
на репетиции сохраняет в data/cues.json.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import APP_NAME, COURSE, VERSION, config

# Запасные слова: с ними ролик идёт, даже если words.json потерян или испорчен.
FALLBACK_WORDS = {
    "title": APP_NAME,
    "subtitle": "прощальный подъём на лифте",
    "course": COURSE,
    "to": "",
    "thanks": "Спасибо!",
    "lines": ["Спасибо за курс."],
    "signature": [],
    "group": "",
    "place": "",
    "floors": [],
    "bubbles": ["До свидания!"],
    "music": "",
    "credits": [],
}


def load_words() -> tuple[dict, str]:
    """Слова прощания и сообщение о неполадке (пустое, если всё в порядке)."""
    words = dict(FALLBACK_WORDS)
    path = config.words_file()
    if not path.exists():
        return words, f"нет файла {path.name} — показаны запасные слова"
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return words, f"{path.name} не читается ({error}) — показаны запасные слова"
    if not isinstance(loaded, dict):
        return words, f"{path.name}: ожидался объект — показаны запасные слова"
    for key, fallback in FALLBACK_WORDS.items():
        value = loaded.get(key)
        # тип значения проверяется по запасному: строка остаётся строкой, список — списком
        if isinstance(value, type(fallback)):
            words[key] = value
    return words, ""


def find_track() -> Path | None:
    """Запись, под которую идёт ролик."""
    source = config.MUSIC
    if source.is_file():
        return source if source.suffix.lower() in config.AUDIO_TYPES else None
    if not source.is_dir():
        return None
    tracks = sorted((p for p in source.iterdir() if p.is_file() and p.suffix.lower() in config.AUDIO_TYPES),
                    key=lambda p: p.name.lower())
    return tracks[0] if tracks else None


# имена устройств Windows: файл «con.mp3» открылся бы как консоль
RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))}


def safe_track_name(name: str) -> str | None:
    """Имя для сохраняемой записи: без папок и служебных знаков, с известным расширением."""
    # папки отрезаются вручную: Path на Windows принял бы «a:» за букву диска
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name).strip(" .")
    stem, dot, suffix = name.rpartition(".")
    if not stem or not dot or "." + suffix.lower() not in config.AUDIO_TYPES:
        return None
    if stem.split(".")[0].upper() in RESERVED_NAMES:
        stem = "_" + stem
    return stem[:110] + "." + suffix


def load_cues() -> dict | None:
    """Сохранённые метки или None."""
    path = config.cues_file()
    if not path.exists():
        return None
    try:
        return check_cues(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def check_cues(data: object) -> dict:
    """Проверяет метки; при ошибке — ValueError с объяснением."""
    if not isinstance(data, dict):
        raise ValueError("ожидался объект с метками")
    numbers = {}
    for key in ("duration", "choir", "leave"):
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
            raise ValueError(f"метка «{key}» должна быть числом секунд")
        numbers[key] = round(float(value), 2)
    if not 0 < numbers["choir"] < numbers["leave"] < numbers["duration"] <= 3600:
        raise ValueError("метки должны идти по порядку: начало хора, конец хора, длина записи")
    track = data.get("track")
    if not isinstance(track, str) or not track or len(track) > 200:
        raise ValueError("не названа запись, к которой относятся метки")
    return {"track": track, **numbers}


def save_cues(data: object) -> dict:
    cues = check_cues(data)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.cues_file().write_text(json.dumps(cues, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return cues


def forget_cues() -> None:
    config.cues_file().unlink(missing_ok=True)


def describe() -> dict:
    """Ответ на /api/show: запись, слова, метки."""
    words, problem = load_words()
    track = find_track()
    cues = load_cues()
    return {
        "app": APP_NAME,
        "version": VERSION,
        "track": None if track is None else {
            "name": track.name,
            "url": "/track/" + track.name,
            "size": track.stat().st_size,
        },
        # метки относятся к одной записи: с другой записью они не годятся
        "cues": cues if cues and track is not None and cues["track"] == track.name else None,
        "words": words,
        "problem": problem,
        "music_folder": str(config.music_dir()),
    }
