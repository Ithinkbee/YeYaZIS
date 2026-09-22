"""Диагностика языкового помощника: сеть, доступность провайдера, ключ.

    python tools/check_llm.py            — проверить настроенного провайдера
    python tools/check_llm.py --scan     — проверить доступность всех известных

Главное, что показывает проверка: доступность сервиса определяется адресом
выхода в сеть, а не ключом. Часть провайдеров закрывает доступ с адресов
дата-центров (а значит, и с большинства VPN) и отвечает 403 ещё до того, как
посмотрит на ключ.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arachne import config  # noqa: E402
from arachne.ai import llm  # noqa: E402


def http_status(url: str, timeout: float = 12.0) -> str:
    """Код ответа на GET без ключа: 401 — сервис доступен, 403 — адрес заблокирован."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return str(response.status)
    except urllib.error.HTTPError as exc:
        return str(exc.code)
    except Exception as exc:  # noqa: BLE001
        return f"нет связи ({type(exc).__name__})"


def verdict(code: str) -> tuple[bool, str]:
    """Расшифровка кода: пускает ли сервис с этого адреса."""
    if code in {"200", "401", "404"}:
        # сервис ответил по существу — контур доступа пройден, дело за ключом
        return True, "доступен, нужен только ключ"
    if code == "403":
        return False, "закрыт для вашего адреса выхода в сеть"
    if code == "429":
        return True, "доступен, но лимит запросов исчерпан"
    return False, code


def external_ip() -> str:
    try:
        with urllib.request.urlopen("http://ip-api.com/json/?fields=query,country,isp,hosting",
                                    timeout=12) as response:
            data = json.loads(response.read().decode())
        marker = ", адрес дата-центра/VPN" if data.get("hosting") else ""
        return f"{data.get('query')} ({data.get('country')}, {data.get('isp')}{marker})"
    except Exception:  # noqa: BLE001
        return "не удалось определить"


def scan() -> None:
    """Опрашивает всех известных провайдеров параллельно и советует рабочего."""
    print("\nДоступность известных сервисов с текущего адреса")
    print("  (проверка идёт без ключа: она показывает именно сетевой доступ)\n")

    names = list(config.LLM_PROVIDERS)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(names)) as pool:
        codes = dict(zip(names, pool.map(
            lambda name: http_status(config.LLM_PROVIDERS[name][0] + "/models"), names)))

    reachable = []
    for name in names:
        ok, note = verdict(codes[name])
        if ok:
            reachable.append(name)
        mark = "+" if ok else "-"
        print(f"  {mark} {name:<12} {codes[name]:>18}   {note}")
        print(f"      модель по умолчанию: {config.LLM_PROVIDERS[name][1]}")

    print()
    if not reachable:
        print("Ни один сервис не отвечает — похоже, нет выхода в сеть вообще.")
        return
    if config.LLM_PROVIDER in reachable:
        print(f"Текущий провайдер «{config.LLM_PROVIDER}» доступен: если запрос всё же "
              "не проходит, дело в ключе или в имени модели.")
        return

    choice = reachable[0]
    print(f"Текущий провайдер «{config.LLM_PROVIDER}» с этого адреса недоступен.")
    print(f"Доступны: {', '.join(reachable)}. Чтобы перейти, например, на «{choice}», "
          "укажите в .env:")
    print(f"  LLM_PROVIDER={choice}")
    print(f"  LLM_API_KEY=ключ_от_{choice}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Проверка языкового помощника ИПС «Арахна»")
    parser.add_argument("--scan", action="store_true",
                        help="проверить доступность всех известных сервисов")
    arguments = parser.parse_args()

    print("Выход в сеть:", external_ip())
    print(f"Провайдер:    {config.LLM_PROVIDER}  ({config.LLM_BASE_URL})")
    print(f"Модель:       {config.LLM_MODEL}")
    print(f"Ключ задан:   {'да' if config.LLM_API_KEY else 'нет'}")
    print()

    code = http_status(f"{config.LLM_BASE_URL}/models")
    ok, note = verdict(code)
    print(f"Доступность эндпоинта без ключа: {code} — {note}")

    result = llm.check()
    print("Проверка запроса:", "УСПЕХ" if result.get("ok") else "ОШИБКА")
    print(" ", result.get("message"))

    if arguments.scan:
        scan()
    elif not ok:
        print("\nЧтобы увидеть, какие сервисы пускают с вашего адреса:")
        print("  python tools/check_llm.py --scan")


if __name__ == "__main__":
    main()
