"""OSTIS без sc-сервера: идентификаторы, онтология, отказ соединения."""

from __future__ import annotations

import re
import time

from izbornik.ostis import keynodes as K
from izbornik.ostis.connection import ONTOLOGY_DIR, ONTOLOGY_FILES, Connection


def test_identifiers_are_valid_system_identifiers():
    pattern = re.compile(r"^[a-z0-9_]+$")
    assert K.document_idtf("ru-cs-ostis") == "doc_ru_cs_ostis"
    assert K.doc_id_from_idtf("doc_ru_cs_ostis") == "ru-cs-ostis"
    assert K.term_idtf("ru", "нейронная сеть") == "term_ru_neyronnaya_set"
    assert K.term_idtf("de", "künstliche Intelligenz") == "term_de_kuenstliche_intelligenz"
    assert K.term_idtf("de", "Straße") == "term_de_strasse"
    for idtf in (K.term_idtf("ru", "Евгений Онегин"), K.user_document_idtf("текст"), K.term_idtf("de", "Übersetzer")):
        assert pattern.match(idtf), idtf
    assert K.user_document_idtf("a") == K.user_document_idtf("a") != K.user_document_idtf("b")


def test_ontology_defines_every_keynode_the_code_uses():
    text = "\n".join((ONTOLOGY_DIR / name).read_text(encoding="utf-8") for name in ONTOLOGY_FILES)
    external = {"nrel_main_idtf", "nrel_system_identifier", "lang_ru", "question"}
    for idtf in K.REQUIRED:
        if idtf in external:
            continue
        assert re.search(rf"^{re.escape(idtf)}\s*$", text, re.M), f"{idtf} не определён в kb/"


def test_ontology_files_are_balanced():
    for name in ONTOLOGY_FILES:
        text = (ONTOLOGY_DIR / name).read_text(encoding="utf-8")
        body = re.sub(r"//[^\n]*", "", text)
        body = re.sub(r"\[(?!\*)[^\[\]]*\]", "[]", body)       # содержимое sc-ссылок не считается
        assert body.count("(*") == body.count("*)"), name
        assert body.count("[*") == body.count("*]"), name
        assert body.rstrip().endswith(";;"), name


def test_watchdog_turns_a_hang_into_an_error(collection):
    import threading

    import pytest

    from izbornik.ostis.connection import OstisError
    from izbornik.ostis.service import Service

    service = Service(collection, mode="on", url="ws://127.0.0.1:1")
    service.state = "ready"
    release = threading.Event()
    started = time.monotonic()
    with pytest.raises(OstisError):
        service._guarded(release.wait, 0.3, 10)        # «зависший» запрос
    assert time.monotonic() - started < 3
    assert service.state == "error" and "не ответил" in service.error
    assert not service.available()
    release.set()


def test_unreachable_server_fails_fast():
    connection = Connection("ws://127.0.0.1:1")
    started = time.monotonic()
    assert connection.connect(wait=2.0) is False
    assert time.monotonic() - started < 5
    assert connection.error
