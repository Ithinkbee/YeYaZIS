"""Немецкие правила чтения: от букв к фонемам (grapheme-to-phoneme).

Немецкая орфография, в отличие от английской, почти однозначна, и
произношение слова выводится правилами. Порядок работы:

1. **Исключения.** Служебные слова и частые слова с непредсказуемым
   ударением («System», «Programm», «Methode», «Mathematik») берутся из
   таблицы с готовой транскрипцией.
2. **Состав слова.** Сложное слово делится по известным основам
   («Betriebs|system», «Daten|bank»); у слова отделяются приставки
   (безударные be-, ge-, ver-, ent-…, ударные an-, auf-, aus-…) и
   суффиксы (-heit, -keit, -lich, -chen…). Границы частей важны: на них
   глухие звонкие («Hand|lung» — [t]), «st» и «sp» в начале основы — [ʃt],
   [ʃp], «h» в начале суффикса произносится («Wahr|heit»).
3. **Буквы в звуки** слева направо, длинными сочетаниями вперёд: «tsch»,
   «sch», «chs», «ch», «ck», «ei», «eu», «ie»… Гласная долгая, если
   написана двойной, с «h» или как «ie», а также в открытом слоге; краткая —
   перед двойной согласной, «ck», «tz» и сочетанием согласных. «ch» после
   a, o, u, au — [x], в остальных случаях — [ç]. «r» после гласной перед
   согласной или в конце — неслоговое [ɐ̯]; безударное «-er» — [ɐ].
   Безударное «e» в конечном слоге и в be-, ge- — [ə]. Звонкие b, d, g в
   конце слога — [p], [t], [k]; «-ig» в конце — [ɪç].
4. **Слоги и ударение.** Слог начинается с наибольшего допустимого
   сочетания согласных. Ударение — на первом слоге основы; иноязычные
   суффиксы (-ion, -ität, -ieren, -ie, -ur, -ell, -al, -ent, -ant, -anz,
   -enz…) перетягивают его на себя; в сложном слове главное ударение — на
   первой части.

Записи немецкими буквами из словарей произношения («Mä'schien 'Lörning»)
читаются теми же правилами; апостроф ставит ударение явно, «äi» — [ɛɪ].
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

# --- фонемы ------------------------------------------------------------------------------

LONG_VOWELS = {"iː", "yː", "eː", "ɛː", "øː", "aː", "oː", "uː"}
SHORT_VOWELS = {"ɪ", "ʏ", "ɛ", "œ", "a", "ɔ", "ʊ", "ə", "ɐ", "i", "y", "e", "ø", "o", "u"}
DIPHTHONGS = {"aɪ", "aʊ", "ɔʏ", "ɛɪ", "oʊ"}
VOWELS = LONG_VOWELS | SHORT_VOWELS | DIPHTHONGS
CONSONANTS = {"p", "b", "t", "d", "k", "ɡ", "ʔ", "f", "v", "s", "z", "ʃ", "ʒ", "ç", "x", "j", "h", "m", "n",
              "ŋ", "l", "ʁ", "ɐ̯", "ts", "pf", "tʃ", "dʒ"}
#: все фонемы, длинные обозначения первыми: так разбирается запись «aɪ» и «ts»
INVENTORY = sorted(VOWELS | CONSONANTS, key=len, reverse=True)

#: долгая гласная -> краткая напряжённая (в безударном слоге): «Theorie» [teoˈʁiː]
TENSE = {"iː": "i", "yː": "y", "eː": "e", "øː": "ø", "aː": "a", "oː": "o", "uː": "u", "ɛː": "ɛ"}

#: какими сочетаниями согласных может начинаться немецкий слог
ONSETS = {
    (), ("p",), ("b",), ("t",), ("d",), ("k",), ("ɡ",), ("f",), ("v",), ("s",), ("z",), ("ʃ",), ("ʒ",), ("ç",),
    ("x",), ("j",), ("h",), ("m",), ("n",), ("l",), ("ʁ",), ("ts",), ("pf",), ("tʃ",), ("dʒ",), ("ʔ",),
    ("p", "l"), ("p", "ʁ"), ("b", "l"), ("b", "ʁ"), ("t", "ʁ"), ("d", "ʁ"), ("k", "l"), ("k", "ʁ"), ("k", "n"),
    ("k", "v"), ("ɡ", "l"), ("ɡ", "ʁ"), ("ɡ", "n"), ("f", "l"), ("f", "ʁ"), ("ʃ", "l"), ("ʃ", "m"), ("ʃ", "n"),
    ("ʃ", "ʁ"), ("ʃ", "v"), ("ʃ", "p"), ("ʃ", "t"), ("ts", "v"), ("pf", "l"), ("pf", "ʁ"), ("v", "ʁ"),
    ("ʃ", "p", "ʁ"), ("ʃ", "p", "l"), ("ʃ", "t", "ʁ"), ("s", "k"), ("s", "t"), ("s", "p"), ("s", "l"),
    ("t", "s"), ("p", "s"), ("t", "v"), ("ç", "ʁ"), ("s", "k", "ʁ"), ("s", "t", "ʁ"), ("v", "l"), ("p", "j"),
    ("k", "j"), ("t", "j"), ("d", "j"), ("n", "j"), ("l", "j"), ("m", "j"), ("ɡ", "j"), ("ts", "j"),
    ("s", "j"), ("z", "j"), ("ʁ", "j"), ("f", "j"), ("b", "j"), ("v", "j"),
}


@dataclass
class Syllable:
    phonemes: list[str]
    stress: int = 0             # 0 — безударный, 1 — главное ударение, 2 — побочное

    @property
    def nucleus(self) -> str:
        return next((p for p in self.phonemes if p in VOWELS), "")


@dataclass
class Pronunciation:
    word: str
    syllables: list[Syllable] = field(default_factory=list)
    source: str = "rules"       # rules | exception

    @property
    def phonemes(self) -> list[str]:
        return [p for syllable in self.syllables for p in syllable.phonemes]

    def ipa(self, dots: bool = True) -> str:
        """Транскрипция в МФА: «ˈʃpʁaː.xə»."""
        parts = []
        for syllable in self.syllables:
            mark = "ˈ" if syllable.stress == 1 else "ˌ" if syllable.stress == 2 else ""
            parts.append(mark + "".join(_display(p) for p in syllable.phonemes))
        joined = "."
        text = joined.join(parts) if dots else "".join(parts)
        return text.replace(".ˈ", "ˈ").replace(".ˌ", "ˌ") if dots else text


def _display(phoneme: str) -> str:
    return {"aɪ": "aɪ̯", "aʊ": "aʊ̯", "ɔʏ": "ɔʏ̯", "ɛɪ": "ɛɪ̯", "oʊ": "oʊ̯", "ts": "t͡s", "pf": "p͡f", "tʃ": "t͡ʃ",
            "dʒ": "d͡ʒ"}.get(phoneme, phoneme)


def parse_ipa(text: str) -> list[Syllable]:
    """Транскрипция из таблицы исключений -> слоги. Точка — граница слога."""
    syllables: list[Syllable] = []
    text = text.replace("͡", "")
    for diphthong in ("aɪ̯", "aʊ̯", "ɔʏ̯", "ɛɪ̯", "oʊ̯"):
        text = text.replace(diphthong, diphthong[:-1])
    for chunk in re.split(r"\.|(?=[ˈˌ])", text):
        if not chunk:
            continue
        stress = 1 if chunk.startswith("ˈ") else 2 if chunk.startswith("ˌ") else 0
        chunk = chunk.lstrip("ˈˌ")
        phonemes = []
        position = 0
        while position < len(chunk):
            for symbol in INVENTORY:
                if chunk.startswith(symbol, position):
                    phonemes.append(symbol)
                    position += len(symbol)
                    break
            else:
                position += 1          # неизвестный знак пропускается
        if phonemes:
            syllables.append(Syllable(phonemes, stress))
    if syllables and not any(syllable.stress for syllable in syllables):
        syllables[0].stress = 1
    return syllables


# --- исключения ----------------------------------------------------------------------------

#: служебные слова и слова с непредсказуемым произношением
EXCEPTIONS: dict[str, str] = {
    "der": "deːɐ̯", "die": "diː", "das": "das", "den": "deːn", "dem": "deːm", "des": "dɛs", "ein": "aɪn",
    "eine": "ˈaɪ.nə", "einen": "ˈaɪ.nən", "einer": "ˈaɪ.nɐ", "eines": "ˈaɪ.nəs", "einem": "ˈaɪ.nəm",
    "und": "ʊnt", "oder": "ˈoː.dɐ", "aber": "ˈaː.bɐ", "in": "ɪn", "im": "ɪm", "an": "an", "am": "am",
    "auf": "aʊf", "aus": "aʊs", "bei": "baɪ", "mit": "mɪt", "nach": "naːx", "von": "fɔn", "vom": "fɔm",
    "zu": "tsuː", "zum": "tsʊm", "zur": "tsuːɐ̯", "für": "fyːɐ̯", "über": "ˈyː.bɐ", "unter": "ˈʊn.tɐ",
    "um": "ʊm", "ab": "ap", "bis": "bɪs", "durch": "dʊʁç", "ohne": "ˈoː.nə", "gegen": "ˈɡeː.ɡən", "ist": "ɪst",
    "sind": "zɪnt", "war": "vaːɐ̯", "wird": "vɪʁt", "werden": "ˈveːɐ̯.dən", "wurde": "ˈvʊʁ.də",
    "wurden": "ˈvʊʁ.dən", "hat": "hat", "haben": "ˈhaː.bən", "kann": "kan", "können": "ˈkœ.nən",
    "es": "ɛs", "er": "eːɐ̯", "sie": "ziː", "wir": "viːɐ̯", "ich": "ɪç", "man": "man", "sich": "zɪç",
    "nicht": "nɪçt", "auch": "aʊx", "noch": "nɔx", "doch": "dɔx", "nur": "nuːɐ̯", "so": "zoː", "wie": "viː",
    "was": "vas", "wer": "veːɐ̯", "wo": "voː", "als": "als", "da": "daː", "dass": "das", "daß": "das",
    "ob": "ɔp", "weil": "vaɪl", "wenn": "vɛn", "dann": "dan", "denn": "dɛn", "schon": "ʃoːn", "sehr": "zeːɐ̯",
    "mehr": "meːɐ̯", "hier": "hiːɐ̯", "jetzt": "jɛtst", "heute": "ˈhɔʏ.tə", "dies": "diːs", "diese": "ˈdiː.zə",
    "dieser": "ˈdiː.zɐ", "dieses": "ˈdiː.zəs", "diesem": "ˈdiː.zəm", "diesen": "ˈdiː.zən",
    "welche": "ˈvɛl.çə", "kein": "kaɪn", "keine": "ˈkaɪ.nə", "alle": "ˈa.lə", "viele": "ˈfiː.lə",
    "viel": "fiːl", "vier": "fiːɐ̯", "vor": "foːɐ̯", "zwischen": "ˈtsvɪ.ʃən", "während": "ˈvɛː.ʁənt",
    "wegen": "ˈveː.ɡən", "sowie": "zoˈviː", "sowohl": "zoˈvoːl", "jedoch": "jeˈdɔx", "zwar": "tsvaːɐ̯",
    "etwa": "ˈɛt.va", "etwas": "ˈɛt.vas", "jeder": "ˈjeː.dɐ", "jede": "ˈjeː.də", "jedes": "ˈjeː.dəs",
    "ihr": "iːɐ̯", "ihre": "ˈiː.ʁə", "sein": "zaɪn", "seine": "ˈzaɪ.nə", "seiner": "ˈzaɪ.nɐ",
    "zusammen": "tsuˈza.mən", "system": "zʏsˈteːm", "systeme": "zʏsˈteː.mə", "systemen": "zʏsˈteː.mən",
    "systems": "zʏsˈteːms", "problem": "pʁoˈbleːm", "probleme": "pʁoˈbleː.mə", "programm": "pʁoˈɡʁam",
    "programme": "pʁoˈɡʁa.mə", "programms": "pʁoˈɡʁams", "programmen": "pʁoˈɡʁa.mən",
    "prozess": "pʁoˈtsɛs", "prozesse": "pʁoˈtsɛ.sə", "methode": "meˈtoː.də", "methoden": "meˈtoː.dən",
    "objekt": "ɔpˈjɛkt", "objekte": "ɔpˈjɛk.tə", "projekt": "pʁoˈjɛkt", "konzept": "kɔnˈtsɛpt",
    "algorithmus": "al.ɡoˈʁɪt.mʊs", "algorithmen": "al.ɡoˈʁɪt.mən", "variable": "vaˈʁjaː.blə",
    "variablen": "vaˈʁjaː.blən", "parameter": "paˈʁaː.me.tɐ", "protokoll": "pʁo.toˈkɔl",
    "interpreter": "ɪnˈtɛʁ.pʁe.tɐ", "assembler": "aˈsɛm.blɐ", "kontrolle": "kɔnˈtʁɔ.lə",
    "mathematik": "ma.te.maˈtiːk", "physik": "fyˈziːk", "musik": "muˈziːk", "politik": "po.liˈtiːk",
    "kritik": "kʁiˈtiːk", "technik": "ˈtɛç.nɪk", "fabrik": "faˈbʁiːk", "medien": "ˈmeː.djən",
    "studien": "ˈʃtuː.djən", "familie": "faˈmiː.ljə", "linie": "ˈliː.njə", "daten": "ˈdaː.tən",
    "monat": "ˈmoː.nat", "erst": "eːɐ̯st", "erste": "ˈeːɐ̯s.tə", "ersten": "ˈeːɐ̯s.tən", "erster": "ˈeːɐ̯s.tɐ",
    "erstes": "ˈeːɐ̯s.təs", "ende": "ˈɛn.də", "erde": "ˈeːɐ̯.də", "genau": "ɡəˈnaʊ", "genug": "ɡəˈnuːk",
    "gerade": "ɡəˈʁaː.də", "gern": "ɡɛʁn", "geben": "ˈɡeː.bən", "gibt": "ɡiːpt", "gehen": "ˈɡeː.ən",
    "geht": "ɡeːt", "gelten": "ˈɡɛl.tən", "gilt": "ɡɪlt", "geld": "ɡɛlt", "beide": "ˈbaɪ.də",
    "beiden": "ˈbaɪ.dən", "analyse": "a.naˈlyː.zə", "neuron": "ˈnɔʏ.ʁɔn", "neuronen": "nɔʏˈʁoː.nən",
    "neuronale": "nɔʏ.ʁoˈnaː.lə", "neuronalen": "nɔʏ.ʁoˈnaː.lən", "neuronales": "nɔʏ.ʁoˈnaː.ləs",
    "version": "vɛʁˈzjoːn", "versionen": "vɛʁˈzjoː.nən", "computer": "kɔmˈpjuː.tɐ", "museum": "muˈzeː.ʊm",
    "chaos": "ˈkaː.ɔs", "chor": "koːɐ̯", "chemie": "çeˈmiː", "china": "ˈçiː.na", "chance": "ˈʃãː.sə",
    "jahr": "jaːɐ̯", "jahre": "ˈjaː.ʁə", "jahren": "ˈjaː.ʁən", "jahrhundert": "jaːɐ̯ˈhʊn.dɐt",
    "anderen": "ˈan.də.ʁən", "andere": "ˈan.də.ʁə", "anders": "ˈan.dɐs", "einige": "ˈaɪ.nɪ.ɡə",
    "einigen": "ˈaɪ.nɪ.ɡən", "immer": "ˈɪ.mɐ", "wieder": "ˈviː.dɐ", "selbst": "zɛlpst", "nun": "nuːn",
    "teil": "taɪl", "weise": "ˈvaɪ.zə", "also": "ˈal.zo", "bereits": "bəˈʁaɪts", "beispiel": "ˈbaɪ.ʃpiːl",
    "beispiele": "ˈbaɪ.ʃpiː.lə", "beispielsweise": "ˈbaɪ.ʃpiːls.vaɪ.zə", "zahl": "tsaːl", "zahlen": "ˈtsaː.lən",
    "arbeit": "ˈaʁ.baɪt", "arbeiten": "ˈaʁ.baɪ.tən", "elektronische": "e.lɛkˈtʁoː.nɪ.ʃə",
    "elektronischen": "e.lɛkˈtʁoː.nɪ.ʃən", "informatik": "ɪn.fɔʁˈmaː.tɪk", "intelligenz": "ɪn.tɛ.liˈɡɛnts",
    "künstliche": "ˈkʏnst.lɪ.çə", "künstliches": "ˈkʏnst.lɪ.çəs", "künstlichen": "ˈkʏnst.lɪ.çən",
    "netz": "nɛts", "netze": "ˈnɛ.tsə", "netzes": "ˈnɛ.tsəs", "netzen": "ˈnɛ.tsən", "web": "vɛp",
    "semantisch": "zeˈman.tɪʃ", "semantische": "zeˈman.tɪ.ʃə", "semantik": "zeˈman.tɪk",
    "ontologie": "ɔn.to.loˈɡiː", "ontologien": "ɔn.to.loˈɡiː.ən", "theorie": "te.oˈʁiː",
    "hallo": "haˈloː", "autsch": "aʊtʃ", "danke": "ˈdaŋ.kə", "bitte": "ˈbɪ.tə", "lecker": "ˈlɛ.kɐ",
    "ja": "jaː", "nein": "naɪn", "okay": "oˈkeː", "tschüss": "tʃʏs", "mein": "maɪn", "meine": "ˈmaɪ.nə",
    "dich": "dɪç", "mich": "mɪç", "mir": "miːɐ̯", "dir": "diːɐ̯", "du": "duː", "ihn": "iːn", "uns": "ʊns",
    "mittel": "ˈmɪ.təl", "mitte": "ˈmɪ.tə", "mitteln": "ˈmɪ.təln", "modell": "moˈdɛl",
    "modelle": "moˈdɛ.lə", "modellen": "moˈdɛ.lən", "tabelle": "taˈbɛ.lə", "tabellen": "taˈbɛ.lən",
    "serie": "ˈzeː.ʁjə", "materie": "maˈteː.ʁjə", "merkmal": "ˈmɛʁk.maːl", "merkmale": "ˈmɛʁk.maː.lə",
    "verb": "vɛʁp", "verben": "ˈvɛʁ.bən", "hallo": "haˈloː", "über": "ˈyː.bɐ",
    "gut": "ɡuːt", "gute": "ˈɡuː.tə", "guten": "ˈɡuː.tən", "nacht": "naxt", "morgen": "ˈmɔʁ.ɡən",
}

#: основы для деления сложных слов: «Betriebs|system», «Daten|bank». Только частые в
#: текстах по информатике и не короче четырёх букв — иначе делились бы и простые слова
STEMS = sorted(set("""
system systeme systemen systems programm programme programmen programms sprache sprachen netz netze netzes
netzwerk netzwerke werk werke daten speicher rechner rechners verarbeitung sicherheit betrieb entwicklung
schicht schichten bereich bereiche struktur strukturen modell modelle modellen verfahren methode methoden
technik technologie anwendung anwendungen funktion funktionen information informationen nutzer benutzer
zugriff zugriffe analyse code programmierung programmiersprache übersetzer übersetzung maschine maschinen
einheit einheiten zeit zeiten schutz ziel ziele quelle quellen ebene ebenen theorie problem probleme
wert werte typ typen form formen kern kerne prozess prozesse prozessor prozessoren dienst dienste
verbindung verbindungen schnittstelle schnittstellen oberfläche zustand zustände regel regeln gesetz gesetze
linie linien medien sprache rechnung verwaltung behandlung
datei dateien bank banken baum bäume liste listen tabelle tabellen menge mengen gruppe gruppen klasse
klassen objekt objekte wissen ordnung steuerung leistung forschung erkennung lernen netzes sprachen
befehl befehle adresse adressen fehler muster vektor vektoren signal signale ausgabe eingabe abschnitt
""".split()), key=len, reverse=True)

#: безударные приставки
UNSTRESSED_PREFIXES = ("zer", "ver", "ent", "emp", "be", "ge", "er", "miss")
#: ударные (отделяемые) приставки
STRESSED_PREFIXES = ("zusammen", "zurück", "wieder", "gegen", "durch", "unter", "über", "nach", "fort", "weg", "auf",
                     "aus", "bei", "ein", "mit", "vor", "dar", "her", "hin", "los", "ab", "an", "um", "zu",
                     "un", "ur")
#: ударение внутри многосложной приставки
_PREFIX_SPELLING = {"zusammen": "zu'sammen", "zurück": "zu'rück", "wieder": "'wieder", "gegen": "'gegen",
                    "unter": "'unter", "über": "'über"}
#: суффиксы, перед которыми проходит граница части слова
SUFFIXES = ("schaft", "heit", "keit", "haft", "lich", "chen", "lein", "bar", "sam", "los", "nis", "tum", "ling")

#: иноязычные суффиксы, принимающие ударение: (окончание слова, сколько последних слогов
#: безударны — 0: ударен последний слог, 1: предпоследний)
FOREIGN_SUFFIXES = [
    ("ierungen", 2), ("ierung", 1), ("ieren", 1), ("ierte", 1), ("ierten", 1), ("iertes", 1), ("ierter", 1),
    ("iert", 0), ("ionen", 1), ("ion", 0), ("itäten", 1), ("ität", 0), ("ismus", 1), ("isten", 1), ("istin", 1),
    ("ist", 0), ("ien", 1), ("ie", 0), ("ell", 0), ("elle", 1), ("ellen", 1), ("eller", 1), ("elles", 1),
    ("ur", 0), ("uren", 1), ("al", 0), ("ale", 1), ("alen", 1), ("ales", 1), ("aler", 1), ("ent", 0),
    ("ente", 1), ("enten", 1), ("ant", 0), ("ante", 1), ("anten", 1), ("anz", 0), ("enz", 0), ("enzen", 1),
    ("är", 0), ("äre", 1), ("ären", 1), ("ös", 0), ("eur", 0), ("ei", 0), ("ik", 1), ("iken", 2),
    ("oren", 1), ("or", 1), ("ose", 1), ("yse", 1), ("ese", 1), ("ium", 1), ("ier", 0), ("at", 0), ("ate", 1),
    ("aten", 1), ("ett", 0), ("ette", 1), ("iv", 0), ("ive", 1), ("iven", 1), ("ativ", 0),
]
#: слова, которые кончаются как иноязычные, но ударение у них обычное
NOT_FOREIGN = {"heimat", "monat", "heirat", "vorrat", "zierrat", "drei", "frei", "brei", "zwei",
               "einzel", "dabei", "vorbei", "herbei", "nebenbei", "teil", "seil", "heil", "weil",
               "fall", "ball", "all", "hall", "schall", "stall", "mal", "zahl", "wahl", "kahl", "saal", "tal",
               "stahl", "fahl", "pfahl", "qual", "schal", "ist", "frist", "list",
               "mist", "zwist", "tor", "chor", "rohr", "ohr", "uhr", "spur", "kur", "schnur", "flur", "nur",
               "tur", "kind", "rind", "wind", "rat", "tat", "saat", "naht", "staat", "pfad", "bad", "grad",
               "ende", "wende", "rente", "ente", "hand", "land", "band", "rand", "sand", "stand", "wand",
               "bekannt", "genannt", "erkannt", "benannt", "verwandt", "tant"}

#: «v» читается [f] в немецких словах с этих начал
NATIVE_V = ("ver", "vor", "voll", "viel", "vier", "von", "vom", "vater", "volk", "vogel", "vorn", "vieh",
            "vetter")
#: …кроме иноязычных
FOREIGN_V = ("verif", "versio", "vertik", "verti", "versus", "variab", "vorti")


# --- разбор слова ------------------------------------------------------------------------

@dataclass
class _Unit:
    graph: str
    kind: str                   # V — гласная, C — согласная
    morph: int                  # номер части слова
    phon: str = ""
    long: bool | None = None    # для гласной: долгота задана написанием
    shortens: bool = False      # для согласной: делает предыдущую гласную краткой
    stressed: bool = False      # перед гласной стоял апостроф


_VOWEL_GRAPHS = [("äi", "ɛɪ"), ("aa", "aː"), ("ee", "eː"), ("oo", "oː"), ("ie", "iː"), ("ei", "aɪ"),
                 ("ey", "aɪ"), ("ai", "aɪ"), ("ay", "aɪ"), ("eu", "ɔʏ"), ("äu", "ɔʏ"), ("au", "aʊ"),
                 ("oi", "ɔʏ"), ("ou", "uː"), ("a", "a"), ("e", "e"), ("i", "i"), ("o", "o"), ("u", "u"),
                 ("ä", "ɛ"), ("ö", "ø"), ("ü", "y"), ("y", "y"), ("é", "e"), ("è", "ɛ"), ("à", "a")]
_CONSONANT_GRAPHS = [("tsch", "tʃ", True), ("dsch", "dʒ", False), ("sch", "ʃ", True), ("chs", "ks", True),
                     ("ck", "k", True), ("ch", "ch", False), ("ph", "f", False), ("pf", "pf", True),
                     ("qu", "k v", False), ("th", "t", False), ("tz", "ts", True), ("dt", "t", False),
                     ("ng", "ŋ", True), ("nk", "ŋ k", True), ("ss", "s", True), ("ß", "s", False),
                     ("sh", "ʃ", False), ("rh", "ʁ", False), ("gh", "ɡ", False), ("zz", "ts", True),
                     ("x", "k s", True)]
_DOUBLE = {"bb": "b", "dd": "d", "ff": "f", "gg": "ɡ", "kk": "k", "ll": "l", "mm": "m", "nn": "n", "pp": "p",
           "rr": "ʁ", "tt": "t"}
_SINGLE = {"b": "b", "c": "k", "d": "d", "f": "f", "g": "ɡ", "h": "h", "j": "j", "k": "k", "l": "l", "m": "m",
           "n": "n", "p": "p", "q": "k", "r": "ʁ", "s": "s", "t": "t", "v": "v", "w": "v", "z": "ts", "ç": "s"}

_BACK = {"a", "aː", "o", "oː", "ɔ", "u", "uː", "ʊ", "aʊ"}
#: основы, где перед «ch» долгая гласная
_LONG_BEFORE_CH = ("buch", "büch", "such", "hoch", "höch", "nach", "näch", "sprach", "spräch", "kuch",
                   "fluch", "tuch", "rach", "brach", "stach", "schmach", "gemach")
#: «шумная + плавная» начинает слог, и гласная перед ними остаётся в открытом слоге
_OPEN_CLUSTERS = {("ɡ", "ʁ"), ("b", "ʁ"), ("d", "ʁ"), ("t", "ʁ"), ("p", "ʁ"), ("k", "ʁ"), ("f", "ʁ"),
                  ("ɡ", "l"), ("b", "l"), ("p", "l"), ("k", "l"), ("f", "l"), ("d", "l")}
#: сочетания, в которых «ch» перед гласной читается [k]
_CH_K = ("cha", "cho", "chr", "chl", "chu")


#: части числительных: «neunzehnhundertvierundfünfzig» = neun|zehn|hundert|vier|und|fünfzig
NUMBER_PARTS = {
    "null": "nʊl", "eins": "aɪns", "ein": "aɪn", "zwei": "tsvaɪ", "drei": "dʁaɪ", "vier": "fiːɐ̯",
    "fünf": "fʏnf", "sechs": "zɛks", "sech": "zɛç", "sieben": "ˈziː.bən", "sieb": "ziːp", "acht": "axt",
    "neun": "nɔʏn", "zehn": "tseːn", "elf": "ɛlf", "zwölf": "tsvœlf", "zwanzig": "ˈtsvan.tsɪç",
    "dreißig": "ˈdʁaɪ.sɪç", "vierzig": "ˈfɪʁ.tsɪç", "fünfzig": "ˈfʏnf.tsɪç", "sechzig": "ˈzɛç.tsɪç",
    "siebzig": "ˈziːp.tsɪç", "achtzig": "ˈax.tsɪç", "neunzig": "ˈnɔʏn.tsɪç", "hundert": "ˈhʊn.dɐt",
    "tausend": "ˈtaʊ.zənt", "und": "ʊnt", "dritt": "dʁɪt", "erst": "eːɐ̯st",
}
#: окончания порядковых и десятилетий
NUMBER_ENDINGS = {"ste": "stə", "sten": "stən", "ster": "stɐ", "stes": "stəs", "stem": "stəm", "te": "tə",
                  "ten": "tən", "ter": "tɐ", "tes": "təs", "tem": "təm", "e": "ə", "en": "ən", "er": "ɐ",
                  "es": "əs", "em": "əm", "ern": "ɐn"}


def _number_parts(word: str) -> list[str] | None:
    """Числительное, разобранное на части, или None, если слово — не числительное."""
    best: dict[int, list[str]] = {0: []}
    for position in range(len(word)):
        if position not in best:
            continue
        for part in NUMBER_PARTS:
            end = position + len(part)
            if word.startswith(part, position) and (end not in best or len(best[end]) > len(best[position]) + 1):
                best[end] = best[position] + [part]
    for end in sorted(best, reverse=True):
        parts = best[end]
        rest = word[end:]
        if not parts or (rest and rest not in NUMBER_ENDINGS):
            continue
        if len(parts) + bool(rest) < 2:
            return None
        return parts + ([rest] if rest else [])
    return None


def _number_word(parts: list[str]) -> list[Syllable]:
    syllables: list[Syllable] = []
    for index, part in enumerate(parts):
        ipa = NUMBER_PARTS.get(part) or NUMBER_ENDINGS.get(part, "")
        sub = parse_ipa(ipa) if part in NUMBER_PARTS else [Syllable(_phonemes(ipa), 0)]
        for syllable in sub:
            if part in NUMBER_ENDINGS:
                # окончание присоединяется к последнему слогу или образует свой
                if any(p in VOWELS for p in syllable.phonemes) and syllables:
                    onset = []
                    while syllable.phonemes and syllable.phonemes[0] not in VOWELS:
                        onset.append(syllable.phonemes.pop(0))
                    syllables[-1].phonemes.extend(onset)
                    syllable.stress = 0
                elif syllables:
                    syllables[-1].phonemes.extend(syllable.phonemes)
                    continue
            elif part == "und":
                syllable.stress = 0
            elif syllable.stress == 1:
                syllable.stress = 1 if index == 0 else 2
            syllables.append(syllable)
    return [s for s in syllables if s.phonemes]


def _phonemes(text: str) -> list[str]:
    result = []
    position = 0
    while position < len(text):
        for symbol in INVENTORY:
            if text.startswith(symbol, position):
                result.append(symbol)
                position += len(symbol)
                break
        else:
            position += 1
    return result


#: так начинаются суффиксы и окончания: остаток с таких букв — не самостоятельная основа
_NOT_A_STEM = ("ier", "ung", "isch", "lich", "ig", "er", "en", "e", "heit", "keit", "chen", "lein", "bar", "sam",
               "los", "nis", "tum", "ling", "ell", "al", "ität", "ion", "ik", "iv", "or", "ent", "ant", "at")


def _split_compound(word: str) -> list[str]:
    """Сложное слово -> части по известным основам.

    Три правила: известная основа в конце («Betriebs|system»), соединительное
    «s» после суффикса («Sicherheits|maßnahmen», «Informations|technik»),
    известная основа в начале с соединительным элементом или без
    («Speicher|medien», «Klasse-n|bibliothek»).
    """
    if "-" in word:
        return [part for chunk in word.split("-") if chunk for part in _split_compound(chunk)]
    plain = word.replace("'", "")
    if "'" in word or len(plain) < 8:
        return [word]
    for stem in STEMS:
        if plain.endswith(stem) and len(plain) - len(stem) >= 4:
            head = word[: len(word) - len(stem)]
            if not re.search(r"[aeiouäöüy]", head):
                continue
            return _split_compound(head) + [word[len(word) - len(stem):]]
    joint = re.search(r"(heit|keit|schaft|ung|ion|tät)s(?=[a-zäöüß]{4,}$)", plain)
    if joint and re.search(r"[aeiouäöüy]", plain[joint.end():]):
        return _split_compound(word[: joint.end()]) + _split_compound(word[joint.end():])
    for stem in STEMS:
        if not plain.startswith(stem):
            continue
        for link in ("es", "en", "s", "n", ""):
            cut = len(stem) + len(link)
            rest = plain[cut:]
            if plain[len(stem):cut] != link or len(rest) < 4 or rest.startswith(_NOT_A_STEM):
                continue
            if not re.search(r"[aeiouäöüy]", rest):
                continue
            return [word[:cut]] + _split_compound(word[cut:])
    return [word]


def _foreign_suffix(word: str) -> tuple[str, int] | None:
    if word in NOT_FOREIGN or len(re.findall(r"[aeiouäöüy]+", word)) < 2:
        return None
    if word.endswith(("ions", "täts")):
        # соединительное «s» в начале сложного слова: «Informations|sicherheit»
        return ("ion", 0) if word.endswith("ions") else ("ität", 0)
    for suffix, back in sorted(FOREIGN_SUFFIXES, key=lambda item: -len(item[0])):
        if word.endswith(suffix) and len(word) > len(suffix) + 1:
            before = word[-len(suffix) - 1]
            if suffix in {"ie", "ien"} and re.search(r"[aeiouäöü]ie[n]?$", word):
                continue
            if suffix.startswith("ell") and (before not in "uinrm" or "quell" in word):
                # «aktuell», «speziell», «maschinell» — да; «Stelle», «Quelle», «Welle» — нет
                continue
            if suffix in {"at", "ate", "aten"} and before in "ah":
                continue
            return suffix, back
    if re.search(r"[^aeiouäöü](ier|ion|ität)[a-zäöüß]{3,}$", word):
        # иноязычная основа внутри сложного слова: «Programmiersprache», «Funktionsweise»
        found = re.search(r"[^aeiouäöü](ier|ion|ität)[a-zäöüß]{3,}$", word)
        return found.group(1), -1
    return None


def _morphs(part: str, foreign: bool) -> tuple[list[str], int | None]:
    """Приставки и суффиксы части слова. Возвращает части и номер ударной приставки."""
    plain = part.replace("'", "")
    if "'" in part:
        return [part], None
    morphs: list[str] = []
    stressed_prefix: int | None = None
    rest = plain
    if not foreign:
        for _ in range(2):
            for prefix in STRESSED_PREFIXES:
                if rest.startswith(prefix) and _good_rest(rest[len(prefix):], prefix) and not morphs:
                    morphs.append(_PREFIX_SPELLING.get(prefix, prefix))
                    stressed_prefix = len(morphs) - 1
                    rest = rest[len(prefix):]
                    break
            else:
                break
        for prefix in UNSTRESSED_PREFIXES:
            if rest.startswith(prefix) and _good_rest(rest[len(prefix):], prefix):
                morphs.append(prefix)
                rest = rest[len(prefix):]
                break
    tail: list[str] = []
    for _ in range(2):
        for suffix in SUFFIXES:
            if rest.endswith(suffix) and len(rest) - len(suffix) >= 3 and re.search(r"[aeiouäöüy]",
                                                                                     rest[:-len(suffix)]):
                tail.insert(0, suffix)
                rest = rest[: -len(suffix)]
                break
            if any(rest.endswith(suffix + ending) for ending in ("en", "e", "er", "s")):
                ending = rest[rest.rindex(suffix) + len(suffix):]
                if len(ending) <= 2 and len(rest) - len(suffix) - len(ending) >= 3:
                    tail.insert(0, suffix + ending)
                    rest = rest[: -len(suffix) - len(ending)]
                    break
        else:
            break
    return morphs + [rest] + tail, stressed_prefix


def _good_rest(rest: str, prefix: str) -> bool:
    """Остаток после приставки похож на основу: есть гласная, начало — допустимое."""
    if len(rest) < 3 or not re.search(r"[aeiouäöüy]", rest):
        return False
    # «be|i…» — это «bei», «ge|h-en» — «gehen»: приставку так не отделить
    if prefix.endswith("e") and rest[0] in "iuhe":
        return False
    if prefix in {"er", "ver", "zer"} and rest[0] in "aeiouäöü" and prefix != "ver":
        return False
    onset = re.match(r"[^aeiouäöüy]*", rest).group(0)
    allowed = {"", "b", "c", "d", "f", "g", "h", "j", "k", "l", "m", "n", "p", "r", "s", "t", "v", "w", "z",
               "bl", "br", "dr", "fl", "fr", "gl", "gn", "gr", "kl", "kn", "kr", "pl", "pr", "sch", "schl",
               "schm", "schn", "schr", "schw", "sp", "spr", "st", "str", "tr", "zw", "ch", "pf", "qu", "ph",
               "th", "sk", "sl", "sm", "sn", "sw", "wr", "ts", "tz", "x", "y"}
    return onset in allowed


def _scan(morphs: list[str]) -> list[_Unit]:
    units: list[_Unit] = []
    for index, morph in enumerate(morphs):
        position = 0
        stress_next = False
        while position < len(morph):
            if morph[position] == "'":
                stress_next = True
                position += 1
                continue
            rest = morph[position:]
            for graph, phon in _VOWEL_GRAPHS:
                if graph == "ie" and re.match(r"ie(nz|nt|ll|nn)", rest) and position > 0:
                    # «Effizienz», «Patient», «speziell»: i и e — разные слоги
                    continue
                if rest.startswith(graph):
                    unit = _Unit(graph, "V", index, phon, stressed=stress_next)
                    if graph in {"aa", "ee", "oo", "ie"}:
                        unit.long = True
                    stress_next = False
                    # гласная + h перед согласной, концом или гласной — долгая, h немая
                    after = morph[position + len(graph):]
                    if after.startswith("h"):
                        # гласная + h — долгая, h немая: «gehen», «Zahl»
                        if graph not in {"ei", "au", "eu", "äu", "ai", "ey", "ay", "äi"}:
                            unit.long = True
                        units.append(unit)
                        position += len(graph) + 1
                        break
                    units.append(unit)
                    position += len(graph)
                    break
            else:
                for graph, phon, shortens in _CONSONANT_GRAPHS:
                    if rest.startswith(graph):
                        units.append(_Unit(graph, "C", index, phon, shortens=shortens))
                        position += len(graph)
                        break
                else:
                    pair = rest[:2]
                    if pair in _DOUBLE:
                        units.append(_Unit(pair, "C", index, _DOUBLE[pair], shortens=True))
                        position += 2
                    elif rest[0] in _SINGLE:
                        units.append(_Unit(rest[0], "C", index, _SINGLE[rest[0]]))
                        position += 1
                    else:
                        position += 1
    return units


def _resolve(units: list[_Unit], morphs: list[str], foreign: bool, first_part: str) -> None:
    """Согласные по соседям: «ch», «s», «v», «st/sp», оглушение, «ti» перед гласной."""
    count = len(units)
    for i, unit in enumerate(units):
        prev = units[i - 1] if i > 0 else None
        nxt = units[i + 1] if i + 1 < count else None
        morph_start = prev is None or prev.morph != unit.morph
        morph_end = nxt is None or nxt.morph != unit.morph
        if unit.kind != "C":
            continue
        graph = unit.graph
        if graph == "ch":
            text = "".join(u.graph for u in units[i:i + 2])
            if morph_start and text.startswith(_CH_K):
                unit.phon = "k"
            elif morph_start and nxt is not None and nxt.kind == "V":
                unit.phon = "ç"
            elif prev is not None and prev.kind == "V" and prev.phon in {"a", "o", "u", "aʊ"} and \
                    morphs[unit.morph] not in {"chen"}:
                unit.phon = "x"
            else:
                unit.phon = "ç"
        elif graph == "s":
            if morph_start and nxt is not None and nxt.graph in {"t", "p"} and (
                    nxt.morph == unit.morph):
                unit.phon = "ʃ"
            elif nxt is not None and nxt.kind == "V" and nxt.morph == unit.morph and (
                    prev is None or prev.kind == "V" or prev.phon in {"l", "m", "n", "ʁ", "ŋ"} or morph_start):
                unit.phon = "z"
            else:
                unit.phon = "s"
        elif graph == "v":
            word = "".join(morphs)
            if i == 0 and word.startswith(NATIVE_V) and not word.startswith(FOREIGN_V):
                unit.phon = "f"
            elif morph_end and nxt is None:
                unit.phon = "f"
            else:
                unit.phon = "v"
        elif graph == "c":
            unit.phon = "ts" if nxt is not None and nxt.graph[:1] in {"e", "i", "ä", "y"} else "k"
        elif graph == "y" or graph == "j":
            unit.phon = "j"
        elif graph == "t" and nxt is not None and nxt.kind == "V" and nxt.graph == "i" and i + 2 < count and \
                units[i + 2].kind == "V" and units[i + 2].graph in {"o", "a", "e", "ö", "u"} and \
                (prev is None or prev.graph not in {"s", "ss"}):
            # «-tion», «-tial», «-tiell», «-tient»: [tsj]
            unit.phon = "ts"
        elif graph in {"b", "d", "g"}:
            voiced = {"b": "b", "d": "d", "g": "ɡ"}[graph]
            unvoiced = {"b": "p", "d": "t", "g": "k"}[graph]
            if nxt is None or morph_end:
                unit.phon = unvoiced
            elif nxt.kind == "C":
                cluster = (voiced, nxt.phon.split(" ")[0])
                onset_ok = cluster in {("b", "l"), ("b", "ʁ"), ("d", "ʁ"), ("ɡ", "l"), ("ɡ", "ʁ"), ("ɡ", "n")}
                starts = prev is None or prev.morph != unit.morph or prev.kind == "V"
                unit.phon = voiced if onset_ok and starts else unvoiced
            else:
                unit.phon = voiced
    # «-ig» в конце части — [ɪç]
    for i, unit in enumerate(units):
        if unit.graph == "g" and i > 0 and units[i - 1].graph == "i" and units[i - 1].kind == "V":
            nxt = units[i + 1] if i + 1 < count else None
            if nxt is None or nxt.morph != unit.morph or nxt.kind == "C":
                # «wichtig», «Königs», «Ewigkeit» — [ɪç]; «Signal», «Siegel» — нет
                if not (nxt is not None and nxt.morph == unit.morph and nxt.graph in {"l", "n", "r"}):
                    unit.phon = "ç"
    # «i» перед гласной в иноязычных окончаниях — неслоговое [j]: «Region», «Kriterium», «Medien»
    for i, unit in enumerate(units):
        if unit.kind == "V" and unit.graph == "i" and i > 0 and units[i - 1].kind == "C" and i + 1 < count:
            nxt = units[i + 1]
            if nxt.kind == "V" and nxt.graph in {"o", "a", "e", "u"} and nxt.morph == unit.morph:
                tail = "".join(u.graph for u in units[i:])
                if re.match(r"i(on|ons|onen|um|en|ell|elle|ellen|eller|al|ale|alen|ent|ente|enten|enz|enzen|ös|a)$",
                            tail) or \
                        re.match(r"ion", tail):
                    unit.kind = "C"
                    unit.phon = "j"


def _length(units: list[_Unit], morphs: list[str]) -> None:
    """Долгота гласных по написанию и по следующим согласным."""
    count = len(units)
    for i, unit in enumerate(units):
        if unit.kind != "V" or unit.long is not None or unit.phon in DIPHTHONGS:
            continue
        following = []
        j = i + 1
        while j < count and units[j].kind == "C" and units[j].morph == unit.morph:
            # неслоговое [j] из «i» («Kriterium») слога не закрывает
            if units[j].graph != "i":
                following.append(units[j])
            j += 1
        vowel_after = j < count and units[j].kind == "V" and units[j].morph == unit.morph
        if following and following[0].graph == "ch":
            # перед «ch» гласная обычно краткая: «machen», «sprechen»; долгая — в немногих основах
            upto = "".join(u.graph for u in units[: i + 2] if u.morph == unit.morph)
            unit.long = upto.endswith(_LONG_BEFORE_CH)
        elif any(c.shortens for c in following[:1]):
            unit.long = False
        elif not following:
            unit.long = True                    # открытый слог: «Da-ten», «so»
        elif len(following) == 1 and len(following[0].phon.split(" ")) == 1:
            if vowel_after:
                unit.long = True                # «le-ben», «Na-me»
            else:
                unit.long = None                # конец слова: решит ударение
        elif vowel_after and len(following) == 2 and \
                (following[0].phon, following[1].phon) in _OPEN_CLUSTERS:
            unit.long = True                    # «Pro-gramm», «Zi-trone», «A-dler»
        else:
            unit.long = False


def _syllables(units: list[_Unit]) -> tuple[list[Syllable], list[int], list[int]]:
    """Слоги по правилу наибольшего начала; не переходят границу частей слова."""
    phonemes: list[tuple[str, int, int]] = []   # (фонема, номер единицы, часть)
    for index, unit in enumerate(units):
        for phon in unit.phon.split(" "):
            if phon:
                phonemes.append((phon, index, unit.morph))
    nuclei = [k for k, (p, _, _) in enumerate(phonemes) if p in VOWELS]
    if not nuclei:
        return [Syllable([p for p, _, _ in phonemes])], [], []
    bounds = [0]
    for left, right in zip(nuclei, nuclei[1:]):
        between = list(range(left + 1, right))
        cut = right
        # граница части слова — граница слога
        boundary = next((k for k in between + [right] if phonemes[k][2] != phonemes[left][2]), None)
        if boundary is not None:
            cut = boundary
        else:
            for start in range(left + 1, right + 1):
                onset = tuple(phonemes[k][0] for k in range(start, right))
                if onset in ONSETS:
                    cut = start
                    break
        bounds.append(cut)
    bounds.append(len(phonemes))
    syllables = []
    owners = []
    for a, b in zip(bounds, bounds[1:]):
        syllables.append(Syllable([p for p, _, _ in phonemes[a:b]]))
        owners.append(next((phonemes[k][1] for k in range(a, b) if phonemes[k][0] in VOWELS), -1))
    morph_of = [phonemes[k][2] for k in nuclei]
    return syllables, owners, morph_of


def _convert_part(part: str) -> Pronunciation:
    """Одна часть сложного слова по правилам."""
    plain = part.replace("'", "")
    suffix = _foreign_suffix(plain) if "'" not in part else None
    foreign = suffix is not None
    morphs, stressed_prefix = _morphs(part, foreign)
    units = _scan(morphs)
    _resolve(units, morphs, foreign, plain)
    _length(units, morphs)
    syllables, owners, morph_of = _syllables(units)
    if not owners:
        return Pronunciation(plain, syllables)

    # ударение
    stressed = None
    for k, owner in enumerate(owners):
        if owner >= 0 and units[owner].stressed:
            stressed = k
            break
    if stressed is None and suffix is not None:
        name, back = suffix
        if back == -1:
            # ударная основа внутри слова: последний слог с «ier», «ion», «ität»
            target = {"ier": "iː", "ion": "o", "ität": "ɛ"}[name]
            candidates = [k for k, s in enumerate(syllables) if target in "".join(s.phonemes)]
            stressed = candidates[0] if candidates else None
        else:
            stressed = max(0, len(syllables) - 1 - back)
    root = next((k for k, m in enumerate(morph_of) if morphs[m] not in UNSTRESSED_PREFIXES
                 and m != stressed_prefix), 0)
    if stressed is None and stressed_prefix is not None:
        stressed = next((k for k, m in enumerate(morph_of) if m == stressed_prefix), 0)
        # у основы после ударной приставки — побочное ударение: «ˈAus|ˌgabe»
        if root != stressed and root < len(syllables):
            syllables[root].stress = 2
    if stressed is None:
        stressed = root
    stressed = min(stressed, len(syllables) - 1)
    syllables[stressed].stress = 1

    # качество гласных: долгие, краткие, редуцированные
    last = len(syllables) - 1
    for k, syllable in enumerate(syllables):
        owner = owners[k]
        if owner < 0:
            continue
        unit = units[owner]
        morph = morphs[unit.morph]
        accented = syllable.stress > 0
        phon = unit.phon
        # последний слог своей части слова: «Spra|che», «setz|er» — здесь «e» редуцируется
        morph_last = k == len(morph_of) - 1 or morph_of[k + 1] != unit.morph if k < len(morph_of) else True
        if phon in DIPHTHONGS or phon == "iː" and unit.graph == "ie":
            vowel = phon
        elif unit.graph == "e" and not accented and morph in {"be", "ge"}:
            vowel = "ə"
        elif unit.graph == "e" and morph in {"ver", "er", "zer", "ent", "emp"}:
            vowel = "ɛ"
        else:
            long = unit.long
            if long is None:
                long = accented and k == last
            vowel = _quality(phon, long)
            if not accented and vowel in LONG_VOWELS:
                vowel = TENSE.get(vowel, vowel)
            if unit.graph == "e" and not accented:
                coda = syllable.phonemes[syllable.phonemes.index(phon) + 1:] if phon in syllable.phonemes else []
                ending = k == last and k > 0 and set(coda) <= {"n", "ʁ", "l", "m", "s", "t"}
                if (not foreign and morph_last and k > 0) or ending:
                    vowel = "ə"                 # «Sprache», «Daten», «setzer», «Faktoren»
                elif foreign and long:
                    vowel = "e"                 # «Element», «Theorie»
        index = syllable.phonemes.index(phon) if phon in syllable.phonemes else None
        if index is not None:
            syllable.phonemes[index] = vowel
    _r_vocalization(syllables)
    return Pronunciation(plain, syllables)


def _quality(letter_phon: str, long: bool) -> str:
    table = {"a": ("aː", "a"), "e": ("eː", "ɛ"), "i": ("iː", "ɪ"), "o": ("oː", "ɔ"), "u": ("uː", "ʊ"),
             "ɛ": ("ɛː", "ɛ"), "ø": ("øː", "œ"), "y": ("yː", "ʏ"), "aː": ("aː", "a"), "eː": ("eː", "ɛ"),
             "oː": ("oː", "ɔ"), "iː": ("iː", "ɪ"), "uː": ("uː", "ʊ")}
    pair = table.get(letter_phon)
    if pair is None:
        return letter_phon
    return pair[0] if long else pair[1]


def _r_vocalization(syllables: list[Syllable]) -> None:
    """«r» в конце слога — неслоговое [ɐ̯]; «ər» — [ɐ]."""
    for syllable in syllables:
        phonemes = syllable.phonemes
        nucleus = next((k for k, p in enumerate(phonemes) if p in VOWELS), None)
        if nucleus is None:
            continue
        for k in range(nucleus + 1, len(phonemes)):
            if phonemes[k] == "ʁ":
                if k == nucleus + 1 and phonemes[nucleus] == "ə":
                    phonemes[nucleus] = "ɐ"
                    phonemes[k] = ""
                else:
                    phonemes[k] = "ɐ̯"
        syllable.phonemes = [p for p in phonemes if p]


@lru_cache(maxsize=20000)
def _cached(word: str) -> tuple[str, tuple[tuple[tuple[str, ...], int], ...]]:
    pron = _transcribe(word)
    return pron.source, tuple((tuple(s.phonemes), s.stress) for s in pron.syllables)


def transcribe(word: str) -> Pronunciation:
    """Произношение одного слова (или записи из словаря произношения)."""
    source, cached = _cached(word)
    return Pronunciation(word, [Syllable(list(p), stress) for p, stress in cached], source)


def _transcribe(word: str) -> Pronunciation:
    lower = word.lower().strip("-")
    if not lower:
        return Pronunciation(word)
    if lower.replace("'", "") in EXCEPTIONS and "'" not in lower:
        return Pronunciation(word, _glottal(parse_ipa(EXCEPTIONS[lower])), "exception")
    number = _number_parts(lower) if "'" not in lower else None
    if number is not None:
        return Pronunciation(word, _number_word(number), "number")
    parts = _split_compound(lower)
    syllables: list[Syllable] = []
    explicit = "'" in lower
    for number, part in enumerate(parts):
        key = part.replace("'", "")
        if key in EXCEPTIONS and "'" not in part:
            sub = parse_ipa(EXCEPTIONS[key])
        else:
            sub = _convert_part(part).syllables
        if number > 0 or (explicit and "'" not in part):
            for syllable in sub:
                if syllable.stress == 1:
                    syllable.stress = 2 if not explicit else 0
        syllables.extend(sub)
    if not any(s.stress == 1 for s in syllables) and syllables:
        first = next((s for s in syllables if s.stress == 2), syllables[0])
        first.stress = 1
    return Pronunciation(word, _glottal(syllables))


def _glottal(syllables: list[Syllable]) -> list[Syllable]:
    """Голосовая смычка перед гласной в начале слова: «Ende» [ˈʔɛn.də]."""
    if syllables and syllables[0].phonemes and syllables[0].phonemes[0] in VOWELS:
        syllables[0].phonemes.insert(0, "ʔ")
    return syllables


def transcribe_text(text: str) -> list[Pronunciation]:
    """Произношение всех слов текста (знаки препинания пропускаются)."""
    return [transcribe(word) for word in re.findall(r"[A-Za-zÄÖÜäöüßÀ-ÿ'][A-Za-zÄÖÜäöüßÀ-ÿ'-]*", text)]


# --- для голосов Piper ----------------------------------------------------------------------
#
# Голоса Piper обучены на транскрипциях eSpeak NG. Чтобы слово из словаря произношения
# («Mä'schien 'Lörning») прозвучало так, как записано, его транскрипция переводится в
# обозначения eSpeak: «r» в начале слога — [r], после гласной — [ɾ], безударное «-er» —
# [ɜ], долгое «a» — [ɑː]; знак ударения стоит прямо перед гласной.

_ESPEAK = {"ʁ": "r", "ɐ̯": "ɾ", "ɐ": "ɜ", "aː": "ɑː", "ɔʏ": "ɔø", "ʔ": "", "oʊ": "oʊ"}


def to_espeak(pronunciation: Pronunciation) -> str:
    """Транскрипция слова в обозначениях eSpeak NG: «ˈSoftwär» -> «zˈɔftvɛɾ»."""
    out = []
    for syllable in pronunciation.syllables:
        mark = "ˈ" if syllable.stress == 1 else "ˌ" if syllable.stress == 2 else ""
        for phoneme in syllable.phonemes:
            symbol = _ESPEAK.get(phoneme, phoneme)
            if phoneme in VOWELS and mark:
                out.append(mark)
                mark = ""
            out.append(symbol)
    return "".join(out)

