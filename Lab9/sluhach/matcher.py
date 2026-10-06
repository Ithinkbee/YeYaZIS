"""Сопоставление распознанной фразы с операциями.

Распознаватель ошибается: вместо «lies vor» слышит «ließ vor», вместо
«сочинение» — «сочинении», склеивает «wie viele» в «wieviele». Поэтому фраза
сравнивается с шаблонами не на равенство, а по сходству: доле букв, которые
не пришлось бы править (расстояние Левенштейна). Операция выбрана, если
сходство с одним из её шаблонов не ниже порога.

У шаблона с параметром («открой сочинение {target}») сравнивается только
начало фразы — столько слов, сколько в команде; остальное — параметр. Из-за
склеек и разрывов число слов в начале может отличаться на одно, поэтому
пробуются три варианта границы.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from sluhach import config
from sluhach.operations import Operation, OperationSet, Template
from sluhach.text import normalize, similarity

_RAW = re.compile(r"[^\W_]+")

#: обращения и слова вежливости, которые команду не меняют. Фраза сверяется с
#: шаблонами и без них, и с ними: шаблон и сам может содержать такое слово
FILLERS: dict[str, frozenset[str]] = {
    "ru": frozenset({"пафнутий", "пожалуйста", "ну", "ка", "давай", "мне", "нам"}),
    "de": frozenset({"pafnuti", "pafnutij", "bitte", "mal", "doch", "hey", "hallo"}),
}
#: сколько слов в начале фразы можно пропустить: «так, открой…», „also öffne…“
MAX_SKIP = 2
#: каждое пропущенное слово снижает сходство: точная команда должна побеждать
SKIP_PENALTY = 0.04
#: очень короткая команда («halt», «стоп») должна прозвучать точно: одна
#: ошибка в четырёх буквах — уже другое слово
SHORT_LITERAL = 5
SHORT_THRESHOLD = 0.8


@dataclass(frozen=True)
class Match:
    operation: Operation
    template: Template
    score: float                 # сходство фразы с шаблоном, 0…1
    slot: tuple[str, ...]        # слова параметра, нормализованные
    raw: tuple[str, ...] = ()    # они же, как услышаны
    skipped: int = 0             # сколько слов пропущено в начале

    @property
    def accepted(self) -> bool:
        return self.score >= threshold(self.template)


def threshold(template: Template) -> float:
    if len(template.literal) <= SHORT_LITERAL:
        return max(config.MATCH_THRESHOLD, SHORT_THRESHOLD)
    return config.MATCH_THRESHOLD


def split(text: str, language: str, fillers: bool = False) -> tuple[list[str], list[str]]:
    """Слова фразы: нормализованные и как сказаны.

    Сравнение идёт по нормализованным словам („raeuber“), а в ответе параметр
    показывается так, как его услышали („räuber“). Обращения и слова
    вежливости отбрасываются, если не указано fillers.
    """
    skip = frozenset() if fillers else FILLERS.get(language, frozenset())
    words, raws = [], []
    for raw in _RAW.findall((text or "").lower()):
        word = normalize(raw)
        if word and " " not in word and word not in skip:
            words.append(word)
            raws.append(raw)
    return words, raws


def clean(text: str, language: str) -> list[str]:
    """Нормализованные слова фразы без обращений и слов вежливости."""
    return split(text, language)[0]


def _score(words: Sequence[str], template: Template, slot_words: int) -> tuple[float, int]:
    """Сходство слов с шаблоном и число слов, занятых командой (остальные — параметр).

    Параметр не бывает пустым и не бывает длиннее, чем положено операции: без
    этого предела любое длинное предложение, начавшееся похоже на команду
    („Er spricht davon, …“ — „sprich …“), сошло бы за команду с параметром.
    """
    if not template.slot:
        return similarity(" ".join(words), template.literal), len(words)
    best, taken = 0.0, len(words)
    size = len(template.words)
    for head in (size - 1, size, size + 1):
        if head < 1 or head >= len(words) or len(words) - head > slot_words:
            continue
        score = similarity(" ".join(words[:head]), template.literal)
        if score > best:
            best, taken = score, head
    return best, taken


def candidates(text: str, language: str, operations: OperationSet, dictation: bool = False) -> list[Match]:
    """Лучшее совпадение для каждой операции, от самого похожего.

    `dictation` — идёт диктовка: фраза сверяется только с её операциями.
    """
    variants = [split(text, language)]
    whole = split(text, language, fillers=True)
    if whole != variants[0]:
        variants.append(whole)            # «не слушай»: слово вежливости здесь — часть команды
    result: list[Match] = []
    for operation, templates in operations.active(language, dictation):
        best: Match | None = None
        for words, raws in variants:
            for template in templates:
                for skipped in range(min(MAX_SKIP, len(words) - 1) + 1):
                    score, taken = _score(words[skipped:], template, operation.slot_words)
                    score -= SKIP_PENALTY * skipped
                    start = skipped + taken
                    found = Match(operation, template, score, tuple(words[start:]), tuple(raws[start:]), skipped)
                    if best is None or _key(found) > _key(best):
                        best = found
        if best is not None:
            result.append(best)
    result.sort(key=_key, reverse=True)
    return result


def _key(match: Match) -> tuple[float, int]:
    # при равном сходстве побеждает шаблон с большим числом слов команды:
    # «найди слово {word}» точнее, чем «найди {word}»
    return round(match.score, 6), len(match.template.words)


def match(text: str, language: str, operations: OperationSet, dictation: bool = False,
          nearest: list[Match] | None = None) -> Match | None:
    """Операция, которую вызывает фраза, или None, если ни одна не подошла.

    `nearest` — уже найденные кандидаты этого режима, если они есть.

    Команды диктовки и остальные действуют в разное время, а звучат похоже:
    «закончи диктовку» и «начни диктовку» совпадают на три четверти. Поэтому
    фраза, которая ближе к команде другого режима, командой этого не
    считается: «закончи диктовку», сказанное не во время диктовки, её не
    начинает, а «начни диктовку» во время неё — не заканчивает.
    """
    if nearest is None:
        nearest = candidates(text, language, operations, dictation)
    found = next((item for item in nearest if item.accepted), None)
    if found is None:
        return None
    rivals = candidates(text, language, operations, not dictation)
    if rivals and rivals[0].score > found.score:
        return None
    return found
