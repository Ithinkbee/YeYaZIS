"""Подключение к sc-серверу и загрузка онтологии предметной области.

Библиотека py-sc-client держит одно соединение на процесс, а ошибки
websocket по умолчанию возбуждает прямо в потоке соединения. Здесь ошибки
перехватываются и запоминаются: недоступность OSTIS — штатная ситуация, при
которой система переходит в локальный режим, а не падает.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from izbornik import config
from izbornik.ostis import keynodes as K

log = logging.getLogger("izbornik.ostis")

#: порядок загрузки файлов онтологии: сначала язык и понятия, затем то, что на них ссылается
ONTOLOGY_FILES = (
    "lang_de.scs",
    "concepts.scs",
    "relations.scs",
    "action_build_summary.scs",
    "section_subject_domain_of_summarization.scs",
)
ONTOLOGY_DIR = config.KB_DIR / "section_subject_domain_of_summarization"


class OstisError(RuntimeError):
    """Операция с базой знаний не удалась."""


@dataclass
class OntologyReport:
    loaded_now: bool = False
    files: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0


class Connection:
    """Соединение с sc-сервером (одно на процесс)."""

    def __init__(self, url: str = config.OSTIS_URL) -> None:
        self.url = url
        self.error: str | None = None
        self.server = None                  # sc_kpm.ScServer
        self._lock = threading.RLock()

    # -- соединение -------------------------------------------------------------

    def _on_error(self, error: Exception) -> None:
        self.error = f"{type(error).__name__}: {error}"
        log.warning("sc-server: %s", self.error)

    def connect(self, wait: float = 3.0) -> bool:
        from sc_client import client
        from sc_kpm import ScServer

        with self._lock:
            if self.is_connected():
                return True
            self.error = None
            client.set_error_handler(self._on_error)
            self.server = ScServer(self.url)
            deadline = time.monotonic() + wait
            try:
                client.connect(self.url)
                while not client.is_connected() and time.monotonic() < deadline and self.error is None:
                    time.sleep(0.05)
                if not client.is_connected():
                    self.error = self.error or "sc-сервер не ответил"
                    self._close()
                    return False
                # sc-kpm запоминает общие ключевые узлы (question, nrel_answer, rrel_1…)
                from sc_kpm.identifiers import _IdentifiersResolver

                _IdentifiersResolver.resolve()
            except Exception as problem:  # noqa: BLE001
                self._on_error(problem)
                self._close()
                return False
            return True

    def is_connected(self) -> bool:
        try:
            from sc_client import client

            return client.is_connected()
        except Exception:  # noqa: BLE001
            return False

    def _close(self) -> None:
        from sc_client import client

        try:
            client.disconnect()
        except Exception:  # noqa: BLE001
            pass

    def disconnect(self) -> None:
        # замок может держать поток, повисший на запросе к зависшему sc-серверу;
        # закрытие соединения как раз и освобождает такой поток, поэтому ждать
        # замок бесконечно нельзя
        acquired = self._lock.acquire(timeout=2)
        try:
            if self.is_connected():
                self._close()
        finally:
            if acquired:
                self._lock.release()

    # -- онтология --------------------------------------------------------------

    def ensure_ontology(self) -> OntologyReport:
        """Загружает kb/*.scs, если раздела ещё нет в базе знаний.

        Повторная загрузка SCs создала бы дубли дуг, поэтому признак загрузки —
        наличие узла раздела. База знаний NIKA пересобирается при каждом
        запуске контейнера, и после перезапуска онтология загрузится заново.
        """
        from sc_client import client
        from sc_client.constants.exceptions import ServerError
        from sc_client.models import ScIdtfResolveParams

        report = OntologyReport()
        started = time.perf_counter()
        with self._lock:
            section = client.resolve_keynodes(ScIdtfResolveParams(idtf=K.SECTION, type=None))[0]
            if not section.is_valid():
                for name in ONTOLOGY_FILES:
                    text = (ONTOLOGY_DIR / name).read_text(encoding="utf-8")
                    try:
                        ok = client.create_elements_by_scs([text])
                    except ServerError as problem:
                        raise OstisError(f"{name}: {problem}") from problem
                    if not all(ok):
                        raise OstisError(f"{name}: sc-сервер не принял SCs-текст")
                    report.files.append(name)
                report.loaded_now = True
            found = client.resolve_keynodes(*[ScIdtfResolveParams(idtf=i, type=None) for i in K.REQUIRED])
            report.missing = [idtf for idtf, addr in zip(K.REQUIRED, found) if not addr.is_valid()]
        report.elapsed_ms = (time.perf_counter() - started) * 1000
        return report


def ontology_sources() -> list[Path]:
    return [ONTOLOGY_DIR / name for name in ONTOLOGY_FILES]
