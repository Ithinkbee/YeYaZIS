"""Проверка системы на озвученных фразах: точность распознавания и реакции.

Проверочный набор составлен из трёх видов фраз:

* команды — все фразы всех операций на обоих языках, с подставленными
  параметрами (номера и названия сочинений, номера абзацев, слова); фразы,
  управляющие диктовкой, проверяются во время диктовки;
* предложения из сочинений по литературе — речь предметной области, на
  которую система должна не выполнить операцию, а просто повторить;
* ключевые фразы-пасхалки.

Каждую фразу произносит синтезатор несколькими голосами (см. synth.py),
запись дополняется тишиной и шумом и проходит тот же путь, что звук с
микрофона: детектор речи -> потоковое распознавание -> сопоставление с
операциями. Считаются:

* WER — доля ошибок в словах: (замены + пропуски + вставки) / слова эталона;
* доля фраз, распознанных дословно;
* доля верных реакций — когда реакция на распознанную фразу та же, что на
  эталонный текст: та же операция с тем же итогом (то же сочинение, абзац,
  язык, найденное слово). Это главная мера: команда может распознаться с
  ошибкой в букве и всё равно выполниться верно;
* доля замеченных фраз — детектор речи открыл фразу, и в ней нашлись слова;
* ложные срабатывания — предложение из сочинения вызвало операцию;
* время распознавания по отношению к длительности звука.
"""

from __future__ import annotations

import json
import random
import time
import zlib
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from sluhach import audio, config
from sluhach.eggs import EggStore
from sluhach.essays import Collection, sentences
from sluhach.listener import Listener
from sluhach.operations import BY_ID, DEFAULTS, OperationSet, parse_template
from sluhach.reactions import Draft, Reaction, Reactor, Session
from sluhach.text import normalize, word_errors

#: условия проверки: без шума и с белым шумом при заданном отношении сигнал/шум, дБ
CONDITIONS: tuple[tuple[str, float | None], ...] = (("clean", None), ("snr20", 20.0), ("snr10", 10.0), ("snr5", 5.0))
CONDITION_NAMES = {"clean": "без шума", "snr20": "шум, 20 дБ", "snr10": "шум, 10 дБ", "snr5": "шум, 5 дБ"}
KIND_NAMES = {"command": "команды", "sentence": "предложения из сочинений", "egg": "фразы-пасхалки"}

#: тишина до и после фразы в записи, мс: детектору нужно услышать и начало, и паузу в конце
PAD_BEFORE_MS = 500
PAD_AFTER_MS = 1100
#: в «чистой» записи вместо цифрового нуля — едва слышный шум, как у настоящего микрофона
CLEAN_SNR_DB = 55.0

#: какими словами заполняются параметры команд: (по-немецки, по-русски)
NUMBER_WORDS = (("eins", "zwei", "drei", "vier", "fünf"), ("один", "два", "три", "четыре", "пять"))
PARAGRAPH_WORDS = (("drei", "sieben", "zwölf"), ("три", "семь", "двенадцать"))
ABOUT = ("über", "про")
LANGUAGE_WORDS = {"de": ("russisch", "deutsch"), "ru": ("по-немецки", "по-русски")}
#: у этих шаблонов параметр звучит иначе: «говори по-русски», но «переключи на русский»
TEMPLATE_WORDS = {("ru", "language", 1): ("русский",), ("ru", "language", 2): ("немецкий",)}
#: слова для операции «найти слово» берутся из самих сочинений: самые частые длинные
FIND_WORDS = 3

#: черновик, с которым проверяются операции диктовки: две фразы, вторую можно стереть
DRAFT_PHRASES = {"de": ("Erster Satz.", "Zweiter Satz."), "ru": ("Первая фраза.", "Вторая фраза.")}

#: предложения предметной области: только слова и запятые, чтобы эталон читался однозначно
SENTENCE_WORDS = (6, 14)
SENTENCE_CHARS = 120


@dataclass(frozen=True)
class TestPhrase:
    id: str
    language: str
    kind: str               # command | sentence | egg
    text: str
    operation: str = ""     # для команд — операция, которую фраза должна вызвать
    essay: str = ""         # сочинение, из которого взято предложение


def _fill(template_text: str, value: str) -> str:
    return template_text[:template_text.index("{")].strip() + " " + value


def _frequent_words(collection: Collection, language: str, count: int) -> list[str]:
    """Самые частые длинные слова сочинений языка — их ищет операция «найти слово»."""
    seen: dict[str, int] = defaultdict(int)
    shown: dict[str, str] = {}
    for essay in collection.by_language(language):
        for paragraph in essay.paragraphs:
            for word in paragraph.text.split():
                clean = word.strip(".,;:!?«»„“\"()—–-")
                key = normalize(clean)
                if len(key) >= 6 and clean.isalpha():
                    seen[key] += 1
                    shown.setdefault(key, clean)
    ranked = sorted(seen, key=lambda key: (-seen[key], key))
    return [shown[key] for key in ranked[:count]]


def command_phrases(collection: Collection) -> list[TestPhrase]:
    """Все фразы всех операций на обоих языках с подставленными параметрами."""
    phrases: list[TestPhrase] = []
    for position, language in enumerate(("de", "ru")):
        essays = collection.by_language(language)
        fillers = {
            # сочинение называют и номером, и словом из названия: «про онегин», „über werther“
            "open": list(NUMBER_WORDS[position][:len(essays)])
                    + [f"{ABOUT[position]} {essay.aliases[1 if len(essay.aliases) > 1 else 0]}" for essay in essays],
            "goto": list(PARAGRAPH_WORDS[position]),
            "find": _frequent_words(collection, language, FIND_WORDS),
            "language": list(LANGUAGE_WORDS[language]),
        }
        for operation in DEFAULTS:
            for number, text in enumerate(operation.phrases[language]):
                template = parse_template(text, operation)
                if not template.slot:
                    phrases.append(TestPhrase(f"{language}-{operation.id}-{number}", language, "command", text,
                                              operation.id))
                    continue
                values = fillers[operation.id]
                # у каждого шаблона — своя часть значений, чтобы набор не разрастался
                picked = TEMPLATE_WORDS.get((language, operation.id, number)) or (
                    values if number == 0 else values[number::len(operation.phrases[language])] or values[:1])
                for index, value in enumerate(picked):
                    phrases.append(TestPhrase(f"{language}-{operation.id}-{number}-{index}", language, "command",
                                              _fill(text, value), operation.id))
    return phrases


def sentence_phrases(collection: Collection, per_language: int = 40, seed: int = 7) -> list[TestPhrase]:
    """Предложения из сочинений: поровну из каждого, только из слов и запятых."""
    phrases: list[TestPhrase] = []
    rng = random.Random(seed)
    for language in config.LANGUAGE_CODES:
        essays = collection.by_language(language)
        if not essays:
            continue
        quota = max(1, per_language // len(essays))
        for essay in essays:
            fit = []
            for paragraph in essay.paragraphs:
                for sentence in sentences(paragraph.text, language):
                    body = sentence.rstrip(".!?")
                    words = body.replace(",", " ").split()
                    plain = all(word.isalpha() for word in words)
                    if plain and SENTENCE_WORDS[0] <= len(words) <= SENTENCE_WORDS[1] and len(body) <= SENTENCE_CHARS:
                        fit.append(sentence)
            rng.shuffle(fit)
            for index, sentence in enumerate(fit[:quota]):
                phrases.append(TestPhrase(f"{essay.id}-s{index}", language, "sentence", sentence, essay=essay.id))
    return phrases


def egg_phrases(eggs: EggStore) -> list[TestPhrase]:
    return [TestPhrase(f"egg-{egg.id}", egg.language, "egg", egg.key) for egg in eggs.all()
            if egg.language in config.LANGUAGE_CODES]


def default_reactor(collection: Collection) -> Reactor:
    """Система с операциями и пасхалками по умолчанию.

    Проверка не должна зависеть от того, что пользователь переименовал или
    выключил: файлов настроек по этому пути нет, поэтому действуют умолчания.
    """
    nowhere = Path(config.STATE_DIR) / ".evaluation-defaults"
    return Reactor(collection, OperationSet(nowhere / "operations.json", companion=True),
                   EggStore(nowhere / "eggs.json"))


def build_phrases(collection: Collection, per_language: int = 40) -> list[TestPhrase]:
    eggs = default_reactor(collection).eggs
    return command_phrases(collection) + sentence_phrases(collection, per_language) + egg_phrases(eggs)


# --- реакция как мера ----------------------------------------------------------------

def dictating(phrase: TestPhrase) -> bool:
    """Фраза управляет диктовкой: действует и проверяется только во время неё."""
    return phrase.kind == "command" and BY_ID[phrase.operation].dictation


def start_session(collection: Collection, language: str, dictation: bool = False) -> Session:
    """Состояние, в котором выполнима любая операция: открыто сочинение, абзац не первый.

    Для операций диктовки в состоянии есть ещё черновик из двух фраз.
    """
    essays = collection.by_language(language)
    session = Session(language=language, last_reply="-", last_language=language)
    if essays:
        session.essay, session.paragraph = essays[0].id, min(5, len(essays[0].paragraphs) - 1)
    if dictation:
        first, second = DRAFT_PHRASES[language]
        session.draft = Draft(text=f"{first} {second}", undo=[[len(first), ""]])
    return session


def signature(reaction: Reaction) -> tuple:
    """Суть реакции без формулировок: вид, операция и то, чем она закончилась."""
    marks = tuple(sorted(form for effect in reaction.effects if effect.get("type") == "highlight"
                         for form in effect.get("forms", [])))
    draft = reaction.session.get("draft")
    return (reaction.kind, reaction.operation, reaction.session.get("essay"), reaction.session.get("paragraph"),
            reaction.session.get("language"), marks, draft["text"] if draft else None)


def reaction_signature(reactor: Reactor, collection: Collection, text: str, language: str,
                       dictation: bool = False) -> tuple:
    return signature(reactor.react(text, start_session(collection, language, dictation)))


# --- прогон ---------------------------------------------------------------------------

@dataclass
class Trial:
    """Одна запись в одном условии."""

    phrase: TestPhrase
    voice: str
    condition: str
    heard: str = ""
    detected: bool = False
    pieces: int = 0                 # на сколько фраз детектор разбил запись
    errors: int = 0
    words: int = 0
    exact: bool = False
    reaction_ok: bool = False
    false_alarm: bool = False       # предложение вызвало операцию
    operation: str = ""             # операция, которую вызвала распознанная фраза
    confidence: float = 0.0
    audio_ms: float = 0.0
    recognition_ms: float = 0.0


@dataclass
class Tally:
    """Сумма по группе испытаний."""

    trials: int = 0
    words: int = 0
    errors: int = 0
    exact: int = 0
    reaction_ok: int = 0
    detected: int = 0
    split: int = 0
    false_alarms: int = 0
    confidence: float = 0.0
    audio_ms: float = 0.0
    recognition_ms: float = 0.0

    def add(self, trial: Trial) -> None:
        self.trials += 1
        self.words += trial.words
        self.errors += trial.errors
        self.exact += trial.exact
        self.reaction_ok += trial.reaction_ok
        self.detected += trial.detected
        self.split += trial.pieces > 1
        self.false_alarms += trial.false_alarm
        self.confidence += trial.confidence
        self.audio_ms += trial.audio_ms
        self.recognition_ms += trial.recognition_ms

    def to_dict(self) -> dict:
        n = max(1, self.trials)
        return {
            "trials": self.trials,
            "wer": self.errors / self.words if self.words else None,
            "exact": self.exact / n,
            "reaction": self.reaction_ok / n,
            "detected": self.detected / n,
            "split": self.split / n,
            "false_alarm": self.false_alarms / n,
            "confidence": self.confidence / max(1, self.detected),
            "rtf": self.recognition_ms / self.audio_ms if self.audio_ms else None,
            "recognition_ms": self.recognition_ms / n,
        }


def run_trial(engine, reactor: Reactor, collection: Collection, phrase: TestPhrase, voice: str, path: Path,
              condition: str, snr: float | None, expected: tuple) -> Trial:
    """Запись проходит путь звука с микрофона: детектор, распознавание, реакция."""
    samples = audio.pad(audio.read_wav(path), PAD_BEFORE_MS, PAD_AFTER_MS)
    # шум у каждой записи свой, но всегда один и тот же — проверка воспроизводима
    rng = np.random.default_rng(zlib.crc32(f"{phrase.id}|{voice}|{condition}".encode("utf-8")))
    samples = audio.add_noise(samples, CLEAN_SNR_DB if snr is None else snr, rng)

    listener = Listener(engine, phrase.language)
    pcm = samples.astype("<i2").tobytes()
    finals = []
    step = 2 * config.SAMPLE_RATE // 10                    # куски по 100 мс, как от браузера
    for offset in range(0, len(pcm), step):
        finals.extend(event for event in listener.feed(pcm[offset:offset + step]) if event["type"] == "final")
    heard = " ".join(event["text"] for event in finals if event["text"])

    trial = Trial(phrase, voice, condition, heard=heard, detected=bool(heard), pieces=len(finals))
    errors = word_errors(phrase.text, heard)
    trial.errors, trial.words = errors.errors, errors.reference
    trial.exact = normalize(heard) == normalize(phrase.text)
    trial.audio_ms = sum(event["duration_ms"] for event in finals)
    trial.recognition_ms = sum(event["recognition_ms"] for event in finals)
    if finals and heard:
        trial.confidence = sum(event["confidence"] for event in finals) / len(finals)
    got = reaction_signature(reactor, collection, heard, phrase.language, dictating(phrase)) if heard \
        else ("silence",)
    # у команды, кроме совпадения с эталоном, проверяется сама операция: иначе фраза,
    # которую система не понимает и в эталонном виде, сошла бы за верно выполненную
    trial.reaction_ok = got == expected and (phrase.kind != "command" or got[1] == phrase.operation)
    trial.false_alarm = phrase.kind == "sentence" and bool(heard) and got[0] == "operation"
    trial.operation = got[1] if len(got) > 1 else ""
    return trial


@dataclass
class Result:
    created: str = ""
    elapsed_ms: float = 0.0
    phrases: dict = field(default_factory=dict)             # сколько фраз каждого вида на язык
    voices: dict = field(default_factory=dict)              # голоса по языкам
    recordings: int = 0
    trials: int = 0
    models: dict = field(default_factory=dict)
    groups: dict = field(default_factory=dict)              # язык -> вид -> условие -> показатели
    by_voice: dict = field(default_factory=dict)            # язык -> голос -> условие -> показатели (команды)
    by_operation: dict = field(default_factory=dict)        # язык -> операция -> условие -> показатели
    mistakes: list = field(default_factory=list)            # примеры ошибок на командах
    false_alarms: list = field(default_factory=list)        # предложения, вызвавшие операцию

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def run(engine, collection: Collection, phrases: list[TestPhrase], recordings: dict[tuple[str, str], Path],
        voices: dict[str, list], conditions=CONDITIONS, workers: int = 4, progress=None) -> Result:
    """Прогоняет все записи во всех условиях и сводит показатели."""
    started = time.perf_counter()
    reactor = default_reactor(collection)
    expected = {phrase.id: reaction_signature(reactor, collection, phrase.text, phrase.language, dictating(phrase))
                for phrase in phrases}
    for language in {phrase.language for phrase in phrases}:
        engine.load(language)

    jobs = []
    for phrase in phrases:
        for voice in voices.get(phrase.language, []):
            path = recordings.get((phrase.text, voice.name))
            if path is None:
                continue
            for name, snr in conditions:
                jobs.append((phrase, voice.speaker, path, name, snr))

    def work(job) -> Trial:
        phrase, voice, path, name, snr = job
        return run_trial(engine, reactor, collection, phrase, voice, path, name, snr, expected[phrase.id])

    trials: list[Trial] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for index, trial in enumerate(pool.map(work, jobs), start=1):
            trials.append(trial)
            if progress and index % 50 == 0:
                progress(index, len(jobs))

    groups: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(Tally)))
    by_voice: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(Tally)))
    by_operation: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(Tally)))
    mistakes: dict[tuple, dict] = {}
    alarms: dict[tuple, dict] = {}
    for trial in trials:
        phrase = trial.phrase
        for language in (phrase.language, "all"):
            groups[language][phrase.kind][trial.condition].add(trial)
        if trial.false_alarm:
            item = alarms.setdefault((phrase.id, trial.heard), {
                "language": phrase.language, "said": phrase.text, "heard": trial.heard,
                "operation": trial.operation, "cases": []})
            item["cases"].append(f"{trial.voice}, {CONDITION_NAMES[trial.condition]}")
        if phrase.kind == "command":
            by_voice[phrase.language][trial.voice][trial.condition].add(trial)
            by_operation[phrase.language][phrase.operation][trial.condition].add(trial)
            if trial.condition == "clean" and not trial.exact:
                key = (phrase.language, phrase.text, trial.heard)
                item = mistakes.setdefault(key, {"language": phrase.language, "operation": phrase.operation,
                                                 "said": phrase.text, "heard": trial.heard, "voices": [],
                                                 "reaction_ok": trial.reaction_ok})
                item["voices"].append(trial.voice)

    def plain(tree):
        if isinstance(tree, Tally):
            return tree.to_dict()
        return {key: plain(value) for key, value in tree.items()}

    counts: dict = defaultdict(lambda: defaultdict(int))
    for phrase in phrases:
        counts[phrase.language][phrase.kind] += 1
    return Result(
        created=datetime.now().strftime("%d.%m.%Y %H:%M"),
        elapsed_ms=(time.perf_counter() - started) * 1000,
        phrases={language: dict(kinds) for language, kinds in counts.items()},
        voices={language: [{"name": voice.name, "speaker": voice.speaker, "gender": voice.gender_ru}
                           for voice in items] for language, items in voices.items()},
        recordings=len({(job[0].id, job[1]) for job in jobs}),
        trials=len(trials),
        models=dict(engine.models),
        groups=plain(groups),
        by_voice=plain(by_voice),
        by_operation=plain(by_operation),
        mistakes=sorted(mistakes.values(), key=lambda item: (item["reaction_ok"], item["language"], item["said"])),
        false_alarms=sorted(alarms.values(), key=lambda item: (item["language"], item["said"])),
    )


def load(path: Path) -> dict | None:
    """Сохранённые результаты проверки или None, если её ещё не запускали."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("groups") else None
