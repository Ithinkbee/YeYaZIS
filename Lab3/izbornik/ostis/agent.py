"""sc-агент построения реферата.

Агент подписан на событие «в множество question_initiated добавлена дуга»
и откликается на действия класса action_build_summary:

1. Читает аргументы действия: rrel_1 — документ, rrel_2 — число предложений.
2. Читает из базы знаний текст документа и его язык, а также тексты всех
   документов тестовой коллекции того же языка — по ним считаются |DB| и df(t).
3. Строит реферат тем же ядром (izbornik.summary.build), что и локальный режим.
4. Записывает реферат в базу знаний (izbornik.ostis.kb.write_summary),
   связывает его с действием отношением nrel_answer и завершает действие.

Разбор документа (сегментация и морфология) — самая долгая часть, поэтому
агент хранит разобранные тексты в памяти по их содержимому: при повторном
вызове коллекция заново не разбирается.
"""

from __future__ import annotations

import hashlib
import threading
import time

from sc_kpm import ScAgentClassic, ScModule, ScResult
from sc_kpm.utils import get_link_content_data
from sc_kpm.utils.action_utils import create_action_answer, finish_action_with_status, get_action_arguments

from izbornik import config, summary as summary_module
from izbornik.ostis import kb, keynodes as K
from izbornik.text.analysis import AnalyzedDocument, analyze
from izbornik.weights import CorpusStats

_cache: dict[tuple[str, str, str], AnalyzedDocument] = {}
_cache_lock = threading.Lock()


def analyzed(idtf: str, text: str, language: str, title: str = "") -> AnalyzedDocument:
    key = (hashlib.sha1(text.encode("utf-8")).hexdigest(), language, idtf)
    with _cache_lock:
        if key not in _cache:
            _cache[key] = analyze(text, language, idtf, title)
        return _cache[key]


class SummaryAgent(ScAgentClassic):
    def __init__(self) -> None:
        super().__init__(K.ACTION_CLASS)
        self._keynodes: kb.Keynodes | None = None
        #: сведения о последнем запуске — для страницы «OSTIS»
        self.last_run: dict = {}
        self.runs = 0

    @property
    def keynodes(self) -> kb.Keynodes:
        if self._keynodes is None:
            self._keynodes = kb.Keynodes()
        return self._keynodes

    def on_event(self, event_element, event_edge, action_element) -> ScResult:
        try:
            status = self.run(action_element)
        except Exception as problem:  # noqa: BLE001 — действие обязано завершиться
            self.logger.exception("реферат не построен: %s", problem)
            self.last_run = {"error": f"{type(problem).__name__}: {problem}"}
            status = ScResult.ERROR
        finish_action_with_status(action_element, status == ScResult.OK)
        return status

    def run(self, action) -> ScResult:
        started = time.perf_counter()
        kn = self.keynodes
        document_addr, size_link = get_action_arguments(action, 2)
        if not document_addr.is_valid():
            self.last_run = {"error": "у действия нет аргумента rrel_1 (документ)"}
            return ScResult.ERROR_INVALID_PARAMS
        size = config.SUMMARY_SENTENCES
        if size_link.is_valid():
            size = max(1, int(get_link_content_data(size_link)))

        timings: dict[str, float] = {}
        mark = time.perf_counter()
        document = kb.read_document(kn, document_addr)
        collection = kb.collection_texts(kn, document.language)
        timings["kb_read"] = _ms(mark)

        mark = time.perf_counter()
        corpus = [analyzed(idtf, text, document.language) for idtf, text in collection]
        target = analyzed(document.idtf, document.text, document.language, document.title)
        stats = CorpusStats.from_documents(corpus, scope="language")
        timings["analysis"] = _ms(mark)

        result = summary_module.build(target, stats, size, domain=document.domain)
        timings.update({f"core_{k}": v for k, v in result.summary.timings.items()})
        processing_ms = _ms(started)

        mark = time.perf_counter()
        kb.unlink_summaries(kn, document_addr, size)
        summary_node = kb.write_summary(kn, document_addr, result, processing_ms)
        create_action_answer(action, summary_node)
        timings["kb_write"] = _ms(mark)

        self.runs += 1
        self.last_run = {
            "document": document.idtf,
            "language": document.language,
            "collection": len(collection),
            "sentences": len(result.summary.sentences),
            "timings": timings,
            "total_ms": _ms(started),
        }
        self.logger.info("реферат %s: %d предл., %.0f мс", document.idtf, size, _ms(started))
        return ScResult.OK


def _ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def module() -> tuple[ScModule, SummaryAgent]:
    agent = SummaryAgent()
    return ScModule(agent), agent
