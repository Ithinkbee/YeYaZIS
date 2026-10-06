"""Чтение размеченных корпусов Universal Dependencies в формате CoNLL-U.

Корпуса нужны только для обучения и проверки анализатора: теггер, синтаксический
анализатор и лемматизатор учатся на английских корпусах EWT и GUM. В строке
корпуса — слово, его лемма, универсальная часть речи (UPOS), тег Penn Treebank
(XPOS), морфологические признаки, номер вершины и синтаксическое отношение.

Две особенности формата учитываются при чтении:

* слитные формы («don't», «cannot») записаны строкой-диапазоном «1-2 don't», за
  которой идут синтаксические слова «do» и «n't». Берутся синтаксические слова —
  так же их выделяет токенизатор системы;
* слова через дефис («state-of-the-art», «well-known») в корпусах разрезаны на
  части и сам дефис. Для перевода такое слово — одна единица словаря, поэтому
  части без пробелов между ними склеиваются обратно в одно слово; вершиной
  склеенного слова становится вершина группы, зависимые частей переходят к нему.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


@dataclass
class TreeToken:
    form: str
    lemma: str
    upos: str
    xpos: str
    feats: dict[str, str]
    head: int                  # номер вершины с 0; −1 — корень предложения
    deprel: str
    space_after: bool = True


@dataclass
class TreeSentence:
    sent_id: str
    text: str
    tokens: list[TreeToken] = field(default_factory=list)

    @property
    def words(self) -> list[str]:
        return [t.form for t in self.tokens]

    @property
    def tags(self) -> list[str]:
        return [t.xpos for t in self.tokens]

    @property
    def heads(self) -> list[int]:
        return [t.head for t in self.tokens]

    @property
    def labels(self) -> list[str]:
        return [t.deprel for t in self.tokens]

    def __len__(self) -> int:
        return len(self.tokens)


def _feats(raw: str) -> dict[str, str]:
    if raw in {"_", ""}:
        return {}
    result = {}
    for item in raw.split("|"):
        key, _, value = item.partition("=")
        result[key] = value
    return result


def _space_after(misc: str) -> bool:
    return "SpaceAfter=No" not in misc


def parse(text: str, merge_hyphens: bool = True) -> Iterator[TreeSentence]:
    """Предложения из текста CoNLL-U."""
    sent_id, sent_text, rows = "", "", []
    span_end = 0               # последний номер слитной формы, у которой нет пробела после
    span_space = True
    for line in text.splitlines():
        if not line.strip():
            if rows:
                yield _finish(sent_id, sent_text, rows, merge_hyphens)
            sent_id, sent_text, rows = "", "", []
            continue
        if line.startswith("#"):
            key, _, value = line[1:].partition("=")
            key = key.strip()
            if key == "sent_id":
                sent_id = value.strip()
            elif key == "text":
                sent_text = value.strip()
            continue
        columns = line.split("\t")
        if len(columns) != 10:
            continue
        ident = columns[0]
        if "." in ident:                      # пустой узел расширенного графа
            continue
        if "-" in ident:                      # слитная форма: пробел после неё — у последнего слова
            span_end = int(ident.split("-")[1])
            span_space = _space_after(columns[9])
            continue
        number = int(ident)
        space = _space_after(columns[9])
        if number < span_end:
            space = False
        elif number == span_end:
            space = span_space
        rows.append(TreeToken(
            form=columns[1],
            lemma=columns[2],
            upos=columns[3],
            xpos=columns[4] if columns[4] != "_" else columns[3],
            feats=_feats(columns[5]),
            head=int(columns[6]) - 1 if columns[6] not in {"_", ""} else -1,
            deprel=columns[7],
            space_after=space,
        ))
    if rows:
        yield _finish(sent_id, sent_text, rows, merge_hyphens)


def _finish(sent_id: str, text: str, rows: list[TreeToken], merge_hyphens: bool) -> TreeSentence:
    sentence = TreeSentence(sent_id, text, rows)
    if merge_hyphens:
        sentence = merge_hyphenated(sentence)
    return sentence


def _is_word(form: str) -> bool:
    return any(ch.isalnum() for ch in form)


def hyphen_groups(tokens: list[TreeToken]) -> list[tuple[int, int]]:
    """Группы «слово-дефис-слово…» без пробелов: пары (первый, последний) номер."""
    groups = []
    i = 0
    n = len(tokens)
    while i < n:
        j = i
        while (j + 2 < n and _is_word(tokens[j].form) and not tokens[j].space_after
               and tokens[j + 1].form == "-" and not tokens[j + 1].space_after
               and _is_word(tokens[j + 2].form)):
            j += 2
        if j > i:
            groups.append((i, j))
            i = j + 1
        else:
            i += 1
    return groups


def merge_hyphenated(sentence: TreeSentence) -> TreeSentence:
    """Склеивает слова через дефис в одно слово (см. описание модуля)."""
    tokens = sentence.tokens
    groups = hyphen_groups(tokens)
    if not groups:
        return sentence
    # у группы должна быть одна вершина: слово, чья вершина вне группы
    plan: list[tuple[int, int, int]] = []
    for first, last in groups:
        inside = range(first, last + 1)
        heads = [k for k in inside if not (first <= tokens[k].head <= last)]
        if len(heads) == 1:
            plan.append((first, last, heads[0]))
    if not plan:
        return sentence

    new_index: dict[int, int] = {}
    merged: list[TreeToken] = []
    group_of = {}
    for first, last, head in plan:
        for k in range(first, last + 1):
            group_of[k] = (first, last, head)
    k = 0
    while k < len(tokens):
        if k in group_of:
            first, last, head = group_of[k]
            part = tokens[first:last + 1]
            top = tokens[head]
            form = "".join(t.form for t in part)
            lemma = "".join(t.form if i < len(part) - 1 else t.lemma for i, t in enumerate(part))
            for i in range(first, last + 1):
                new_index[i] = len(merged)
            merged.append(TreeToken(form, lemma, top.upos, top.xpos, dict(top.feats), top.head, top.deprel,
                                    part[-1].space_after))
            k = last + 1
        else:
            new_index[k] = len(merged)
            merged.append(TreeToken(tokens[k].form, tokens[k].lemma, tokens[k].upos, tokens[k].xpos,
                                    dict(tokens[k].feats), tokens[k].head, tokens[k].deprel,
                                    tokens[k].space_after))
            k += 1
    for token in merged:
        if token.head >= 0:
            token.head = new_index[token.head]
    return TreeSentence(sentence.sent_id, sentence.text, merged)


def read(path: Path, merge_hyphens: bool = True) -> list[TreeSentence]:
    return list(parse(Path(path).read_text(encoding="utf-8"), merge_hyphens))


def is_projective(heads: list[int]) -> bool:
    """Дерево проективно: ни одна дуга не пересекает другую."""
    arcs = [(min(d, h), max(d, h)) for d, h in enumerate(heads) if h >= 0]
    for a, (l1, r1) in enumerate(arcs):
        for l2, r2 in arcs[a + 1:]:
            if l1 < l2 < r1 < r2 or l2 < l1 < r2 < r1:
                return False
    return True


def to_conllu(sentence: TreeSentence) -> str:
    lines = [f"# sent_id = {sentence.sent_id}", f"# text = {sentence.text}"]
    for i, t in enumerate(sentence.tokens, start=1):
        feats = "|".join(f"{k}={v}" for k, v in sorted(t.feats.items())) or "_"
        misc = "_" if t.space_after else "SpaceAfter=No"
        lines.append("\t".join([str(i), t.form, t.lemma, t.upos, t.xpos, feats, str(t.head + 1), t.deprel, "_", misc]))
    return "\n".join(lines) + "\n"
