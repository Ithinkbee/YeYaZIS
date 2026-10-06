"""Синтаксический анализ: дерево зависимостей английского предложения.

Анализатор переходный (transition-based), система переходов arc-hybrid
(Kuhlmann и др., 2011). Слова читаются слева направо; состояние — стек
разобранных частей и буфер ещё не прочитанных слов. На каждом шаге
классификатор выбирает один из трёх переходов:

    SHIFT  — перенести первое слово буфера в стек;
    LEFT   — слово с вершины стека становится зависимым первого слова буфера;
    RIGHT  — слово с вершины стека становится зависимым слова под ним.

Корень предложения — условное слово ROOT в конце буфера (Ballesteros и Nivre,
2013): к нему присоединяется последнее оставшееся в стеке слово, поэтому у
дерева всегда ровно одна вершина. Разбор занимает 2n шагов — линейное время.

Классификатор — усреднённый перцептрон (Honnibal, 2013). Обучается он с
динамическим оракулом (Goldberg и Nivre, 2012): на каждом шаге известно, какие
переходы не теряют ни одной верной дуги, и после ошибки обучение продолжается
из того состояния, куда пришёл сам анализатор, — так он учится исправлять
последствия собственных ошибок, а не только идти по эталону.

Названия отношений (nsubj, obj, amod, …) расставляет отдельный классификатор
по готовому дереву: у него перед глазами всё дерево, в том числе зависимые
обоих слов дуги (у существительного с предлогом — «obl», с «by» при
страдательном глаголе — «obl:agent»).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from dragoman.english.perceptron import AveragedPerceptron, load_json, save_json, shuffled

SHIFT, RIGHT, LEFT = 0, 1, 2
MOVES = (SHIFT, RIGHT, LEFT)
MOVE_NAMES = {SHIFT: "SHIFT", RIGHT: "RIGHT", LEFT: "LEFT"}


@dataclass
class Parse:
    """Частично построенное дерево: вершины и зависимые слева и справа."""

    n: int
    heads: list[int] = field(default_factory=list)
    lefts: list[list[int]] = field(default_factory=list)
    rights: list[list[int]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.heads = [-1] * self.n
        self.lefts = [[] for _ in range(self.n + 1)]
        self.rights = [[] for _ in range(self.n + 1)]

    def add(self, head: int, child: int) -> None:
        self.heads[child] = head
        if child < head:
            self.lefts[head].append(child)
        else:
            self.rights[head].append(child)


def valid_moves(b: int, n: int, depth: int) -> list[int]:
    moves = []
    if b < n:
        moves.append(SHIFT)
    if depth >= 2:
        moves.append(RIGHT)
    # к ROOT присоединяется только последнее слово в стеке: вершина одна
    if depth >= 1 and (b < n or depth == 1):
        moves.append(LEFT)
    return moves


def apply(move: int, b: int, stack: list[int], parse: Parse) -> int:
    if move == SHIFT:
        stack.append(b)
        return b + 1
    if move == RIGHT:
        child = stack.pop()
        parse.add(stack[-1], child)
        return b
    child = stack.pop()
    parse.add(b, child)
    return b


def move_costs(b: int, n: int, stack: list[int], gold: list[int]) -> dict[int, int]:
    """Сколько верных дуг теряет каждый допустимый переход (динамический оракул)."""
    costs = {}
    depth = len(stack)
    if b < n:
        lost = 0
        if gold[b] in stack[:-1]:
            lost += 1
        lost += sum(1 for s in stack if gold[s] == b)
        costs[SHIFT] = lost
    if depth >= 1:
        s0 = stack[-1]
        dependents = sum(1 for d in range(b, n) if gold[d] == s0)
        if depth >= 2:
            s1 = stack[-2]
            costs[RIGHT] = dependents + (1 if gold[s0] != s1 and b <= gold[s0] <= n else 0)
        if b < n or depth == 1:
            reachable = (depth >= 2 and gold[s0] == stack[-2]) or b < gold[s0] <= n
            costs[LEFT] = dependents + (1 if gold[s0] != b and reachable else 0)
    return costs


def features(words: list[str], tags: list[str], b: int, n: int, stack: list[int], parse: Parse) -> list[str]:
    """Признаки состояния: слова и теги стека, буфера и уже найденных зависимых."""
    depth = len(stack)

    def word(i: int) -> str:
        return words[i] if 0 <= i < n else ("<root>" if i == n else "")

    def tag(i: int) -> str:
        return tags[i] if 0 <= i < n else ("ROOT" if i == n else "")

    s0 = stack[-1] if depth >= 1 else -1
    s1 = stack[-2] if depth >= 2 else -1
    s2 = stack[-3] if depth >= 3 else -1
    n0 = b
    n1 = b + 1 if b + 1 <= n else -1
    n2 = b + 2 if b + 2 <= n else -1

    def kids(i: int, side: list[list[int]]) -> tuple[int, int, int]:
        if i < 0:
            return 0, -1, -1
        children = side[i]
        if not children:
            return 0, -1, -1
        return len(children), children[-1], children[-2] if len(children) > 1 else -1

    vn0b, n0b1, n0b2 = kids(n0, parse.lefts)
    vs0b, s0b1, s0b2 = kids(s0, parse.lefts)
    vs0f, s0f1, s0f2 = kids(s0, parse.rights)

    Ws0, Ws1, Ws2 = word(s0), word(s1), word(s2)
    Ts0, Ts1, Ts2 = tag(s0), tag(s1), tag(s2)
    Wn0, Wn1, Wn2 = word(n0), word(n1), word(n2)
    Tn0, Tn1, Tn2 = tag(n0), tag(n1), tag(n2)
    Wn0b1, Wn0b2, Tn0b1, Tn0b2 = word(n0b1), word(n0b2), tag(n0b1), tag(n0b2)
    Ws0b1, Ws0b2, Ts0b1, Ts0b2 = word(s0b1), word(s0b2), tag(s0b1), tag(s0b2)
    Ws0f1, Ws0f2, Ts0f1, Ts0f2 = word(s0f1), word(s0f2), tag(s0f1), tag(s0f2)
    distance = str(min(n0 - s0, 5)) if s0 >= 0 else "0"

    f = ["bias"]
    for prefix, value in (("wn0", Wn0), ("wn1", Wn1), ("wn2", Wn2), ("ws0", Ws0), ("ws1", Ws1), ("ws2", Ws2),
                          ("wn0b1", Wn0b1), ("wn0b2", Wn0b2), ("ws0b1", Ws0b1), ("ws0b2", Ws0b2),
                          ("ws0f1", Ws0f1), ("ws0f2", Ws0f2)):
        if value:
            f.append(prefix + "=" + value)
    for prefix, value in (("tn0", Tn0), ("tn1", Tn1), ("tn2", Tn2), ("ts0", Ts0), ("ts1", Ts1), ("ts2", Ts2),
                          ("tn0b1", Tn0b1), ("tn0b2", Tn0b2), ("ts0b1", Ts0b1), ("ts0b2", Ts0b2),
                          ("ts0f1", Ts0f1), ("ts0f2", Ts0f2)):
        if value:
            f.append(prefix + "=" + value)
    f += [
        "wtn0=" + Wn0 + "/" + Tn0,
        "wtn1=" + Wn1 + "/" + Tn1,
        "wtn2=" + Wn2 + "/" + Tn2,
        "wts0=" + Ws0 + "/" + Ts0,
        "ws0 wn0=" + Ws0 + " " + Wn0,
        "wtn0 ws0=" + Wn0 + "/" + Tn0 + " " + Ws0,
        "wtn0 ts0=" + Wn0 + "/" + Tn0 + " " + Ts0,
        "wts0 wn0=" + Ws0 + "/" + Ts0 + " " + Wn0,
        "wts0 tn0=" + Ws0 + "/" + Ts0 + " " + Tn0,
        "wts0 wtn0=" + Ws0 + "/" + Ts0 + " " + Wn0 + "/" + Tn0,
        "ts0 tn0=" + Ts0 + " " + Tn0,
        "tn0 tn1=" + Tn0 + " " + Tn1,
        "ttt0=" + Tn0 + " " + Tn1 + " " + Tn2,
        "ttt1=" + Ts0 + " " + Tn0 + " " + Tn1,
        "ttt2=" + Ts0 + " " + Ts1 + " " + Tn0,
        "ttt3=" + Ts0 + " " + Ts0f1 + " " + Tn0,
        "ttt4=" + Ts0 + " " + Tn0 + " " + Tn0b1,
        "ttt5=" + Ts0 + " " + Ts0b1 + " " + Ts0b2,
        "ttt6=" + Ts0 + " " + Ts0f1 + " " + Ts0f2,
        "ttt7=" + Tn0 + " " + Tn0b1 + " " + Tn0b2,
        "ttt8=" + Ts0 + " " + Ts1 + " " + Ts2,
        "ttt9=" + Ts1 + " " + Ts0 + " " + Ts0b1,
        "vws0f=" + Ws0 + " " + str(vs0f),
        "vws0b=" + Ws0 + " " + str(vs0b),
        "vwn0b=" + Wn0 + " " + str(vn0b),
        "vts0f=" + Ts0 + " " + str(vs0f),
        "vts0b=" + Ts0 + " " + str(vs0b),
        "vtn0b=" + Tn0 + " " + str(vn0b),
        "dws0=" + Ws0 + " " + distance,
        "dwn0=" + Wn0 + " " + distance,
        "dts0=" + Ts0 + " " + distance,
        "dtn0=" + Tn0 + " " + distance,
        "dtt=" + Tn0 + Ts0 + " " + distance,
        "dww=" + Wn0 + " " + Ws0 + " " + distance,
    ]
    return f


# --- разметка отношений ------------------------------------------------------------------

#: служебные слова, которые разметчик видит среди зависимых слова
FUNCTION_TAGS = {"IN", "TO", "DT", "PDT", "POS", "MD", "WDT", "WP", "WP$", "WRB", "CC", "RP", "EX", "PRP$"}
AUX_LEMMAS = {"be", "is", "are", "was", "were", "been", "being", "am", "'s", "'re", "'m",
              "have", "has", "had", "do", "does", "did", "get", "got", "gets"}


def _bucket(distance: int) -> str:
    distance = abs(distance)
    return "1" if distance == 1 else "2" if distance == 2 else "3-4" if distance <= 4 else "5-7" if distance <= 7 else "8+"


def label_features(words: list[str], tags: list[str], heads: list[int], children: list[list[int]], d: int) -> list[str]:
    n = len(words)
    h = heads[d]
    hw = words[h] if h >= 0 else "<root>"
    ht = tags[h] if h >= 0 else "ROOT"
    dw, dt = words[d], tags[d]
    direction = "L" if h > d or h < 0 else "R"
    dist = _bucket(h - d) if h >= 0 else "root"
    prev_t = tags[d - 1] if d > 0 else "<s>"
    next_t = tags[d + 1] if d + 1 < n else "</s>"
    f = [
        "bias",
        "dw=" + dw, "dt=" + dt, "hw=" + hw, "ht=" + ht,
        "ds3=" + dw[-3:],
        "dir=" + direction,
        "dt ht dir=" + dt + " " + ht + " " + direction,
        "dw ht dir=" + dw + " " + ht + " " + direction,
        "dt hw dir=" + dt + " " + hw + " " + direction,
        "dw hw=" + dw + " " + hw,
        "dt ht dist=" + dt + " " + ht + " " + dist + direction,
        "ctx=" + prev_t + " " + dt + " " + next_t,
        "dt prev=" + dt + " " + prev_t,
    ]
    kid_tags = sorted({tags[c] for c in children[d]})
    f.append("dkids=" + dt + " " + "_".join(kid_tags[:6]))
    for c in children[d]:
        if tags[c] in FUNCTION_TAGS or words[c] in AUX_LEMMAS:
            side = "L" if c < d else "R"
            f.append("dfun=" + side + words[c] + " " + dt + " " + ht)
            f.append("dfunt=" + side + tags[c] + " " + dt + " " + ht + " " + direction)
    if h >= 0:
        for c in children[h]:
            if c == d:
                continue
            if words[c] in AUX_LEMMAS or tags[c] in {"MD", "TO", "WDT", "WP", "WRB", "EX"}:
                side = "L" if c < h else "R"
                f.append("hfun=" + side + words[c] + " " + ht + " " + dt + " " + direction)
        siblings = [c for c in children[h] if c != d]
        nominal_before = any(c < d and tags[c].startswith(("NN", "PRP")) for c in siblings)
        f.append("nomL=" + str(nominal_before) + " " + dt + " " + ht + " " + direction)
        if h >= 0 and heads[h] >= 0:
            f.append("hh=" + tags[heads[h]] + " " + ht + " " + dt)
    if d == 0:
        f.append("first=" + dt)
    return f


class Parser:
    MODEL_NAME = "parser.json.gz"

    def __init__(self) -> None:
        self.model = AveragedPerceptron(MOVES)
        self.labeler = AveragedPerceptron()

    # --- разбор ------------------------------------------------------------------

    @staticmethod
    def _normalize(words: list[str]) -> list[str]:
        result = []
        for w in words:
            if w[:1].isdigit():
                result.append("!num")
            else:
                result.append(w.lower())
        return result

    def heads(self, words: list[str], tags: list[str]) -> list[int]:
        n = len(words)
        lowered = self._normalize(words)
        parse = Parse(n)
        stack: list[int] = []
        b = 0
        while b < n or stack:
            valid = valid_moves(b, n, len(stack))
            move = valid[0] if len(valid) == 1 else self.model.predict(
                features(lowered, tags, b, n, stack, parse), valid)
            b = apply(move, b, stack, parse)
        return [h if h < n else -1 for h in parse.heads]

    def labels(self, words: list[str], tags: list[str], heads: list[int]) -> list[str]:
        lowered = self._normalize(words)
        children = _children(heads)
        result = []
        for d, h in enumerate(heads):
            if h < 0:
                result.append("root")
                continue
            label = self.labeler.predict(label_features(lowered, tags, heads, children, d))
            result.append("dep" if label == "root" else label)
        return result

    def parse(self, words: list[str], tags: list[str]) -> tuple[list[int], list[str]]:
        if not words:
            return [], []
        heads = self.heads(words, tags)
        return heads, self.labels(words, tags, heads)

    # --- обучение ------------------------------------------------------------------------

    def train(self, sentences: list[tuple[list[str], list[str], list[int]]], epochs: int, seed: int = 4,
              log=print) -> None:
        """sentences — (слова, теги, вершины); вершина корня — −1. Только проективные деревья."""
        self.model = AveragedPerceptron(MOVES)
        for epoch in range(epochs):
            started = time.perf_counter()
            correct = total = 0
            for words, tags, gold_heads in shuffled(sentences, seed, epoch):
                n = len(words)
                lowered = self._normalize(words)
                gold = [h if h >= 0 else n for h in gold_heads]
                parse = Parse(n)
                stack: list[int] = []
                b = 0
                while b < n or stack:
                    valid = valid_moves(b, n, len(stack))
                    feats = features(lowered, tags, b, n, stack, parse)
                    scores = self.model.scores(feats)
                    guess = max(valid, key=lambda m: scores.get(m, 0.0))
                    costs = move_costs(b, n, stack, gold)
                    best_cost = min(costs[m] for m in valid)
                    zero = [m for m in valid if costs[m] == best_cost]
                    if guess not in zero:
                        best = max(zero, key=lambda m: scores.get(m, 0.0))
                        self.model.update(best, guess, feats)
                    else:
                        self.model.instances += 1
                    b = apply(guess, b, stack, parse)
                correct += sum(1 for d in range(n) if parse.heads[d] == gold[d])
                total += n
            log(f"    анализатор, эпоха {epoch + 1}: UAS {100 * correct / max(1, total):.2f} % "
                f"на обучающих ({time.perf_counter() - started:.0f} с)")
        self.model.average()

    def train_labeler(self, sentences: list[tuple[list[str], list[str], list[int], list[str]]], epochs: int,
                      seed: int = 4, log=print) -> None:
        classes = sorted({label for *_, labels in sentences for label in labels})
        self.labeler = AveragedPerceptron(classes)
        for epoch in range(epochs):
            started = time.perf_counter()
            correct = total = 0
            for words, tags, heads, labels in shuffled(sentences, seed + 7, epoch):
                lowered = self._normalize(words)
                children = _children(heads)
                for d, h in enumerate(heads):
                    if h < 0:
                        continue
                    feats = label_features(lowered, tags, heads, children, d)
                    guess = self.labeler.predict(feats)
                    self.labeler.update(labels[d], guess, feats)
                    correct += guess == labels[d]
                    total += 1
            log(f"    отношения, эпоха {epoch + 1}: {100 * correct / max(1, total):.2f} % на обучающих "
                f"({time.perf_counter() - started:.0f} с)")
        self.labeler.average()

    # --- сохранение --------------------------------------------------------------------------

    def save(self, directory: Path, prune: float = 1.5, digits: int = 1) -> Path:
        """Сохраняет модель, отбросив малые веса.

        Усреднённых весов — около 3,3 млн, и полная модель занимает 17 МБ.
        Веса меньше 1,5 по модулю почти не влияют на выбор перехода: без них
        точность на тестовых частях падает на 0,3–0,5 пункта, а модель
        становится в три с лишним раза меньше (подбор — в README).
        """
        for model in (self.model, self.labeler):
            for row in model.weights.values():
                for cls in row:
                    row[cls] = round(row[cls], digits)
            model.prune(prune)
        path = Path(directory) / self.MODEL_NAME
        save_json({"moves": self.model.to_dict(digits), "labels": self.labeler.to_dict(digits)}, path)
        return path

    @classmethod
    def load(cls, directory: Path) -> "Parser":
        data = load_json(Path(directory) / cls.MODEL_NAME)
        parser = cls()
        parser.model = AveragedPerceptron.from_dict(data["moves"])
        parser.labeler = AveragedPerceptron.from_dict(data["labels"])
        return parser


def _children(heads: list[int]) -> list[list[int]]:
    children: list[list[int]] = [[] for _ in heads]
    for d, h in enumerate(heads):
        if h >= 0:
            children[h].append(d)
    return children
