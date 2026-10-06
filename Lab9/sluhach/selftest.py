"""Проверка своим голосом: человек читает фразы вслух, система считает ошибки.

Проверка на озвученных фразах (evaluation.py) повторима, но живой голос,
микрофон и комната в ней не участвуют. Здесь фразы из того же набора —
команды и предложения из сочинений — читает сам пользователь, и для его
голоса считаются те же показатели: WER, доля фраз, распознанных дословно, и
доля верных реакций на команды. Рядом показываются числа синтезатора.

Сервер ничего не запоминает: страница получает фразы, сама слушает микрофон
(тем же путём, что пульт) и присылает распознанное на оценку.
"""

from __future__ import annotations

import random
from collections import defaultdict

from sluhach import config, evaluation as ev
from sluhach.essays import Collection
from sluhach.operations import BY_ID
from sluhach.reactions import Reactor
from sluhach.text import align, normalize, word_errors

#: сколько в наборе команд и сколько предложений из сочинений
COMMANDS = 6
SENTENCES = 4
#: предложение длиннее этого трудно прочесть на одном дыхании, а пауза разрывает фразу
SENTENCE_WORDS = 10
#: пауза, которая заканчивает прочитанную фразу, мс: дольше, чем на пульте, — читают с листа медленнее
PAUSE_MS = 1200

#: чем система отвечает на фразу, если это не операция
_KINDS = {"echo": "фраза повторена", "egg": "особый ответ", "dictation": "фраза записана в текст",
          "noise": "нет реакции", "silence": "нет реакции"}


def table(collection: Collection) -> dict[str, ev.TestPhrase]:
    """Все фразы, из которых составляются наборы: команды и короткие предложения."""
    phrases = ev.command_phrases(collection) + [
        phrase for phrase in ev.sentence_phrases(collection) if len(phrase.text.split()) <= SENTENCE_WORDS]
    return {phrase.id: phrase for phrase in phrases}


def pick(phrases: dict[str, ev.TestPhrase], language: str, seed: int | None = None) -> list[ev.TestPhrase]:
    """Набор для чтения вслух: команды разных операций, за ними предложения из сочинений."""
    rng = random.Random(seed)
    by_operation: dict[str, list[ev.TestPhrase]] = defaultdict(list)
    sentences = []
    for phrase in phrases.values():
        if phrase.language != language:
            continue
        if phrase.kind == "command":
            by_operation[phrase.operation].append(phrase)
        else:
            sentences.append(phrase)
    # по одной фразе на операцию: иначе набор состоял бы из одних «открой сочинение …»
    operations = rng.sample(sorted(by_operation), k=min(COMMANDS, len(by_operation)))
    order = {operation: index for index, operation in enumerate(BY_ID)}
    picked = [rng.choice(by_operation[operation]) for operation in sorted(operations, key=order.get)]
    return picked + rng.sample(sentences, k=min(SENTENCES, len(sentences)))


def describe(phrase: ev.TestPhrase) -> dict:
    return {"id": phrase.id, "text": phrase.text, "kind": phrase.kind, "operation": phrase.operation,
            "title": BY_ID[phrase.operation].title if phrase.operation else ""}


def _did(signature: tuple) -> str:
    """Что система сделала бы в ответ на фразу — словами."""
    if signature[0] == "operation":
        return "операция «" + BY_ID[signature[1]].title + "»"
    return _KINDS.get(signature[0], signature[0])


def judge(reactor: Reactor, collection: Collection, phrase: ev.TestPhrase, heard: str) -> dict:
    """Сравнивает распознанное с эталоном: ошибки по словам и реакция системы."""
    heard = " ".join((heard or "").split())[:config.MAX_DICTATED_PHRASE_CHARS]
    errors = word_errors(phrase.text, heard)
    dictation = ev.dictating(phrase)
    got = ev.reaction_signature(reactor, collection, heard, phrase.language, dictation) if normalize(heard) \
        else ("silence",)
    if phrase.kind == "command":
        expected = ev.reaction_signature(reactor, collection, phrase.text, phrase.language, dictation)
        # как и в проверке на озвученных фразах: та же операция с тем же итогом
        reaction_ok = got == expected and got[1] == phrase.operation
    else:
        # предложение из сочинения — не команда: операции оно вызывать не должно
        reaction_ok = got[0] != "operation"
    return {
        **describe(phrase), "heard": heard, "words": errors.reference, "errors": errors.errors,
        "substitutions": errors.substitutions, "deletions": errors.deletions, "insertions": errors.insertions,
        "exact": normalize(heard) == normalize(phrase.text), "reaction_ok": reaction_ok, "did": _did(got),
        "alignment": [{"op": item.op, "said": item.said, "heard": item.heard} for item in align(phrase.text, heard)],
    }


def score(reactor: Reactor, collection: Collection, phrases: dict[str, ev.TestPhrase], items: list[dict],
          synthetic: dict | None = None) -> dict:
    """Оценка набора: по фразам и в сумме. `items` — [{id, heard}]; незнакомые фразы пропускаются."""
    judged = []
    language = ""
    for item in items[:COMMANDS + SENTENCES + 10]:
        phrase = phrases.get(str(item.get("id") or "")) if isinstance(item, dict) else None
        if phrase is None:
            continue
        language = language or phrase.language
        judged.append(judge(reactor, collection, phrase, str(item.get("heard") or "")))

    def total(kind: str | None) -> dict:
        mine = [entry for entry in judged if kind is None or entry["kind"] == kind]
        words = sum(entry["words"] for entry in mine)
        return {"phrases": len(mine), "words": words, "errors": sum(entry["errors"] for entry in mine),
                "wer": sum(entry["errors"] for entry in mine) / words if words else None,
                "exact": sum(entry["exact"] for entry in mine),
                "reaction_ok": sum(entry["reaction_ok"] for entry in mine)}

    return {"language": language, "items": judged,
            "totals": {"all": total(None), "command": total("command"), "sentence": total("sentence")},
            "synthetic": reference(synthetic, language)}


def reference(evaluation: dict | None, language: str) -> dict | None:
    """Те же показатели на озвученных фразах без шума — с чем сравнить свой результат."""
    groups = ((evaluation or {}).get("groups") or {}).get(language) or {}
    command = (groups.get("command") or {}).get("clean")
    sentence = (groups.get("sentence") or {}).get("clean")
    if not command or not sentence:
        return None
    return {"command": {"wer": command["wer"], "exact": command["exact"], "reaction": command["reaction"]},
            "sentence": {"wer": sentence["wer"], "exact": sentence["exact"],
                         "reaction": 1 - sentence["false_alarm"]}}
