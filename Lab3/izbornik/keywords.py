"""Реферат в виде списка ключевых слов.

Методичка описывает его как список, возможно иерархический, наиболее
информативных слов и именных групп документа:

    лазер
        лазерный луч
        синий лазер
    устройство

Построение:

1. Ключевые слова верхнего уровня — существительные с наибольшей значимостью
   tf(t, D) · log(|DB| / df(t)). Вес w(t, D) из формулы методички здесь не
   годится: множитель 0,5 · (1 + tf / tf_max) нарочно сглаживает частоту —
   для оценки предложений это правильно, но в коллекции из десяти документов
   почти все слова имеют df = 1, и слово, встреченное трижды, получало бы
   почти тот же вес, что главное понятие статьи, встреченное тридцать раз.
2. Именные группы, встретившиеся не реже PHRASE_MIN_FREQ раз:
   * русский — прилагательное (причастие) + существительное с согласованием
     в роде, числе и падеже: «нейронная сеть», «искусственная нейронная сеть»;
     существительное + существительное в родительном падеже: «база данных»,
     «обработка естественного языка»;
   * немецкий — прилагательное + существительное: «künstliche Intelligenz»;
     сложное слово, содержащее ключевое слово: «Datenbanksystem» при
     «Datenbank». Немецкое сложное слово и есть именная группа, записанная
     слитно, поэтому оно подчиняется своей основе так же, как русская
     «реляционная база данных» подчиняется «базе».
3. Значимость именной группы — частота группы, умноженная на среднюю
   обратную документную частоту log(|DB| / df) её слов.
4. Группа подчиняется ключевому слову, которое в неё входит (для русского —
   и однокоренному: «лазерный луч» — к «лазеру»). Если подходят несколько,
   выбирается самое весомое. Более длинная группа подчиняется более короткой,
   если содержит её целиком: «сеть → нейронная сеть → искусственная нейронная
   сеть».
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from izbornik import config
from izbornik.text import morphology
from izbornik.text.analysis import AnalyzedDocument, Token
from izbornik.weights import TermWeight


@dataclass
class Keyword:
    text: str
    terms: tuple[str, ...]
    weight: float
    freq: int
    kind: str = "word"             # word | phrase | compound
    children: list["Keyword"] = field(default_factory=list)

    def walk(self, depth: int = 0):
        yield depth, self
        for child in self.children:
            yield from child.walk(depth + 1)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "terms": list(self.terms),
            "weight": round(self.weight, 6),
            "freq": self.freq,
            "kind": self.kind,
            "children": [child.to_dict() for child in self.children],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Keyword":
        return cls(
            text=data["text"],
            terms=tuple(data.get("terms", ())),
            weight=float(data.get("weight", 0.0)),
            freq=int(data.get("freq", 0)),
            kind=data.get("kind", "word"),
            children=[cls.from_dict(child) for child in data.get("children", [])],
        )


@dataclass
class KeywordSummary:
    tree: list[Keyword]
    #: весомые группы, не подчинённые ни одному ключевому слову
    loose: list[Keyword] = field(default_factory=list)

    def flat(self) -> list[Keyword]:
        items = [kw for top in self.tree for _, kw in top.walk()]
        return items + self.loose

    def texts(self) -> list[str]:
        return [kw.text for kw in self.flat()]

    def to_dict(self) -> dict:
        return {"tree": [k.to_dict() for k in self.tree], "loose": [k.to_dict() for k in self.loose]}

    @classmethod
    def from_dict(cls, data: dict) -> "KeywordSummary":
        return cls(
            tree=[Keyword.from_dict(k) for k in data.get("tree", [])],
            loose=[Keyword.from_dict(k) for k in data.get("loose", [])],
        )


# --- поиск именных групп --------------------------------------------------------

@dataclass
class _Phrase:
    terms: tuple[str, ...]
    forms: Counter = field(default_factory=Counter)
    freq: int = 0
    kind: str = "phrase"


def _russian_phrases(document: AnalyzedDocument) -> dict[tuple[str, ...], _Phrase]:
    morph = morphology.for_language("ru")
    found: dict[tuple[str, ...], _Phrase] = {}

    def add(tokens: list[Token], form: str) -> None:
        key = tuple(t.term for t in tokens)
        phrase = found.setdefault(key, _Phrase(key))
        phrase.forms[form] += 1
        phrase.freq += 1

    # термины, которые где-то в документе написаны со строчной: «Роман» в начале
    # предложения — это роман, а не имя, и «Роман Пушкина» — не «Роман Пушкин»
    common = {t.term for tokens in document.sentence_tokens for t in tokens
              if t.counted and not t.initial and t.surface[:1].islower()}

    def is_genitive_noun(token: Token) -> bool:
        return token.adjacent and token.counted and token.noun and morph.info(token.surface).genitive

    for tokens in (*document.sentence_tokens, *document.heading_tokens):
        for i, token in enumerate(tokens):
            if not (token.counted and token.noun):
                continue
            info = morph.info(token.surface)

            # имя человека: имя, отчество, фамилия подряд — «Евгения Онегина» →
            # «Евгений Онегин», «Елены Сергеевны» → «Елена Сергеевна»
            if info.person:
                previous = tokens[i - 1] if i else None
                if (previous is not None and token.adjacent and previous.counted
                        and morph.info(previous.surface).person):
                    continue            # середина имени уже учтена с его начала
                run = [token]
                while (len(run) < 3 and i + len(run) < len(tokens)
                       and tokens[i + len(run)].adjacent and tokens[i + len(run)].counted
                       and morph.info(tokens[i + len(run)].surface).person):
                    run.append(tokens[i + len(run)])
                if len(run) >= 2:
                    if not (token.initial and token.term in common):
                        add(run, morph.person_form(tuple(t.surface for t in run), token.term))
                    continue

            # прилагательные (до двух) перед существительным, согласованные с ним
            adjectives: list[Token] = []
            j = i
            while j > 0 and len(adjectives) < 2:
                previous = tokens[j - 1]
                if not (tokens[j].adjacent and previous.counted and previous.adjective):
                    break
                if not morph.agree(previous.surface, token.surface):
                    break
                adjectives.insert(0, previous)
                j -= 1
            for size in range(1, len(adjectives) + 1):
                chosen = adjectives[-size:]
                add([*chosen, token], morph.phrase_form(tuple(a.surface for a in chosen), token.surface))

            # существительное + существительное в родительном падеже: «база данных»,
            # «проектирование баз данных», «обработка естественного языка».
            # Аббревиатура не склоняется, и «БЗ систем» группой не является.
            if i + 1 >= len(tokens) or info.abbreviation or info.person:
                continue
            nxt = tokens[i + 1]
            head = info.lemma
            if is_genitive_noun(nxt):
                add([token, nxt], f"{head} {morph.surface(nxt.surface)}")
                if i + 2 < len(tokens) and is_genitive_noun(tokens[i + 2]):
                    third = tokens[i + 2]
                    add([token, nxt, third],
                        f"{head} {morph.surface(nxt.surface)} {morph.surface(third.surface)}")
            elif (i + 2 < len(tokens) and nxt.adjacent and nxt.counted and nxt.adjective
                  and is_genitive_noun(tokens[i + 2])
                  and morph.agree(nxt.surface, tokens[i + 2].surface)):
                third = tokens[i + 2]
                add([token, nxt, third], f"{head} {nxt.surface.lower()} {morph.surface(third.surface)}")
    return found


def _german_phrases(document: AnalyzedDocument) -> dict[tuple[str, ...], _Phrase]:
    morph = morphology.for_language("de")
    found: dict[tuple[str, ...], _Phrase] = {}
    for tokens in (*document.sentence_tokens, *document.heading_tokens):
        for i in range(1, len(tokens)):
            adjective, noun = tokens[i - 1], tokens[i]
            if not (noun.adjacent and noun.counted and noun.noun):
                continue
            if not (adjective.counted and adjective.adjective):
                continue
            key = (adjective.term, noun.term)
            phrase = found.setdefault(key, _Phrase(key))
            phrase.forms[f"{morph.adjective_base(adjective.surface)} {document.show(noun.term)}"] += 1
            phrase.freq += 1
    return found


def _derived(term: str, head: str) -> bool:
    """Однокоренное ли слово (ru): «лазерный» от «лазер», «сетевой» — нет (слишком коротко)."""
    if len(head) < 4 or term == head:
        return False
    common = 0
    for a, b in zip(term, head):
        if a != b:
            break
        common += 1
    return common >= max(4, len(head) - 1)


#: глагольные приставки: «Versöhnung» — не сложное слово от «Sohn»
_GERMAN_PREFIXES = ("ver", "be", "ent", "er", "zer", "ge", "miss", "emp", "un", "ur")


def _contains_compound(term: str, head: str) -> bool:
    """Немецкое сложное слово начинается или кончается основой ключевого слова.

    Datenbank → Datenbanksystem, Sohn → Lieblingssohn, Räuber → Räuberbande.
    """
    if len(head) < 4 or term == head or head not in term:
        return False
    if term.startswith(head) or f"-{head}" in term:
        return True
    if term.endswith(head):
        rest = term[: -len(head)].rstrip("s-")
        return len(rest) >= 3 and rest not in _GERMAN_PREFIXES
    return False


# --- сборка реферата ------------------------------------------------------------

def extract(
    document: AnalyzedDocument,
    weights: dict[str, TermWeight],
    top: int = config.KEYWORDS_TOP,
    children: int = config.KEYWORD_CHILDREN,
    min_freq: int = config.PHRASE_MIN_FREQ,
) -> KeywordSummary:
    language = document.language

    def idf(term: str) -> float:
        item = weights.get(term)
        return item.idf if item else 0.0

    def w(term: str) -> float:          # значимость слова: tf · idf
        return document.tf.get(term, 0) * idf(term)

    nouns = [t for t in document.noun_terms if w(t) > 0]
    nouns.sort(key=lambda t: (-w(t), t))
    heads: list[Keyword] = []
    for t in nouns:
        if len(heads) >= top:
            break
        # немецкое сложное слово с уже выбранным ключевым словом внутри
        # (Datenbanksystem при Datenbank) верхнего уровня не занимает —
        # оно станет подчинённым; его место получает следующее слово
        if language == "de" and any(_contains_compound(t, h.terms[0]) for h in heads):
            continue
        heads.append(Keyword(text=document.show(t), terms=(t,), weight=w(t), freq=document.tf[t], kind="word"))
    head_terms = {h.terms[0]: h for h in heads}

    raw = _russian_phrases(document) if language == "ru" else _german_phrases(document)
    phrases: list[Keyword] = []
    for key, phrase in raw.items():
        if phrase.freq < min_freq:
            continue
        mean = sum(idf(t) for t in key) / len(key)
        if mean <= 0:
            continue
        form = sorted(phrase.forms.items(), key=lambda item: (-item[1], item[0]))[0][0]
        phrases.append(Keyword(text=form, terms=key, weight=phrase.freq * mean, freq=phrase.freq))

    if language == "de":
        # сложные слова, содержащие основу ключевого слова: Datenbank → Datenbanksystem
        for term in document.noun_terms:
            if term in head_terms or document.tf[term] < min_freq or w(term) <= 0:
                continue
            if any(_contains_compound(term, head) for head in head_terms):
                phrases.append(Keyword(text=document.show(term), terms=(term,),
                                       weight=w(term), freq=document.tf[term], kind="compound"))

    phrases.sort(key=lambda k: (-k.weight, k.text))

    attached: dict[str, list[Keyword]] = defaultdict(list)
    loose: list[Keyword] = []
    for phrase in phrases:
        related = []
        for head_term, head in head_terms.items():
            if head_term in phrase.terms:
                related.append(head)
            elif language == "ru" and any(_derived(t, head_term) for t in phrase.terms):
                related.append(head)
            elif language == "de" and any(_contains_compound(t, head_term) for t in phrase.terms):
                related.append(head)
        if related:
            best = max(related, key=lambda h: (h.weight, h.text))
            attached[best.terms[0]].append(phrase)
        else:
            loose.append(phrase)

    for head in heads:
        head.children = _nest(attached.get(head.terms[0], []), children)

    return KeywordSummary(tree=heads, loose=loose[:5])


def _nest(phrases: list[Keyword], limit: int) -> list[Keyword]:
    """Подчиняет длинные группы коротким, если те содержатся в них целиком."""
    chosen = sorted(phrases, key=lambda k: (-k.weight, k.text))[:limit]
    chosen.sort(key=lambda k: (len(k.terms), -k.weight))
    roots: list[Keyword] = []
    for phrase in chosen:
        phrase.children = []
        parent = None
        for candidate in roots:
            for _, node in candidate.walk():
                if (len(node.terms) < len(phrase.terms)
                        and set(node.terms) <= set(phrase.terms) and node.kind != "compound"):
                    parent = node
        if parent is not None:
            parent.children.append(phrase)
        else:
            roots.append(phrase)
    roots.sort(key=lambda k: (-k.weight, k.text))
    return roots
