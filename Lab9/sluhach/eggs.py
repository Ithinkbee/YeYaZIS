"""Фразы-пасхалки: ключевая фраза и ответ на неё.

Фразу, которая не вызывает ни одной операции, система повторяет вслух. Но
если это одна из ключевых фраз, вместо повторения звучит заготовленный
ответ: на «Сколько стоит слон?» — «Вам тут не рынок и не цирк». Пары
«фраза — ответ» вписывает администратор в окне, которого у обычного
пользователя нет (см. admin.py); здесь они хранятся и сравниваются с
услышанным.

Сравнение то же, что у операций, — по сходству букв: распознаватель не
ставит вопросительных знаков и может ошибиться в букве, а фраза всё равно
должна сработать. Порог выше, чем у команд: ключевая фраза должна прозвучать
целиком.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from sluhach import config
from sluhach.matcher import clean
from sluhach.text import normalize, script_language, similarity

#: пасхалки, с которыми система начинает работу, пока администратор не задал свои
DEFAULT_EGGS: tuple[tuple[str, str], ...] = (
    ("Сколько стоит слон?", "Вам тут не рынок и не цирк."),
    ("Wie viel kostet ein Elefant?", "Hier ist weder ein Markt noch ein Zirkus."),
)
#: ключевая фраза короче этого срабатывала бы на любой звук
MIN_KEY_LETTERS = 3


class EggError(ValueError):
    """Фразу нельзя сохранить; текст ошибки показывается администратору."""


@dataclass(frozen=True)
class Egg:
    id: str
    key: str            # ключевая фраза, как её вписал администратор
    answer: str         # фраза-ответ
    created: str = ""

    @property
    def language(self) -> str:
        """Язык, на котором фразу нужно произнести, — по алфавиту ключа."""
        return script_language(self.key)

    @property
    def answer_language(self) -> str:
        """Каким голосом читать ответ — по алфавиту ответа."""
        return script_language(self.answer, default=self.language)

    def to_dict(self) -> dict:
        return {**asdict(self), "language": self.language, "answer_language": self.answer_language}


class EggStore:
    """Хранилище пасхалок в eggs.json."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config.EGGS_PATH
        self._lock = threading.RLock()
        self._eggs: list[Egg] = []
        self.load()

    def load(self) -> None:
        with self._lock:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                items = data["eggs"]
            except (OSError, ValueError, KeyError, TypeError):
                # файла ещё нет — действуют пасхалки по умолчанию
                self._eggs = [Egg(f"default{i}", key, answer) for i, (key, answer) in enumerate(DEFAULT_EGGS, 1)]
                return
            self._eggs = [Egg(str(item["id"]), str(item["key"]), str(item["answer"]), str(item.get("created", "")))
                          for item in items if isinstance(item, dict) and item.get("key") and item.get("answer")]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        payload = {"version": 1, "eggs": [asdict(egg) for egg in self._eggs]}
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)

    def all(self) -> list[Egg]:
        with self._lock:
            return list(self._eggs)

    def get(self, egg_id: str) -> Egg | None:
        return next((egg for egg in self.all() if egg.id == egg_id), None)

    # --- правка (только администратор) --------------------------------------------

    def _check(self, key: str, answer: str, except_id: str = "") -> tuple[str, str]:
        key, answer = " ".join((key or "").split()), " ".join((answer or "").split())
        letters = normalize(key).replace(" ", "")
        if len(letters) < MIN_KEY_LETTERS:
            raise EggError(f"ключевая фраза слишком короткая: нужно хотя бы {MIN_KEY_LETTERS} буквы")
        if len(key) > config.MAX_EGG_KEY_CHARS:
            raise EggError(f"ключевая фраза длиннее {config.MAX_EGG_KEY_CHARS} знаков")
        if not answer:
            raise EggError("нет фразы-ответа")
        if len(answer) > config.MAX_EGG_ANSWER_CHARS:
            raise EggError(f"фраза-ответ длиннее {config.MAX_EGG_ANSWER_CHARS} знаков")
        same = next((egg for egg in self._eggs if egg.id != except_id and normalize(egg.key) == normalize(key)), None)
        if same:
            raise EggError(f"такая ключевая фраза уже есть: «{same.key}»")
        return key, answer

    def add(self, key: str, answer: str) -> Egg:
        with self._lock:
            if len(self._eggs) >= config.MAX_EGGS:
                raise EggError(f"пасхалок уже {config.MAX_EGGS} — больше нельзя")
            key, answer = self._check(key, answer)
            egg = Egg(secrets.token_hex(4), key, answer, datetime.now().strftime("%Y-%m-%d %H:%M"))
            self._eggs.append(egg)
            self._save()
            return egg

    def update(self, egg_id: str, key: str, answer: str) -> Egg:
        with self._lock:
            old = self.get(egg_id)
            if old is None:
                raise EggError("такой пасхалки нет")
            key, answer = self._check(key, answer, except_id=egg_id)
            egg = Egg(egg_id, key, answer, old.created)
            self._eggs = [egg if item.id == egg_id else item for item in self._eggs]
            self._save()
            return egg

    def remove(self, egg_id: str) -> bool:
        with self._lock:
            kept = [egg for egg in self._eggs if egg.id != egg_id]
            if len(kept) == len(self._eggs):
                return False
            self._eggs = kept
            self._save()
            return True

    # --- сравнение с услышанным -----------------------------------------------------

    def match(self, text: str, language: str = "") -> tuple[Egg, float] | None:
        """Пасхалка, ключевая фраза которой прозвучала, и сходство с ней.

        Фраза сравнивается и целиком, и без обращения: «Пафнутий, сколько
        стоит слон?» — та же ключевая фраза.
        """
        heard = normalize(text)
        if not heard:
            return None
        variants = {heard}
        for code in ([language] if language else config.LANGUAGE_CODES):
            variants.add(" ".join(clean(text, code)))
        best: tuple[Egg, float] | None = None
        for egg in self.all():
            key = normalize(egg.key)
            score = max(similarity(variant, key) for variant in variants if variant)
            if score >= config.EGG_THRESHOLD and (best is None or score > best[1]):
                best = (egg, score)
        return best
