"""Просодия: сколько длится каждый звук и как меняется высота голоса.

Собственному синтезатору мало знать фонемы — ему нужна «партитура»:
длительность каждого звука и мелодия фразы. Здесь она строится правилами,
как в классических синтезаторах (правила длительностей Клатта, модель
интонации с понижением к концу фразы и акцентами на ударных слогах).

Длительность. У каждой фонемы есть собственная длительность; ударный слог
длиннее безударного, последний слог перед паузой растягивается (фразовое
удлинение), согласные в скоплении сокращаются. Темп делит всё на одно число.

Мелодия. Основной тон плавно снижается от начала фразы к концу
(деклинация). На ударном слоге каждого знаменательного слова — подъём
(акцент); служебные слова акцента не получают. В конце утверждения тон
падает, в конце вопроса — поднимается, перед запятой — чуть приподнят:
слушатель понимает, что фраза не кончилась.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from glashatai.phonetics.g2p import DIPHTHONGS, LONG_VOWELS, VOWELS, Pronunciation, transcribe

#: служебные слова — без акцента
FUNCTION_WORDS = set("""
der die das den dem des ein eine einen einem einer eines und oder aber in im an am auf aus bei mit nach von vom
zu zum zur für über unter um ab bis durch ohne gegen ist sind war wird werden wurde wurden hat haben kann können
es er sie wir ich man sich nicht auch noch doch nur so wie als da dass ob weil wenn dann denn sehr mehr hier
dies diese dieser dieses diesem diesen welche welcher welches kein keine sein seine ihr ihre zwar etwa jedoch
sowie bzw also zwischen während wegen vor
""".split())

#: собственные длительности фонем, мс, при обычном темпе
DURATIONS = {
    "p": 95, "t": 90, "k": 95, "b": 70, "d": 65, "ɡ": 70, "ʔ": 35,
    "f": 95, "v": 65, "s": 100, "z": 75, "ʃ": 105, "ʒ": 80, "ç": 95, "x": 95, "h": 60, "j": 55,
    "m": 70, "n": 65, "ŋ": 75, "l": 65, "ʁ": 60, "ɐ̯": 55,
    "ts": 125, "pf": 125, "tʃ": 130, "dʒ": 115,
}
VOWEL_DURATIONS = {"long": 135, "short": 80, "schwa": 50, "diphthong": 165, "ɐ": 70}

#: паузы внутри предложения по знакам, мс
PAUSES = {",": 170, ";": 260, ":": 240, "-": 120}


@dataclass
class Phone:
    """Звук в партитуре: фонема, длительность и мелодия."""
    symbol: str                 # фонема или «_» — пауза
    duration: float             # мс
    stress: int = 0             # ударение слога
    word: int = -1              # номер слова
    f0: list[tuple[float, float]] = field(default_factory=list)   # (доля длительности 0…1, множитель тона)
    final: bool = False         # последний слог фразы

    @property
    def is_vowel(self) -> bool:
        return self.symbol in VOWELS


@dataclass
class Score:
    phones: list[Phone]
    kind: str = "statement"

    @property
    def duration(self) -> float:
        return sum(phone.duration for phone in self.phones)


_WORD = re.compile(r"[A-Za-zÄÖÜäöüßÀ-ÿ'][A-Za-zÄÖÜäöüßÀ-ÿ'-]*|[,;:.!?]")


def _vowel_duration(symbol: str, stress: int) -> float:
    if symbol == "ə":
        base = VOWEL_DURATIONS["schwa"]
    elif symbol == "ɐ":
        base = VOWEL_DURATIONS["ɐ"]
    elif symbol in DIPHTHONGS:
        base = VOWEL_DURATIONS["diphthong"]
    elif symbol in LONG_VOWELS:
        base = VOWEL_DURATIONS["long"]
    else:
        base = VOWEL_DURATIONS["short"]
    if stress == 1:
        return base * 1.15
    if stress == 2:
        return base
    return base * 0.75


def score(text: str, kind: str = "statement", rate: float = 1.0, intonation: float = 1.0,
          seed: int = 0) -> Score:
    """Партитура предложения: звуки с длительностями и мелодией.

    text — произношение («Mä'schien 'Lörning ist …»), kind — statement,
    question или exclamation, rate — темп, intonation — размах мелодии (0 —
    монотонно, 1 — обычно, 2 — очень выразительно).
    """
    rng = random.Random(seed)
    items = _WORD.findall(text)
    words: list[tuple[str, Pronunciation | None]] = []
    for item in items:
        if item in PAUSES or item in ".!?":
            words.append((item, None))
        else:
            words.append((item, transcribe(item)))

    phones: list[Phone] = [Phone("_", 60)]
    # фразы между паузами: в каждой своя деклинация и свой ядерный акцент
    phrases: list[list[int]] = [[]]
    for index, (word, pron) in enumerate(words):
        if pron is None:
            if word in PAUSES:
                phrases.append([])
            continue
        phrases[-1].append(index)

    accent_words = set()
    nuclear = set()
    for phrase in phrases:
        content = [i for i in phrase if words[i][0].lower().replace("'", "") not in FUNCTION_WORDS]
        if not content and phrase:
            content = [phrase[-1]]
        accent_words.update(content)
        if content:
            nuclear.add(content[-1])

    for index, (word, pron) in enumerate(words):
        if pron is None:
            if word in PAUSES:
                phones.append(Phone("_", PAUSES[word], word=index))
            continue
        syllables = pron.syllables
        for s_index, syllable in enumerate(syllables):
            last_syllable = s_index == len(syllables) - 1
            phrase_final = last_syllable and _before_pause(words, index)
            nucleus_seen = False
            for p_index, symbol in enumerate(syllable.phonemes):
                if symbol in VOWELS:
                    duration = _vowel_duration(symbol, syllable.stress)
                    nucleus_seen = True
                else:
                    duration = DURATIONS.get(symbol, 70)
                    cluster = (p_index > 0 and syllable.phonemes[p_index - 1] not in VOWELS) or \
                        (p_index + 1 < len(syllable.phonemes) and syllable.phonemes[p_index + 1] not in VOWELS)
                    if cluster:
                        duration *= 0.8
                    if syllable.stress == 1:
                        duration *= 1.08
                    if symbol in {"p", "t", "k"} and not nucleus_seen and syllable.stress == 0:
                        duration *= 0.85           # безударный взрывной без сильного придыхания
                if phrase_final and (symbol in VOWELS or nucleus_seen):
                    duration *= 1.4
                phones.append(Phone(symbol, duration, syllable.stress, index, final=phrase_final))
        # граница слова: короткая щель, чтобы слова не сливались в одно
        phones.append(Phone("_", 12, word=index))
    phones.append(Phone("_", 80))

    for phone in phones:
        phone.duration = phone.duration / max(0.3, rate)

    _melody(phones, words, accent_words, nuclear, kind, intonation, rng)
    return Score(phones, kind)


def _before_pause(words: list[tuple[str, Pronunciation | None]], index: int) -> bool:
    for word, pron in words[index + 1:]:
        if pron is None:
            return True
        return False
    return True


def _melody(phones: list[Phone], words, accent_words: set[int], nuclear: set[int], kind: str,
            intonation: float, rng: random.Random) -> None:
    """Мелодия: множители основного тона в начале, середине и конце каждого звука."""
    total = sum(phone.duration for phone in phones) or 1.0
    elapsed = 0.0
    # где кончается каждая фраза — для конечного падения или подъёма
    last_vowel_of_phrase: dict[int, str] = {}
    for position, phone in enumerate(phones):
        if phone.is_vowel and phone.final:
            following = next((p for p in phones[position + 1:] if p.symbol == "_" and p.duration > 30), None)
            boundary = "end"
            if following is not None and following.word >= 0:
                boundary = words[following.word][0]
            last_vowel_of_phrase[position] = boundary
    accented_done: set[int] = set()
    for position, phone in enumerate(phones):
        progress = elapsed / total
        # деклинация: от 1,12 до 0,92 за предложение
        base = 1.12 - 0.20 * progress
        points = [(0.0, base), (1.0, base - 0.20 * phone.duration / total)]
        if phone.is_vowel and phone.stress == 1 and phone.word in accent_words and phone.word not in accented_done:
            accented_done.add(phone.word)
            height = 0.20 if phone.word in nuclear else 0.13
            height *= intonation * (0.85 + 0.3 * rng.random())
            points = [(0.0, base + height * 0.3), (0.45, base + height), (1.0, base + height * 0.55)]
        if position in last_vowel_of_phrase:
            boundary = last_vowel_of_phrase[position]
            if boundary in {"end", ".", "!"} and kind != "question":
                drop = 0.22 * intonation
                points = [(0.0, points[0][1]), (0.5, base - drop * 0.5), (1.0, base - drop)]
            elif kind == "question" and boundary in {"end", "?", "."}:
                rise = 0.45 * intonation
                points = [(0.0, base - 0.05), (0.6, base + rise * 0.6), (1.0, base + rise)]
            else:
                # продолжение фразы: лёгкий подъём перед запятой
                rise = 0.10 * intonation
                points = [(0.0, base), (1.0, base + rise)]
        if kind == "exclamation" and phone.is_vowel:
            points = [(t, 1 + (v - 1) * 1.3 + 0.05) for t, v in points]
        phone.f0 = points
        elapsed += phone.duration
