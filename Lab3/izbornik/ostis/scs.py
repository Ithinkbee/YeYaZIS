"""Реферат в виде текста на языке SCs.

Выгрузка повторяет структуру, которую sc-агент записывает в базу знаний
(см. izbornik/ostis/kb.py): её можно загрузить в любую ostis-систему — через
sc-builder или запросом create_elements_by_scs, — и в sc-web она будет
выглядеть так же, как реферат, построенный агентом.
"""

from __future__ import annotations

from datetime import datetime

from izbornik.keywords import Keyword
from izbornik.ostis import keynodes as K
from izbornik.summary import Summary


def escape(text: str) -> str:
    """Содержимое sc-ссылки: экранируются «[», «]», «\\»; «*» в начале недопустима."""
    text = text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    if text.startswith("*"):
        text = "∗" + text[1:]
    return text


def _number(value: float, digits: int = 6) -> str:
    return f"[{round(value, digits)}]"


def document_idtf(summary: Summary) -> str:
    if summary.ostis and summary.ostis.get("document_idtf"):
        return summary.ostis["document_idtf"]
    return K.document_idtf(summary.doc_id) if summary.doc_id else "doc_user_text"


def to_scs(summary: Summary) -> str:
    lang = K.LANG[summary.language]
    doc = document_idtf(summary)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    s_id = f"summary_{doc[4:]}_{summary.requested}_{stamp}"
    classic = f"{s_id}_classic"
    keywords = f"{s_id}_keywords"

    lines = [
        f"// Реферат документа «{summary.title}» — «Изборник», метод sentence extraction.",
        f"// Построен {summary.created}; источник данных: "
        f"{'база знаний (sc-агент)' if summary.engine == 'ostis' else 'локальный расчёт'}.",
        "",
        doc,
        "<- concept_text_document;",
    ]
    if summary.domain in K.DOMAIN_CLASS:
        lines.append(f"<- {K.DOMAIN_CLASS[summary.domain]};")
    lines += [
        "=> nrel_main_idtf:",
        f"    [{escape(summary.title)}]",
        f"    (* <- {lang};; *);",
    ]
    if summary.source_url:
        lines.append(f"=> nrel_source_address: [{escape(summary.source_url)}];")
    lines += [f"=> nrel_summary: {s_id};;", ""]

    stats = summary.stats
    lines += [
        s_id,
        "<- concept_summary;",
        f"=> nrel_summary_size: {_number(summary.requested)};",
        f"=> nrel_document_length: {_number(stats.get('chars', 0))};",
        f"=> nrel_collection_size: {_number(stats.get('db_docs', 0))};",
        f"=> nrel_compression_ratio: {_number(stats.get('compression', 0.0), 4)};",
        "=> nrel_summarization_method: sentence_extraction;",
        f"-> rrel_classic_summary: {classic};",
        f"-> rrel_keyword_summary: {keywords};;",
        "",
        classic,
        "<- concept_classic_summary;",
    ]
    for position, sentence in enumerate(summary.sentences, start=1):
        end = ";;" if position == len(summary.sentences) else ";"
        lines += [
            f"-> rrel_{position}: [{escape(sentence.text)}]",
            "    (*",
            "    <- concept_sentence;;",
            f"    <- {lang};;",
            f"    => nrel_sentence_number: {_number(sentence.index + 1)};;",
            f"    => nrel_sentence_score: {_number(sentence.score, 4)};;",
            f"    => nrel_position_in_document: {_number(sentence.posd, 4)};;",
            f"    => nrel_position_in_paragraph: {_number(sentence.posp, 4)};;",
            f"    => nrel_sentence_weight: {_number(sentence.weight, 4)};;",
            f"    => nrel_sentence_rank: {_number(sentence.rank)};;",
            f"    *){end}",
        ]
    if not summary.sentences:
        lines[-1] = lines[-1].rstrip(";") + ";;"
    lines.append("")

    terms: dict[str, Keyword] = {}
    for top in summary.keywords.tree:
        for _, kw in top.walk():
            terms[K.term_idtf(summary.language, kw.text)] = kw
    for kw in summary.keywords.loose:
        terms[K.term_idtf(summary.language, kw.text)] = kw

    for idtf, kw in terms.items():
        kind = "concept_keyword" if kw.kind == "word" else "concept_key_phrase"
        lines += [
            idtf,
            "<- concept_key_term;",
            f"<- {kind};",
            f"=> nrel_main_idtf: [{escape(kw.text)}] (* <- {lang};; *);;",
        ]
    lines += ["", keywords, "<- concept_keyword_summary;;", ""]

    # Дуга принадлежности термина реферату несёт значимость термина, поэтому
    # она записывается явной конструкцией с псевдонимом дуги.
    blocks: list[str] = []
    counter = 0

    def arc_block(kw: Keyword, order: int | None) -> None:
        nonlocal counter
        counter += 1
        alias = f"@kw_arc_{counter}"
        idtf = K.term_idtf(summary.language, kw.text)
        blocks.append(f"{alias} = ({keywords} -> {idtf});;")
        if order:
            blocks.append(f"rrel_{order} -> {alias};;")
        blocks.append(f"{alias} => nrel_term_significance: {_number(kw.weight, 4)};;")
        blocks.append(f"{alias} => nrel_term_frequency: {_number(kw.freq)};;")

    def sub_block(parent: Keyword, child: Keyword) -> None:
        nonlocal counter
        counter += 1
        alias = f"@kw_sub_{counter}"
        blocks.append(f"{alias} = ({K.term_idtf(summary.language, parent.text)} => "
                      f"{K.term_idtf(summary.language, child.text)});;")
        blocks.append(f"nrel_subordinate_key_term -> {alias};;")
        blocks.append(f"{keywords} -> {alias};;")

    def tree(kw: Keyword) -> None:
        for child in kw.children:
            arc_block(child, None)
            sub_block(kw, child)
            tree(child)

    for order, top in enumerate(summary.keywords.tree, start=1):
        arc_block(top, order)
        tree(top)
    for kw in summary.keywords.loose:
        arc_block(kw, None)

    lines += blocks
    return "\n".join(lines) + "\n"
