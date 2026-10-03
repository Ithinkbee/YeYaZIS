"""sc-агент построения реферата — отдельным процессом.

    python tools/agent.py                    подключиться к ws://localhost:8090 и ждать действий
    python tools/agent.py --url ws://host:8090
    python tools/agent.py --demo ru-cs-ostis создать действие для документа и дождаться ответа

По умолчанию агент регистрируется прямо в процессе веб-интерфейса
(IZBORNIK_AGENT=embedded). Отдельный запуск показывает, что агент — это
самостоятельный компонент решателя задач ostis-системы: веб-интерфейс лишь
помещает в базу знаний действие, а выполняет его тот, кто на него подписан.
В этом случае интерфейс запускается с IZBORNIK_AGENT=external.

Перед регистрацией агент при необходимости загружает онтологию и документы
коллекции в базу знаний — так он работает и без веб-интерфейса.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from izbornik import config, console  # noqa: E402
from izbornik.collection import Collection  # noqa: E402
from izbornik.ostis.service import Service  # noqa: E402

console.setup()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=config.OSTIS_URL)
    parser.add_argument("--demo", metavar="ID", help="построить реферат документа коллекции и выйти")
    parser.add_argument("-n", type=int, default=config.SUMMARY_SENTENCES)
    arguments = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    collection = Collection()
    service = Service(collection, mode="on", url=arguments.url, agent_mode="embedded")
    if not service.start():
        print(f"Не удалось запустить агента: {service.error}")
        return 1
    print(f"Агент построения реферата зарегистрирован на {arguments.url}. Ctrl+C — остановить.")
    try:
        if arguments.demo:
            entry = collection.get(arguments.demo)
            if entry is None:
                print(f"нет документа {arguments.demo}")
                return 1
            summary = service.summarize_entry(entry, arguments.n, force=True)
            print(f"\nРеферат «{summary.title}» — {len(summary.sentences)} предложений, "
                  f"{summary.timings['ostis_total']:.0f} мс:")
            for position, sentence in enumerate(summary.sentences, start=1):
                print(f"  {position:2}. {sentence.text}")
            print("\nКлючевые слова:", ", ".join(k.text for k in summary.keywords.tree))
            return 0
        while service.connection.is_connected():
            time.sleep(1)
        print("Соединение с sc-сервером потеряно.")
        return 1
    except KeyboardInterrupt:
        print("\nОстановка агента.")
        return 0
    finally:
        service.stop()


if __name__ == "__main__":
    sys.exit(main())
