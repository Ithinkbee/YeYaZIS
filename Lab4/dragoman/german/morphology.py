"""Немецкая морфология для синтеза перевода.

Здесь всё, что нужно, чтобы поставить слово в нужную форму:

* существительное — по роду, числу и падежу (des Programms, den Daten, dem
  Studenten — слабое склонение);
* артикли и местоименные слова — определённые (der), неопределённые (ein,
  kein, mein) и указательные (dieser, jeder);
* прилагательное — сильное, слабое и смешанное склонение (neuronales Netz,
  das neuronale Netz, ein neuronales Netz), степени сравнения (schneller,
  am schnellsten, größer, besser);
* личные, возвратные и относительные местоимения;
* глагол — настоящее и прошедшее время, конъюнктив II, причастие II,
  инфинитив с «zu», отделяемые приставки (stellt … vor, vorgestellt,
  vorzustellen);
* сложные слова: Netzwerk + Protokoll → Netzwerkprotokoll, Sicherheit +
  Lücke → Sicherheitslücke (соединительное -s-).

Падежи обозначаются буквами N, A, D, G; число — «sg» и «pl»; род — m, f, n.
"""

from __future__ import annotations

import re

from dragoman.german.verbs import AUXILIARY, INSEPARABLE, PARADIGMS, SEPARABLE, STRONG

CASES = ("N", "A", "D", "G")
CASE_NAMES = {"N": "именительный (Nominativ)", "A": "винительный (Akkusativ)",
              "D": "дательный (Dativ)", "G": "родительный (Genitiv)"}
GENDER_NAMES = {"m": "мужской", "f": "женский", "n": "средний", "pl": "только мн. ч."}

# --- артикли и местоименные слова -----------------------------------------------------

#: род/число -> падеж -> окончание «der»-слов (dieser, jeder, welcher, jener, solcher, mancher)
DER_ENDINGS = {
    "m": {"N": "er", "A": "en", "D": "em", "G": "es"},
    "f": {"N": "e", "A": "e", "D": "er", "G": "er"},
    "n": {"N": "es", "A": "es", "D": "em", "G": "es"},
    "pl": {"N": "e", "A": "e", "D": "en", "G": "er"},
}
DEFINITE = {
    "m": {"N": "der", "A": "den", "D": "dem", "G": "des"},
    "f": {"N": "die", "A": "die", "D": "der", "G": "der"},
    "n": {"N": "das", "A": "das", "D": "dem", "G": "des"},
    "pl": {"N": "die", "A": "die", "D": "den", "G": "der"},
}
#: окончания «ein»-слов (ein, kein, mein, sein, ihr, unser, euer)
EIN_ENDINGS = {
    "m": {"N": "", "A": "en", "D": "em", "G": "es"},
    "f": {"N": "e", "A": "e", "D": "er", "G": "er"},
    "n": {"N": "", "A": "", "D": "em", "G": "es"},
    "pl": {"N": "e", "A": "e", "D": "en", "G": "er"},
}

#: прилагательное после «der»-слова (слабое склонение)
WEAK = {
    "m": {"N": "e", "A": "en", "D": "en", "G": "en"},
    "f": {"N": "e", "A": "e", "D": "en", "G": "en"},
    "n": {"N": "e", "A": "e", "D": "en", "G": "en"},
    "pl": {"N": "en", "A": "en", "D": "en", "G": "en"},
}
#: прилагательное без артикля (сильное склонение)
STRONG_ADJ = {
    "m": {"N": "er", "A": "en", "D": "em", "G": "en"},
    "f": {"N": "e", "A": "e", "D": "er", "G": "er"},
    "n": {"N": "es", "A": "es", "D": "em", "G": "en"},
    "pl": {"N": "e", "A": "e", "D": "en", "G": "er"},
}
#: прилагательное после «ein»-слова (смешанное склонение)
MIXED = {
    "m": {"N": "er", "A": "en", "D": "en", "G": "en"},
    "f": {"N": "e", "A": "e", "D": "en", "G": "en"},
    "n": {"N": "es", "A": "es", "D": "en", "G": "en"},
    "pl": {"N": "en", "A": "en", "D": "en", "G": "en"},
}


def key(gender: str, number: str) -> str:
    return "pl" if number == "pl" or gender == "pl" else (gender if gender in {"m", "f", "n"} else "n")


def determiner(kind: str, gender: str, number: str, case: str, stem: str = "") -> str:
    """Артикль или местоименное слово перед существительным.

    kind: def — der; indef — ein; ein — kein/mein/sein (stem — основа);
    der — dieser/jeder/welcher (stem — основа без окончания); none — без артикля.
    """
    k = key(gender, number)
    if kind == "def":
        return DEFINITE[k][case]
    if kind == "indef":
        if k == "pl":
            return ""
        return "ein" + EIN_ENDINGS[k][case]
    if kind == "ein":
        ending = EIN_ENDINGS[k][case]
        base = stem
        # unser, euer: «unsere», «eure»
        if base == "euer" and ending:
            base = "eur"
        return base + ending
    if kind == "der":
        return stem + DER_ENDINGS[k][case]
    return ""


def adjective_table(kind: str) -> dict:
    """Какое склонение прилагательного требует артикль данного вида."""
    if kind in {"def", "der"}:
        return WEAK
    if kind in {"indef", "ein"}:
        return MIXED
    return STRONG_ADJ


# --- местоимения ---------------------------------------------------------------------

#: (лицо, число, род) -> падеж -> форма
PERSONAL = {
    (1, "sg", ""): {"N": "ich", "A": "mich", "D": "mir", "G": "meiner"},
    (2, "sg", ""): {"N": "du", "A": "dich", "D": "dir", "G": "deiner"},
    (3, "sg", "m"): {"N": "er", "A": "ihn", "D": "ihm", "G": "seiner"},
    (3, "sg", "f"): {"N": "sie", "A": "sie", "D": "ihr", "G": "ihrer"},
    (3, "sg", "n"): {"N": "es", "A": "es", "D": "ihm", "G": "seiner"},
    (1, "pl", ""): {"N": "wir", "A": "uns", "D": "uns", "G": "unser"},
    (2, "pl", ""): {"N": "Sie", "A": "Sie", "D": "Ihnen", "G": "Ihrer"},
    (3, "pl", ""): {"N": "sie", "A": "sie", "D": "ihnen", "G": "ihrer"},
}
REFLEXIVE = {
    (1, "sg"): {"A": "mich", "D": "mir"}, (2, "sg"): {"A": "dich", "D": "dir"},
    (3, "sg"): {"A": "sich", "D": "sich"}, (1, "pl"): {"A": "uns", "D": "uns"},
    (2, "pl"): {"A": "sich", "D": "sich"}, (3, "pl"): {"A": "sich", "D": "sich"},
}
RELATIVE = {
    "m": {"N": "der", "A": "den", "D": "dem", "G": "dessen"},
    "f": {"N": "die", "A": "die", "D": "der", "G": "deren"},
    "n": {"N": "das", "A": "das", "D": "dem", "G": "dessen"},
    "pl": {"N": "die", "A": "die", "D": "denen", "G": "deren"},
}
#: притяжательное местоимение по лицу, числу и роду владельца
POSSESSIVE = {
    (1, "sg", ""): "mein", (2, "sg", ""): "dein", (3, "sg", "m"): "sein", (3, "sg", "f"): "ihr",
    (3, "sg", "n"): "sein", (1, "pl", ""): "unser", (2, "pl", ""): "Ihr", (3, "pl", ""): "ihr",
}


def personal(person: int, number: str, gender: str, case: str) -> str:
    g = gender if person == 3 and number == "sg" else ""
    if person == 3 and number == "sg" and g not in {"m", "f", "n"}:
        g = "n"
    return PERSONAL[(person, number, g)][case if case in "NADG" else "N"]


def relative(gender: str, number: str, case: str) -> str:
    return RELATIVE[key(gender, number)][case]


# --- существительное ----------------------------------------------------------------------

_GEN_ES = re.compile(r"(s|ß|x|z|sch|tz)$")
_NO_GEN_ENDING = re.compile(r"(us|os|is|ismus|as)$")


def noun_form(lemma: str, gender: str, plural: str | None, number: str, case: str,
              weak: bool = False, genitive: str = "") -> str:
    """Форма существительного. plural — форма мн. ч. (None или «-» — нет мн. ч.)."""
    if not lemma:
        return lemma
    if gender == "pl":
        number = "pl"
        plural = plural if plural and plural != "-" else lemma
    if number == "pl":
        form = plural if plural and plural != "-" else lemma
        if case == "D" and not form.endswith(("n", "s")) and form[-1:].isalpha():
            form += "n"
        return form
    if " " in lemma:                       # словосочетание: склоняется последнее слово
        head, _, last = lemma.rpartition(" ")
        return head + " " + noun_form(last, gender, None, number, case, weak, genitive)
    if weak and case != "N":
        if case == "G" and genitive:
            return genitive
        return lemma + ("n" if lemma.endswith("e") else "en")
    if case == "G" and gender in {"m", "n"}:
        if genitive:
            return genitive
        if not lemma[-1:].isalpha() or lemma.isupper():
            return lemma + "s" if lemma.isupper() else lemma
        if _NO_GEN_ENDING.search(lemma):
            return lemma
        if _GEN_ES.search(lemma):
            return lemma + ("ses" if lemma.endswith(("nis",)) else "es")
        # односложное слово на согласный: des Gottes, des Textes, des Buches
        if len(re.findall(r"[aeiouäöüy]+", lemma.lower())) == 1 and lemma[-1] not in "aeiouäöüy" \
                and not lemma.isupper():
            return lemma + "es"
        return lemma + "s"
    return lemma


# --- прилагательное ----------------------------------------------------------------------------

#: неправильные степени сравнения: положительная -> (сравнительная, превосходная основа)
COMPARISON = {
    "gut": ("besser", "best"), "viel": ("mehr", "meist"), "gern": ("lieber", "liebst"),
    "hoch": ("höher", "höchst"), "nah": ("näher", "nächst"), "groß": ("größer", "größt"),
    "alt": ("älter", "ältest"), "arm": ("ärmer", "ärmst"), "jung": ("jünger", "jüngst"),
    "kalt": ("kälter", "kältest"), "warm": ("wärmer", "wärmst"), "kurz": ("kürzer", "kürzest"),
    "lang": ("länger", "längst"), "stark": ("stärker", "stärkst"), "schwach": ("schwächer", "schwächst"),
    "scharf": ("schärfer", "schärfst"), "klug": ("klüger", "klügst"), "hart": ("härter", "härtest"),
    "oft": ("öfter", "öftest"), "wenig": ("weniger", "wenigst"), "dunkel": ("dunkler", "dunkelst"),
    "teuer": ("teurer", "teuerst"), "klar": ("klarer", "klarst"), "dumm": ("dümmer", "dümmst"),
    "grob": ("gröber", "gröbst"), "gesund": ("gesünder", "gesündest"), "krank": ("kränker", "kränkst"),
    "schwer": ("schwerer", "schwerst"), "nass": ("nasser", "nassest"), "groß-": ("größer", "größt"),
}
#: прилагательные, которые не склоняются (lila, prima, цвета на -a, «extra»)
INDECLINABLE = {"lila", "rosa", "prima", "extra", "super", "online", "offline", "mehr", "weniger", "genug",
                "allerlei", "beiderlei"}
#: не склоняются в единственном числе: «viel Zeit», но «viele Fehler»
INDECLINABLE_SG = {"viel", "wenig"}


def adjective_stem(lemma: str) -> str:
    """Основа для окончаний: hoch → hoh, dunkel → dunkl, teuer → teur, flexibel → flexibl."""
    if lemma == "hoch":
        return "hoh"
    if lemma.endswith("el") and len(lemma) > 4:
        return lemma[:-2] + "l"
    if lemma.endswith(("euer", "auer")):
        return lemma[:-2] + "r"
    return lemma


def comparative(lemma: str) -> str:
    if lemma in COMPARISON:
        return COMPARISON[lemma][0]
    if lemma.endswith("el"):
        return lemma[:-2] + "ler"
    return lemma + ("r" if lemma.endswith("e") else "er")


def superlative_stem(lemma: str) -> str:
    if lemma in COMPARISON:
        return COMPARISON[lemma][1]
    if re.search(r"(d|t|s|ß|sch|z|x|tz)$", lemma) and not lemma.endswith("isch"):
        return lemma + "est"
    return lemma + "st"


def adjective_form(lemma: str, degree: str, table: dict | None, gender: str, number: str, case: str) -> str:
    """Прилагательное в атрибутивной позиции (table — вид склонения) или предикативной (table=None).

    degree: pos — положительная, comp — сравнительная, sup — превосходная.
    """
    if not lemma:
        return lemma
    if " " in lemma:                      # «sehr wichtig»: склоняется последнее слово
        head, _, last = lemma.rpartition(" ")
        return head + " " + adjective_form(last, degree, table, gender, number, case)
    if degree == "comp":
        base = comparative(lemma)
    elif degree == "sup":
        base = superlative_stem(lemma)
    else:
        base = lemma
    if table is None:
        if degree == "sup":
            return "am " + base + "en"
        return base
    if base in INDECLINABLE or lemma in INDECLINABLE and degree == "pos":
        return base
    if lemma in INDECLINABLE_SG and degree == "pos" and number != "pl":
        return base
    ending = table[key(gender, number)][case]
    stem = adjective_stem(base) if degree == "pos" else base
    if stem.endswith("e") and ending.startswith("e"):
        return stem + ending[1:]
    return stem + ending


# --- глагол -------------------------------------------------------------------------------------------

#: немецкие глаголы словаря (заполняет словарь при загрузке): по ним узнаются
#: отделяемые приставки у глаголов без пометки «|»
KNOWN_VERBS: set[str] = set()

#: приставки, которые без пометки «|» считаются неотделяемыми
_INSEPARABLE_DEFAULT = tuple(sorted(set(INSEPARABLE) | {"um", "durch", "wieder"}, key=len, reverse=True))
_SEPARABLE_AUTO = tuple(p for p in sorted(SEPARABLE, key=len, reverse=True) if p not in {"um", "durch", "wieder"})


def split_verb(lemma: str) -> tuple[str, str, str]:
    """(отделяемая приставка, неотделяемая приставка, простой глагол) по инфинитиву.

    Отделяемая приставка в словаре отмечена «|»: «vor|stellen». Без пометки
    приставка считается отделяемой, только если остаток — известный глагол
    («anwenden» = an + wenden), иначе «antworten» превратился бы в «twortet an».
    """
    if lemma.startswith("sich "):
        lemma = lemma[5:]
    separable = ""
    if "|" in lemma:
        separable, _, lemma = lemma.partition("|")
    if lemma in STRONG or lemma in PARADIGMS:
        return separable, "", lemma
    for prefix in _INSEPARABLE_DEFAULT:
        if lemma.startswith(prefix) and len(lemma) > len(prefix) + 3:
            rest = lemma[len(prefix):]
            # «geben», «gehen» — не приставка
            if prefix == "ge" and rest in {"ben", "hen"}:
                continue
            return separable, prefix, rest
    if not separable:
        for prefix in _SEPARABLE_AUTO:
            rest = lemma[len(prefix):]
            if lemma.startswith(prefix) and (rest in STRONG or rest in KNOWN_VERBS) and len(rest) >= 4:
                return prefix, "", rest
    return separable, "", lemma


def is_reflexive(lemma: str) -> bool:
    return lemma.startswith("sich ")


def bare(lemma: str) -> str:
    """Инфинитив без «sich» и без пометки приставки: «sich vor|stellen» → «vorstellen»."""
    return lemma.removeprefix("sich ").replace("|", "")


def _stem(infinitive: str) -> str:
    if infinitive.endswith(("eln", "ern")):
        return infinitive[:-1]
    if infinitive.endswith("en"):
        return infinitive[:-2]
    if infinitive.endswith("n"):
        return infinitive[:-1]
    return infinitive


_E_INSERT = re.compile(r"([dt]|chn|ckn|[bdfgkpstvwz]n|[bdfgkpstvz]m|chm)$")


def _needs_e(stem: str) -> bool:
    """arbeitet, rechnet, öffnet, atmet — но lernt, wohnt, filmt."""
    return bool(_E_INSERT.search(stem))


def _index(person: int, number: str) -> int:
    return (person - 1) + (0 if number == "sg" else 3)


def _regular_present(base: str, person: int, number: str) -> str:
    stem = _stem(base)
    i = _index(person, number)
    if base.endswith(("eln", "ern")):
        endings = ("e", "st", "t", "n", "t", "n")
        if i == 0 and base.endswith("eln"):
            return stem[:-2] + "le"
        return stem + endings[i]
    e = "e" if _needs_e(stem) else ""
    sibilant = stem.endswith(("s", "ß", "z", "x"))
    endings = ("e", (e + "t") if sibilant else e + "st", e + "t", "en", e + "t", "en")
    if base.endswith("n") and not base.endswith("en"):      # tun-образные
        endings = ("e", "st", "t", "n", "t", "n")
    return stem + endings[i]


def present(lemma: str, person: int, number: str) -> tuple[str, str]:
    """Настоящее время: (спрягаемая форма, отделяемая приставка)."""
    separable, prefix, base = split_verb(lemma)
    i = _index(person, number)
    if base in PARADIGMS:
        form = PARADIGMS[base]["pres"][i]
    elif base in STRONG and i in (1, 2):
        third = STRONG[base][0]
        if i == 2:
            form = third
        else:
            stem3 = third[:-1] if third.endswith("t") and not third.endswith(("ält", "ät")) else third
            form = stem3 + ("t" if stem3.endswith(("s", "ß", "z", "x")) else "st")
    else:
        form = _regular_present(base, person, number)
    return prefix + form, separable


def past(lemma: str, person: int, number: str) -> tuple[str, str]:
    """Претерит: (спрягаемая форма, отделяемая приставка)."""
    separable, prefix, base = split_verb(lemma)
    i = _index(person, number)
    if base in PARADIGMS:
        return prefix + PARADIGMS[base]["past"][i], separable
    if base in STRONG:
        stem = STRONG[base][1]
        if stem.endswith("te"):                      # смешанные: brachte, dachte
            endings = ("", "st", "", "n", "t", "n")
        else:
            endings = ("", "st" if not stem.endswith(("s", "ß")) else "est", "", "en", "t", "en")
        return prefix + stem + endings[i], separable
    stem = _stem(base)
    if base.endswith(("eln", "ern")):
        stem = base[:-1]
    e = "e" if _needs_e(stem) else ""
    endings = ("te", "test", "te", "ten", "tet", "ten")
    return prefix + stem + e + endings[i], separable


def subjunctive(lemma: str, person: int, number: str) -> tuple[str, str]:
    """Конъюнктив II (würde, könnte, hätte); у прочих глаголов — würde + инфинитив, см. transfer."""
    separable, prefix, base = split_verb(lemma)
    i = _index(person, number)
    if base in PARADIGMS:
        return prefix + PARADIGMS[base]["subj"][i], separable
    return past(lemma, person, number)


def participle(lemma: str) -> str:
    """Причастие II: gemacht, verwendet, implementiert, vorgestellt, angegeben."""
    separable, prefix, base = split_verb(lemma)
    if base in STRONG:
        form = STRONG[base][2]
    elif base in PARADIGMS:
        form = {"sein": "gewesen", "haben": "gehabt", "werden": "geworden"}.get(base, STRONG.get(base, ("", "", "ge" + _stem(base) + "t"))[2])
    else:
        stem = base[:-1] if base.endswith(("eln", "ern")) else _stem(base)
        form = "ge" + stem + ("e" if _needs_e(stem) else "") + "t"
    # неотделяемая приставка и глаголы на -ieren — без ge-
    if (prefix or (base.endswith("ieren") and base not in STRONG)) and form.startswith("ge"):
        form = form[2:]
    return separable + prefix + form


def zu_infinitive(lemma: str) -> str:
    separable, prefix, base = split_verb(lemma)
    if separable:
        return separable + "zu" + prefix + base
    return "zu " + prefix + base


def infinitive(lemma: str) -> str:
    return bare(lemma)


def auxiliary(lemma: str) -> str:
    """«haben» или «sein» для перфекта: ist gekommen, ist angekommen, hat bekommen."""
    full = bare(lemma)
    if full in AUXILIARY:
        return "sein" if AUXILIARY[full] == "s" else "haben"
    separable, prefix, base = split_verb(lemma)
    if prefix:                    # неотделяемая приставка обычно делает глагол переходным
        return "haben"
    if base in AUXILIARY:
        return "sein" if AUXILIARY[base] == "s" else "haben"
    if base in STRONG:
        return "sein" if STRONG[base][3] == "s" else "haben"
    return "haben"


# --- сложные слова ------------------------------------------------------------------------------

_LINKING_S = re.compile(r"(ung|heit|keit|schaft|ion|tät|ität|ling|tum|sicht)$")


def compound_part(noun: str, gender: str, explicit: str = "") -> str:
    """Форма существительного как первой части сложного слова (Kompositionsform).

    Kompilieren → Kompilier- (Kompilierprozess), Sicherheit → Sicherheits- (Sicherheitslücke),
    Entwurf → Entwurfs- (Entwurfsmuster: приставочное существительное), Seite → Seiten- (Seitenzahl).
    Исключения задаются в словаре полем cf: Sprache → Sprach-.
    """
    if explicit:
        return explicit
    if " " in noun or not noun.isalpha():
        return noun
    if noun.endswith("ieren"):
        return noun[:-2]
    if _LINKING_S.search(noun):
        return noun + "s"
    if gender in {"m", "n"} and noun[:1].isupper() and re.match(r"(Be|Ge|Ent|Er|Ver|Zer|Emp|Miss)[a-zäöü]", noun)             and not noun.endswith(("e", "en", "er", "el")) and len(noun) > 5:
        return noun + "s"
    if gender == "f" and noun.endswith("e") and len(noun) > 4 and not noun.endswith(("ce", "ge", "que")):
        return noun + "n"
    return noun


def compound(parts: list[str], head: str) -> str:
    """Сложное слово из частей и главного слова: «Netzwerk» + «Protokoll» → «Netzwerkprotokoll».

    Части из прописных букв и имена собственные присоединяются через дефис:
    «CPU-Zeit», «Java-Programm».
    """
    result = ""
    for part in parts + [head]:
        if not result:
            result = part
            continue
        if result.endswith("-"):
            result += part
            continue
        if result.isupper() or result[-1:].isdigit() or not part[:1].isalpha() or "-" in result[-1:]:
            result += "-" + part
        elif part.isupper() or not result.isalpha():
            result += "-" + part
        else:
            result += part[:1].lower() + part[1:]
    return result
