"""Начальная форма английского слова (лемма) по слову и его тегу.

Лемматизатор не написан правилами вручную, а выучен по тем же корпусам, что и
теггер. Для каждого примера «слово, тег → лемма» запоминается, какое окончание
отрезать и какое приписать («studies»/NNS: «ies» → «y», «running»/VBG: «nning»
→ «n», «made»/VBD: «de» → «ke»). Правило привязано к окончанию слова: для нового
слова берётся самое длинное окончание, по которому в корпусе есть уверенное
правило, — так «debugging» становится «debug», хотя в корпусах этого слова нет.

Неправильные формы, которые правилом не выводятся («went» → «go», «men» →
«man», «ca» → «can»), хранятся списком исключений.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

#: теги, у которых лемма отличается от слова; у остальных лемма — само слово
INFLECTED = {"NNS", "NNPS", "VBZ", "VBD", "VBN", "VBG", "VBP", "VB", "JJR", "JJS", "RBR", "RBS",
             "PRP", "PRP$", "MD", "POS", "WP$", "DT", "RB", "NN", "JJ", "IN"}
PROPER = {"NNP", "NNPS"}
MAX_SUFFIX = 7
MIN_EVIDENCE = 2


def _rule(form: str, lemma: str) -> tuple[str, str]:
    """(что отрезать, что приписать) — переход от слова к лемме."""
    prefix = 0
    for a, b in zip(form, lemma):
        if a != b:
            break
        prefix += 1
    return form[prefix:], lemma[prefix:]


class Lemmatizer:
    MODEL_NAME = "lemmatizer.json"

    def __init__(self) -> None:
        #: тег -> окончание -> (отрезать, приписать)
        self.rules: dict[str, dict[str, tuple[str, str]]] = {}
        #: «слово|тег» -> лемма
        self.exceptions: dict[str, str] = {}

    # --- применение ---------------------------------------------------------------

    def _by_rule(self, lower: str, tag: str) -> str:
        table = self.rules.get(tag)
        if not table:
            return lower
        for k in range(min(MAX_SUFFIX, len(lower)), -1, -1):
            suffix = lower[-k:] if k else ""
            rule = table.get(suffix)
            if rule is None:
                continue
            strip, add = rule
            if lower.endswith(strip) and len(lower) - len(strip) + len(add) >= 2:
                return lower[: len(lower) - len(strip)] + add
        return lower

    #: существительные и прилагательные на -ed, которые теггер иногда принимает за причастия
    ED_WORDS = {"hatred", "kindred", "sacred", "naked", "wicked", "rugged", "ragged", "crooked", "wretched",
                "beloved", "hundred", "bed", "seed", "need", "deed", "red", "shed", "creed", "speed", "breed"}

    def lemma(self, form: str, tag: str) -> str:
        lower = form.lower()
        known = self.exceptions.get(f"{lower}|{tag}")
        if known is not None:
            return known
        if lower in self.ED_WORDS:
            return lower                                   # «hatred», а не «hatr»
        if tag in {"NNS", "VBZ"} and lower.endswith("olves") and not lower.endswith("wolves"):
            return lower[:-1]                              # involves → involve, а не «involf» (wolves → wolf)
        if tag in PROPER:
            if tag == "NNPS" and len(form) > 3 and form.endswith("s"):
                return form[:-2] + "y" if form.endswith("ies") else form[:-1]
            return form
        if not any(ch.isalpha() for ch in form):
            return form
        if form == "I":
            return "I"
        return self._by_rule(lower, tag)

    def candidates(self, form: str, tag: str) -> list[str]:
        """Лемма и запасные варианты: «using» → «use», «us»: словарь выбирает известную."""
        first = self.lemma(form, tag)
        result = [first]
        lower = form.lower()
        if tag in {"VBG", "VBD", "VBN"}:
            stem = lower[:-3] if tag == "VBG" and lower.endswith("ing") else lower[:-2] if lower.endswith("ed") else ""
            for option in (stem, stem + "e", stem[:-1] if len(stem) > 2 and stem[-1] == stem[-2] else ""):
                if option and option not in result:
                    result.append(option)
        if tag in {"NNS", "VBZ"} and lower.endswith("s"):
            for option in (lower[:-1], lower[:-2] if lower.endswith("es") else "",
                           lower[:-3] + "y" if lower.endswith("ies") else ""):
                if option and option not in result:
                    result.append(option)
        if lower not in result:
            result.append(lower)
        return result

    # --- обучение ---------------------------------------------------------------------

    def train(self, examples: list[tuple[str, str, str]]) -> dict:
        """examples — тройки (слово, тег, лемма) из корпусов. Возвращает сводку."""
        counts: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
        by_form: dict[str, Counter] = defaultdict(Counter)
        for form, tag, lemma in examples:
            if tag in PROPER or not any(ch.isalpha() for ch in form):
                continue
            lower, lemma_lower = form.lower(), lemma.lower()
            by_form[f"{lower}|{tag}"][lemma_lower if lemma != "I" else "I"] += 1
            if tag not in INFLECTED:
                continue
            rule = _rule(lower, lemma_lower)
            for k in range(0, min(MAX_SUFFIX, len(lower)) + 1):
                suffix = lower[-k:] if k else ""
                counts[tag][suffix][rule] += 1

        self.rules = {}
        for tag, table in counts.items():
            chosen: dict[str, tuple[str, str]] = {}
            for suffix, rules in table.items():
                rule, count = rules.most_common(1)[0]
                if count >= MIN_EVIDENCE or suffix == "":
                    chosen[suffix] = rule
            # окончание, правило которого совпадает с правилом более короткого, лишнее
            pruned = {}
            for suffix, rule in chosen.items():
                shorter = None
                for k in range(len(suffix) - 1, -1, -1):
                    if suffix[len(suffix) - k:] in chosen:
                        shorter = chosen[suffix[len(suffix) - k:]] if k else chosen.get("")
                        break
                if suffix == "" or shorter != rule:
                    pruned[suffix] = rule
            self.rules[tag] = pruned

        self.exceptions = {}
        for key, lemmas in by_form.items():
            lower, tag = key.rsplit("|", 1)
            lemma, count = lemmas.most_common(1)[0]
            if count / sum(lemmas.values()) < 0.6:
                continue
            if self._by_rule(lower, tag) != lemma:
                self.exceptions[key] = lemma
        return {"tags": len(self.rules), "rules": sum(len(t) for t in self.rules.values()),
                "exceptions": len(self.exceptions)}

    # --- сохранение -------------------------------------------------------------------------

    def save(self, directory: Path) -> Path:
        path = Path(directory) / self.MODEL_NAME
        data = {"rules": {tag: {s: list(r) for s, r in table.items()} for tag, table in self.rules.items()},
                "exceptions": self.exceptions}
        path.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                        encoding="utf-8")
        return path

    @classmethod
    def load(cls, directory: Path) -> "Lemmatizer":
        data = json.loads((Path(directory) / cls.MODEL_NAME).read_text(encoding="utf-8"))
        lemmatizer = cls()
        lemmatizer.rules = {tag: {s: tuple(r) for s, r in table.items()} for tag, table in data["rules"].items()}
        lemmatizer.exceptions = data["exceptions"]
        return lemmatizer
