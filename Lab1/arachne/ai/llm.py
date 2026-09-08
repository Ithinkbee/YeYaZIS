"""Необязательный языковой помощник поверх поисковой выдачи.

Работает с любым OpenAI-совместимым сервисом (Groq, OpenRouter, Mistral,
Cerebras, Together — адрес и модель задаются в .env). Слой полностью
отключаемый: без ключа система работает как обычная векторная ИПС, просто без
кнопок помощника. Сам поиск и ранжирование языковая модель не выполняет — она
только помогает пользователю сформулировать запрос и кратко изложить то, что
уже нашла ИПС.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .. import config


class LLMUnavailable(Exception):
    """Помощник выключен или сервис недоступен."""


def available() -> bool:
    return bool(config.LLM_ENABLED and config.LLM_API_KEY)


def _disabled_reason() -> str:
    """Почему помощник недоступен — текст для интерфейса."""
    if not config.LLM_API_KEY:
        return "не задан LLM_API_KEY в файле .env"
    # ключ есть, значит выключен флагом: это состояние по умолчанию
    return "выключен (ARACHNE_LLM=1 в .env — включить)"


def status() -> dict:
    return {
        "enabled": available(),
        "model": config.LLM_MODEL if available() else "",
        "provider": config.LLM_PROVIDER,
        "base_url": config.LLM_BASE_URL,
        "reason": "" if available() else _disabled_reason(),
    }


def _headers() -> dict:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.LLM_API_KEY}",
    }
    if "openrouter" in config.LLM_BASE_URL:
        # OpenRouter просит указывать источник запроса
        headers["HTTP-Referer"] = "http://localhost/arachne"
        headers["X-Title"] = "Arachne IR system"
    return headers


def _explain_http_error(code: int, detail: str) -> str:
    """Понятное объяснение вместо голого кода ответа."""
    if code == 401:
        return "сервис не принял ключ (401): проверьте LLM_API_KEY в .env"
    if code == 403:
        return (
            f"провайдер «{config.LLM_PROVIDER}» отклонил запрос по адресу выхода в "
            "сеть (403). Ключ здесь ни при чём: отказ приходит от защитного контура "
            "провайдера ещё до проверки ключа. Так закрывают доступ с адресов "
            "дата-центров, к которым относится большинство VPN. Смена узла того же "
            "VPN обычно не помогает — весь пул адресов в одном списке. Рабочий путь: "
            "выбрать провайдера, который пускает с вашего адреса — "
            "python tools/check_llm.py --scan"
        )
    if code == 404:
        return f"модель «{config.LLM_MODEL}» не найдена у провайдера (404)"
    if code == 429:
        return "превышен лимит запросов (429), попробуйте позже"
    return f"сервис вернул {code}: {detail}"


def chat(
    messages: list[dict],
    temperature: float = 0.3,
    max_tokens: int = 700,
) -> str:
    """Запрос к чат-модели по OpenAI-совместимому интерфейсу."""
    if not available():
        raise LLMUnavailable("языковой помощник выключен")

    payload = json.dumps(
        {
            "model": config.LLM_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        f"{config.LLM_BASE_URL}/chat/completions",
        data=payload,
        headers=_headers(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.LLM_TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:300]
        raise LLMUnavailable(_explain_http_error(exc.code, detail)) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LLMUnavailable(f"нет связи с сервисом: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise LLMUnavailable("некорректный ответ сервиса") from exc

    try:
        return body["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, AttributeError) as exc:
        raise LLMUnavailable("ответ сервиса не содержит текста") from exc


def check() -> dict:
    """Диагностика: доступен ли сервис и принимает ли он ключ."""
    result = {"provider": config.LLM_PROVIDER, "base_url": config.LLM_BASE_URL,
              "model": config.LLM_MODEL, "key": bool(config.LLM_API_KEY)}
    if not config.LLM_API_KEY:
        result.update(ok=False, message="ключ не задан (LLM_API_KEY в .env)")
        return result
    try:
        answer = chat(
            [{"role": "user", "content": "Ответь одним словом: работает"}],
            temperature=0.0,
            max_tokens=16,
        )
        result.update(ok=True, message=f"сервис ответил: {answer}")
    except LLMUnavailable as exc:
        result.update(ok=False, message=str(exc))
    return result


SYSTEM_PROMPT = (
    "Ты — помощник информационно-поисковой системы по документам локальной сети "
    "организации. Отвечай по-русски, кратко и по существу, опираясь только на "
    "переданные фрагменты документов. Если сведений недостаточно, честно скажи об этом."
)


def answer_over_documents(query: str, documents: list[dict]) -> str:
    """Краткая сводка по найденным документам со ссылками на их номера."""
    if not documents:
        raise LLMUnavailable("нет документов для обобщения")

    context = "\n\n".join(
        f"[{index}] {document['title']}\n{document['text'][:1200]}"
        for index, document in enumerate(documents, 1)
    )
    return chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Запрос пользователя: «{query}»\n\n"
                    f"Найденные документы:\n{context}\n\n"
                    "Составь ответ в 3–5 предложениях. После каждого утверждения "
                    "указывай номер документа в квадратных скобках, например [2]. "
                    "Не придумывай фактов, которых нет в документах."
                ),
            },
        ],
        temperature=0.2,
        max_tokens=500,
    )


def rephrase_query(query: str, vocabulary_hint: list[str] | None = None) -> list[str]:
    """Варианты переформулировки запроса — подсказка при плохой выдаче."""
    hint = ""
    if vocabulary_hint:
        hint = "Слова, которые точно есть в коллекции: " + ", ".join(vocabulary_hint[:40])
    text = chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Пользователь ищет: «{query}». {hint}\n"
                    "Предложи три коротких варианта того же запроса другими словами. "
                    "Ответь только списком вариантов, по одному в строке, без нумерации "
                    "и пояснений."
                ),
            },
        ],
        temperature=0.6,
        max_tokens=200,
    )
    variants = [line.strip(" -•\t") for line in text.splitlines() if line.strip()]
    return variants[:3]


def explain_relevance(query: str, title: str, fragment: str) -> str:
    """Объяснение, чем документ отвечает запросу (дополняет числовое объяснение)."""
    return chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Запрос: «{query}»\nДокумент: {title}\nФрагмент: {fragment[:1500]}\n\n"
                    "Объясни в одном-двух предложениях, чем этот документ полезен по "
                    "запросу. Если он не по теме — так и скажи."
                ),
            },
        ],
        temperature=0.3,
        max_tokens=200,
    )


def companion_line(context: str) -> str:
    """Реплика паука-компаньона (используется, только если помощник включён)."""
    return chat(
        [
            {
                "role": "system",
                "content": (
                    f"Ты — {config.COMPANION_NAME}, паук, живущий в углу окна "
                    "поисковой системы. Ты дружелюбный, ироничный и очень краткий: "
                    "одна фраза не длиннее двенадцати слов, без смайликов."
                ),
            },
            {"role": "user", "content": context},
        ],
        temperature=0.9,
        max_tokens=60,
    )
