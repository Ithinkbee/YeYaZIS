"""Записи для тестов распознавания: tests/audio/*.wav и их список index.json.

    python tools/make_test_audio.py

Несколько коротких фраз на обоих языках, озвученных синтезатором Windows.
Записи лежат в репозитории, поэтому тесты распознавания идут и там, где
синтезатора нет; сценарий нужен, только чтобы создать их заново.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sluhach import console, synth  # noqa: E402

console.setup()

TARGET = Path(__file__).resolve().parent.parent / "tests" / "audio"

#: (имя файла, язык, диктор, фраза)
PHRASES = [
    ("de-open", "de", "Hedda", "Öffne den Aufsatz über die Räuber"),
    ("de-read", "de", "Stefan", "Lies vor"),
    ("de-count", "de", "Katja", "Wie viele Wörter hat der Aufsatz"),
    ("de-egg", "de", "Stefan", "Wie viel kostet ein Elefant"),
    ("ru-open", "ru", "Irina", "Открой сочинение про Евгения Онегина"),
    ("ru-next", "ru", "Irina", "Читай дальше"),
    ("ru-find", "ru", "Pavel", "Найди слово дуэль"),
    ("ru-egg", "ru", "Pavel", "Сколько стоит слон"),
]


def main() -> int:
    if not synth.available():
        print("Синтезатор речи Windows недоступен.")
        return 1
    voices = synth.voices()
    index, missing = [], []
    TARGET.mkdir(parents=True, exist_ok=True)
    for name, language, speaker, text in PHRASES:
        voice = next((v for v in voices[language] if v.speaker == speaker), None) or (voices[language] or [None])[0]
        if voice is None:
            missing.append(name)
            continue
        made = synth.synthesize([(text, voice)])
        path = made.get((text, voice.name))
        if path is None:
            missing.append(name)
            continue
        shutil.copyfile(path, TARGET / f"{name}.wav")
        index.append({"file": f"{name}.wav", "language": language, "voice": voice.speaker, "text": text})
        print(f"  {name}.wav  {voice.speaker:7} {text}")
    (TARGET / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if missing:
        print("Не озвучено: " + ", ".join(missing))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
