"""Деревья синтаксического разбора выбранного предложения (вкладка 2) — в виде SVG.

Анализатор строит дерево зависимостей: у каждого слова одна вершина, дуга
подписана отношением (подлежащее, дополнение, определение…). Оно рисуется
дугами над строкой слов. Для привычного школьного вида из него же выводится
дерево составляющих: группа существительного (NP), предложная группа (PP),
глагольная группа (VP), предложение (S) — каждая вершина со своими зависимыми
образует группу, названную по части речи вершины.

Рисунки строятся на сервере, поэтому видны и без JavaScript, сохраняются
вместе со страницей и выводятся на печать.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape

from dragoman.english import tags as tagset
from dragoman.english.analyzer import AnalyzedSentence, Word

SUBJECTS = {"nsubj", "nsubj:pass", "csubj", "csubj:pass", "nsubj:outer", "expl"}
CLAUSE_HEADS = {"root", "ccomp", "advcl", "acl:relcl", "parataxis", "csubj", "xcomp", "conj"}

FONT = 13
CHAR = 7.4          # средняя ширина знака при размере шрифта 13
GAP = 18


def text_width(text: str, size: int = FONT) -> float:
    wide = sum(1 for ch in text if ch in "mwMWЖШЩФЮ@%")
    narrow = sum(1 for ch in text if ch in "iljtfr.,;:'!|I()[]")
    return (len(text) + 0.4 * wide - 0.45 * narrow) * CHAR * size / FONT


# --- дерево зависимостей ------------------------------------------------------------------

def dependency_svg(sentence: AnalyzedSentence, highlight: set[int] | None = None) -> str:
    words = [w for w in sentence.words]
    if not words:
        return ""
    highlight = highlight or set()
    widths = [max(text_width(w.text), text_width(w.tag, 11), 26) for w in words]
    xs = []
    x = 12.0
    for width in widths:
        xs.append(x + width / 2)
        x += width + GAP
    total_width = x
    arcs = [(w.head, w.index, w.deprel) for w in words if w.head >= 0]
    # уровни дуг: короткие ниже, длинные выше
    levels: dict[tuple[int, int], int] = {}
    for head, dep, _ in sorted(arcs, key=lambda a: abs(a[0] - a[1])):
        lo, hi = sorted((head, dep))
        inner = [levels[(h, d)] for (h, d) in levels if lo <= min(h, d) and max(h, d) <= hi]
        levels[(head, dep)] = (max(inner) + 1) if inner else 1
    max_level = max(levels.values(), default=1)
    step = 22
    top = 26 + max_level * step
    height = top + 46
    parts = [f'<svg class="tree tree-dep" viewBox="0 0 {total_width:.0f} {height}" width="{total_width:.0f}" '
             f'height="{height}" role="img" aria-label="дерево зависимостей">']
    parts.append('<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" '
                 'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="arrow-head"/></marker></defs>')
    root = next((w for w in words if w.head < 0), None)
    if root is not None:
        rx = xs[root.index]
        parts.append(f'<line class="arc root-arc" x1="{rx:.1f}" y1="6" x2="{rx:.1f}" y2="{top - 4}" '
                     f'marker-end="url(#arrow)"/>')
        parts.append(f'<text class="arc-label" x="{rx + 4:.1f}" y="14">root</text>')
    for head, dep, label in arcs:
        level = levels[(head, dep)]
        x1, x2 = xs[head], xs[dep]
        y = top - 4
        lift = level * step
        offset = 4 if head < dep else -4
        path = (f"M{x1 + offset:.1f},{y} C{x1 + offset:.1f},{y - lift:.1f} {x2:.1f},{y - lift:.1f} {x2:.1f},{y}")
        css = "arc arc-hl" if dep in highlight or head in highlight else "arc"
        parts.append(f'<path class="{css}" d="{path}" marker-end="url(#arrow)">'
                     f'<title>{escape(label)} — {escape(tagset.describe_deprel(label))}</title></path>')
        mid = (x1 + x2) / 2
        parts.append(f'<text class="arc-label" x="{mid:.1f}" y="{y - lift * 0.75 - 3:.1f}" text-anchor="middle">'
                     f'{escape(label)}</text>')
    for w, x0 in zip(words, xs):
        css = "word word-hl" if w.index in highlight else "word"
        parts.append(f'<text class="{css}" x="{x0:.1f}" y="{top + 14}" text-anchor="middle">{escape(w.text)}'
                     f'<title>{escape(w.lemma)} · {escape(w.tag)} — {escape(tagset.describe(w.tag))}</title></text>')
        parts.append(f'<text class="tag" x="{x0:.1f}" y="{top + 31}" text-anchor="middle">{escape(w.tag)}</text>')
    parts.append("</svg>")
    return "".join(parts)


# --- дерево составляющих ------------------------------------------------------------------------

@dataclass
class PhraseNode:
    label: str
    children: list["PhraseNode"] = field(default_factory=list)
    word: Word | None = None
    x: float = 0.0
    y: float = 0.0

    @property
    def is_leaf(self) -> bool:
        return self.word is not None


def phrase_label(w: Word, sentence: AnalyzedSentence) -> str:
    kids = [sentence.words[c] for c in w.children]
    if any(k.deprel == "case" for k in kids) and w.upos not in {"VERB"}:
        return "PP"
    if any(k.deprel in SUBJECTS for k in kids) or (w.deprel in CLAUSE_HEADS and w.upos in {"VERB", "AUX"}):
        return "S"
    return {"NOUN": "NP", "PROPN": "NP", "PRON": "NP", "NUM": "NP", "VERB": "VP", "AUX": "VP", "ADJ": "AP",
            "ADV": "AdvP", "DET": "DP"}.get(w.upos, "XP")


def build_phrases(sentence: AnalyzedSentence, i: int) -> PhraseNode:
    w = sentence.words[i]
    leaf = PhraseNode(w.tag, word=w)
    kids = sorted(w.children)
    kids = [k for k in kids if sentence.words[k].deprel != "punct" or True]
    if not kids:
        return leaf
    label = phrase_label(w, sentence)
    left = [build_phrases(sentence, k) for k in kids if k < i]
    right = [build_phrases(sentence, k) for k in kids if k > i]
    if label == "S":
        # S → то, что стоит перед сказуемым (подлежащее, союз, обстоятельство), + VP — сказуемое
        # со вспомогательными глаголами, отрицанием и всем, что справа
        left_ids = [k for k in kids if k < i]
        subject_pos = max((k for k in left_ids if sentence.words[k].deprel in SUBJECTS), default=-1)
        front, vp_children = [], []
        for node, k in zip(left, left_ids):
            if k > subject_pos and sentence.words[k].deprel in {"aux", "aux:pass", "cop", "advmod", "compound:prt"}:
                vp_children.append(node)
            else:
                front.append(node)
        vp = PhraseNode("VP", vp_children + [leaf] + right)
        return PhraseNode("S", front + [vp])
    return PhraseNode(label, left + [leaf] + right)


def constituency_svg(sentence: AnalyzedSentence) -> str:
    words = sentence.words
    if not words:
        return ""
    root = next((w.index for w in words if w.head < 0), 0)
    tree = build_phrases(sentence, root)
    # листья — по порядку слов
    leaves: list[PhraseNode] = []

    def collect(node: PhraseNode) -> None:
        if node.is_leaf:
            leaves.append(node)
        for child in node.children:
            collect(child)

    collect(tree)
    leaves.sort(key=lambda n: n.word.index)
    x = 12.0
    for leaf in leaves:
        width = max(text_width(leaf.word.text), 28)
        leaf.x = x + width / 2
        x += width + 14
    total_width = x

    def depth(node: PhraseNode) -> int:
        return 0 if node.is_leaf else 1 + max(depth(c) for c in node.children)

    levels = depth(tree)
    row = 40
    height = 30 + (levels + 1) * row + 20

    def place(node: PhraseNode) -> None:
        for child in node.children:
            place(child)
        if not node.is_leaf:
            node.x = sum(c.x for c in node.children) / len(node.children)
            node.y = 22 + (levels - depth(node)) * row

    place(tree)
    leaf_y = 22 + levels * row + row * 0.6
    for leaf in leaves:
        leaf.y = leaf_y
    parts = [f'<svg class="tree tree-ps" viewBox="0 0 {total_width:.0f} {height:.0f}" width="{total_width:.0f}" '
             f'height="{height:.0f}" role="img" aria-label="дерево составляющих">']

    def draw(node: PhraseNode) -> None:
        for child in node.children:
            y1 = node.y + 6
            y2 = child.y - (26 if child.is_leaf else 14)
            parts.append(f'<line class="branch" x1="{node.x:.1f}" y1="{y1:.1f}" x2="{child.x:.1f}" y2="{y2:.1f}"/>')
            draw(child)
        if node.is_leaf:
            w = node.word
            parts.append(f'<text class="tag" x="{node.x:.1f}" y="{node.y - 14:.1f}" text-anchor="middle">'
                         f'{escape(w.tag)}<title>{escape(tagset.describe(w.tag))}</title></text>')
            parts.append(f'<text class="word" x="{node.x:.1f}" y="{node.y + 4:.1f}" text-anchor="middle">'
                         f'{escape(w.text)}</text>')
        else:
            parts.append(f'<text class="phrase phrase-{node.label}" x="{node.x:.1f}" y="{node.y:.1f}" '
                         f'text-anchor="middle">{escape(node.label)}</text>')

    draw(tree)
    parts.append("</svg>")
    return "".join(parts)


PHRASE_NAMES = {
    "S": "предложение (клауза)", "NP": "группа существительного", "VP": "глагольная группа",
    "PP": "предложная группа", "AP": "группа прилагательного", "AdvP": "группа наречия", "DP": "группа определителя",
    "XP": "прочая группа",
}
