"""Документы и рефераты в базе знаний: запись и чтение.

Структура, которую строит sc-агент (обозначения SCs):

    doc_ru_cs_ostis
        <- concept_text_document; <- concept_test_collection_document;
        <- concept_scientific_article_on_computer_science;
        => nrel_main_idtf: [Семантические модели …] (* <- lang_ru;; *);
        => nrel_document_text: [текст документа] (* <- lang_ru;; *);
        => nrel_source_address: [https://cyberleninka.ru/…];
        => nrel_summary: _summary;;

    _summary <- concept_summary;
        => nrel_summary_size: [10];  => nrel_document_length: [18192];
        => nrel_collection_size: [10];  => nrel_compression_ratio: [0.24];
        => nrel_summarization_method: sentence_extraction;
        => nrel_processing_time: [520.3];
        -> rrel_classic_summary: _classic;
        -> rrel_keyword_summary: _keywords;;

    _classic <- concept_classic_summary;
        -> rrel_1: [первое предложение реферата] (* <- concept_sentence;; <- lang_ru;;
               => nrel_sentence_number: [2];  => nrel_sentence_score: [14.54];
               => nrel_position_in_document: [0.99];  => nrel_position_in_paragraph: [0.85];
               => nrel_sentence_weight: [12.34];  => nrel_sentence_rank: [8];; *);
        -> rrel_2: …;;

    _keywords <- concept_keyword_summary;
        -> rrel_1: (_keywords -> term_ru_ontologiya)  // ключевое слово верхнего уровня
             (* => nrel_term_significance: [71.4];; => nrel_term_frequency: [31];; *);
        -> (_keywords -> term_ru_ontologiya_predmetnoy_oblasti) (* => … *);
        -> (term_ru_ontologiya => term_ru_ontologiya_predmetnoy_oblasti)
             (* <- nrel_subordinate_key_term;; *);;

Ключевой термин — общий узел с системным идентификатором term_<язык>_<…>:
разные документы с одним понятием указывают на один узел, и в sc-web видно,
в рефератах каких документов он встречается. Значимость термина зависит от
документа, поэтому она приписана дуге принадлежности, а не самому термину.

Все элементы одного реферата создаются одним запросом create_elements.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sc_client import client
from sc_client.constants import sc_types
from sc_client.models import (
    ScAddr,
    ScConstruction,
    ScIdtfResolveParams,
    ScLinkContent,
    ScLinkContentType,
    ScTemplate,
)

from izbornik.keywords import Keyword, KeywordSummary
from izbornik.ostis import keynodes as K
from izbornik.ostis.connection import OstisError
from izbornik.summary import Result, SummarySentence

ACCESS = sc_types.EDGE_ACCESS_CONST_POS_PERM
COMMON = sc_types.EDGE_D_COMMON_CONST
V_ACCESS = sc_types.EDGE_ACCESS_VAR_POS_PERM
V_COMMON = sc_types.EDGE_D_COMMON_VAR

MAX_ROLE = 40


class Keynodes:
    """Адреса ключевых узлов онтологии, разрешённые один раз."""

    def __init__(self) -> None:
        names = list(K.REQUIRED)
        found = client.resolve_keynodes(*[ScIdtfResolveParams(idtf=i, type=None) for i in names])
        self.addr: dict[str, ScAddr] = dict(zip(names, found))
        missing = [n for n, a in self.addr.items() if not a.is_valid()]
        if missing:
            raise OstisError("в базе знаний нет узлов онтологии: " + ", ".join(missing))
        roles = client.resolve_keynodes(*[
            ScIdtfResolveParams(idtf=f"rrel_{i}", type=sc_types.NODE_CONST_ROLE)
            for i in range(1, MAX_ROLE + 1)
        ])
        self.roles = {i: addr for i, addr in enumerate(roles, start=1)}
        self.role_index = {addr.value: i for i, addr in self.roles.items()}

    def __getitem__(self, idtf: str) -> ScAddr:
        return self.addr[idtf]

    def lang(self, language: str) -> ScAddr:
        return self.addr[K.LANG[language]]


# --- помощники ------------------------------------------------------------------

def _text(value: str) -> ScLinkContent:
    return ScLinkContent(value, ScLinkContentType.STRING)


def _float(value: float) -> ScLinkContent:
    return ScLinkContent(round(float(value), 6), ScLinkContentType.FLOAT)


def _int(value: int) -> ScLinkContent:
    return ScLinkContent(int(value), ScLinkContentType.INT)


class _Builder:
    """Обёртка над ScConstruction с автоматическими псевдонимами."""

    def __init__(self) -> None:
        self.construction = ScConstruction()
        self._counter = 0

    def _alias(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}{self._counter}"

    def node(self, sc_type=sc_types.NODE_CONST) -> str:
        alias = self._alias("n")
        self.construction.create_node(sc_type, alias)
        return alias

    def link(self, content: ScLinkContent) -> str:
        alias = self._alias("l")
        self.construction.create_link(sc_types.LINK_CONST, content, alias)
        return alias

    def arc(self, source, target, sc_type=ACCESS) -> str:
        alias = self._alias("e")
        self.construction.create_edge(sc_type, source, target, alias)
        return alias

    def member(self, cls, element) -> str:
        return self.arc(cls, element, ACCESS)

    def relation(self, source, target, relation, sc_type=COMMON) -> str:
        """source =(relation)=> target: общая дуга и дуга принадлежности отношению."""
        edge = self.arc(source, target, sc_type)
        self.arc(relation, edge, ACCESS)
        return edge

    def run(self) -> dict[str, ScAddr]:
        addrs = client.create_elements(self.construction)
        if not addrs:
            raise OstisError("sc-сервер не создал элементы")
        return {alias: addrs[index] for alias, index in self.construction.aliases.items()}


def _contents(*links: ScAddr) -> list:
    if not links:
        return []
    return [item.data for item in client.get_link_content(*links)]


def _relation_value(source: ScAddr, relation: ScAddr) -> ScAddr:
    template = ScTemplate()
    template.triple_with_relation(source, V_COMMON, sc_types.LINK_VAR >> "_value", V_ACCESS, relation)
    found = client.template_search(template)
    return found[0].get("_value") if found else ScAddr(0)


def find_node(idtf: str) -> ScAddr:
    return client.resolve_keynodes(ScIdtfResolveParams(idtf=idtf, type=None))[0]


# --- документы ------------------------------------------------------------------

@dataclass
class KbDocument:
    addr: ScAddr
    idtf: str
    title: str
    language: str
    domain: str | None
    text: str
    in_collection: bool


def ensure_document(
    kn: Keynodes,
    *,
    idtf: str,
    title: str,
    language: str,
    text: str,
    domain: str | None = None,
    source_url: str = "",
    in_collection: bool = False,
) -> tuple[ScAddr, bool]:
    """Помещает документ в базу знаний, если его там нет. Возвращает (адрес, создан ли)."""
    existing = find_node(idtf)
    if existing.is_valid() and _relation_value(existing, kn[K.NREL_TEXT]).is_valid():
        return existing, False

    node = client.resolve_keynodes(ScIdtfResolveParams(idtf=idtf, type=sc_types.NODE_CONST))[0]
    b = _Builder()
    lang = kn.lang(language)
    b.member(kn[K.TEXT_DOCUMENT], node)
    if in_collection:
        b.member(kn[K.COLLECTION_DOCUMENT], node)
    if domain in K.DOMAIN_CLASS:
        b.member(kn[K.DOMAIN_CLASS[domain]], node)
    title_link = b.link(_text(title))
    b.member(lang, title_link)
    b.relation(node, title_link, kn[K.NREL_MAIN_IDTF])
    text_link = b.link(_text(text))
    b.member(lang, text_link)
    b.relation(node, text_link, kn[K.NREL_TEXT])
    if source_url:
        b.relation(node, b.link(_text(source_url)), kn[K.NREL_SOURCE])
    b.run()
    return node, True


def read_document(kn: Keynodes, node: ScAddr) -> KbDocument:
    """Читает из базы знаний то, что нужно агенту: текст, язык, заголовок, область."""
    text_link = _relation_value(node, kn[K.NREL_TEXT])
    if not text_link.is_valid():
        raise OstisError("у документа в базе знаний нет текста (nrel_document_text)")
    language = next(
        (code for code in K.LANG if _is_member(kn.lang(code), text_link)), None
    )
    if language is None:
        raise OstisError("язык текста документа не указан (lang_ru / lang_de)")
    title_link = _relation_value(node, kn[K.NREL_MAIN_IDTF])
    sys_link = _relation_value(node, kn[K.NREL_SYSTEM_IDTF])
    text = _contents(text_link)[0]
    title = _contents(title_link)[0] if title_link.is_valid() else ""
    idtf = _contents(sys_link)[0] if sys_link.is_valid() else ""
    domain = next((code for code, cls in K.DOMAIN_CLASS.items() if _is_member(kn[cls], node)), None)
    return KbDocument(
        addr=node,
        idtf=str(idtf),
        title=str(title),
        language=language,
        domain=domain,
        text=str(text),
        in_collection=_is_member(kn[K.COLLECTION_DOCUMENT], node),
    )


def _is_member(cls: ScAddr, element: ScAddr) -> bool:
    template = ScTemplate()
    template.triple(cls, V_ACCESS, element)
    return bool(client.template_search(template))


def collection_texts(kn: Keynodes, language: str) -> list[tuple[str, str]]:
    """Документы тестовой коллекции языка: (системный идентификатор, текст).

    Поиск разбит на два шаблона — «текст на нужном языке» и «системный
    идентификатор» — и результаты соединяются по адресу документа: шаблон,
    объединяющий обе части, sc-machine 0.8 не находит (проверено на NIKA).
    """
    texts = ScTemplate()
    texts.triple(kn[K.COLLECTION_DOCUMENT], V_ACCESS, sc_types.NODE_VAR >> "_doc")
    texts.triple_with_relation("_doc", V_COMMON, sc_types.LINK_VAR >> "_text", V_ACCESS, kn[K.NREL_TEXT])
    texts.triple(kn.lang(language), V_ACCESS, "_text")
    by_doc = {item.get("_doc").value: item.get("_text") for item in client.template_search(texts)}

    names = ScTemplate()
    names.triple(kn[K.COLLECTION_DOCUMENT], V_ACCESS, sc_types.NODE_VAR >> "_doc")
    names.triple_with_relation("_doc", V_COMMON, sc_types.LINK_VAR >> "_sys", V_ACCESS, kn[K.NREL_SYSTEM_IDTF])
    sys_of = {item.get("_doc").value: item.get("_sys") for item in client.template_search(names)}

    docs = [doc for doc in by_doc if doc in sys_of]
    contents = _contents(*[link for doc in docs for link in (sys_of[doc], by_doc[doc])])
    pairs = [(str(contents[i]), str(contents[i + 1])) for i in range(0, len(contents), 2)]
    return sorted(dict(pairs).items())


def document_count(kn: Keynodes) -> int:
    template = ScTemplate()
    template.triple(kn[K.COLLECTION_DOCUMENT], V_ACCESS, sc_types.NODE_VAR)
    return len(client.template_search(template))


# --- запись реферата ----------------------------------------------------------------

def _term_nodes(kn: Keynodes, language: str, keywords: list[Keyword]) -> dict[str, ScAddr]:
    """Узлы ключевых терминов; недостающие создаются вместе с основным идентификатором."""
    idtfs = {K.term_idtf(language, kw.text): kw for kw in keywords}
    names = list(idtfs)
    found = client.resolve_keynodes(*[ScIdtfResolveParams(idtf=i, type=None) for i in names])
    missing = [name for name, addr in zip(names, found) if not addr.is_valid()]
    if missing:
        created = client.resolve_keynodes(*[
            ScIdtfResolveParams(idtf=i, type=sc_types.NODE_CONST) for i in missing
        ])
        b = _Builder()
        lang = kn.lang(language)
        for name, node in zip(missing, created):
            kw = idtfs[name]
            b.member(kn[K.KEY_TERM], node)
            b.member(kn[K.KEYWORD] if kw.kind == "word" else kn[K.KEY_PHRASE], node)
            label = b.link(_text(kw.text))
            b.member(lang, label)
            b.relation(node, label, kn[K.NREL_MAIN_IDTF])
        b.run()
        found = client.resolve_keynodes(*[ScIdtfResolveParams(idtf=i, type=None) for i in names])
    return {name: addr for name, addr in zip(names, found)}


def write_summary(kn: Keynodes, document: ScAddr, result: Result, processing_ms: float) -> ScAddr:
    """Записывает оба раздела реферата; возвращает узел реферата."""
    summary = result.summary
    language = summary.language
    lang = kn.lang(language)
    all_keywords = [kw for top in summary.keywords.tree for _, kw in top.walk()] + summary.keywords.loose
    terms = _term_nodes(kn, language, all_keywords)

    b = _Builder()
    node = b.node()
    b.member(kn[K.SUMMARY], node)
    b.relation(document, node, kn[K.NREL_SUMMARY])
    stats = summary.stats
    b.relation(node, b.link(_int(summary.requested)), kn[K.NREL_SIZE])
    b.relation(node, b.link(_int(stats.get("chars", 0))), kn[K.NREL_LENGTH])
    b.relation(node, b.link(_int(stats.get("db_docs", 0))), kn[K.NREL_DB])
    b.relation(node, b.link(_float(stats.get("compression", 0.0))), kn[K.NREL_COMPRESSION])
    b.relation(node, b.link(_float(processing_ms)), kn[K.NREL_TIME])
    b.relation(node, kn[K.METHOD], kn[K.NREL_METHOD])

    classic = b.node()
    b.member(kn[K.CLASSIC_SUMMARY], classic)
    part = b.arc(node, classic)
    b.member(kn[K.RREL_CLASSIC], part)
    for position, sentence in enumerate(summary.sentences, start=1):
        link = b.link(_text(sentence.text))
        b.member(kn[K.SENTENCE], link)
        b.member(lang, link)
        arc = b.arc(classic, link)
        b.member(kn.roles[min(position, MAX_ROLE)], arc)
        b.relation(link, b.link(_int(sentence.index + 1)), kn[K.NREL_NUMBER])
        b.relation(link, b.link(_float(sentence.score)), kn[K.NREL_SCORE])
        b.relation(link, b.link(_float(sentence.posd)), kn[K.NREL_POSD])
        b.relation(link, b.link(_float(sentence.posp)), kn[K.NREL_POSP])
        b.relation(link, b.link(_float(sentence.weight)), kn[K.NREL_WEIGHT])
        b.relation(link, b.link(_int(sentence.rank)), kn[K.NREL_RANK])

    keywords = b.node()
    b.member(kn[K.KEYWORD_SUMMARY], keywords)
    part = b.arc(node, keywords)
    b.member(kn[K.RREL_KEYWORDS], part)

    def put(kw: Keyword, order: int | None) -> None:
        term = terms[K.term_idtf(language, kw.text)]
        arc = b.arc(keywords, term)
        if order is not None:
            b.member(kn.roles[min(order, MAX_ROLE)], arc)
        b.relation(arc, b.link(_float(kw.weight)), kn[K.NREL_SIGNIFICANCE])
        b.relation(arc, b.link(_int(kw.freq)), kn[K.NREL_FREQUENCY])

    def put_tree(kw: Keyword) -> None:
        parent = terms[K.term_idtf(language, kw.text)]
        for child in kw.children:
            put(child, None)
            sub = b.relation(parent, terms[K.term_idtf(language, child.text)], kn[K.NREL_SUBORDINATE])
            b.member(keywords, sub)
            put_tree(child)

    for order, top in enumerate(summary.keywords.tree, start=1):
        put(top, order)
        put_tree(top)
    for kw in summary.keywords.loose:
        put(kw, None)

    return b.run()[node]


# --- чтение реферата ----------------------------------------------------------------

@dataclass
class KbSummary:
    addr: ScAddr
    size: int = 0
    chars: int = 0
    db_docs: int = 0
    compression: float = 0.0
    processing_ms: float = 0.0
    sentences: list[SummarySentence] = field(default_factory=list)
    keywords: KeywordSummary = field(default_factory=lambda: KeywordSummary(tree=[]))


def find_summaries(kn: Keynodes, document: ScAddr) -> list[tuple[ScAddr, int]]:
    """Рефераты документа в базе знаний: (узел, размер в предложениях), новые — последними."""
    template = ScTemplate()
    template.triple_with_relation(document, V_COMMON, sc_types.NODE_VAR >> "_summary", V_ACCESS, kn[K.NREL_SUMMARY])
    template.triple_with_relation("_summary", V_COMMON, sc_types.LINK_VAR >> "_size", V_ACCESS, kn[K.NREL_SIZE])
    found = client.template_search(template)
    sizes = _contents(*[item.get("_size") for item in found])
    pairs = [(item.get("_summary"), int(size)) for item, size in zip(found, sizes)]
    return sorted(pairs, key=lambda pair: pair[0].value)


def unlink_summaries(kn: Keynodes, document: ScAddr, size: int) -> int:
    """Отвязывает от документа прежние рефераты того же размера.

    У документа остаётся не больше одного реферата каждого размера. Узел
    старого реферата не удаляется, удаляется только дуга реферат*: адреса
    в sc-памяти переиспользуются, и определять «самый новый» реферат по
    адресу было бы ненадёжно.
    """
    template = ScTemplate()
    template.triple_with_relation(document, V_COMMON >> "_arc", sc_types.NODE_VAR >> "_summary",
                                  V_ACCESS, kn[K.NREL_SUMMARY])
    template.triple_with_relation("_summary", V_COMMON, sc_types.LINK_VAR >> "_size", V_ACCESS, kn[K.NREL_SIZE])
    found = client.template_search(template)
    sizes = _contents(*[item.get("_size") for item in found])
    stale = [item.get("_arc") for item, value in zip(found, sizes) if int(value) == size]
    if stale:
        client.delete_elements(*stale)
    return len(stale)


def read_summary(kn: Keynodes, node: ScAddr) -> KbSummary:
    result = KbSummary(addr=node)

    # числовые характеристики реферата
    names = [K.NREL_SIZE, K.NREL_LENGTH, K.NREL_DB, K.NREL_COMPRESSION, K.NREL_TIME]
    links = [_relation_value(node, kn[name]) for name in names]
    values = dict(zip(names, _contents(*[l for l in links if l.is_valid()]))) if all(l.is_valid() for l in links) else {}
    result.size = int(values.get(K.NREL_SIZE, 0))
    result.chars = int(values.get(K.NREL_LENGTH, 0))
    result.db_docs = int(values.get(K.NREL_DB, 0))
    result.compression = float(values.get(K.NREL_COMPRESSION, 0.0))
    result.processing_ms = float(values.get(K.NREL_TIME, 0.0))

    # классический реферат: предложения со всеми коэффициентами — одним поиском
    template = ScTemplate()
    template.triple_with_relation(node, V_ACCESS, sc_types.NODE_VAR >> "_classic", V_ACCESS, kn[K.RREL_CLASSIC])
    template.triple("_classic", V_ACCESS, sc_types.LINK_VAR >> "_s")
    relations = [K.NREL_NUMBER, K.NREL_SCORE, K.NREL_POSD, K.NREL_POSP, K.NREL_WEIGHT, K.NREL_RANK]
    for index, name in enumerate(relations):
        template.triple_with_relation("_s", V_COMMON, sc_types.LINK_VAR >> f"_v{index}", V_ACCESS, kn[name])
    rows = client.template_search(template)
    flat = []
    for row in rows:
        flat.append(row.get("_s"))
        flat.extend(row.get(f"_v{i}") for i in range(len(relations)))
    contents = _contents(*flat)
    width = 1 + len(relations)
    sentences = []
    for offset in range(0, len(contents), width):
        text, number, score, posd, posp, weight, rank = contents[offset:offset + width]
        sentences.append(SummarySentence(
            index=int(number) - 1, paragraph=-1, text=str(text), compressed=str(text),
            score=float(score), posd=float(posd), posp=float(posp), weight=float(weight), rank=int(rank),
        ))
    result.sentences = sorted({s.index: s for s in sentences}.values(), key=lambda s: s.index)

    result.keywords = _read_keywords(kn, node)
    return result


def _read_keywords(kn: Keynodes, node: ScAddr) -> KeywordSummary:
    template = ScTemplate()
    template.triple_with_relation(node, V_ACCESS, sc_types.NODE_VAR >> "_kw", V_ACCESS, kn[K.RREL_KEYWORDS])
    found = client.template_search(template)
    if not found:
        return KeywordSummary(tree=[])
    keywords = found[0].get("_kw")

    # все термины реферата: значимость и частота на дуге, название — у термина
    members = ScTemplate()
    members.triple(keywords, V_ACCESS >> "_arc", sc_types.NODE_VAR >> "_term")
    members.triple_with_relation("_arc", V_COMMON, sc_types.LINK_VAR >> "_sig", V_ACCESS, kn[K.NREL_SIGNIFICANCE])
    members.triple_with_relation("_arc", V_COMMON, sc_types.LINK_VAR >> "_freq", V_ACCESS, kn[K.NREL_FREQUENCY])
    members.triple_with_relation("_term", V_COMMON, sc_types.LINK_VAR >> "_name", V_ACCESS, kn[K.NREL_MAIN_IDTF])
    rows = client.template_search(members)
    flat = []
    for row in rows:
        flat.extend([row.get("_name"), row.get("_sig"), row.get("_freq")])
    contents = _contents(*flat)
    items: dict[int, Keyword] = {}
    arc_of: dict[int, int] = {}
    for row, offset in zip(rows, range(0, len(contents), 3)):
        name, sig, freq = contents[offset:offset + 3]
        term = row.get("_term").value
        items[term] = Keyword(text=str(name), terms=(), weight=float(sig), freq=int(freq))
        arc_of[term] = row.get("_arc").value

    # ключевые слова верхнего уровня отмечены порядковой ролью rrel_i на дуге
    heads = ScTemplate()
    heads.triple(keywords, V_ACCESS >> "_arc", sc_types.NODE_VAR >> "_term")
    heads.triple(sc_types.NODE_VAR >> "_role", V_ACCESS, "_arc")
    order: dict[int, int] = {}
    for row in client.template_search(heads):
        index = kn.role_index.get(row.get("_role").value)
        if index is not None:
            order[row.get("_term").value] = index

    # подчинение: общая дуга «термин ⇒ словосочетание», входящая в реферат
    links = ScTemplate()
    links.triple(sc_types.NODE_VAR >> "_parent", V_COMMON >> "_sub", sc_types.NODE_VAR >> "_child")
    links.triple(kn[K.NREL_SUBORDINATE], V_ACCESS, "_sub")
    links.triple(keywords, V_ACCESS, "_sub")
    children: dict[int, list[int]] = {}
    child_set: set[int] = set()
    for row in client.template_search(links):
        parent, child = row.get("_parent").value, row.get("_child").value
        children.setdefault(parent, []).append(child)
        child_set.add(child)

    def build(term: int) -> Keyword:
        kw = items[term]
        kw.children = sorted((build(c) for c in children.get(term, []) if c in items),
                             key=lambda k: (-k.weight, k.text))
        for child in kw.children:
            child.kind = "phrase" if " " in child.text else "compound"
        return kw

    tree = [build(t) for t in sorted(order, key=order.get) if t in items]
    loose = sorted((items[t] for t in items if t not in order and t not in child_set),
                   key=lambda k: (-k.weight, k.text))
    for kw in loose:
        kw.kind = "phrase"
    return KeywordSummary(tree=tree, loose=loose)
