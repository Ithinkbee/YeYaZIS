"""Веб-интерфейс: страницы, реакция на фразу, список операций, тайник, поток звука.

Настройки и пасхалки пишутся во временный каталог (см. conftest.py).
"""

from __future__ import annotations

import json
import re

import numpy as np
import pytest
from fastapi.testclient import TestClient

from sluhach import admin, audio, config


@pytest.fixture(scope="module")
def client():
    from sluhach.web.app import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def fresh(client):
    """Список операций и пасхалки — как при первом запуске; вход администратора сброшен."""
    from sluhach.web.app import state

    def clean():
        state.operations.reset()
        for essay in state.dictations.all():
            state.dictations.remove(essay.id)
        for path in (config.OPERATIONS_PATH, config.EGGS_PATH, config.DICTATED_PATH):
            path.unlink(missing_ok=True)
        state.eggs.load()
        state.admin = admin.Admin()
        client.cookies.clear()

    clean()
    yield client
    clean()


def boot(html: str) -> dict:
    found = re.search(r'<script type="application/json" id="console-data">(.*?)</script>', html, re.S)
    return json.loads(found.group(1))


def login(client: TestClient) -> None:
    credentials = {"login": config.ADMIN_LOGIN, "password": config.ADMIN_PASSWORD}
    assert client.post("/api/admin/login", json=credentials).status_code == 200


# --- страницы -------------------------------------------------------------------------

@pytest.mark.parametrize("url", ["/", "/operations", "/evaluation", "/walk", "/help", "/api/status"])
def test_pages(client, url):
    assert client.get(url).status_code == 200


def test_console_page_starts_with_everything_it_needs(client):
    html = client.get("/").text
    data = boot(html)
    assert data["language"] == "de" and set(data["languages"]) == {"de", "ru"}
    assert data["languages"]["de"]["tag"] == "de-DE" and data["languages"]["ru"]["name"] == "русский"
    assert set(data["engines"]) == {"vosk", "browser"} and data["engine"] == "vosk"
    assert len(data["essays"]["de"]) == 5 and len(data["essays"]["ru"]) == 5
    assert data["essays"]["de"][0]["title"] == "Die Räuber" and data["essays"]["de"][0]["title_ru"] == "Разбойники"
    assert len(data["cheatsheet"]["de"]) == 24 and data["cheatsheet"]["ru"][0]["phrases"][0] == "список сочинений"
    assert data["examples"]["de"] == {"open": "öffne den aufsatz zwei", "dictate": "diktat starten"}
    assert data["dictation"]["limit"] == config.MAX_DRAFT_CHARS
    assert ["запятая", ","] in data["dictation"]["spoken"]["ru"] and ["Komma", ","] in data["dictation"]["spoken"]["de"]
    assert [item["id"] for item in data["cheatsheet"]["ru"] if item["dictation"]] == ["dictate_undo", "dictate_end"]
    assert data["voice"] == "Пафнутий" and data["threshold"] == config.MATCH_THRESHOLD
    assert set(data["status"]["languages"]) == {"de", "ru"}
    for script in ("mic.js", "voice.js", "console.js", "app.js", "pafnuty.js"):
        assert f"/static/{script}?v=" in html
    assert 'id="listen-toggle"' in html and 'id="language-switch"' in html and 'id="journal"' in html


def test_language_can_be_chosen_on_the_page(client):
    html = client.get("/").text
    assert 'data-language="de"' in html and 'data-language="ru"' in html
    assert ">Deutsch<" in html and ">Русский<" in html


def test_static_versions_change_with_the_files(client):
    from sluhach.web.app import static_url

    assert re.fullmatch(r"/static/style\.css\?v=[0-9a-f]+", static_url("style.css"))
    assert static_url("нет-такого.js") == "/static/нет-такого.js"
    assert client.get(static_url("style.css")).status_code == 200


def test_unknown_page_is_404(client):
    response = client.get("/нет-такой-страницы")
    assert response.status_code == 404 and "Страница не найдена" in response.text
    assert client.get("/api/essay/нет").json() == {"error": "нет сочинения «нет»"}
    assert client.get("/report/../run.py").status_code == 404
    assert client.get("/report/evaluation.json").status_code == 404        # наружу отдаются только графики


def test_help_page_lists_operations(client):
    html = client.get("/help").text
    assert "Справка" in html and "Открыть сочинение" in html and "öffne den aufsatz ‹Nummer oder Titel›" in html
    assert "vosk-model-small-de-0.15" in html and "Если что-то не так" in html


def test_help_tells_about_the_admin_but_not_the_password(client):
    """Справку читают все: в ней сказано, где вход администратора, но не имя и не пароль."""
    text = client.get("/help").text.split("<main>")[1].split("</main>")[0]
    assert 'id="admin"' in text and "Вход администратора" in text and "фразы-пасхалки" in text.lower()
    assert config.ADMIN_PASSWORD not in text and "--admin-password" in text


def test_evaluation_page(client):
    html = client.get("/evaluation").text
    assert "Проверка распознавания и реакции" in html
    assert ("WER" in html and "Верная реакция" in html) or "python tools/evaluate.py" in html


# --- реакция на фразу ----------------------------------------------------------------------

def react(client: TestClient, text: str, session: dict | None = None) -> dict:
    response = client.post("/api/react", json={"text": text, "session": session or {"language": "de"}, "source": "keyboard"})
    assert response.status_code == 200
    return response.json()


def test_react_runs_an_operation(fresh):
    data = react(fresh, "Öffne den Aufsatz über Kafka")
    assert data["kind"] == "operation" and data["operation"] == "open" and data["title"] == "Открыть сочинение"
    assert data["session"]["essay"] == "de-lit-verwandlung" and data["speech_language"] == "de"
    assert data["speech"].startswith("Ich öffne den Aufsatz „Die Verwandlung“") and data["gloss"].startswith("Открываю")


def test_react_keeps_the_conversation_on_the_page(fresh):
    """Сервер не помнит разговор: состояние приходит с фразой и уходит с ответом."""
    first = react(fresh, "öffne aufsatz eins")
    second = react(fresh, "weiter", first["session"])
    assert second["operation"] == "next" and second["session"]["paragraph"] == 1
    assert second["effects"] == [{"type": "read", "index": 1}]
    alone = react(fresh, "weiter")                                          # без состояния сочинение не открыто
    assert alone["speech"].startswith("Öffnen Sie zuerst einen Aufsatz")


def test_react_echo_egg_and_noise(fresh):
    assert react(fresh, "heute ist schönes wetter")["speech"] == "Ich wiederhole: heute ist schönes wetter."
    egg = react(fresh, "Сколько стоит слон?", {"language": "ru"})
    assert egg["kind"] == "egg" and egg["speech"] == "Вам тут не рынок и не цирк."
    assert react(fresh, "hm")["kind"] == "noise" and react(fresh, "")["kind"] == "silence"


def test_react_tolerates_bad_input(fresh):
    assert react(fresh, "lies vor", {"language": "xx", "essay": 42, "paragraph": "много"})["kind"] == "operation"
    assert fresh.post("/api/react", json={"text": "lies vor", "session": "мусор"}).status_code == 422
    assert fresh.post("/api/react", json={"text": "я" * 3000}).status_code == 422
    assert fresh.post("/api/react", content=b"not json", headers={"Content-Type": "application/json"}).status_code == 422
    assert fresh.post("/api/react", json={}).json()["kind"] == "silence"


def test_essay_api(client):
    data = client.get("/api/essay/ru-lit-onegin").json()
    assert data["title"] == "Евгений Онегин" and len(data["items"]) == data["paragraphs"] == 45
    assert data["items"][0]["section"] == "История создания" and data["source"]["license"] == "CC BY-SA 4.0"


# --- диктовка -----------------------------------------------------------------------------

def say(client, text: str, session: dict | None, **extra) -> dict:
    return client.post("/api/react", json={"text": text, "session": session, **extra}).json()


def test_dictation_goes_through_the_page(fresh):
    started = say(fresh, "", {"language": "ru"}, action="dictate")              # кнопка «Диктовать»
    assert started["operation"] == "dictate" and started["speech"] == "Диктуйте."
    assert started["session"]["draft"] == {"text": "", "title": "", "essay": "", "period": True, "undo": []}

    written = say(fresh, "татьяна любит онегина", started["session"])
    assert written["kind"] == "dictation" and written["speech"] == "" and written["display"] == "Татьяна любит Онегина."
    session = written["session"]
    assert session["draft"]["text"] == "Татьяна любит Онегина." and session["draft"]["undo"] == [[0, ""]]

    session["draft"]["title"] = "Про Татьяну"                                   # название вписано на странице
    saved = say(fresh, "конец диктовки", session)
    assert saved["operation"] == "dictate_end" and saved["session"]["draft"] is None
    essay_id = saved["session"]["essay"]
    assert saved["speech"] == "Сохранил сочинение «Про Татьяну»: 3 слова. Оно открыто."
    listed = saved["effects"][0]
    assert listed["type"] == "essays" and listed["language"] == "ru" and len(listed["items"]) == 6
    assert listed["items"][-1]["id"] == essay_id and listed["items"][-1]["dictated"]

    content = fresh.get(f"/api/essay/{essay_id}").json()
    assert content["dictated"] and content["title"] == "Про Татьяну" and content["created"]
    assert [item["text"] for item in content["items"]] == ["Татьяна любит Онегина."]
    assert boot(fresh.get("/").text)["essays"]["ru"][-1]["id"] == essay_id      # и после перезагрузки страницы
    assert say(fresh, "сколько слов", saved["session"])["speech"] == "В сочинении 3 слова, 1 предложение и 1 абзац."

    removed = fresh.delete(f"/api/dictations/{essay_id}")
    assert removed.status_code == 200 and removed.json()["language"] == "ru" and len(removed.json()["essays"]) == 5
    assert fresh.get(f"/api/essay/{essay_id}").status_code == 404
    assert fresh.delete(f"/api/dictations/{essay_id}").status_code == 404


def test_catalog_essays_cannot_be_removed(fresh):
    assert fresh.delete("/api/dictations/ru-lit-onegin").status_code == 404
    assert fresh.get("/api/essay/ru-lit-onegin").status_code == 200


def test_unknown_action_is_just_a_phrase(fresh):
    reaction = say(fresh, "который час", {"language": "ru"}, action="game")     # кнопкой вызывается только диктовка
    assert reaction["operation"] == "time"
    assert say(fresh, "", {"language": "ru"}, action="нет такой")["kind"] == "silence"


def test_long_phrase_is_accepted_during_dictation(fresh):
    session = say(fresh, "", {"language": "ru"}, action="dictate")["session"]
    phrase = " ".join(["слово"] * 300)
    assert len(phrase) > config.MAX_PHRASE_CHARS
    assert say(fresh, phrase, session)["session"]["draft"]["text"].count("лово") == 300
    too_long = fresh.post("/api/react", json={"text": "я" * (config.MAX_DICTATED_PHRASE_CHARS + 1), "session": session})
    assert too_long.status_code == 422


# --- проверка своим голосом ---------------------------------------------------------------

def test_selftest_block_is_on_the_evaluation_page(client):
    html = client.get("/evaluation").text
    assert 'id="selftest"' in html and "Проверка своим голосом" in html and 'id="selftest-start"' in html
    assert "/static/selftest.js?v=" in html and "/static/mic.js?v=" in html
    data = json.loads(re.search(r'<script type="application/json" id="selftest-data">(.*?)</script>', html, re.S).group(1))
    assert set(data["languages"]) == {"de", "ru"} and data["pause"] == 1200
    assert set(data["lines"]) == {"selftest_start", "selftest_good", "selftest_fair", "selftest_poor"}
    assert set(data["status"]["languages"]) == {"de", "ru"}


def test_selftest_phrases_and_score(client):
    first = client.get("/api/selftest/phrases", params={"language": "ru", "seed": 3}).json()
    again = client.get("/api/selftest/phrases", params={"language": "ru", "seed": 3}).json()
    assert first == again and first["language"] == "ru" and len(first["phrases"]) == 10
    assert [p["kind"] for p in first["phrases"]] == ["command"] * 6 + ["sentence"] * 4
    assert all(p["title"] for p in first["phrases"][:6]) and not any(p["title"] for p in first["phrases"][6:])
    assert client.get("/api/selftest/phrases", params={"language": "de"}).json()["phrases"][0]["kind"] == "command"
    assert client.get("/api/selftest/phrases", params={"language": "fr"}).status_code == 400

    command, sentence = first["phrases"][0], first["phrases"][-1]
    result = client.post("/api/selftest/score", json={"items": [
        {"id": command["id"], "heard": command["text"]}, {"id": sentence["id"], "heard": "совсем не то"}]}).json()
    assert [entry["exact"] for entry in result["items"]] == [True, False]
    assert result["items"][0]["reaction_ok"] and result["items"][0]["alignment"][0]["op"] == "ok"
    assert result["totals"]["all"]["phrases"] == 2 and result["totals"]["command"]["reaction_ok"] == 1
    assert result["language"] == "ru"
    if result["synthetic"] is not None:                                         # числа синтезатора — если проверка запускалась
        assert 0 <= result["synthetic"]["command"]["reaction"] <= 1
    assert client.post("/api/selftest/score", json={"items": []}).json()["items"] == []
    assert client.post("/api/selftest/score", json={"items": [{}] * 41}).status_code == 422


def test_selftest_ignores_user_settings_and_dictations(fresh):
    """Проверка своим голосом, как и проверка на озвученных фразах, идёт по умолчаниям."""
    from sluhach.web.app import state

    state.operations.update({"time": {"enabled": False}})
    state.dictations.save("ru", "Моё", "Лишнее сочинение.")
    phrases = {p["id"]: p for seed in range(8)
               for p in fresh.get("/api/selftest/phrases", params={"language": "ru", "seed": seed}).json()["phrases"]}
    timed = next((p for p in phrases.values() if p["operation"] == "time"), None)
    assert timed is not None                                                    # выключенная операция в наборе осталась
    result = fresh.post("/api/selftest/score", json={"items": [{"id": timed["id"], "heard": timed["text"]}]}).json()
    assert result["items"][0]["reaction_ok"]


# --- список операций -----------------------------------------------------------------------

def form(**changes) -> dict:
    """Форма страницы «Операции» целиком, с правками: enabled_<id>=False, <id>_<язык>=[фразы]."""
    from sluhach.operations import DEFAULTS

    data = {}
    for operation in DEFAULTS:
        if changes.get(f"enabled_{operation.id}", True):
            data[f"enabled-{operation.id}"] = "on"
        for language in config.LANGUAGE_CODES:
            phrases = changes.get(f"{operation.id}_{language}", operation.phrases[language])
            data[f"phrases-{operation.id}-{language}"] = "\n".join(phrases)
    return data


def test_operations_page_shows_the_list(fresh):
    html = fresh.get("/operations").text
    assert "24 из 24" in html and html.count('type="checkbox"') == 24
    assert 'name="phrases-open-de"' in html and "öffne den aufsatz {target}" in html
    assert "Что делает система, услышав фразу" in html


def test_saving_the_list_changes_what_the_system_reacts_to(fresh):
    response = fresh.post("/operations", data=form(enabled_time=False, read_ru=["огласи", "зачитай"]),
                          follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/operations?saved=1"
    html = fresh.get("/operations?saved=1").text
    assert "Список операций сохранён" in html and "23 из 24" in html and "фразы изменены" in html
    assert react(fresh, "который час", {"language": "ru"})["kind"] == "echo"           # операция выключена
    opened = react(fresh, "открой сочинение один", {"language": "ru"})
    assert react(fresh, "огласи", opened["session"])["operation"] == "read"
    assert react(fresh, "читай", opened["session"])["kind"] == "echo"
    sheet = boot(fresh.get("/").text)["cheatsheet"]["ru"]                              # и подсказка на пульте обновилась
    assert "time" not in [item["id"] for item in sheet]
    assert next(item for item in sheet if item["id"] == "read")["phrases"] == ["огласи", "зачитай"]
    assert config.OPERATIONS_PATH.exists()


def test_bad_list_is_shown_back_with_errors(fresh):
    response = fresh.post("/operations", data=form(read_de=["lies vor", "lies {word}"], enabled_time=False))
    assert response.status_code == 200 and "Не сохранено" in response.text
    assert "у этой операции нет параметра" in response.text
    assert "lies {word}" in response.text                                   # введённое не пропало
    assert react(fresh, "wie spät ist es")["operation"] == "time"           # и ничего не применилось
    assert not config.OPERATIONS_PATH.exists()


def test_reset_brings_the_defaults_back(fresh):
    fresh.post("/operations", data=form(enabled_time=False))
    response = fresh.post("/operations/reset", follow_redirects=False)
    assert response.status_code == 303 and "reset=1" in response.headers["location"]
    assert "возвращён к исходному" in fresh.get("/operations?reset=1").text
    assert react(fresh, "wie spät ist es")["operation"] == "time"


# --- тайник -----------------------------------------------------------------------------------

def test_secret_window_is_empty_until_login(fresh):
    html = fresh.get("/").text
    assert 'id="secret"' in html and 'id="secret-name"' in html and 'id="secret-password"' in html
    assert "Сколько стоит слон" not in html and "не рынок" not in html             # фраз в разметке нет
    assert f'value="{config.ADMIN_LOGIN}"' not in html                             # и имя администратора не подсказано
    for method, url in (("get", "/api/eggs"), ("post", "/api/eggs"), ("put", "/api/eggs/default1"),
                        ("delete", "/api/eggs/default1"), ("post", "/api/eggs/test")):
        response = getattr(fresh, method)(url, **({} if method in {"get", "delete"} else {"json": {"key": "a", "answer": "b"}}))
        assert response.status_code == 401 and response.json() == {"error": "нужен вход администратора"}, url
    assert react(fresh, "сколько стоит слон", {"language": "ru"})["kind"] == "egg"   # сами пасхалки при этом работают


def test_login(fresh):
    for credentials in ({"login": config.ADMIN_LOGIN, "password": "не тот"},
                        {"login": "не тот", "password": config.ADMIN_PASSWORD},
                        {"password": config.ADMIN_PASSWORD}, {}):
        response = fresh.post("/api/admin/login", json=credentials)
        assert response.status_code == 403 and response.json() == {"error": "неверное имя или пароль"}
    assert fresh.get("/api/eggs").status_code == 401
    assert fresh.get("/api/admin/state").json() == {"admin": False}

    response = fresh.post("/api/admin/login", json={"login": config.ADMIN_LOGIN, "password": config.ADMIN_PASSWORD})
    assert response.status_code == 200
    assert [egg["key"] for egg in response.json()["eggs"]] == ["Сколько стоит слон?", "Wie viel kostet ein Elefant?"]
    cookie = response.headers["set-cookie"]
    assert admin.COOKIE in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert fresh.get("/api/eggs").status_code == 200
    assert fresh.get("/api/admin/state").json() == {"admin": True}

    assert fresh.post("/api/admin/logout").json() == {"admin": False}
    assert fresh.get("/api/eggs").status_code == 401
    assert fresh.get("/api/admin/state").json() == {"admin": False}


def test_pages_show_the_way_in_and_the_way_out(fresh):
    """Всем видна ссылка входа; вошедшему — пункт «Тайник» и выход. Пасхалок в разметке нет ни у кого."""
    for url in ("/", "/operations", "/help"):
        html = fresh.get(url).text
        assert "Вход администратора" in html and "data-admin-open" in html
        assert "is-admin" not in html.split("<body", 1)[1].split(">", 1)[0], url
    login(fresh)
    for url in ("/", "/operations", "/help"):
        html = fresh.get(url).text
        assert "is-admin" in html.split("<body", 1)[1].split(">", 1)[0], url
        assert "data-admin-logout" in html and ">Тайник<" in html
        assert "Сколько стоит слон" not in html
    fresh.post("/api/admin/logout")
    assert "is-admin" not in fresh.get("/").text.split("<body", 1)[1].split(">", 1)[0]


def test_admin_address_opens_the_window(fresh):
    response = fresh.get("/admin", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/#admin"
    assert "location.hash === '#admin'" in fresh.get("/static/app.js").text


def test_login_is_locked_after_wrong_passwords(fresh):
    wrong = {"login": config.ADMIN_LOGIN, "password": "мимо"}
    for _ in range(config.ADMIN_ATTEMPTS):
        assert fresh.post("/api/admin/login", json=wrong).json()["error"] == "неверное имя или пароль"
    response = fresh.post("/api/admin/login", json={"login": config.ADMIN_LOGIN, "password": config.ADMIN_PASSWORD})
    assert response.status_code == 403 and "слишком много попыток" in response.json()["error"]


def test_stolen_or_invented_cookie_does_not_open(fresh):
    fresh.cookies.set(admin.COOKIE, "made-up-session-key")
    assert fresh.get("/api/eggs").status_code == 401


def test_admin_edits_eggs_and_the_system_answers(fresh):
    login(fresh)
    response = fresh.post("/api/eggs", json={"key": "Кто живёт в углу?", "answer": "Я живу. И мух не отдам."})
    assert response.status_code == 200 and len(response.json()["eggs"]) == 3
    egg = response.json()["eggs"][-1]
    assert egg["language"] == "ru" and config.EGGS_PATH.exists()
    assert react(fresh, "кто живет в углу", {"language": "ru"})["speech"] == "Я живу. И мух не отдам."

    response = fresh.put(f"/api/eggs/{egg['id']}", json={"key": "Кто сидит в углу?", "answer": "Пафнутий."})
    assert response.json()["eggs"][-1]["answer"] == "Пафнутий."
    assert react(fresh, "кто сидит в углу", {"language": "ru"})["speech"] == "Пафнутий."

    assert fresh.delete(f"/api/eggs/{egg['id']}").json()["eggs"][-1]["key"] == "Wie viel kostet ein Elefant?"
    assert react(fresh, "кто сидит в углу", {"language": "ru"})["kind"] == "echo"
    assert fresh.delete(f"/api/eggs/{egg['id']}").status_code == 404


def test_bad_egg_is_refused_with_a_reason(fresh):
    login(fresh)
    response = fresh.post("/api/eggs", json={"key": "да", "answer": "нет"})
    assert response.status_code == 400 and "слишком короткая" in response.json()["error"]
    assert len(response.json()["eggs"]) == 2                               # список возвращается и при ошибке
    assert fresh.post("/api/eggs", json={"key": "сколько стоит слон", "answer": "дубль"}).status_code == 400
    assert fresh.put("/api/eggs/нет", json={"key": "Кто там?", "answer": "Никого."}).status_code == 400


def test_probe_tells_which_egg_would_answer(fresh):
    login(fresh)
    data = fresh.post("/api/eggs/test", json={"text": "пафнутий, сколько стоит слон"}).json()
    assert data["match"]["answer"] == "Вам тут не рынок и не цирк." and data["score"] == 1.0
    assert fresh.post("/api/eggs/test", json={"text": "сколько стоит билет"}).json() == {"match": None}


# --- поток звука ------------------------------------------------------------------------------

def test_websocket_greets_and_switches_language(client):
    with client.websocket_connect("/ws/listen") as socket:
        hello = socket.receive_json()
        assert hello["type"] == "hello" and hello["rate"] == config.SAMPLE_RATE and "languages" in hello["status"]
        socket.send_json({"type": "language", "code": "ru"})
        assert socket.receive_json()["code"] == "ru"
        socket.send_text("это не JSON")                                     # мусор не роняет соединение
        socket.send_json({"type": "language", "code": "fr"})               # неизвестный язык не принимается
        socket.send_json({"type": "config", "margin": "много", "pause": None})
        socket.send_json({"type": "нет такого"})
        socket.send_bytes(b"\x00" * (5 * config.SAMPLE_RATE))              # слишком большой кусок отбрасывается
        socket.send_json({"type": "language", "code": "de"})
        assert socket.receive_json() == {"type": "language", "code": "de", "state": socket_state(client, "de")}


def socket_state(client: TestClient, language: str) -> str:
    return client.get("/api/status").json()["languages"][language]["state"]


def stream(socket, pcm: bytes, chunk: int = 3200) -> list[dict]:
    """Шлёт звук кусками и собирает события до отметки-конца."""
    for offset in range(0, len(pcm), chunk):
        socket.send_bytes(pcm[offset:offset + chunk])
    socket.send_json({"type": "language", "code": "fr"})                    # ничего не меняет
    socket.send_json({"type": "language", "code": "ru"})                    # ответ на это — отметка конца
    events = []
    while True:
        event = socket.receive_json()
        if event["type"] == "language":
            return events
        events.append(event)


def test_websocket_recognises_speech(client, engine, recordings):
    item = next(r for r in recordings if r["file"] == "de-open.wav")
    samples = audio.add_noise(audio.pad(audio.read_wav(item["path"]), 600, 1200), 50, np.random.default_rng(5))
    with client.websocket_connect("/ws/listen") as socket:
        socket.receive_json()
        socket.send_json({"type": "language", "code": "de"})
        socket.receive_json()
        events = stream(socket, samples.astype("<i2").tobytes())
    kinds = [event["type"] for event in events if event["type"] != "level"]
    assert kinds[0] == "speech_start" and kinds[-2:] == ["speech_end", "final"] and "partial" in kinds
    final = next(event for event in events if event["type"] == "final")
    assert final["text"] == "öffne den aufsatz über die räuber" and final["language"] == "de"
    # и распознанная фраза выполняется
    assert react(client, final["text"])["session"]["essay"] == "de-lit-raeuber"


def test_websocket_does_not_listen_while_the_system_speaks(client, engine, recordings):
    item = next(r for r in recordings if r["file"] == "de-open.wav")
    pcm = audio.add_noise(audio.pad(audio.read_wav(item["path"]), 600, 1200), 50,
                          np.random.default_rng(5)).astype("<i2").tobytes()
    with client.websocket_connect("/ws/listen") as socket:
        socket.receive_json()
        socket.send_json({"type": "language", "code": "de"})
        socket.receive_json()
        socket.send_json({"type": "mute", "on": True})
        assert stream(socket, pcm) == []                                    # звук пришёл, событий нет
        socket.send_json({"type": "language", "code": "de"})
        socket.receive_json()
        socket.send_json({"type": "mute", "on": False})
        finals = [event for event in stream(socket, pcm) if event["type"] == "final"]
    assert len(finals) == 1 and "aufsatz" in finals[0]["text"]
