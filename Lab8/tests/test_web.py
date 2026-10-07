"""Веб-интерфейс: страницы, синтез, словарь, настройки, другие программы, игра.

Словарь, настройки и реплики Пафнутия пишутся во временные каталоги (см. conftest.py).
"""

from __future__ import annotations

import json
import re

import numpy as np
import pytest
from fastapi.testclient import TestClient

from glashatai import config, dsp, pafnuty


@pytest.fixture(scope="module")
def client():
    from glashatai.web.app import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def clean(client):
    from glashatai.web.app import state

    state.speaker.reader.lexicon.user.clear()
    yield client
    state.speaker.reader.lexicon.user.clear()


def boot(html: str) -> dict:
    return json.loads(re.search(r'<script type="application/json" id="boot">(.*?)</script>', html, re.S).group(1))


# --- страницы ---------------------------------------------------------------------------------

@pytest.mark.parametrize("url", ["/", "/articles", "/articles/de-cs-compiler", "/elsewhere", "/lexicon", "/evaluation",
                                 "/talking", "/help", "/demo", "/api/voices", "/api/settings", "/api/desktop",
                                 "/api/lexicon", "/static/pointer.js"])
def test_pages(client, url):
    assert client.get(url).status_code == 200


def test_reader_page_has_everything(client):
    html = client.get("/").text
    data = boot(html)
    assert {"voices", "default", "settings", "options", "ranges", "kinds"} <= set(data)
    assert data["settings"]["voice"] and data["ranges"]["rate"] == list(config.RATE_RANGE)
    assert any(v["id"] == "formant:karl" for v in data["voices"])
    for script in ("player.js", "settings.js", "docview.js", "reader.js", "app.js", "pafnuty.js"):
        assert f"/static/{script}?v=" in html
    assert 'id="text"' in html and "Übersetzerbau" in html


def test_missing_pages(client):
    assert client.get("/articles/nope").status_code == 404
    assert "не найдена" in client.get("/nowhere").text
    assert client.get("/api/nowhere").json()["error"]
    assert client.get("/report/../run.py").status_code == 404


# --- синтез ------------------------------------------------------------------------------------

def test_prepare(client):
    data = client.post("/api/prepare", json={"text": "# Titel\n\nAb 1954 nutzt z. B. die CPU. Zweiter Satz."}).json()
    paragraphs = data["paragraphs"]
    assert paragraphs[0]["heading"] and len(paragraphs[1]["sentences"]) == 2
    first = paragraphs[1]["sentences"][0]
    assert first["text"] == "Ab 1954 nutzt z. B. die CPU." and "neunzehnhundert" in first["say"]
    assert data["stats"]["changed"] == 3 and data["stats"]["sentences"] == 3
    assert client.post("/api/prepare", json={"text": "1954", "options": {"numbers": False}}).json()[
        "paragraphs"][0]["sentences"][0]["say"] == "1954."


def test_speak_returns_wav(client):
    response = client.post("/api/speak", json={"text": "Ein kurzer Satz.", "settings": {"voice": "formant:karl"}})
    assert response.status_code == 200 and response.headers["content-type"] == "audio/wav"
    assert response.headers["x-voice"] == "formant:karl" and response.headers["x-fallback"] == "0"
    samples, rate = dsp.read_wav(response.content)
    assert rate == 22050 and float(response.headers["x-duration"]) == pytest.approx(len(samples) / rate, abs=0.01)
    again = client.post("/api/speak", json={"text": "Ein kurzer Satz.", "settings": {"voice": "formant:karl"}})
    assert again.headers["x-cached"] == "1"


def test_speak_falls_back_for_unknown_voice(client):
    response = client.post("/api/speak", json={"text": "Hallo.", "settings": {"voice": "sapi:Microsoft Nobody"}})
    assert response.status_code == 200 and response.headers["x-fallback"] == "1"


def test_render_whole_text(client):
    response = client.post("/api/render", json={"text": "Erster Satz. Zweiter Satz.",
                                                "settings": {"voice": "formant:karl", "volume": 50}})
    assert response.status_code == 200
    assert "Erster-Satz-Zweiter-Satz.wav" in response.headers["content-disposition"]
    assert client.post("/api/render", json={"text": "  "}).status_code == 400


def test_say_wav_for_bookmarklet(client):
    response = client.get("/api/say.wav", params={"text": "Hallo von einer fremden Seite.", "voice": "formant:klara"})
    assert response.status_code == 200 and response.headers["access-control-allow-origin"] == "*"
    assert response.headers["access-control-allow-private-network"] == "true"
    assert client.get("/api/say.wav").status_code == 400
    assert client.options("/api/say.wav").headers["access-control-allow-origin"] == "*"


def test_transcribe(client):
    data = client.post("/api/transcribe", json={"text": "Der Compiler übersetzt."}).json()
    words = {w["word"]: w for w in data["words"]}
    assert words["Kompeiler"]["kind"] == "english" and words["übersetzt"]["ipa"]
    assert data["score"] and data["score"][0]["symbol"] == "_"


def test_extract_upload(client):
    response = client.post("/api/extract", files={"file": ("seite.html", b"<title>T</title><p>Hallo</p>", "text/html")})
    assert response.json() == {"title": "T", "text": "Hallo", "truncated": False}
    bad = client.post("/api/extract", files={"file": ("x.docx", b"kaputt", "application/octet-stream")})
    assert bad.status_code == 400 and bad.json()["error"]


def test_fetch_rejects_bad_address(client):
    assert client.post("/api/fetch", json={"url": "file:///etc/passwd"}).status_code == 400


def test_article_api(client):
    data = client.get("/api/articles/de-cs-os").json()
    assert data["title"] == "Betriebssystem" and data["text"].startswith("#")


# --- словарь и настройки ---------------------------------------------------------------------------

def test_lexicon_crud_changes_reading(clean):
    client = clean
    added = client.post("/api/lexicon", json={"written": "GitLab", "reading": "Gitt 'Läbb"}).json()
    assert added["entries"][0]["written"] == "GitLab"
    say = client.post("/api/prepare", json={"text": "Mit GitLab."}).json()["paragraphs"][0]["sentences"][0]["say"]
    assert say == "Mit Gitt Läbb."
    entry_id = added["entries"][0]["id"]
    assert client.put(f"/api/lexicon/{entry_id}", json={"written": "GitLab", "reading": "Gitt 'Lab"}).status_code == 200
    duplicate = client.post("/api/lexicon", json={"written": "gitlab", "reading": "x"})
    assert duplicate.status_code == 400 and "уже есть" in duplicate.json()["error"]
    assert client.delete(f"/api/lexicon/{entry_id}").json()["entries"] == []
    assert client.delete(f"/api/lexicon/{entry_id}").status_code == 404


def test_settings_are_saved_for_other_programs(client):
    saved = client.post("/api/settings", json={"settings": {"voice": "formant:klara", "rate": 1.4},
                                               "options": {"citations": True}}).json()
    assert saved["settings"]["rate"] == 1.4 and saved["options"]["citations"] is True
    assert json.loads(config.SETTINGS_PATH.read_text(encoding="utf-8"))["settings"]["voice"] == "formant:klara"
    assert client.get("/api/settings").json()["settings"]["voice"] == "formant:klara"


def test_desktop_state(client):
    state = client.get("/api/desktop").json()
    assert {"supported", "clipboard", "hotkeys", "hotkey_read", "events"} <= set(state)
    assert client.post("/api/stop").json() == {"stopped": True}


def test_desktop_text_reaches_reader_page(client):
    """Текст из другой программы уходит открытой странице «Чтец» через поток событий."""
    import asyncio

    from glashatai.web.app import state

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.new_event_loop()
    state.bus.loop, saved_loop = loop, state.bus.loop
    state.bus.listeners.append((queue, "reader"))
    try:
        state.on_desktop_text("Kopierter Text.", "clipboard")
        loop.run_until_complete(asyncio.sleep(0))
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        assert {"type": "read", "text": "Kopierter Text.", "source": "clipboard"} in events
    finally:
        state.bus.listeners.remove((queue, "reader"))
        state.bus.loop = saved_loop
        loop.close()


# --- «Мой говорящий Пафнутий» --------------------------------------------------------------------

def test_talking_page_data(client):
    html = client.get("/talking").text
    game = json.loads(re.search(r'id="game">(.*?)</script>', html, re.S).group(1))
    assert set(game["lines"]) == set(pafnuty.TALK) and set(game["effects"]) == {"squeak", "bass", "robot", "whisper", "echo"}
    assert game["mode"] in {"neural", "formant"}
    assert "talking.js" in html and 'id="room"' in html


def test_talking_say_formant(client):
    response = client.post("/api/talking/say", json={"text": "Hallo!", "emotion": "amused", "mode": "formant"})
    assert response.status_code == 200
    samples, rate = dsp.read_wav(response.content)
    assert rate == 22050 and dsp.estimate_f0(samples, rate) > 200            # высокий голос паука
    assert client.post("/api/talking/say", json={"text": " "}).status_code == 400


def test_talking_echo(client):
    t = np.arange(16000) / 16000
    voice = (0.3 * np.sin(2 * np.pi * 140 * t) * (t > 0.2)).astype(np.float32)
    pcm = (voice * 32767).astype("<i2").tobytes()
    response = client.post("/api/talking/echo?effect=squeak", content=pcm)
    samples, rate = dsp.read_wav(response.content)
    assert rate == 16000 and dsp.estimate_f0(samples, rate) == pytest.approx(140 * 2 ** (7 / 12), rel=0.05)
    assert client.post("/api/talking/echo", content=b"\x00" * 100).status_code == 400


def test_talking_read(client):
    data = client.get("/api/talking/read").json()
    assert 40 <= len(data["text"]) <= 160 and data["title"]
