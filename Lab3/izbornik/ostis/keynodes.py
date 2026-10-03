"""Системные идентификаторы ключевых узлов (см. kb/section_subject_domain_of_summarization)."""

from __future__ import annotations

import hashlib
import re
import unicodedata

# --- понятия ---------------------------------------------------------------------
SECTION = "section_subject_domain_of_summarization"
TEXT_DOCUMENT = "concept_text_document"
COLLECTION_DOCUMENT = "concept_test_collection_document"
SCIENTIFIC_ARTICLE = "concept_scientific_article_on_computer_science"
LITERARY_ESSAY = "concept_essay_on_literature"
SENTENCE = "concept_sentence"
SUMMARY = "concept_summary"
CLASSIC_SUMMARY = "concept_classic_summary"
KEYWORD_SUMMARY = "concept_keyword_summary"
KEY_TERM = "concept_key_term"
KEYWORD = "concept_keyword"
KEY_PHRASE = "concept_key_phrase"
METHOD = "sentence_extraction"

# --- отношения ---------------------------------------------------------------------
NREL_TEXT = "nrel_document_text"
NREL_SOURCE = "nrel_source_address"
NREL_SUMMARY = "nrel_summary"
RREL_CLASSIC = "rrel_classic_summary"
RREL_KEYWORDS = "rrel_keyword_summary"
NREL_NUMBER = "nrel_sentence_number"
NREL_SCORE = "nrel_sentence_score"
NREL_POSD = "nrel_position_in_document"
NREL_POSP = "nrel_position_in_paragraph"
NREL_WEIGHT = "nrel_sentence_weight"
NREL_RANK = "nrel_sentence_rank"
NREL_SIGNIFICANCE = "nrel_term_significance"
NREL_FREQUENCY = "nrel_term_frequency"
NREL_SUBORDINATE = "nrel_subordinate_key_term"
NREL_SIZE = "nrel_summary_size"
NREL_LENGTH = "nrel_document_length"
NREL_DB = "nrel_collection_size"
NREL_COMPRESSION = "nrel_compression_ratio"
NREL_METHOD = "nrel_summarization_method"
NREL_TIME = "nrel_processing_time"

# --- общие узлы базы знаний --------------------------------------------------------
NREL_MAIN_IDTF = "nrel_main_idtf"
NREL_SYSTEM_IDTF = "nrel_system_identifier"
LANG = {"ru": "lang_ru", "de": "lang_de"}
DOMAIN_CLASS = {"cs": SCIENTIFIC_ARTICLE, "lit": LITERARY_ESSAY}

# --- действие ----------------------------------------------------------------------
ACTION_CLASS = "action_build_summary"
QUESTION = "question"

#: все узлы онтологии, которые нужны коду (проверяются после загрузки kb/*.scs)
REQUIRED = [
    TEXT_DOCUMENT, COLLECTION_DOCUMENT, SCIENTIFIC_ARTICLE, LITERARY_ESSAY, SENTENCE,
    SUMMARY, CLASSIC_SUMMARY, KEYWORD_SUMMARY, KEY_TERM, KEYWORD, KEY_PHRASE, METHOD,
    NREL_TEXT, NREL_SOURCE, NREL_SUMMARY, RREL_CLASSIC, RREL_KEYWORDS, NREL_NUMBER,
    NREL_SCORE, NREL_POSD, NREL_POSP, NREL_WEIGHT, NREL_RANK, NREL_SIGNIFICANCE,
    NREL_FREQUENCY, NREL_SUBORDINATE, NREL_SIZE, NREL_LENGTH, NREL_DB, NREL_COMPRESSION,
    NREL_METHOD, NREL_TIME, NREL_MAIN_IDTF, NREL_SYSTEM_IDTF, "lang_ru", "lang_de",
    ACTION_CLASS, QUESTION,
]

# --- системные идентификаторы документов и терминов ---------------------------------

_RU_TRANSLIT = dict(zip(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p",
     "r", "s", "t", "u", "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"],
))
_DE_FOLD = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}


def ascii_idtf(text: str) -> str:
    """Строка из латиницы, цифр и «_»: так выглядит системный идентификатор OSTIS."""
    out = []
    for ch in text.lower():
        if ch in _RU_TRANSLIT:
            out.append(_RU_TRANSLIT[ch])
        elif ch in _DE_FOLD:
            out.append(_DE_FOLD[ch])
        else:
            decomposed = unicodedata.normalize("NFKD", ch)
            base = "".join(c for c in decomposed if c.isascii())
            out.append(base if base.isalnum() else "_")
    return re.sub(r"_+", "_", "".join(out)).strip("_")


def document_idtf(doc_id: str) -> str:
    """doc_ru_cs_ostis для документа коллекции ru-cs-ostis."""
    return "doc_" + ascii_idtf(doc_id)


def doc_id_from_idtf(idtf: str) -> str:
    """Обратное преобразование для документов коллекции: doc_ru_cs_ostis → ru-cs-ostis."""
    return idtf[4:].replace("_", "-") if idtf.startswith("doc_") else idtf


def user_document_idtf(text: str) -> str:
    """Свой текст пользователя: идентификатор по содержимому, повтор не создаёт дубль."""
    return "doc_user_" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def term_idtf(language: str, text: str) -> str:
    """term_ru_neyronnaya_set — общий для всех документов узел ключевого термина."""
    base = ascii_idtf(text)[:60] or hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
    return f"term_{language}_{base}"
