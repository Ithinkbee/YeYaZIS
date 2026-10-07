"""Перевод незнакомого слова по правилам словообразования.

Научная лексика английского и немецкого во многом общая: она пришла из
латыни и греческого и различается окончаниями и написанием. Поэтому многие
слова, которых нет в словаре, переводятся правилами:

    optimization → Optimierung        -ization → -ierung (f)
    modularity   → Modularität        -ity → -ität (f)
    formalism    → Formalismus        -ism → -ismus (m)
    algorithmic  → algorithmisch      -ic → -isch
    interactive  → interaktiv         -ive → -iv
    virtualize   → virtualisieren     -ize → -isieren
    calculate    → kalkulieren        -ate → -ieren, c → k
    configurable → konfigurierbar     основа глагола из словаря + -bar
    dataflow     → Datenfluss         сложное слово из двух слов словаря
    non-linear   → nichtlinear        приставки non-, un-, re-, self-, multi-

Догадка получает оценку уверенности. Перевод по правилу помечается в тексте,
а в разделе «Словарь» его можно одним щелчком утвердить и сохранить в базе
данных — так словарь пополняется автоматически.
"""

from __future__ import annotations

import re

from dragoman.lexicon.db import Entry, Lexicon, clean

#: окончания существительных: английское -> (немецкое, род, окончание мн. ч., уверенность)
NOUN_SUFFIXES = [
    ("isations", "isierung", "f", "en", 0.9), ("izations", "isierung", "f", "en", 0.9),
    ("isation", "isierung", "f", "en", 0.9), ("ization", "isierung", "f", "en", 0.9),
    ("ification", "ifizierung", "f", "en", 0.85),
    ("ation", "ation", "f", "en", 0.7), ("ition", "ition", "f", "en", 0.75), ("ction", "ktion", "f", "en", 0.75),
    ("ssion", "ssion", "f", "en", 0.75), ("sion", "sion", "f", "en", 0.7), ("tion", "tion", "f", "en", 0.65),
    ("ility", "ilität", "f", "en", 0.85), ("ality", "alität", "f", "en", 0.85), ("ivity", "ivität", "f", "en", 0.85),
    ("arity", "arität", "f", "en", 0.85), ("icity", "izität", "f", "en", 0.85), ("ity", "ität", "f", "en", 0.7),
    ("ism", "ismus", "m", "ismen", 0.85), ("ist", "ist", "m", "isten", 0.6),
    ("ology", "ologie", "f", "n", 0.9), ("graphy", "grafie", "f", "n", 0.85), ("sophy", "sophie", "f", "n", 0.85),
    ("nomy", "nomie", "f", "n", 0.8), ("metry", "metrie", "f", "n", 0.8), ("logy", "logie", "f", "n", 0.85),
    ("ics", "ik", "f", "", 0.75), ("ure", "ur", "f", "en", 0.55), ("ance", "anz", "f", "en", 0.6),
    ("ence", "enz", "f", "en", 0.6), ("ment", "ment", "n", "e", 0.45), ("um", "um", "n", "", 0.45),
]
ADJ_SUFFIXES = [
    ("ical", "isch", 0.85), ("ic", "isch", 0.8), ("ual", "uell", 0.8), ("ial", "iell", 0.7), ("ive", "iv", 0.85),
    ("al", "al", 0.6), ("ary", "är", 0.6), ("ant", "ant", 0.6), ("ent", "ent", 0.6), ("ous", "ös", 0.4),
    ("ible", "ibel", 0.5), ("able", "abel", 0.45), ("ar", "ar", 0.5), ("id", "id", 0.5),
]
VERB_SUFFIXES = [
    ("ize", "isieren", 0.85), ("ise", "isieren", 0.8), ("ify", "ifizieren", 0.85), ("ate", "ieren", 0.65),
]
#: приставки существительных и прилагательных -> немецкая приставка
PREFIXES = [
    ("non-", "nicht", "ADJ"), ("non", "nicht", "ADJ"), ("un", "un", "ADJ"), ("self-", "Selbst", "NOUN"),
    ("multi-", "Multi", "NOUN"), ("multi", "Multi", "NOUN"), ("meta", "Meta", "NOUN"),
    ("micro", "Mikro", "NOUN"), ("sub", "Teil", "NOUN"), ("super", "Super", "NOUN"), ("pre-", "Vor", "NOUN"),
    ("inter", "Inter", "NOUN"), ("hyper", "Hyper", "NOUN"), ("cyber", "Cyber", "NOUN"),
]


def germanize(stem: str, final_c: str = "k") -> str:
    """Написание латинской основы по-немецки: c перед e, i, y → z, иначе → k (accumulate → akkumul-).

    final_c — чем стать «c» в конце основы: communicate → kommuniz-ieren, но algorithmic → algorithm-isch.
    """
    tail = ""
    if stem.endswith("c"):
        stem, tail = stem[:-1], final_c
    s = re.sub(r"c(?=[eiy])", "z", stem)
    s = s.replace("ck", "k").replace("c", "k")
    return s + tail


def capitalize(word: str) -> str:
    return word[:1].upper() + word[1:]


def _plural(noun: str, ending: str) -> str:
    if not ending:
        return "-"
    if ending == "ismen":
        return noun[:-2] + "en"
    if ending == "isten":
        return noun + "en"
    if ending == "n":
        return noun + "n"
    return noun + ending


def guess(word: str, pos: str, lexicon: Lexicon, domain: str | None = None) -> Entry | None:
    """Догадка о переводе по правилам; None — правила не подходят."""
    lower = word.lower()
    if len(lower) < 3:
        return None
    if pos in {"NOUN", "PROPN"}:
        return _noun(lower, lexicon, domain)
    if pos == "ADJ":
        return _adjective(lower, lexicon, domain)
    if pos == "VERB":
        return _verb(lower, lexicon, domain)
    if pos == "ADV":
        return _adverb(lower, lexicon, domain)
    return None


def _entry(en: str, pos: str, de: str, confidence: float, gender: str = "", plural: str = "",
           note: str = "") -> Entry:
    entry = Entry(en, pos, de, gender, plural, source="rule", note=note)
    entry.confidence = confidence
    return entry


def _noun(lower: str, lexicon: Lexicon, domain: str | None) -> Entry | None:
    if "-" in lower[1:-1]:
        return _hyphenated(lower, "NOUN", lexicon, domain)
    for suffix, german, gender, plural, confidence in NOUN_SUFFIXES:
        if lower.endswith(suffix) and len(lower) > len(suffix) + 2:
            stem = germanize(lower[: -len(suffix)])
            noun = capitalize(stem + german)
            return _entry(lower, "NOUN", noun, confidence, gender, _plural(noun, plural),
                          f"-{suffix} → -{german}")
    # -ness: прилагательное из словаря + -heit/-keit
    if lower.endswith("ness") and len(lower) > 6:
        base = lower[:-4]
        base = base[:-1] + "y" if base.endswith("i") else base
        adjective = lexicon.best(base, "ADJ", domain)
        if adjective:
            stem = clean(adjective.de)
            suffix = "keit" if stem.endswith(("ig", "lich", "bar", "sam", "los")) else "heit"
            if stem.endswith("iv"):
                suffix = "ität"
            noun = capitalize(stem + suffix)
            return _entry(lower, "NOUN", noun, 0.6, "f", noun + "en", f"{base} + -ness → -{suffix}")
    compound = _compound(lower, lexicon, domain)
    if compound:
        return compound
    for prefix, german, kind in PREFIXES:
        if kind == "NOUN" and lower.startswith(prefix) and len(lower) > len(prefix) + 3:
            rest = lower[len(prefix):].lstrip("-")
            base = lexicon.best(rest, "NOUN", domain) or _noun_suffix_only(rest)
            if base:
                noun = german + clean(base.de).lower()
                return _entry(lower, "NOUN", noun, 0.6, base.gender, "", f"{prefix}… → {german}…")
    return None


def _noun_suffix_only(lower: str) -> Entry | None:
    for suffix, german, gender, plural, confidence in NOUN_SUFFIXES:
        if lower.endswith(suffix) and len(lower) > len(suffix) + 2:
            noun = capitalize(germanize(lower[: -len(suffix)]) + german)
            return _entry(lower, "NOUN", noun, confidence, gender, _plural(noun, plural))
    return None


def _compound(lower: str, lexicon: Lexicon, domain: str | None) -> Entry | None:
    """Слитное английское сложное слово из двух слов словаря: dataflow → Datenfluss."""
    from dragoman.german.morphology import compound, compound_part

    for cut in range(3, len(lower) - 2):
        left, right = lower[:cut], lower[cut:]
        head = lexicon.best(right, "NOUN", domain, strict=True)
        if not head or " " in clean(head.de):
            continue
        modifier = lexicon.best(left, "NOUN", domain, strict=True)
        if not modifier or " " in clean(modifier.de):
            continue
        part = compound_part(clean(modifier.de), modifier.gender, modifier.props.get("cf", ""))
        noun = compound([part], clean(head.de))
        plural = compound([part], head.plural_form) if head.plural_form else "-"
        return _entry(lower, "NOUN", noun, 0.75, head.gender, plural, f"{left} + {right}")
    return None


def _hyphenated(lower: str, pos: str, lexicon: Lexicon, domain: str | None) -> Entry | None:
    """Слово через дефис: well-known, rule-based, state-of-the-art."""
    from dragoman.german.morphology import compound, compound_part

    parts = lower.split("-")
    if len(parts) == 2:
        first, second = parts
        for english_suffix, german in (("based", "basiert"), ("oriented", "orientiert"), ("driven", "gesteuert"),
                                       ("specific", "spezifisch"), ("like", "ähnlich"), ("free", "frei"),
                                       ("aware", "bewusst"), ("intensive", "intensiv"), ("friendly", "freundlich")):
            if second == english_suffix:
                noun = lexicon.best(first, "NOUN", domain)
                base = clean(noun.de) if noun and " " not in clean(noun.de) else first.upper() if len(first) <= 4 else first
                adjective = (compound_part(base, noun.gender if noun else "") if noun else base)
                return _entry(lower, "ADJ", adjective.lower() + german if noun else base + "-" + german, 0.7,
                              note=f"X-{english_suffix} → X{german}")
        if first in {"non", "self", "multi", "well", "pre", "post", "re", "co", "anti", "semi", "pseudo"}:
            german_prefix = {"non": "nicht", "self": "selbst", "multi": "multi", "well": "gut", "pre": "vor",
                             "post": "nach", "re": "wieder", "co": "ko", "anti": "anti", "semi": "halb",
                             "pseudo": "pseudo"}[first]
            rest = lexicon.best(second, pos, domain) or lexicon.best(second, "ADJ", domain)
            if rest:
                text = german_prefix + clean(rest.de) if pos != "NOUN" else capitalize(german_prefix) + clean(rest.de).lower()
                return _entry(lower, pos, text, 0.65, rest.gender, "", f"{first}- → {german_prefix}")
        if pos == "NOUN":
            head = lexicon.best(second, "NOUN", domain)
            modifier = lexicon.best(first, "NOUN", domain)
            if head and modifier and " " not in clean(head.de) and " " not in clean(modifier.de):
                part = compound_part(clean(modifier.de), modifier.gender, modifier.props.get("cf", ""))
                return _entry(lower, "NOUN", compound([part], clean(head.de)), 0.7, head.gender,
                              compound([part], head.plural_form) if head.plural_form else "-",
                              f"{first} + {second}")
    return None


def _adjective(lower: str, lexicon: Lexicon, domain: str | None) -> Entry | None:
    if "-" in lower[1:-1]:
        return _hyphenated(lower, "ADJ", lexicon, domain)
    # -able: основа глагола из словаря + -bar (executable → ausführbar)
    if lower.endswith(("able", "ible")) and len(lower) > 6:
        stem = lower[:-4]
        for candidate in (stem, stem + "e", stem[:-1] if stem.endswith(stem[-1] * 2) else ""):
            verb = lexicon.best(candidate, "VERB", domain) if candidate else None
            if verb and " " not in clean(verb.de).removeprefix("sich "):
                infinitive = clean(verb.de).removeprefix("sich ")
                base = infinitive[:-2] if infinitive.endswith("en") else infinitive[:-1]
                if infinitive.endswith("ieren"):
                    base = infinitive[:-2]
                return _entry(lower, "ADJ", base + "bar", 0.75, note=f"{candidate} + -able → -bar")
    for prefix in ("un", "in", "im", "ir", "il", "non"):
        if lower.startswith(prefix) and len(lower) > len(prefix) + 4:
            base = lexicon.best(lower[len(prefix):], "ADJ", domain, strict=True)
            if base and " " not in clean(base.de):
                german = clean(base.de)
                text = ("nicht" if prefix == "non" else "un") + german
                return _entry(lower, "ADJ", text, 0.7, note=f"{prefix}- → un-")
    for suffix, german, confidence in ADJ_SUFFIXES:
        if lower.endswith(suffix) and len(lower) > len(suffix) + 3:
            stem = germanize(lower[: -len(suffix)])
            return _entry(lower, "ADJ", stem + german, confidence, note=f"-{suffix} → -{german}")
    if lower.endswith("ful") and len(lower) > 6:
        noun = lexicon.best(lower[:-3], "NOUN", domain)
        if noun and " " not in clean(noun.de):
            from dragoman.german.morphology import compound_part

            return _entry(lower, "ADJ", compound_part(clean(noun.de), noun.gender).lower() + "voll", 0.55,
                          note="-ful → -voll")
    if lower.endswith("less") and len(lower) > 6:
        noun = lexicon.best(lower[:-4], "NOUN", domain)
        if noun and " " not in clean(noun.de):
            return _entry(lower, "ADJ", clean(noun.de).lower() + "los", 0.55, note="-less → -los")
    return None


def _verb(lower: str, lexicon: Lexicon, domain: str | None) -> Entry | None:
    if lower.startswith("re") and len(lower) > 5:
        base = lexicon.best(lower[2:], "VERB", domain, strict=True)
        if base and "|" not in base.de and " " not in clean(base.de):
            return _entry(lower, "VERB", "wieder|" + base.de, 0.6, note="re- → wieder-")
    for suffix, german, confidence in VERB_SUFFIXES:
        if lower.endswith(suffix) and len(lower) > len(suffix) + 2:
            stem = germanize(lower[: -len(suffix)], final_c="z")
            return _entry(lower, "VERB", stem + german, confidence, note=f"-{suffix} → -{german}")
    return None


def _adverb(lower: str, lexicon: Lexicon, domain: str | None) -> Entry | None:
    """-ly: перевод прилагательного (efficiently → effizient)."""
    if not lower.endswith("ly") or len(lower) < 5:
        return None
    candidates = [lower[:-2], lower[:-3] + "y" if lower.endswith("ily") else "",
                  lower[:-4] if lower.endswith("ally") else "", lower[:-2] + "e",
                  lower[:-1] + "e" if lower.endswith("bly") else ""]
    for candidate in candidates:
        if not candidate:
            continue
        adjective = lexicon.best(candidate, "ADJ", domain, strict=True)
        if adjective:
            return _entry(lower, "ADV", clean(adjective.de), 0.85, note=f"{candidate} + -ly")
    for candidate in candidates:
        if candidate:
            rule = _adjective(candidate, lexicon, domain)
            if rule:
                return _entry(lower, "ADV", rule.de, rule.confidence * 0.9, note=f"{candidate} + -ly; {rule.note}")
    return None
