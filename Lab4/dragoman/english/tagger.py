"""Морфологическая разметка: теги частей речи Penn Treebank.

Теггер — усреднённый перцептрон с жадным проходом слева направо (Collins,
2002; Honnibal, 2013): тег слова выбирается по самому слову, его приставке и
окончанию, по соседним словам и по двум уже выбранным тегам слева. Частые
однозначные слова («the», «of», «is») размечаются по словарю, без перцептрона:
это быстрее и не хуже.

Признаки окончания решают судьбу незнакомых слов: «-ization» почти всегда у
существительного, «-ed» после «is» — у причастия, «-ly» — у наречия. Поэтому
теггер разумно размечает и слова, которых не было в обучающих корпусах, —
а в научных текстах таких много.
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from pathlib import Path

from dragoman.english.perceptron import AveragedPerceptron, load_json, save_json, shuffled

START = ("-START-", "-START2-")
END = ("-END-", "-END2-")


def normalize(word: str) -> str:
    if word.isdigit() and len(word) == 4:
        return "!YEAR"
    if word[:1].isdigit():
        return "!DIGITS"
    return word.lower()


def shape(word: str) -> str:
    """Вид слова: «Xx» — с заглавной, «X» — прописными, «d» — цифры, «x-x» — через дефис."""
    out = []
    for ch in word:
        kind = "X" if ch.isupper() else "x" if ch.isalpha() else "d" if ch.isdigit() else ch
        if not out or out[-1] != kind:
            out.append(kind)
    return "".join(out)[:6]


class Tagger:
    MODEL_NAME = "tagger.json.gz"

    def __init__(self) -> None:
        self.model = AveragedPerceptron()
        self.tagdict: dict[str, str] = {}

    @property
    def classes(self) -> list[str]:
        return list(self.model.classes)

    # --- признаки ------------------------------------------------------------------

    @staticmethod
    def features(i: int, word: str, context: list[str], prev: str, prev2: str) -> list[str]:
        """Признаки слова i; context — нормализованные слова с полями START и END."""
        c = i + len(START)
        lower = context[c]
        f = [
            "bias",
            "w=" + lower,
            "s3=" + word[-3:].lower(),
            "s2=" + word[-2:].lower(),
            "p1=" + word[0],
            "sh=" + shape(word),
            "t-1=" + prev,
            "t-2=" + prev2,
            "t-1t-2=" + prev + " " + prev2,
            "t-1w=" + prev + " " + lower,
            "w-1=" + context[c - 1],
            "s3-1=" + context[c - 1][-3:],
            "w-2=" + context[c - 2],
            "w+1=" + context[c + 1],
            "s3+1=" + context[c + 1][-3:],
            "w+2=" + context[c + 2],
            "ww+1=" + lower + " " + context[c + 1],
            "w-1w=" + context[c - 1] + " " + lower,
            "t-1s3=" + prev + " " + word[-3:].lower(),
        ]
        if len(word) > 4:
            f.append("s4=" + word[-4:].lower())
            f.append("p3=" + word[:3].lower())
        if i == 0:
            f.append("first sh=" + shape(word))
        if "-" in word[1:-1]:
            f.append("hyphen s=" + word.rsplit("-", 1)[-1][-3:].lower())
        return f

    # --- разметка ---------------------------------------------------------------------

    def _known(self, i: int, word: str) -> str | None:
        """Тег частого однозначного слова; первое слово предложения ищется и строчным."""
        tag = self.tagdict.get(word)
        if tag is None and i == 0:
            tag = self.tagdict.get(word.lower())
        return tag

    def tag(self, words: list[str], questions: bool = True) -> list[str]:
        tags = self._tag(words, {})
        if questions and words and words[-1] == "?":
            forced = self._question_fixes(words, tags)
            if forced:
                tags = self._tag(words, forced)
        if questions and words and words[-1] in {".", "!"}:
            forced = self._verbless_fixes(words, tags)
            if forced:
                tags = self._tag(words, forced)
        return tags

    def _verbless_fixes(self, words: list[str], tags: list[str]) -> dict[int, str]:
        """«The system manages software resources.» — теггер принял «manages» за мн. ч. существительного,
        и в предложении не осталось глагола. Первое после существительного слово, известное корпусу как
        глагол в личной форме, становится глаголом."""
        # глагола в личной форме нет (герундий и причастие не в счёт: «Training involves adjusting …»)
        if len(words) < 4 or any(t in {"VBZ", "VBP", "VBD", "MD"} for t in tags):
            return {}
        context = list(START) + [normalize(w) for w in words] + list(END)
        for i in range(1, len(words) - 1):
            if words[i].lower() == "like" and tags[i] == "IN" and tags[i - 1] in {"NNS", "PRP", "NNP"} and                     tags[i + 1] in {"DT", "NN", "NNS", "PRP", "PRP$", "JJ", "NNP"}:
                return {i: "VBP" if tags[i - 1] != "NNP" else "VBZ"}   # «Most users like it»
            final = i + 1 == len(words) - 1 and words[i + 1] in {".", "!"}
            if tags[i] in {"NNS", "NN", "JJ"} and tags[i - 1] in {"NN", "NNS", "NNP", "PRP", "VBG"} and                     (tags[i + 1] in {"DT", "NN", "NNS", "JJ", "PRP", "PRP$", "IN", "RB", "CD", "VBG"} or
                     final and tags[i] == "NNS" and tags[0] in {"DT", "PRP", "PRP$"}):
                scores = self.model.scores(self.features(i, words[i], context, tags[i - 1],
                                                         tags[i - 2] if i > 1 else START[0]))
                if tags[i] == "JJ":
                    # «These plays present contradictions»: после мн. ч. — глагол в форме VBP
                    if tags[i - 1] not in {"NNS", "PRP"}:
                        continue
                    verb = "VBP"
                    if scores.get(verb, 0.0) > 0 and scores.get(verb, 0.0) >= 0.4 * scores.get("JJ", 0.0):
                        return {i: verb}
                    continue
                verb = "VBZ" if tags[i] == "NNS" else max(("VBP", "VBD"), key=lambda t: scores.get(t, 0.0))
                # глагол — второй по оценке модели, и оценка не намного меньше
                if scores.get(verb, 0.0) > 0 and scores.get(verb, 0.0) >= 0.5 * scores.get(tags[i], 0.0):
                    return {i: verb}
        return {}

    def _tag(self, words: list[str], forced: dict[int, str]) -> list[str]:
        context = list(START) + [normalize(w) for w in words] + list(END)
        prev, prev2 = START
        tags = []
        for i, word in enumerate(words):
            tag = forced.get(i) or self._known(i, word)
            if not tag:
                tag = self.model.predict(self.features(i, word, context, prev, prev2))
            tags.append(tag)
            prev2, prev = prev, tag
        return tags

    def _seen_as(self, word: str, tags: set[str]) -> str | None:
        """Тег из tags, с которым слово встречалось в обучающем корпусе (вес признака слова > 0)."""
        row = self.model.weights.get("w=" + normalize(word), {})
        best = max(tags, key=lambda t: row.get(t, 0.0))
        return best if row.get(best, 0.0) > 0 else None

    def _question_fixes(self, words: list[str], tags: list[str]) -> dict[int, str]:
        """Вопросы в корпусах редки, и жадный теггер путается после вспомогательного глагола:
        «What does the parser produce?» — «produce» он считает частью «parser produce».
        Правило: после do/does/did (или be в вопросе) подлежащее — именная группа; если она
        «съела» глагол (два существительных подряд, второе — в форме NN), а слово известно
        корпусу как глагол (как прилагательное — после be), тег исправляется."""
        lowers = [w.lower() for w in words]
        for a, lower in enumerate(lowers[:4]):
            if lower not in {"do", "does", "did", "is", "are", "was", "were"} or not tags[a].startswith("VB"):
                continue
            if a > 0 and not all(t in {"WDT", "WP", "WRB", "WP$", "NN", "NNS", "JJ", "RB"} for t in tags[:a]):
                continue
            j = a + 1
            if j < len(words) and tags[j] == "PRP":
                start = end = j + 1
            else:
                while j < len(words) and tags[j] in {"DT", "PRP$", "JJ", "CD", "POS"}:
                    j += 1
                start = end = j
            while end < len(words) and tags[end] in {"NN", "NNS", "NNP"}:
                end += 1
            nouns = end - start
            last = end - 1
            if nouns < 1 or tags[last] != "NN" or (nouns < 2 and tags[start - 1] != "PRP"):
                continue
            if lower in {"do", "does", "did"}:
                tag = self._seen_as(words[last], {"VB"})
            else:
                tag = self._seen_as(words[last], {"JJ", "JJR", "VBN", "VBG"}) if words[end] == "?" else None
            if tag:
                return {last: tag}
        return {}

    # --- обучение -------------------------------------------------------------------------

    def _make_tagdict(self, sentences: list[tuple[list[str], list[str]]]) -> None:
        counts: dict[str, Counter] = defaultdict(Counter)
        for words, tags in sentences:
            for word, tag in zip(words, tags):
                counts[word][tag] += 1
        self.tagdict = {}
        for word, tag_counts in counts.items():
            tag, mode = tag_counts.most_common(1)[0]
            total = sum(tag_counts.values())
            if total >= 20 and mode / total >= 0.97:
                self.tagdict[word] = tag

    def train(self, sentences: list[tuple[list[str], list[str]]], epochs: int, seed: int = 4,
              log=print) -> None:
        self._make_tagdict(sentences)
        self.model = AveragedPerceptron(sorted({tag for _, tags in sentences for tag in tags}))
        for epoch in range(epochs):
            started = time.perf_counter()
            correct = total = 0
            for words, gold in shuffled(sentences, seed, epoch):
                context = list(START) + [normalize(w) for w in words] + list(END)
                prev, prev2 = START
                for i, word in enumerate(words):
                    guess = self._known(i, word)
                    if not guess:
                        features = self.features(i, word, context, prev, prev2)
                        guess = self.model.predict(features)
                        self.model.update(gold[i], guess, features)
                    prev2, prev = prev, guess
                    correct += guess == gold[i]
                    total += 1
            log(f"    теггер, эпоха {epoch + 1}: {100 * correct / max(1, total):.2f} % "
                f"на обучающих ({time.perf_counter() - started:.0f} с)")
        self.model.average()

    # --- сохранение ----------------------------------------------------------------------------

    def save(self, directory: Path, prune: float = 0.05, digits: int = 2) -> Path:
        for row in self.model.weights.values():
            for cls in row:
                row[cls] = round(row[cls], digits)
        self.model.prune(prune)
        path = Path(directory) / self.MODEL_NAME
        save_json({"tagdict": self.tagdict, "model": self.model.to_dict(digits)}, path)
        return path

    @classmethod
    def load(cls, directory: Path) -> "Tagger":
        data = load_json(Path(directory) / cls.MODEL_NAME)
        tagger = cls()
        tagger.tagdict = data["tagdict"]
        tagger.model = AveragedPerceptron.from_dict(data["model"])
        return tagger
