"""Тир Пафнутия: план волн из слов переведённого текста.

Каждое разное слово текста — один противник. Слово несёт свой немецкий
перевод — тот, что получился в переводе текста (с падежом и числом), а если
слово перевод потеряло — словарный. Противники разные:

* **мелочь** — служебные слова (артикли, предлоги, союзы, местоимения): мелкие
  и быстрые, бегут стайкой;
* **обычное слово** — существительные, прилагательные, наречия, имена: идут
  на Пафнутия и кусают;
* **слово с пушкой** — глаголы, слова действия: держатся на расстоянии и
  стреляют буквами;
* **мини-босс** в конце каждой волны — длинное слово из верхушки списка самых
  длинных слов текста. Если волн N, то первую волну закрывает N-е по длине
  слово, вторую — (N−1)-е, …, последнюю — самое длинное.

Число волн задаётся перед игрой, а противники распределяются так, чтобы
волны росли (вторая больше первой и так далее) и за все волны вышли все слова
текста — тогда победа означает, что переведён весь документ. Внутри волн
слова идут от простых к сложным: в начале короткие служебные, к концу —
длинные и глаголы.

Правила боя (скорость, урон, оружие) — в web/static/shooter.js; здесь — только
состав волн, чтобы его можно было проверить тестами.
"""

from __future__ import annotations

import random
import re
from collections import Counter
from dataclasses import asdict, dataclass, field

from dragoman import config
from dragoman.german import morphology as gm
from dragoman.lexicon.db import clean
from dragoman.translate.lexical import NAME, NUMBER, UNKNOWN
from dragoman.translate.pipeline import Translation

FUNCTION_POS = {"DET", "ADP", "CCONJ", "SCONJ", "PRON", "PART", "AUX", "NUM"}
GUNNER_POS = {"VERB"}

#: признаки противников: прочность, скорость (м/с), урон
KINDS = {
    "swarm": {"name": "мелочь", "note": "служебное слово: маленькое и быстрое"},
    "walker": {"name": "слово", "note": "идёт на Пафнутия и кусает"},
    "gunner": {"name": "слово с пушкой", "note": "глагол: стреляет буквами издалека"},
    "boss": {"name": "мини-босс", "note": "длинное слово текста: много попаданий"},
}


@dataclass
class Enemy:
    id: int
    en: str
    de: str
    pos: str
    kind: str
    count: int                 # сколько раз слово встречается в тексте
    length: int
    hp: int = 1
    translated: bool = True    # есть ли перевод (у имён и чисел он совпадает с исходным)


@dataclass
class Wave:
    number: int
    enemies: list[Enemy] = field(default_factory=list)
    boss: Enemy | None = None

    @property
    def size(self) -> int:
        return len(self.enemies) + (1 if self.boss else 0)


@dataclass
class Plan:
    waves: list[Wave]
    words: int
    tokens: int
    seed: int
    bosses: list[str]

    def to_dict(self) -> dict:
        return {
            "waves": [{"number": w.number, "enemies": [asdict(e) for e in w.enemies],
                       "boss": asdict(w.boss) if w.boss else None, "size": w.size} for w in self.waves],
            "words": self.words,
            "tokens": self.tokens,
            "seed": self.seed,
            "bosses": self.bosses,
        }


def wave_sizes(total: int, waves: int) -> list[int]:
    """Размеры волн, растущие как 1 : 2 : … : N, в сумме — total; каждая не меньше предыдущей."""
    if waves <= 0:
        return []
    weights = list(range(1, waves + 1))
    raw = [total * w / sum(weights) for w in weights]
    sizes = [int(x) for x in raw]
    # остаток — волнам с наибольшей дробной частью, начиная с последних
    rest = total - sum(sizes)
    order = sorted(range(waves), key=lambda k: (raw[k] - sizes[k], k), reverse=True)
    for k in order[:rest]:
        sizes[k] += 1
    # рост по волнам: каждая не меньше предыдущей
    return sorted(sizes)


def collect_words(t: Translation) -> list[dict]:
    """Разные слова текста с переводом, частью речи и числом вхождений."""
    words: dict[str, dict] = {}
    for s_index, sentence in enumerate(t.analysis.sentences):
        status = t.statuses[s_index]
        for w in sentence.words:
            if not w.counts:
                continue
            key = w.text.lower()
            item = words.get(key)
            if item is None:
                item = {"en": key, "pos": Counter(), "count": 0, "german": Counter(), "shared": Counter(),
                        "status": Counter(), "forms": Counter(), "tags": Counter()}
                words[key] = item
            item["forms"][w.text] += 1
            item["tags"][w.tag] += 1
            item["count"] += 1
            item["pos"][w.upos] += 1
            item["status"][status.get(w.index, UNKNOWN)] += 1
            tokens = [g for g in t.sentences[s_index].tokens if w.index in g.src and g.kind != "punct"]
            # слово, слившееся с соседями в композит или оборот («machine code» → «Maschinencode»),
            # получает в игре свой словарный перевод, а не перевод всего оборота
            own = [g.text for g in tokens if len(set(g.src)) == 1]
            if own:
                item["german"][" ".join(dict.fromkeys(own))] += 1
            elif tokens:
                item["shared"][" ".join(dict.fromkeys(g.text for g in tokens))] += 1
    entries = {form.lower(): list_item.entry for list_item in t.words for form in list_item.forms
               if list_item.entry is not None}
    result = []
    for key, item in words.items():
        pos = item["pos"].most_common(1)[0][0]
        status = item["status"].most_common(1)[0][0]
        # «Tragedy» в названии и «tragedy» в тексте — одно слово; с прописной — только имя
        item["display"] = item["forms"].most_common(1)[0][0] if pos == "PROPN" else key
        german = item["german"].most_common(1)[0][0] if item["german"] else ""
        if not german:
            german = t.word_translation(key, dictionary_first=True)
        if not german and item["shared"]:
            german = item["shared"].most_common(1)[0][0]
        german = base_form(german, pos, entries.get(key), item["tags"].most_common(1)[0][0])
        translated = status not in {UNKNOWN} and bool(german)
        if status in {NAME, NUMBER}:
            german = item["display"]           # имена не переводятся (и не склоняются: «Shakespeares»)
        result.append({"en": item["display"], "de": german or item["display"], "pos": pos, "count": item["count"],
                       "translated": translated})
    return result


def base_form(german: str, pos: str, entry, tag: str) -> str:
    """Форма для надписи над словом: в тексте слово стоит в падеже («mit den Widersprüchen»), а над
    противником — существительное в именительном падеже того же числа, прилагательное — в словарной
    форме. Глаголы и служебные слова остаются как в переводе («führt ein», «dem»)."""
    if entry is None or not german or " " in clean(entry.de):
        return german
    if pos == "NOUN" and entry.pos == "NOUN" and entry.gender in {"m", "f", "n", "pl"}:
        number = "pl" if tag in {"NNS", "NNPS"} else "sg"
        nominative = gm.noun_form(clean(entry.de), entry.gender, entry.plural_form or None, number, "N",
                                  "weak" in entry.props)
        # слово, слившееся в переводе в сложное слово с соседями, сохраняет свою словарную форму
        return nominative if german.lower().endswith(nominative.lower()[:4]) or len(german.split()) == 1 else german
    if pos == "ADJ" and entry.pos == "ADJ" and not clean(entry.de).endswith("-"):
        base = clean(entry.de)
        if tag == "JJR":
            return gm.comparative(base)                                      # größer
        if tag == "JJS":
            return gm.adjective_form(base, "sup", None, "n", "sg", "N")     # am größten
        return base
    return german


def kind_of(word: dict) -> str:
    if word["pos"] in GUNNER_POS:
        return "gunner"
    if word["pos"] in FUNCTION_POS and len(word["en"]) <= 4:
        return "swarm"
    return "walker"


def plan(t: Translation, waves: int = config.SHOOTER_WAVES, seed: int = 7) -> Plan:
    """План игры: N волн растущего размера, в конце каждой — мини-босс."""
    low, high = config.SHOOTER_WAVES_RANGE
    words = collect_words(t)
    waves = max(low, min(high, waves, max(1, len(words) // 3)))
    rng = random.Random(seed)

    # мини-боссы: самые длинные слова, при равной длине — более частые, затем по алфавиту
    def letters(word: dict) -> int:
        return len(re.sub(r"[^A-Za-zÀ-ÿ]", "", word["en"]))

    by_length = sorted(words, key=lambda w: (-letters(w), -w["count"], w["en"]))
    bosses = by_length[:waves]
    boss_keys = {b["en"] for b in bosses}
    rest = [w for w in words if w["en"] not in boss_keys]

    # от простого к сложному: длина слова, глаголы чуть «тяжелее», немного случайности
    def difficulty(word: dict) -> float:
        bonus = 3 if kind_of(word) == "gunner" else (-2 if kind_of(word) == "swarm" else 0)
        return letters(word) + bonus + rng.random() * 4

    rest.sort(key=difficulty)
    sizes = wave_sizes(len(rest), waves)
    result: list[Wave] = []
    next_id = 1
    position = 0
    for number, size in enumerate(sizes, start=1):
        wave = Wave(number)
        chunk = rest[position: position + size]
        position += size
        rng.shuffle(chunk)
        for word in chunk:
            wave.enemies.append(Enemy(next_id, word["en"], word["de"], word["pos"], kind_of(word), word["count"],
                                      letters(word), 1, word["translated"]))
            next_id += 1
        boss_word = bosses[waves - number]          # 1-я волна — N-е по длине слово, последняя — самое длинное
        hp = max(6, letters(boss_word)) + 2 * (number - 1)
        wave.boss = Enemy(next_id, boss_word["en"], boss_word["de"], boss_word["pos"], "boss", boss_word["count"],
                          letters(boss_word), hp, boss_word["translated"])
        next_id += 1
        result.append(wave)
    return Plan(result, len(words), sum(w["count"] for w in words), seed,
                [b["en"] for b in reversed(bosses)])


def document_tokens(t: Translation) -> list[list[dict]]:
    """Текст документа для панели в игре: абзацы из слов; переведённое слово меняется на немецкое."""
    paragraphs: list[list[dict]] = []
    current = None
    for s_index, sentence in enumerate(t.analysis.sentences):
        if current is None or sentence.paragraph != current:
            paragraphs.append([])
            current = sentence.paragraph
        for w in sentence.words:
            item = {"t": w.text, "s": 1 if w.space_after else 0}
            if w.counts:
                item["k"] = w.text.lower()
            paragraphs[-1].append(item)
        if paragraphs[-1]:
            paragraphs[-1][-1]["s"] = 1
    return paragraphs
