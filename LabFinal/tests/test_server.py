"""Сервер: страница, сценарии, музыка, слова, метки и то, чего он не должен отдавать и принимать."""

from __future__ import annotations

import json

import pytest

from poklon import config, show

from .conftest import ROOT

WORDS = (ROOT / "data" / "words.json").read_text(encoding="utf-8")


def put_track(folders, name: str = "песня.mp3", size: int = 5000) -> bytes:
    music, _ = folders
    raw = bytes(range(256)) * (size // 256 + 1)
    (music / name).write_bytes(raw[:size])
    return raw[:size]


# --- страница и сценарии ----------------------------------------------------------

def test_page(client):
    status, headers, raw = client.get("/")
    assert status == 200
    assert headers["Content-Type"].startswith("text/html")
    page = raw.decode("utf-8")
    for script in ("score.js", "spider.js", "troupe.js", "stage.js", "show.js"):
        assert f"/static/{script}" in page


@pytest.mark.parametrize("name, kind", [("score.js", "text/javascript"), ("style.css", "text/css")])
def test_static(client, name, kind):
    status, headers, raw = client.get(f"/static/{name}")
    assert status == 200
    assert headers["Content-Type"].startswith(kind)
    assert int(headers["Content-Length"]) == len(raw) > 100
    assert headers["Cache-Control"] == "no-cache"


@pytest.mark.parametrize("path", [
    "/static/../server.py",
    "/static/%2e%2e/server.py",
    "/static/..%5cserver.py",
    "/static/%2e%2e/%2e%2e/run.py",
    "/static/",
    "/static/%D0%BD%D0%B5%D1%82.js",
    "/poklon/server.py",
    "/track/../data/words.json",
])
def test_nothing_outside_static(client, path):
    status, _, raw = client.get(path)
    assert status == 404
    assert b"import" not in raw


def test_head_has_no_body(client):
    status, headers, raw = client.request("HEAD", "/static/score.js")
    assert status == 200 and raw == b"" and int(headers["Content-Length"]) > 100


# --- слова ---------------------------------------------------------------------------

def test_shipped_words_are_complete(folders):
    """Слова, которые лежат в data/words.json, читаются целиком — без запасных."""
    _, data = folders
    (data / "words.json").write_text(WORDS, encoding="utf-8")
    words, problem = show.load_words()
    assert problem == ""
    assert words == {**show.FALLBACK_WORDS, **json.loads(WORDS)}
    assert len(words["floors"]) == 6 and len(words["lines"]) >= 2 and words["signature"]
    assert all(set(floor) == {"number", "name", "about", "props"} for floor in words["floors"])
    assert all(isinstance(prop, str) and prop for floor in words["floors"] for prop in floor["props"])
    assert all(len(row) == 2 for row in words["credits"])


def test_words_missing(client):
    status, info = client.json("GET", "/api/show")
    assert status == 200
    assert info["words"]["thanks"] == "Спасибо!"
    assert "words.json" in info["problem"]


@pytest.mark.parametrize("text", ["{не json", "[1, 2, 3]", ""])
def test_words_broken(folders, text):
    _, data = folders
    (data / "words.json").write_text(text, encoding="utf-8")
    words, problem = show.load_words()
    assert words == show.FALLBACK_WORDS
    assert problem


def test_words_wrong_types_fall_back(folders):
    """Строка вместо списка не должна сломать страницу: берётся запасное значение."""
    _, data = folders
    (data / "words.json").write_text(json.dumps({"lines": "одна строка", "to": "Имя Отчество!", "floors": {}}), encoding="utf-8")
    words, problem = show.load_words()
    assert problem == ""
    assert words["to"] == "Имя Отчество!"
    assert words["lines"] == show.FALLBACK_WORDS["lines"]
    assert words["floors"] == []


# --- музыка ---------------------------------------------------------------------------

def test_no_track(client):
    _, info = client.json("GET", "/api/show")
    assert info["track"] is None and info["cues"] is None


def test_track_is_found_and_served(client, folders):
    raw = put_track(folders)
    _, info = client.json("GET", "/api/show")
    assert info["track"]["name"] == "песня.mp3" and info["track"]["size"] == len(raw)
    from urllib.parse import quote

    status, headers, body = client.get(quote(info["track"]["url"]))
    assert status == 200 and body == raw
    assert headers["Content-Type"] == "audio/mpeg" and headers["Accept-Ranges"] == "bytes"


def test_first_track_by_name_and_only_audio(folders):
    music, _ = folders
    (music / "заметки.txt").write_text("не музыка", encoding="utf-8")
    assert show.find_track() is None
    put_track(folders, "b.mp3")
    put_track(folders, "A.ogg")
    assert show.find_track().name == "A.ogg"


def test_track_named_at_launch(folders, monkeypatch):
    music, _ = folders
    put_track(folders, "a.mp3")
    put_track(folders, "выбранная.wav")
    monkeypatch.setattr(config, "MUSIC", music / "выбранная.wav")
    assert show.find_track().name == "выбранная.wav"
    assert config.music_dir() == music


@pytest.mark.parametrize("span, first, last", [("bytes=100-199", 100, 199), ("bytes=4900-", 4900, 4999),
                                                ("bytes=-50", 4950, 4999), ("bytes=10-999999", 10, 4999)])
def test_track_range(client, folders, span, first, last):
    raw = put_track(folders, "song.mp3")
    status, headers, body = client.get("/track/song.mp3", {"Range": span})
    assert status == 206
    assert body == raw[first:last + 1]
    assert headers["Content-Range"] == f"bytes {first}-{last}/5000"


def test_track_range_out_of_file(client, folders):
    put_track(folders, "song.mp3")
    status, headers, _ = client.get("/track/song.mp3", {"Range": "bytes=9000-9100"})
    assert status == 416 and headers["Content-Range"] == "bytes */5000"


def test_only_current_track_is_served(client, folders):
    music, _ = folders
    put_track(folders, "a.mp3")
    (music / "секрет.txt").write_text("тайна", encoding="utf-8")
    assert client.get("/track/b.mp3")[0] == 404
    assert client.get("/track/%D1%81%D0%B5%D0%BA%D1%80%D0%B5%D1%82.txt")[0] == 404


# --- метки ---------------------------------------------------------------------------

GOOD = {"track": "song.mp3", "duration": 154.2, "choir": 70.5, "leave": 118}


def test_cues_saved_and_returned(client, folders):
    _, data = folders
    put_track(folders, "song.mp3")
    status, answer = client.json("POST", "/api/cues", GOOD)
    assert status == 200 and answer["ok"]
    assert json.loads((data / "cues.json").read_text(encoding="utf-8")) == {**GOOD, "leave": 118.0}
    _, info = client.json("GET", "/api/show")
    assert info["cues"]["choir"] == 70.5


def test_cues_belong_to_one_track(client, folders):
    put_track(folders, "другая.mp3")
    client.json("POST", "/api/cues", GOOD)
    _, info = client.json("GET", "/api/show")
    assert info["cues"] is None


def test_cues_forgotten(client, folders):
    _, data = folders
    client.json("POST", "/api/cues", GOOD)
    status, answer = client.json("DELETE", "/api/cues")
    assert status == 200 and answer["ok"] and not (data / "cues.json").exists()
    assert client.json("DELETE", "/api/cues")[0] == 200


@pytest.mark.parametrize("bad", [
    {**GOOD, "choir": 120},                 # хор кончился раньше, чем начался
    {**GOOD, "leave": 200},                 # позже конца записи
    {**GOOD, "choir": "70"},
    {**GOOD, "choir": True},
    {**GOOD, "duration": 99999},
    {**GOOD, "track": ""},
    {"choir": 1, "leave": 2},
    [70, 118],
    None,
])
def test_cues_rejected(client, folders, bad):
    _, data = folders
    status, answer = client.json("POST", "/api/cues", bad)
    assert status == 400 and not answer["ok"] and answer["error"]
    assert not (data / "cues.json").exists()


def test_cues_not_json(client):
    status, _, _ = client.request("POST", "/api/cues", b"\xff\xfe{", {"Content-Type": "application/json"})
    assert status == 400


def test_broken_cues_file_is_ignored(folders):
    _, data = folders
    (data / "cues.json").write_text('{"track": "a.mp3", "duration": 10, "choir": 9, "leave": 3}', encoding="utf-8")
    assert show.load_cues() is None
    (data / "cues.json").write_text("мусор", encoding="utf-8")
    assert show.load_cues() is None


# --- запись, перетащенная на страницу ---------------------------------------------------

def test_dropped_track_is_saved(client, folders):
    music, _ = folders
    status, answer = client.json("POST", "/api/track?name=%D0%BF%D0%B5%D1%81%D0%BD%D1%8F.mp3")
    assert status == 400                    # пустая запись не сохраняется
    status, _, raw = client.request("POST", "/api/track?name=%D0%BF%D0%B5%D1%81%D0%BD%D1%8F.mp3", b"ID3" + b"\0" * 400)
    answer = json.loads(raw)
    assert status == 200 and answer == {"ok": True, "name": "песня.mp3", "playing": "песня.mp3"}
    assert (music / "песня.mp3").read_bytes().startswith(b"ID3")


@pytest.mark.parametrize("name, saved", [
    ("..%2F..%2Fevil.mp3", "evil.mp3"),
    ("..%5C..%5Cevil.mp3", "evil.mp3"),
    ("C%3A%5CWindows%5Cx.wav", "x.wav"),
    ("a%3Ab%3F.ogg", "a_b_.ogg"),
    ("con.mp3", "_con.mp3"),
    ("%D0%BF%D0%B5%D1%81%D0%BD%D1%8F%20%E2%84%96%201.FLAC", "песня № 1.FLAC"),
])
def test_dropped_track_stays_in_music_folder(client, folders, name, saved):
    music, _ = folders
    status, _, raw = client.request("POST", f"/api/track?name={name}", b"x" * 64)
    assert status == 200 and json.loads(raw)["name"] == saved
    assert [path.name for path in music.iterdir()] == [saved]
    assert not (music.parent / saved).exists()


@pytest.mark.parametrize("name", ["virus.exe", "page.html", "run.py", "", ".mp3", "..", "song.mp3.exe"])
def test_dropped_file_must_be_audio(client, folders, name):
    music, _ = folders
    status, _, _ = client.request("POST", f"/api/track?name={name}", b"x" * 64)
    assert status == 415
    assert list(music.iterdir()) == []


def test_dropped_track_size_limit(client, folders, monkeypatch):
    music, _ = folders
    monkeypatch.setattr(config, "MAX_TRACK_BYTES", 1000)
    status, _, _ = client.request("POST", "/api/track?name=big.mp3", b"x" * 5000)
    assert status == 413
    assert list(music.iterdir()) == []


def test_refusals_answer_instead_of_dropping_the_connection(client, folders):
    """Отказ приходит ответом, а не обрывом: тело запроса сервер дочитывает."""
    body = b"x" * 300_000
    for _ in range(5):
        assert client.request("POST", "/api/track?name=page.html", body)[0] == 415
        assert client.request("POST", "/api/unknown", body)[0] == 404
        assert client.request("POST", "/api/cues", body)[0] == 413
        assert client.request("POST", "/api/track?name=a.mp3", body, {"Origin": "http://evil.example"})[0] == 403


def test_huge_refused_body_is_not_read(client, folders, monkeypatch):
    """Очень большое тело отвергнутого запроса сервер не читает — закрывает соединение."""
    from poklon.server import Handler

    monkeypatch.setattr(Handler, "SKIP_LIMIT", 1000)
    try:
        status, headers, _ = client.request("POST", "/api/track?name=virus.exe", b"x" * 200_000)
    except (ConnectionError, OSError):
        return                              # соединение закрыто раньше, чем клиент дописал тело
    assert status == 415 and headers.get("Connection") == "close"


def test_other_tracks_reported(client, folders):
    put_track(folders, "a.mp3")
    _, _, raw = client.request("POST", "/api/track?name=z.mp3", b"x" * 64)
    assert json.loads(raw) == {"ok": True, "name": "z.mp3", "playing": "a.mp3"}


# --- чужие страницы ------------------------------------------------------------------------

@pytest.mark.parametrize("method, path, body", [
    ("POST", "/api/cues", json.dumps(GOOD).encode()),
    ("POST", "/api/track?name=evil.mp3", b"x" * 64),
    ("DELETE", "/api/cues", None),
])
def test_other_sites_cannot_write(client, folders, method, path, body):
    """Страница с другого адреса не может писать на диск через открытый ролик."""
    music, data = folders
    (data / "cues.json").write_text(json.dumps(GOOD), encoding="utf-8")
    before = (data / "cues.json").read_text(encoding="utf-8")
    status, _, _ = client.request(method, path, body, {"Origin": "http://evil.example"})
    assert status == 403
    assert list(music.iterdir()) == []
    assert (data / "cues.json").read_text(encoding="utf-8") == before


def test_own_page_can_write(client, folders):
    status, answer = client.json("POST", "/api/cues", GOOD, {"Origin": f"http://127.0.0.1:{client.port}",
                                                             "Host": f"127.0.0.1:{client.port}"})
    assert status == 200 and answer["ok"]


def test_unknown_routes(client):
    assert client.get("/api/unknown")[0] == 404
    assert client.request("POST", "/api/unknown", b"{}")[0] == 404
    assert client.request("DELETE", "/api/show")[0] == 404
