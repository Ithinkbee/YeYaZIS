"""Режим OSTIS для веб-интерфейса.

Порядок работы при запуске (в фоновом потоке, интерфейс доступен сразу):

1. подключение к sc-серверу;
2. загрузка онтологии kb/*.scs, если её ещё нет в базе знаний;
3. синхронизация коллекции: каждый документ получает узел doc_<…> с текстом,
   заголовком, языком, предметной областью и адресом источника;
4. регистрация sc-агента построения реферата (если агент не запущен отдельно).

Реферат по запросу пользователя:

1. если в базе знаний уже есть реферат этого документа того же размера, он
   читается оттуда — база знаний служит хранилищем рефератов;
2. иначе создаётся действие класса action_build_summary с аргументами
   «документ» и «число предложений» и инициируется добавлением в
   question_initiated; sc-агент строит реферат и записывает его в базу знаний;
3. интерфейс дожидается question_finished и читает реферат из базы знаний.
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading
import time
from collections import deque
from datetime import datetime

from izbornik import config
from izbornik.collection import CatalogEntry, Collection
from izbornik.ostis import keynodes as K
from izbornik.ostis.connection import Connection, OntologyReport, OstisError
from izbornik.summary import Summary
from izbornik.text.compress import compress

log = logging.getLogger("izbornik.ostis")


class Service:
    """Состояние интеграции с OSTIS и операции над базой знаний."""

    STATES = {
        "off": "выключен",
        "connecting": "подключение…",
        "ready": "работает",
        "unavailable": "sc-сервер недоступен",
        "error": "ошибка",
    }

    def __init__(self, collection: Collection, mode: str | None = None,
                 url: str | None = None, agent_mode: str | None = None) -> None:
        self.collection = collection
        self.mode = mode or config.OSTIS_MODE
        self.url = url or config.OSTIS_URL
        self.agent_mode = agent_mode or config.AGENT_MODE
        self.state = "off" if self.mode == "off" else "connecting"
        self.error: str | None = None
        self.connection = Connection(self.url)
        self.keynodes = None
        self.agent = None
        self.ontology: OntologyReport | None = None
        self.synced = {"created": 0, "present": 0, "ms": 0.0}
        self.started_at: str | None = None
        self.events: deque = deque(maxlen=40)
        self._lock = threading.RLock()
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="izbornik-ostis")

    # -- сторожевой таймаут --------------------------------------------------------
    #
    # py-sc-client ждёт ответа sc-сервера без ограничения по времени, пока
    # соединение открыто. Если sc-сервер завис, но сокет не закрыл (так бывает
    # с sc-machine 0.8), любой запрос повис бы навсегда вместе со страницей.
    # Поэтому обращения к базе знаний выполняются в отдельном потоке с
    # таймаутом: по его истечении режим OSTIS помечается ошибкой, соединение
    # закрывается (это освобождает зависший поток), а интерфейс строит реферат
    # локально.

    def _guarded(self, function, timeout: float, *args, **kwargs):
        future = self._executor.submit(function, *args, **kwargs)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            self.state = "error"
            self.error = f"sc-сервер не ответил за {timeout:.0f} с"
            self._event(f"ошибка: {self.error}; соединение закрыто")
            self._lock = threading.RLock()
            self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1,
                                                                   thread_name_prefix="izbornik-ostis")
            self.connection.disconnect()
            raise OstisError(self.error) from None

    # -- жизненный цикл ----------------------------------------------------------

    def _event(self, message: str) -> None:
        self.events.appendleft((datetime.now().strftime("%H:%M:%S"), message))
        log.info("OSTIS: %s", message)

    def start(self) -> bool:
        if self.mode == "off":
            self.state = "off"
            self._event("режим OSTIS выключен (IZBORNIK_OSTIS=off)")
            return False
        with self._lock:
            self.state = "connecting"
            self.error = None
            if not self.connection.connect():
                self.state = "unavailable"
                self.error = self.connection.error
                self._event(f"нет подключения к {self.url}: {self.error}")
                return False
            self._event(f"подключено к {self.url}")
            try:
                self.ontology = self.connection.ensure_ontology()
                if self.ontology.missing:
                    raise OstisError("не найдены узлы: " + ", ".join(self.ontology.missing))
                self._event("онтология загружена" if self.ontology.loaded_now else "онтология уже в базе знаний")

                from izbornik.ostis import kb

                self.keynodes = kb.Keynodes()
                self.sync_collection()
                if self.agent_mode == "embedded":
                    self._register_agent()
                else:
                    self._event("агент ожидается во внешнем процессе (python tools/agent.py)")
                self.state = "ready"
                self.started_at = datetime.now().isoformat(timespec="seconds")
                return True
            except Exception as problem:  # noqa: BLE001
                self.state = "error"
                self.error = f"{type(problem).__name__}: {problem}"
                self._event(f"ошибка: {self.error}")
                log.exception("OSTIS не запущен")
                return False

    def start_in_background(self) -> threading.Thread:
        thread = threading.Thread(target=self.start, name="izbornik-ostis-start", daemon=True)
        thread.start()
        return thread

    def _register_agent(self) -> None:
        from izbornik.ostis.agent import module

        sc_module, self.agent = module()
        server = self.connection.server
        server.add_modules(sc_module)
        server.register_modules()
        self._event("sc-агент построения реферата зарегистрирован")

    def stop(self) -> None:
        # замок может держать поток, повисший на запросе к sc-серверу, — долго
        # его не ждём: закрытие соединения этот поток и освободит
        acquired = self._lock.acquire(timeout=3)
        try:
            try:
                server = self.connection.server
                if server is not None and server.is_registered and self.connection.is_connected():
                    self._guarded(server.unregister_modules, 5)
            except Exception:  # noqa: BLE001
                pass
            self.connection.disconnect()
            if self.state == "ready":
                self.state = "unavailable"
        finally:
            if acquired:
                self._lock.release()

    def available(self) -> bool:
        return self.state == "ready" and self.connection.is_connected()

    # -- документы ---------------------------------------------------------------

    def sync_collection(self) -> None:
        from izbornik.ostis import kb

        started = time.perf_counter()
        created = present = 0
        for entry in self.collection:
            _, new = kb.ensure_document(
                self.keynodes,
                idtf=K.document_idtf(entry.id),
                title=entry.title,
                language=entry.language,
                text=self.collection.text(entry.id),
                domain=entry.domain,
                source_url=entry.source_url,
                in_collection=True,
            )
            created += new
            present += not new
        self.synced = {"created": created, "present": present, "ms": (time.perf_counter() - started) * 1000}
        self._event(f"коллекция в базе знаний: создано {created}, уже было {present}")

    def sc_web_url(self, idtf: str) -> str:
        return f"{config.SC_WEB_URL}/?sys_id={idtf}"

    # -- реферат -------------------------------------------------------------------

    def summarize_entry(self, entry: CatalogEntry, count: int, force: bool = False) -> Summary:
        return self._guarded(
            self._summarize,
            config.OSTIS_ACTION_TIMEOUT + 15,
            idtf=K.document_idtf(entry.id),
            doc_id=entry.id,
            title=entry.title,
            language=entry.language,
            text_provider=lambda: self.collection.text(entry.id),
            domain=entry.domain,
            source_url=entry.source_url,
            in_collection=True,
            count=count,
            force=force,
        )

    def summarize_text(self, text: str, language: str, title: str, count: int, doc_id: str) -> Summary:
        return self._guarded(
            self._summarize,
            config.OSTIS_ACTION_TIMEOUT + 15,
            idtf=K.user_document_idtf(text),
            doc_id=doc_id,
            title=title,
            language=language,
            text_provider=lambda: text,
            domain=None,
            source_url="",
            in_collection=False,
            count=count,
            force=False,
        )

    def _summarize(self, *, idtf, doc_id, title, language, text_provider, domain, source_url,
                   in_collection, count, force) -> Summary:
        if not self.available():
            raise OstisError(f"OSTIS недоступна: {self.STATES.get(self.state, self.state)}")
        from sc_client.models import ScLinkContentType
        from sc_kpm.utils import create_link
        from sc_kpm.utils.action_utils import call_agent, check_edge, wait_agent
        from sc_kpm.identifiers import QuestionStatus
        from sc_kpm import ScKeynodes
        from sc_client.constants import sc_types

        from izbornik.ostis import kb

        timings: dict[str, float] = {}
        started = time.perf_counter()
        with self._lock:
            kn = self.keynodes
            mark = time.perf_counter()
            node, _ = kb.ensure_document(
                kn, idtf=idtf, title=title, language=language, text=text_provider(),
                domain=domain, source_url=source_url, in_collection=in_collection,
            )
            timings["kb_document"] = _ms(mark)

            summary_node = None
            action = None
            from_kb = False
            if not force:
                existing = [addr for addr, size in kb.find_summaries(kn, node) if size == count]
                if existing:
                    summary_node = existing[-1]
                    from_kb = True

            if summary_node is None:
                mark = time.perf_counter()
                size_link = create_link(count, ScLinkContentType.INT)
                action = call_agent({node: False, size_link: False}, [K.QUESTION, K.ACTION_CLASS])
                wait_agent(config.OSTIS_ACTION_TIMEOUT, action)
                timings["agent_wait"] = _ms(mark)
                finished = check_edge(sc_types.EDGE_ACCESS_VAR_POS_PERM,
                                      ScKeynodes[QuestionStatus.QUESTION_FINISHED], action)
                if not finished:
                    raise OstisError(
                        f"агент не завершил действие за {config.OSTIS_ACTION_TIMEOUT:.0f} с — "
                        "запущен ли агент (IZBORNIK_AGENT)?")
                success = check_edge(sc_types.EDGE_ACCESS_VAR_POS_PERM,
                                     ScKeynodes[QuestionStatus.QUESTION_FINISHED_SUCCESSFULLY], action)
                if not success:
                    detail = (self.agent.last_run.get("error") if self.agent else None) or "подробности в журнале агента"
                    raise OstisError(f"агент завершил действие неуспешно: {detail}")
                summary_node = _answer_summary(kn, action) or kb.find_summaries(kn, node)[-1][0]

            mark = time.perf_counter()
            stored = kb.read_summary(kn, summary_node)
            timings["kb_read"] = _ms(mark)
        timings["ostis_total"] = _ms(started)
        timings["agent"] = stored.processing_ms

        sentences = stored.sentences
        for sentence in sentences:
            sentence.compressed = compress(sentence.text, language) if config.COMPRESS_SENTENCES else sentence.text
        summary_chars = sum(len(s.text) for s in sentences)
        if action is not None:
            self._event(f"агент построил реферат {idtf} за {stored.processing_ms:.0f} мс")
        return Summary(
            doc_id=doc_id,
            title=title,
            language=language,
            domain=domain,
            source_url=source_url or None,
            requested=stored.size or count,
            sentences=sentences,
            keywords=stored.keywords,
            stats={
                "chars": stored.chars,
                "db_docs": stored.db_docs,
                "compression": stored.compression,
                "summary_chars": summary_chars,
                "compressed_chars": sum(len(s.compressed) for s in sentences),
            },
            timings=timings,
            engine="ostis",
            ostis={
                "document_idtf": idtf,
                "document_addr": node.value,
                "summary_addr": summary_node.value,
                "action_addr": action.value if action is not None else None,
                "from_kb": from_kb,
                "sc_web_url": self.sc_web_url(idtf),
            },
        )

    # -- состояние ------------------------------------------------------------------

    def status(self) -> dict:
        info = {
            "mode": self.mode,
            "state": self.state,
            "state_text": self.STATES.get(self.state, self.state),
            "url": self.url,
            "sc_web": config.SC_WEB_URL,
            "error": self.error,
            "agent_mode": self.agent_mode,
            "agent_runs": self.agent.runs if self.agent else None,
            "agent_last": self.agent.last_run if self.agent else None,
            "ontology": self.ontology,
            "synced": self.synced,
            "started_at": self.started_at,
            "events": list(self.events),
        }
        if self.available():
            try:
                from izbornik.ostis import kb

                info["documents_in_kb"] = self._guarded(kb.document_count, 5, self.keynodes)
            except Exception:  # noqa: BLE001
                info["documents_in_kb"] = None
                info["state"] = self.state
                info["state_text"] = self.STATES.get(self.state, self.state)
                info["error"] = self.error
        return info


def _answer_summary(kn, action):
    """Узел реферата из структуры ответа действия (nrel_answer)."""
    from sc_client import client
    from sc_client.constants import sc_types
    from sc_client.models import ScTemplate
    from sc_kpm.utils.action_utils import get_action_answer

    answer = get_action_answer(action)
    if not answer.is_valid():
        return None
    template = ScTemplate()
    template.triple(answer, sc_types.EDGE_ACCESS_VAR_POS_PERM, sc_types.NODE_VAR >> "_s")
    template.triple(kn[K.SUMMARY], sc_types.EDGE_ACCESS_VAR_POS_PERM, "_s")
    found = client.template_search(template)
    return found[0].get("_s") if found else None


def _ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000
