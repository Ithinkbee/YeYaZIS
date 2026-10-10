"""Проверка системы синтеза: что и как измеряется.

1. **Нормализация.** Эталонный набор (data/eval/normalization.tsv) — трудные
   места немецкого научного текста с чтением, записанным вручную: числа,
   годы, порядковые, дроби, единицы, даты, диапазоны, сокращения,
   аббревиатуры, формулы, адреса, ссылки, знаки, деление на предложения.
   Мера — доля случаев, прочитанных слово в слово как в эталоне. Для
   сравнения тот же текст без нормализации отдаётся eSpeak NG (он строит
   фонемы для голосов Piper и сам умеет читать числа): насколько его фонемы
   отличаются от фонем эталонного чтения.
2. **Правила произношения.** Собственная транскрипция слов из статей
   сравнивается с транскрипцией eSpeak NG: доля фонем, которые пришлось бы
   исправить (PER), доля слов, совпавших целиком, совпадение ударения.
   eSpeak не эталон, а независимое мнение: расхождения бывают ошибками
   обеих сторон.
3. **Разборчивость.** Предложения из статей синтезируются каждым голосом и
   распознаются Vosk; мера — доля ошибок в словах (WER). То же — на разных
   темпах и для фраз, где есть числа и сокращения, с нормализацией и без неё.
4. **Настройки.** Действительно ли темп ×1,5 укорачивает запись в полтора
   раза, +4 полутона поднимают тон в 2^(4/12) раза, громкость 50 % — на 6 дБ.
5. **Скорость** — отношение времени синтеза к длительности звука (RTF).
6. **Голоса Пафнутия** — насколько эффекты меняют тон и сохраняют слова.
"""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from glashatai import config, dsp, voicefx
from glashatai.articles import Collection
from glashatai.engines import Settings, split_voice
from glashatai.phonetics.g2p import to_espeak, transcribe
from glashatai.text import ReadingOptions, Sentence, TextReader

GOLD_PATH = config.EVAL_DIR / "normalization.tsv"

CATEGORY_NAMES = {
    "zahl": "числа", "jahr": "годы и десятилетия", "ordinal": "порядковые", "dezimal": "дроби и проценты",
    "einheit": "единицы", "datum": "даты и время", "bereich": "диапазоны", "abk": "сокращения",
    "akronym": "аббревиатуры", "formel": "формулы", "adresse": "адреса", "quelle": "ссылки на источники",
    "zeichen": "знаки", "satz": "границы предложений",
}
#: токены, из-за которых предложение не годится для проверки разборчивости:
#: распознаватель не знает ни аббревиатур по буквам, ни английских слов
NOT_FOR_ASR = {"english", "acronym", "mixed", "letter", "formula", "url", "email", "user", "citation", "roman"}


# --- общее ----------------------------------------------------------------------------

def words(text: str) -> list[str]:
    """Слова для сравнения: строчные буквы, без знаков; дефис — граница слова."""
    return re.findall(r"[a-zäöüß0-9]+", text.lower().replace("-", " "))


def edit_distance(a: list, b: list) -> int:
    row = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        previous, row[0] = row[0], i
        for j in range(1, len(b) + 1):
            current = min(row[j] + 1, row[j - 1] + 1, previous + (a[i - 1] != b[j - 1]))
            previous, row[j] = row[j], current
    return row[len(b)]


def wer(reference: str, hypothesis: str) -> tuple[int, int]:
    """(ошибки, слов в эталоне)."""
    ref = words(reference)
    return edit_distance(ref, words(hypothesis)), len(ref)


@dataclass
class GoldCase:
    category: str
    text: str
    expected: str


def load_gold(path: Path | None = None) -> list[GoldCase]:
    cases = []
    for line in (path or GOLD_PATH).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            cases.append(GoldCase(parts[0].strip(), parts[1].strip(), parts[2].strip()))
    return cases


# --- 1. нормализация ----------------------------------------------------------------------

_PHONE_STRIP = re.compile(r"[ˈˌ\s.,;:!?'\"()\[\]-]")


def simplify_phonemes(text: str) -> list[str]:
    """Фонемы eSpeak для сравнения: без ударений и пробелов, «r»-звуки — одним знаком."""
    text = _PHONE_STRIP.sub("", text)
    text = text.replace("ɾ", "r").replace("ɐ", "ɜ").replace("ɑ", "a").replace("ʔ", "")
    return list(text)


def normalization(reader: TextReader, piper=None) -> dict:
    cases = []
    for case in load_gold():
        if case.category == "satz":
            got = len(reader.prepare(case.text).sentences)
            cases.append({"category": case.category, "text": case.text, "expected": case.expected, "got": str(got),
                          "ok": str(got) == case.expected})
            continue
        document = reader.prepare(case.text, limit=None)
        spoken = " ".join(s.render("normalized") for s in document.sentences)
        entry = {"category": case.category, "text": case.text, "expected": case.expected, "got": spoken,
                 "ok": words(spoken) == words(case.expected)}
        if piper is not None:
            gold = simplify_phonemes(piper.phonemes(case.expected))
            raw = simplify_phonemes(piper.phonemes(case.text))
            ours = simplify_phonemes(piper.phonemes(spoken))
            entry["per_raw"] = edit_distance(raw, gold) / max(1, len(gold))
            entry["per_ours"] = edit_distance(ours, gold) / max(1, len(gold))
        cases.append(entry)
    categories = {}
    for name in CATEGORY_NAMES:
        chosen = [c for c in cases if c["category"] == name]
        if not chosen:
            continue
        row = {"name": CATEGORY_NAMES[name], "cases": len(chosen), "accuracy": sum(c["ok"] for c in chosen) / len(chosen)}
        if piper is not None and name != "satz":
            row["per_raw"] = float(np.mean([c["per_raw"] for c in chosen]))
            row["per_ours"] = float(np.mean([c["per_ours"] for c in chosen]))
            row["raw_exact"] = sum(c["per_raw"] == 0 for c in chosen) / len(chosen)
        categories[name] = row
    text_cases = [c for c in cases if c["category"] != "satz"]
    summary = {"cases": len(cases), "accuracy": sum(c["ok"] for c in cases) / len(cases)}
    if piper is not None:
        summary["per_raw"] = float(np.mean([c["per_raw"] for c in text_cases]))
        summary["per_ours"] = float(np.mean([c["per_ours"] for c in text_cases]))
        summary["raw_exact"] = sum(c["per_raw"] == 0 for c in text_cases) / len(text_cases)
        summary["ours_exact"] = sum(c["per_ours"] == 0 for c in text_cases) / len(text_cases)
    return {"summary": summary, "categories": categories,
            "failures": [c for c in cases if not c["ok"]]}


def leftovers(reader: TextReader, collection: Collection) -> dict:
    """Независимая мера на настоящих статьях: что после нормализации осталось не словами.

    Эталонный набор составлялся вместе с системой; эта мера — нет: в пяти
    статьях считаются токены, в произношении которых остались цифры или
    знаки, которые синтезатору пришлось бы читать по своему усмотрению.
    """
    tokens = 0
    left = []
    dropped = []
    changed = 0
    for article in collection:
        for sentence in reader.prepare(article.text).sentences:
            for token in sentence.tokens:
                if token.kind in {"space", "punct", "quote", "pause"}:
                    continue
                tokens += 1
                changed += token.changed
                plain = token.say.replace("'", "")
                if re.search(r"[0-9]|[^\w\s\-.,]", plain):
                    left.append(token.text)
                elif not plain.strip() and token.kind not in {"citation"}:
                    dropped.append(token.text)
    return {"tokens": tokens, "changed": changed, "left": len(left), "examples": sorted(set(left))[:30],
            "dropped": len(dropped), "dropped_examples": sorted(set(dropped))[:30]}


# --- 2. правила произношения против eSpeak NG ------------------------------------------------

def _stress_position(symbols: str) -> int | None:
    """Номер гласной под главным ударением (в обозначениях eSpeak знак стоит перед гласной)."""
    vowels = "aeiouyøœɛɪʊɔʏəɜɐæɑ"
    count = 0
    marked = False
    for ch in symbols:
        if ch == "ˈ":
            marked = True
        elif ch in vowels:
            if marked:
                return count
            count += 1
    return None


def article_words(collection: Collection, reader: TextReader, minimum: int = 2, limit: int = 1500) -> list[str]:
    """Немецкие слова статей: встречаются не реже minimum раз, не из словарей произношения."""
    counts: dict[str, int] = {}
    lexicon = reader.lexicon
    for article in collection:
        for word in re.findall(r"\b[A-Za-zÄÖÜäöüß]{3,}\b", article.text):
            if re.search(r"[A-ZÄÖÜ].*[A-ZÄÖÜ]", word) or lexicon.english_word(word) or lexicon.acronym(word):
                continue
            if word.lower() in {"http", "https", "www", "bzw", "usw", "etc", "vgl", "inkl", "evtl"}:
                continue
            if len(word) > 4 and lexicon.compound_part(word):
                continue
            if any(ch in word for ch in "qxyQXY") and word.lower() not in {"typ", "typen", "system", "systeme"}:
                continue
            counts[word] = counts.get(word, 0) + 1
    chosen = sorted((w for w, n in counts.items() if n >= minimum), key=lambda w: (-counts[w], w))
    return chosen[:limit]


def g2p(collection: Collection, reader: TextReader, piper) -> dict:
    items = []
    for word in article_words(collection, reader):
        ours = to_espeak(transcribe(word))
        theirs = piper.phonemes(word)
        a, b = simplify_phonemes(ours), simplify_phonemes(theirs)
        plain_a = [ch for ch in a if ch != "ː"]
        plain_b = [ch for ch in b if ch != "ː"]
        items.append({"word": word, "ours": ours, "espeak": theirs,
                      "distance": edit_distance(a, b), "length": len(b),
                      "distance_plain": edit_distance(plain_a, plain_b), "length_plain": len(plain_b),
                      "stress": _stress_position(ours) == _stress_position(theirs)})
    total = sum(i["length"] for i in items) or 1
    total_plain = sum(i["length_plain"] for i in items) or 1
    worst = sorted((i for i in items if i["distance"]), key=lambda i: (-i["distance"], i["word"]))[:20]
    return {
        "words": len(items),
        "per": sum(i["distance"] for i in items) / total,
        "per_plain": sum(i["distance_plain"] for i in items) / total_plain,
        "exact": sum(i["distance"] == 0 for i in items) / max(1, len(items)),
        "exact_plain": sum(i["distance_plain"] == 0 for i in items) / max(1, len(items)),
        "stress": sum(i["stress"] for i in items) / max(1, len(items)),
        "examples": worst,
    }


# --- 3. разборчивость --------------------------------------------------------------------------

def _plain(sentence: Sentence) -> bool:
    return not sentence.heading and not any(t.kind in NOT_FOR_ASR for t in sentence.tokens)


def dev_sentences(reader: TextReader, collection: Collection, count: int = 24) -> list[Sentence]:
    """Набор для настройки собственного синтезатора — в проверку не входит."""
    article = collection.get("de-cs-compiler")
    if article is None:
        return []
    found = [s for s in reader.prepare(article.text).sentences if 40 <= len(s.text) <= 140 and _plain(s)]
    random.Random(5).shuffle(found)
    return found[:count]


def test_sentences(reader: TextReader, collection: Collection, per_article: int = 10, seed: int = 8) -> list[Sentence]:
    """Проверочные предложения: по per_article из каждой статьи, без аббревиатур и терминов."""
    tuned = {s.text for s in dev_sentences(reader, collection)}
    chosen = []
    for article in collection:
        found = [s for s in reader.prepare(article.text).sentences
                 if 40 <= len(s.text) <= 160 and _plain(s) and s.text not in tuned]
        random.Random(seed).shuffle(found)
        chosen += found[:per_article]
    return chosen


def evaluation_voices(speaker) -> list[str]:
    """Голоса для проверки: все доступные, у многоголосой модели — спокойная манера."""
    chosen = []
    for voice in speaker.voices():
        if not voice.available or voice.engine == "browser":
            continue
        engine, name, manner = split_voice(voice.id)
        if manner and manner != "neutral":
            continue
        chosen.append(voice.id)
    return chosen


def _synthesize(speaker, sentence: Sentence, settings: Settings, phonetic: bool = True):
    """Синтез без кэша — чтобы честно измерить время."""
    started = time.perf_counter()
    audio = speaker._engine(sentence, settings.voice, settings, phonetic)
    return audio, time.perf_counter() - started


def intelligibility(speaker, recognizer, voices: list[str], sentences: list[Sentence], rate: float = 1.0,
                    progress=None) -> dict:
    result = {}
    for voice in voices:
        errors = total = 0
        synth_time = audio_time = 0.0
        examples = []
        for sentence in sentences:
            audio, spent = _synthesize(speaker, sentence, Settings(voice=voice, rate=rate))
            heard = recognizer.recognize(audio.samples, audio.rate)
            e, n = wer(sentence.render("written"), heard)
            errors += e
            total += n
            synth_time += spent
            audio_time += audio.seconds
            if len(examples) < 4:
                examples.append({"text": sentence.render("written"), "heard": heard, "wer": e / max(1, n)})
            if progress:
                progress()
        result[voice] = {"wer": errors / max(1, total), "words": total, "sentences": len(sentences),
                         "rtf": synth_time / max(1e-9, audio_time), "ms": 1000 * synth_time / max(1, len(sentences)),
                         "examples": examples}
    return result


def tempo(speaker, recognizer, voices: list[str], sentences: list[Sentence], rates: list[float],
          progress=None) -> dict:
    result = {}
    for voice in voices:
        result[voice] = {}
        for rate in rates:
            errors = total = 0
            for sentence in sentences:
                audio, _ = _synthesize(speaker, sentence, Settings(voice=voice, rate=rate))
                e, n = wer(sentence.render("written"), recognizer.recognize(audio.samples, audio.rate))
                errors += e
                total += n
                if progress:
                    progress()
            result[voice][str(rate)] = errors / max(1, total)
    return result


def normalization_by_ear(speaker, recognizer, voice: str, categories: tuple[str, ...] = (
        "zahl", "jahr", "ordinal", "dezimal", "einheit", "datum", "bereich", "abk")) -> dict:
    """Нейросетевой голос читает трудные фразы как есть и после нормализации; кто ближе к эталону."""
    reader = speaker.reader
    rows = {}
    for case in load_gold():
        if case.category not in categories:
            continue
        settings = Settings(voice=voice)
        raw = reader.sentence(case.text, ReadingOptions.raw())
        ours = reader.sentence(case.text, ReadingOptions())
        row = rows.setdefault(case.category, {"raw": [0, 0], "ours": [0, 0]})
        for key, sentence, phonetic in (("raw", raw, False), ("ours", ours, True)):
            audio, _ = _synthesize(speaker, sentence, settings, phonetic)
            e, n = wer(case.expected, recognizer.recognize(audio.samples, audio.rate))
            row[key][0] += e
            row[key][1] += n
    result = {name: {"name": CATEGORY_NAMES[name], "raw": r["raw"][0] / max(1, r["raw"][1]),
                     "ours": r["ours"][0] / max(1, r["ours"][1])} for name, r in rows.items()}
    all_raw = sum(r["raw"][0] for r in rows.values()) / max(1, sum(r["raw"][1] for r in rows.values()))
    all_ours = sum(r["ours"][0] for r in rows.values()) / max(1, sum(r["ours"][1] for r in rows.values()))
    return {"voice": voice, "categories": result, "raw": all_raw, "ours": all_ours}


# --- 4. настройки ---------------------------------------------------------------------------------

def settings_accuracy(speaker, voices: list[str], sentence: Sentence) -> dict:
    result = {}
    for voice in voices:
        base, _ = _synthesize(speaker, sentence, Settings(voice=voice))
        base_samples = dsp.trim(base.samples, base.rate)
        base_length = len(base_samples) / base.rate
        base_f0 = dsp.estimate_f0(base_samples, base.rate)
        tempo_rows = {}
        for rate in (0.5, 0.75, 1.25, 1.5, 2.0):
            audio, _ = _synthesize(speaker, sentence, Settings(voice=voice, rate=rate))
            length = len(dsp.trim(audio.samples, audio.rate)) / audio.rate
            tempo_rows[str(rate)] = base_length / max(1e-6, length)
        pitch_rows = {}
        for semitones in (-6, -3, 3, 6):
            audio, _ = _synthesize(speaker, sentence, Settings(voice=voice, pitch=semitones))
            f0 = dsp.estimate_f0(dsp.trim(audio.samples, audio.rate), audio.rate)
            pitch_rows[str(semitones)] = 12 * np.log2(f0 / base_f0) if f0 and base_f0 else None
        result[voice] = {"tempo": tempo_rows, "pitch": pitch_rows, "f0": base_f0}
    # громкость одинакова для всех голосов: множитель после приведения к общему уровню
    reference = dsp.normalize(base_samples, base.rate, config.TARGET_LEVEL_DB)
    level = dsp.speech_level(reference, base.rate)
    volume = {str(p): dsp.speech_level(dsp.apply_volume(reference, p), base.rate) - level for p in (25, 50, 75)}
    return {"voices": result, "volume": volume}


# --- 6. голоса Пафнутия -------------------------------------------------------------------------

def effects(speaker, recognizer, voice: str, sentences: list[Sentence]) -> dict:
    result = {}
    recordings = []
    for sentence in sentences:
        audio, _ = _synthesize(speaker, sentence, Settings(voice=voice))
        recordings.append((sentence, dsp.resample(audio.samples, audio.rate, 16000)))
    for effect in ("none", *voicefx.EFFECTS):
        errors = total = 0
        shifts = []
        for sentence, samples in recordings:
            processed = samples if effect == "none" else voicefx.apply(samples, 16000, effect)
            e, n = wer(sentence.render("written"), recognizer.recognize(processed, 16000))
            errors += e
            total += n
            before, after = dsp.estimate_f0(samples, 16000), dsp.estimate_f0(processed, 16000)
            # у шёпота основного тона нет — сдвиг не измеряется
            if before and after and effect != "whisper":
                shifts.append(12 * np.log2(after / before))
        result[effect] = {"wer": errors / max(1, total), "shift": float(np.median(shifts)) if shifts else None,
                          "name": voicefx.EFFECTS.get(effect, "без эффекта")}
    return result
