"""Обход коллекции пауком и построение индекса из командной строки.

То же, что кнопки «Обойти сеть» и «Переиндексировать» на странице «Индекс»,
но без запуска веб-интерфейса — нужно после каждой пересборки коллекции
(`python tools/make_collection.py`).

    python tools/reindex.py                — обойти источники и построить индекс
    python tools/reindex.py --add-nodes    — сначала зарегистрировать узлы коллекции
    python tools/reindex.py --load-qrels   — затем загрузить эталонную разметку
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arachne import config, crawler, db, indexer  # noqa: E402
from arachne.evaluation import qrels  # noqa: E402


def add_collection_nodes(conn) -> list[str]:
    """Регистрирует каталоги NODE-* тестовой коллекции как источники паука."""
    added = []
    for node in sorted(path for path in config.COLLECTION_DIR.glob("NODE-*") if path.is_dir()):
        existing = conn.execute(
            "SELECT id FROM sources WHERE root_path = ?", (str(node),)
        ).fetchone()
        if existing is None:
            crawler.add_source(conn, str(node), label=node.name)
            added.append(node.name)
    return added


def main() -> None:
    parser = argparse.ArgumentParser(description="Переиндексация коллекции ИПС «Арахна»")
    parser.add_argument("--add-nodes", action="store_true",
                        help="зарегистрировать каталоги NODE-* как источники")
    parser.add_argument("--load-qrels", action="store_true",
                        help="загрузить эталонные запросы и разметку из CSV")
    arguments = parser.parse_args()

    with db.session() as conn:
        if arguments.add_nodes:
            added = add_collection_nodes(conn)
            print("Добавлены источники:", ", ".join(added) if added else "новых нет")

        sources = crawler.list_sources(conn)
        if not sources:
            raise SystemExit(
                "Источники не заданы. Запустите с ключом --add-nodes или добавьте "
                "каталоги на странице «Индекс»."
            )
        print(f"Источников: {len(sources)}")

        report = crawler.crawl(conn)
        print(
            f"Обход:  добавлено {report.added}, обновлено {report.updated}, "
            f"пропущено {report.skipped}, удалено {report.removed}, "
            f"ошибок {report.errors}  ({report.took_ms / 1000:.1f} с)"
        )

        statistics = indexer.build_index(conn)
        print(
            f"Индекс: документов {statistics['documents']}, терминов "
            f"{statistics['terms']}, вхождений {statistics['postings']}"
        )

        if arguments.load_qrels:
            loaded = qrels.load_from_csv(conn)
            print(f"Эталон: запросов {loaded['queries']}, оценок {loaded['judgements']}")
            if loaded.get("missing"):
                print("  не найдены документы:", ", ".join(sorted(loaded["missing"])[:10]))

        summary = db.stats(conn)
        print(
            f"\nВ базе: {summary['documents']} документов "
            f"(проиндексировано {summary['indexed']}), {summary['terms']} терминов, "
            f"{summary['hosts']} узлов"
        )


if __name__ == "__main__":
    main()
