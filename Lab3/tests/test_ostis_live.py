"""Проверки на живой ostis-системе. Пропускаются, если sc-сервер недоступен.

Если в это время запущен веб-интерфейс, его sc-агент уже подписан на
действия, и второй агент не регистрируется: иначе одно действие было бы
выполнено дважды.
"""

from __future__ import annotations

import pytest

from izbornik import config

from .conftest import port_open, sc_server_alive

pytestmark = pytest.mark.skipif(not sc_server_alive(), reason="sc-сервер недоступен или не отвечает")


@pytest.fixture(scope="module")
def service(collection):
    from izbornik.ostis.service import Service

    external = port_open(config.HOST, config.PORT)
    svc = Service(collection, mode="on", agent_mode="external" if external else "embedded")
    assert svc.start(), svc.error
    yield svc
    svc.stop()


def test_ontology_is_not_loaded_twice(service):
    report = service.connection.ensure_ontology()
    assert report.loaded_now is False and report.missing == []


def test_collection_is_in_knowledge_base(service):
    from izbornik.ostis import kb

    assert kb.document_count(service.keynodes) >= 20
    texts = dict(kb.collection_texts(service.keynodes, "de"))
    assert len(texts) == 10 and "doc_de_lit_effi" in texts


@pytest.mark.parametrize("doc_id", ["ru-cs-neuro", "de-lit-raeuber"])
def test_agent_result_equals_local(service, collection, doc_id):
    entry = collection.get(doc_id)
    built = service.summarize_entry(entry, 7, force=True)
    local = collection.summarize(doc_id, 7).summary
    assert built.engine == "ostis" and built.ostis["action_addr"]
    assert [s.index for s in built.sentences] == [s.index for s in local.sentences]
    for a, b in zip(built.sentences, local.sentences):
        assert a.weight == pytest.approx(b.weight, rel=1e-5) and a.rank == b.rank
    assert built.keywords.texts() == local.keywords.texts()

    again = service.summarize_entry(entry, 7)
    assert again.ostis["from_kb"] and again.ostis["action_addr"] is None
    assert [s.index for s in again.sentences] == [s.index for s in built.sentences]


def test_rebuild_keeps_one_summary_per_size(service, collection):
    from izbornik.ostis import kb
    from izbornik.ostis import keynodes as K

    entry = collection.get("ru-lit-woe")
    service.summarize_entry(entry, 4, force=True)
    service.summarize_entry(entry, 4, force=True)
    node = kb.find_node(K.document_idtf(entry.id))
    sizes = [size for _, size in kb.find_summaries(service.keynodes, node)]
    assert sizes.count(4) == 1


def test_scs_export_is_accepted_by_server(collection, service):
    from sc_client import client

    from izbornik.ostis.scs import to_scs

    summary = collection.summarize("de-cs-semweb", 5).summary
    summary.doc_id = "pytest-scs-export"
    assert client.create_elements_by_scs([to_scs(summary)]) == [True]
