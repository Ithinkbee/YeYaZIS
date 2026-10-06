"""Список операций, на которые система может реагировать.

Операция — это действие системы и фразы, которыми оно вызывается. Набор
действий задан в программе, а сам список — какие операции включены и на
какие фразы каждая откликается на немецком и на русском — задаёт
пользователь на странице «Операции»; его выбор хранится в operations.json.

Фраза-шаблон — это слова команды и, если операции нужен параметр, его место
в конце: «открой сочинение {target}». Параметр — всё, что сказано после
слов команды: номер, название, искомое слово.
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from sluhach import config
from sluhach.text import tokens

GROUPS: dict[str, str] = {
    "collection": "Сочинения",
    "reading": "Чтение вслух",
    "analysis": "Разбор сочинения",
    "dictation": "Диктовка",
    "system": "Система",
}

_SLOT = re.compile(r"\{(\w+)\}")


@dataclass(frozen=True)
class Operation:
    id: str
    group: str
    title: str                              # название для интерфейса
    description: str                        # как система реагирует
    phrases: dict[str, tuple[str, ...]]     # фразы по умолчанию: язык -> шаблоны
    slot: str = ""                          # имя параметра в шаблонах
    slot_words: int = 3                     # сколько слов может быть в параметре
    slot_hint: tuple[str, str] = ("", "")   # что на его месте говорят: (по-немецки, по-русски)
    example: tuple[str, str] = ("", "")     # пример параметра: (по-немецки, по-русски)
    needs_essay: bool = False               # выполняется только при открытом сочинении
    dictation: bool = False                 # действует только во время диктовки (и только она тогда действует)
    companion: bool = False                 # операция Пафнутия: без него её нет

    def hint(self, language: str) -> str:
        return self.slot_hint[0 if language == "de" else 1]

    def sample(self, language: str) -> str:
        return self.example[0 if language == "de" else 1]


@dataclass(frozen=True)
class Template:
    """Разобранная фраза-шаблон."""

    text: str                    # как задана: «открой сочинение {target}»
    words: tuple[str, ...]       # нормализованные слова команды, без параметра
    slot: bool                   # есть ли в конце параметр

    @property
    def literal(self) -> str:
        return " ".join(self.words)

    def shown(self, filler: str) -> str:
        """Фраза для подсказки: на месте параметра — что нужно сказать."""
        return _SLOT.sub(lambda _: filler, self.text)


def parse_template(text: str, operation: Operation) -> Template:
    """Проверяет фразу, заданную пользователем; при ошибке — ValueError с объяснением."""
    raw = " ".join((text or "").split())
    if not raw:
        raise ValueError("пустая фраза")
    if len(raw) > config.MAX_TEMPLATE_CHARS:
        raise ValueError(f"фраза длиннее {config.MAX_TEMPLATE_CHARS} знаков")
    slots = _SLOT.findall(raw)
    rest = _SLOT.sub(" ", raw)
    if "{" in rest or "}" in rest:
        raise ValueError("фигурные скобки допустимы только вокруг имени параметра")
    words = tuple(tokens(rest))
    if not words:
        raise ValueError("во фразе нет слов команды")
    if operation.slot:
        marker = "{" + operation.slot + "}"
        if slots != [operation.slot] or not raw.endswith(marker):
            raise ValueError(f"фраза должна заканчиваться параметром {marker}")
    elif slots:
        raise ValueError("у этой операции нет параметра — уберите фигурные скобки")
    return Template(raw, words, bool(operation.slot))


def _op(ident: str, group: str, title: str, description: str, de: tuple[str, ...], ru: tuple[str, ...],
        **extra) -> Operation:
    return Operation(ident, group, title, description, {"de": de, "ru": ru}, **extra)


#: операции по умолчанию. Порядок — как на странице «Операции».
DEFAULTS: tuple[Operation, ...] = (
    _op("list", "collection", "Список сочинений",
        "показывает список сочинений на выбранном языке и называет их по номерам",
        ("liste der aufsätze", "zeige die aufsätze", "welche aufsätze gibt es"),
        ("список сочинений", "покажи сочинения", "какие есть сочинения")),
    _op("open", "collection", "Открыть сочинение",
        "открывает сочинение по номеру в списке, по названию, герою или автору",
        ("öffne den aufsatz {target}", "öffne aufsatz {target}", "zeige den aufsatz {target}", "öffne {target}"),
        ("открой сочинение {target}", "покажи сочинение {target}", "открой {target}"),
        # в названии бывает много слов: „den Aufsatz über die Leiden des jungen Werthers“
        slot="target", slot_words=8, slot_hint=("Nummer oder Titel", "номер или название"), example=("zwei", "два")),
    _op("next_essay", "collection", "Следующее сочинение", "открывает следующее сочинение списка",
        ("nächster aufsatz", "der nächste aufsatz"),
        ("следующее сочинение", "другое сочинение"), needs_essay=True),
    _op("prev_essay", "collection", "Предыдущее сочинение", "открывает предыдущее сочинение списка",
        ("vorheriger aufsatz", "der vorherige aufsatz"),
        ("предыдущее сочинение",), needs_essay=True),
    _op("close", "collection", "Закрыть сочинение", "закрывает сочинение и возвращается к списку",
        ("schließe den aufsatz", "aufsatz schließen", "zurück zur liste"),
        ("закрой сочинение", "вернись к списку", "к списку")),

    _op("read", "reading", "Читать абзац", "читает вслух текущий абзац сочинения",
        ("lies vor", "vorlesen", "lies den absatz"),
        ("читай", "прочитай", "читай вслух", "прочитай абзац"), needs_essay=True),
    _op("next", "reading", "Следующий абзац", "переходит к следующему абзацу и читает его",
        ("weiter", "lies weiter", "nächster absatz"),
        ("дальше", "читай дальше", "следующий абзац"), needs_essay=True),
    _op("back", "reading", "Предыдущий абзац", "возвращается к предыдущему абзацу и читает его",
        ("zurück", "vorheriger absatz"),
        ("назад", "предыдущий абзац"), needs_essay=True),
    _op("start", "reading", "В начало", "возвращается к первому абзацу и читает его",
        ("zum anfang", "von vorne", "erster absatz"),
        ("в начало", "с начала", "первый абзац"), needs_essay=True),
    _op("goto", "reading", "Перейти к абзацу", "переходит к абзацу с названным номером и читает его",
        ("gehe zu absatz {number}", "absatz nummer {number}", "absatz {number}"),
        ("перейди к абзацу {number}", "абзац номер {number}", "абзац {number}"),
        slot="number", slot_hint=("Nummer", "номер"), example=("fünf", "пять"), needs_essay=True),

    _op("info", "analysis", "О сочинении", "называет произведение, его автора и объём сочинения",
        ("worum geht es", "was ist das für ein aufsatz", "erzähl über den aufsatz"),
        ("о чём сочинение", "что это за сочинение", "расскажи о сочинении"), needs_essay=True),
    _op("count", "analysis", "Объём сочинения", "считает слова, предложения и абзацы сочинения",
        ("wie viele wörter", "wie viele wörter hat der aufsatz", "wie lang ist der aufsatz"),
        ("сколько слов", "сколько слов в сочинении", "какой объём"), needs_essay=True),
    _op("find", "analysis", "Найти слово",
        "ищет слово во всех его формах, отмечает его в тексте и переходит к ближайшему абзацу",
        ("suche das wort {word}", "finde das wort {word}", "suche {word}"),
        ("найди слово {word}", "найди {word}", "поиск {word}"),
        slot="word", slot_hint=("Wort", "слово"), example=("Liebe", "любовь"), needs_essay=True),
    _op("where", "analysis", "Где я", "называет открытое сочинение и номер текущего абзаца",
        ("wo bin ich", "wo sind wir", "welcher absatz"),
        ("где я", "где мы", "какой абзац")),

    # фразы диктовки подобраны по тому, что распознаватель слышит без ошибок: вместо «сотри»
    # он пишет «смотри» и «со три», вместо „Diktat stopp“ — „Diktat shop“. „Diktat beginnen“ среди
    # них нет: оно на четыре пятых совпадает с „Diktat beenden“
    _op("dictate", "dictation", "Начать диктовку",
        "включает диктовку: каждая следующая фраза не выполняется, а записывается в новое сочинение",
        ("diktat starten", "ich möchte diktieren", "ich diktiere"),
        ("начни диктовку", "начать диктовку", "хочу диктовать", "буду диктовать")),
    _op("dictate_undo", "dictation", "Стереть последнюю фразу",
        "во время диктовки убирает из текста последнюю записанную фразу",
        ("letzten satz löschen", "lösche den letzten satz", "streiche das"),
        ("удали последнюю фразу", "сотри последнюю фразу", "удали фразу"), dictation=True),
    _op("dictate_end", "dictation", "Закончить диктовку",
        "заканчивает диктовку: сохраняет текст как сочинение и открывает его",
        ("diktat beenden", "diktat ende", "ende des diktats"),
        ("конец диктовки", "закончи диктовку", "закончить диктовку", "диктовка окончена"), dictation=True),

    _op("help", "system", "Что ты умеешь", "перечисляет примеры команд",
        ("was kannst du", "hilfe", "welche befehle gibt es"),
        ("что ты умеешь", "помощь", "какие есть команды")),
    _op("language", "system", "Сменить язык", "переключает язык распознавания и ответов",
        ("sprich {language}", "wechsle zu {language}", "sprache {language}"),
        ("говори {language}", "переключи на {language}", "язык {language}"),
        slot="language", slot_hint=("Russisch / Deutsch", "по-немецки / по-русски"),
        example=("russisch", "по-немецки")),
    _op("repeat", "system", "Повторить ответ", "повторяет свой последний ответ",
        ("wiederhole", "noch einmal", "wiederhole die antwort"),
        ("повтори", "ещё раз", "повтори ответ")),
    _op("time", "system", "Который час", "называет текущее время",
        ("wie spät ist es", "wie viel uhr ist es"),
        ("который час", "сколько времени", "сколько сейчас времени")),
    _op("stop", "system", "Замолчать", "обрывает свой ответ на полуслове",
        ("stopp", "halt", "hör auf", "sei still", "ruhe"),
        ("стоп", "хватит", "замолчи", "тихо")),
    _op("sleep", "system", "Не слушать", "выключает микрофон до нажатия кнопки «Слушать»",
        ("hör nicht zu", "mikrofon aus", "schlaf jetzt"),
        ("не слушай", "выключи микрофон", "отбой")),
    _op("game", "system", "Открыть игру", "открывает прогулку с Пафнутием",
        ("öffne das spiel", "ich will spielen", "gehen wir spazieren"),
        ("открой игру", "хочу играть", "пойдём гулять"), companion=True),
)

BY_ID: dict[str, Operation] = {operation.id: operation for operation in DEFAULTS}


@dataclass(frozen=True)
class Entry:
    """Операция вместе с тем, что о ней задал пользователь."""

    operation: Operation
    enabled: bool
    templates: dict[str, tuple[Template, ...]]       # язык -> шаблоны
    customized: bool                                  # фразы отличаются от заданных по умолчанию

    def texts(self, language: str) -> list[str]:
        return [template.text for template in self.templates.get(language, ())]


class OperationSet:
    """Действующий список операций: умолчания и выбор пользователя поверх них."""

    def __init__(self, path: Path | None = None, companion: bool | None = None) -> None:
        self.path = path or config.OPERATIONS_PATH
        self.companion = config.COMPANION_ENABLED if companion is None else companion
        self._lock = threading.RLock()
        self._custom: dict[str, dict] = {}
        self._entries: list[Entry] = []
        self.load()

    # --- чтение и запись --------------------------------------------------------

    def load(self) -> None:
        with self._lock:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                custom = data.get("operations", {}) if isinstance(data, dict) else {}
            except (OSError, ValueError):
                custom = {}
            self._custom = {key: value for key, value in custom.items()
                            if key in BY_ID and isinstance(value, dict)}
            self._rebuild()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"version": 1, "operations": self._custom}, ensure_ascii=False, indent=1)
                             + "\n", encoding="utf-8")
        os.replace(temporary, self.path)

    def _rebuild(self) -> None:
        entries = []
        for operation in DEFAULTS:
            if operation.companion and not self.companion:
                continue
            custom = self._custom.get(operation.id, {})
            templates, customized = {}, False
            for language in config.LANGUAGE_CODES:
                texts = (custom.get("phrases") or {}).get(language)
                parsed = self._parse_all(texts, operation) if isinstance(texts, list) else None
                if parsed is None:
                    parsed = tuple(parse_template(text, operation) for text in operation.phrases[language])
                else:
                    customized = True
                templates[language] = parsed
            entries.append(Entry(operation, bool(custom.get("enabled", True)), templates, customized))
        self._entries = entries

    @staticmethod
    def _parse_all(texts: list, operation: Operation) -> tuple[Template, ...] | None:
        """Шаблоны из файла настроек; испорченная запись заменяется умолчанием."""
        try:
            return tuple(parse_template(str(text), operation) for text in texts)[:config.MAX_TEMPLATES]
        except ValueError:
            return None

    # --- что действует ------------------------------------------------------------

    def entries(self) -> list[Entry]:
        with self._lock:
            return list(self._entries)

    def entry(self, operation_id: str) -> Entry | None:
        return next((entry for entry in self.entries() if entry.operation.id == operation_id), None)

    def active(self, language: str, dictation: bool = False) -> list[tuple[Operation, tuple[Template, ...]]]:
        """Включённые операции и их фразы на языке — то, с чем сравнивается речь.

        Во время диктовки действуют только её собственные операции: остальная
        речь — текст сочинения, даже если она похожа на команду.
        """
        return [(entry.operation, entry.templates.get(language, ()))
                for entry in self.entries()
                if entry.enabled and entry.templates.get(language) and entry.operation.dictation == dictation]

    def cheatsheet(self, language: str) -> list[dict]:
        """Подсказка «что можно сказать» для страницы пульта: включённые операции по порядку."""
        result = []
        for entry in self.entries():
            templates = entry.templates.get(language, ())
            if not entry.enabled or not templates:
                continue
            operation = entry.operation
            filler = "‹" + operation.hint(language) + "›"
            result.append({"id": operation.id, "group": operation.group, "title": operation.title,
                           "needs_essay": operation.needs_essay, "dictation": operation.dictation,
                           "phrases": [template.shown(filler) for template in templates]})
        return result

    def example(self, operation_id: str, language: str) -> str:
        """Первая фраза операции с подставленным примером параметра — для подсказок."""
        entry = self.entry(operation_id)
        if entry is None or not entry.enabled or not entry.templates.get(language):
            return ""
        return entry.templates[language][0].shown(entry.operation.sample(language))

    # --- задание списка -------------------------------------------------------------

    def update(self, changes: dict[str, dict]) -> list[str]:
        """Принимает новый список: {операция: {"enabled": …, "phrases": {язык: [фразы]}}}.

        Возвращает список ошибок; если он не пуст, ничего не сохранено.
        """
        errors: list[str] = []
        custom: dict[str, dict] = {}
        taken: dict[tuple[str, str, bool], str] = {}
        for entry in self.entries():
            operation = entry.operation
            change = changes.get(operation.id) or {}
            enabled = bool(change.get("enabled", entry.enabled))
            record: dict = {}
            if not enabled:
                record["enabled"] = False
            for language in config.LANGUAGE_CODES:
                given = (change.get("phrases") or {}).get(language)
                texts = [" ".join(str(text).split()) for text in given] if given is not None else entry.texts(language)
                texts = [text for text in texts if text]
                where = f"«{operation.title}», {config.language_name(language)}"
                if len(texts) > config.MAX_TEMPLATES:
                    errors.append(f"{where}: не больше {config.MAX_TEMPLATES} фраз")
                    continue
                parsed = []
                for text in texts:
                    try:
                        parsed.append(parse_template(text, operation))
                    except ValueError as problem:
                        errors.append(f"{where}, фраза «{text}»: {problem}")
                for template in parsed:
                    key = (language, template.literal, template.slot)
                    other = taken.get(key)
                    if other and other != operation.title and enabled:
                        errors.append(f"{where}: фраза «{template.text}» уже вызывает операцию «{other}»")
                    elif enabled:
                        taken[key] = operation.title
                if [t.text for t in parsed] != list(operation.phrases[language]):
                    record.setdefault("phrases", {})[language] = [t.text for t in parsed]
            if record:
                custom[operation.id] = record
        if errors:
            return errors
        with self._lock:
            # операции, скрытые вместе с пауком, свои настройки не теряют
            hidden = {key: value for key, value in self._custom.items()
                      if BY_ID[key].companion and not self.companion}
            self._custom = {**hidden, **custom}
            self._save()
            self._rebuild()
        return []

    def reset(self) -> None:
        """Возвращает список операций к заданному по умолчанию."""
        with self._lock:
            self._custom = {}
            self._save()
            self._rebuild()
