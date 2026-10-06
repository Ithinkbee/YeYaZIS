"""Распознавание записей: Vosk, слушатель (детектор речи + поток), реакция.

Записи — фразы, озвученные синтезатором (tests/audio). Тесты пропускаются,
если не установлен пакет vosk или не скачаны модели.
"""

from __future__ import annotations

import numpy as np
import pytest

from sluhach import audio, config, evaluation
from sluhach.listener import MARGIN_RANGE, PAUSE_RANGE, Listener
from sluhach.recognizer import Recognition, RecognizerError, VoskEngine
from sluhach.text import word_errors


def microphone(path, snr: float = 50.0) -> bytes:
    """Запись как с микрофона: тишина до и после, слабый шум вместо цифрового нуля."""
    samples = audio.pad(audio.read_wav(path), 600, 1200)
    return audio.add_noise(samples, snr, np.random.default_rng(11)).astype("<i2").tobytes()


def listen(listener: Listener, pcm: bytes, chunk: int = 3200) -> list[dict]:
    events = []
    for offset in range(0, len(pcm), chunk):
        events.extend(listener.feed(pcm[offset:offset + chunk]))
    return events


def kinds(events: list[dict]) -> list[str]:
    return [event["type"] for event in events if event["type"] != "level"]


def final_of(events: list[dict]) -> dict:
    return next(event for event in events if event["type"] == "final")


def almost(reference: str, heard: str) -> bool:
    """Почти дословно: не больше одной ошибки на три слова (у короткой фразы — одна ошибка)."""
    errors = word_errors(reference, heard)
    return errors.errors <= max(1, 0.34 * errors.reference)


# --- распознаватель -----------------------------------------------------------------

def test_engine_reports_models(engine):
    status = engine.status()
    assert status["package"] is True and set(status["languages"]) == set(config.LANGUAGE_CODES)
    for language in config.LANGUAGE_CODES:
        engine.load(language)
        state = engine.status()["languages"][language]
        assert state["state"] == "ready" and state["available"] and state["model"] == config.VOSK_MODELS[language]


def test_missing_model_is_reported_not_raised_at_start(tmp_path):
    empty = VoskEngine(models_dir=tmp_path)
    if not empty.package():
        pytest.skip("пакет vosk не установлен")
    assert empty.state("de") == "missing" and not empty.available("de") and not empty.installed("de")
    assert empty.status()["languages"]["de"]["text"] == "модель не скачана"
    with pytest.raises(RecognizerError, match="get_models"):
        empty.load("de")
    with pytest.raises(RecognizerError):
        empty.stream("ru")


def test_recordings_are_recognised(engine, recordings):
    """Каждая запись распознаётся почти дословно («ließ vor» вместо «lies vor» — тоже почти)."""
    for item in recordings:
        result = engine.recognize(audio.read_wav(item["path"]), item["language"])
        assert isinstance(result, Recognition) and result.text
        assert almost(item["text"], result.text), f"{item['file']}: «{result.text}»"
        assert 0.5 <= result.confidence <= 1.0 and result.ms > 0
        assert len(result.words) == len(result.text.split())


def test_recognised_phrase_gives_the_right_reaction(engine, recordings, collection):
    """Главное: ошибка в букве не мешает выполнить ту же операцию, что и по эталонному тексту."""
    reactor = evaluation.default_reactor(collection)
    for item in recordings:
        heard = engine.recognize(audio.read_wav(item["path"]), item["language"]).text
        expected = evaluation.reaction_signature(reactor, collection, item["text"], item["language"])
        got = evaluation.reaction_signature(reactor, collection, heard, item["language"])
        assert got == expected, f"{item['file']}: «{heard}»"
        assert expected[0] in {"operation", "egg"}                  # записи тестов — команды и пасхалки


def test_recognition_is_faster_than_speech(engine, recordings):
    item = recordings[0]
    samples = audio.read_wav(item["path"])
    engine.recognize(samples, item["language"])                     # первый вызов прогревает модель
    result = engine.recognize(samples, item["language"])
    assert result.ms < 1000 * len(samples) / config.SAMPLE_RATE


def test_wrong_language_model_does_not_understand(engine, recordings):
    item = next(r for r in recordings if r["language"] == "ru")
    heard = engine.recognize(audio.read_wav(item["path"]), "de").text
    assert word_errors(item["text"], heard).rate > 0.6              # выбор языка — это выбор модели


# --- слушатель -------------------------------------------------------------------------

def test_listener_turns_sound_into_events(engine, recordings):
    item = next(r for r in recordings if r["file"] == "de-open.wav")
    events = listen(Listener(engine, "de"), microphone(item["path"]))
    order = kinds(events)
    assert order[0] == "speech_start" and order[-2:] == ["speech_end", "final"]
    assert set(order[1:-2]) == {"partial"} and len(order) >= 5

    partials = [event["text"] for event in events if event["type"] == "partial"]
    assert all(len(b) >= len(a) for a, b in zip(partials, partials[1:]))          # текст растёт по мере речи
    final = final_of(events)
    assert almost(item["text"], final["text"])
    assert final["language"] == "de" and final["confidence"] > 0.5
    assert 1500 < final["duration_ms"] < 3500 and 0 < final["recognition_ms"] < final["duration_ms"]
    assert not [event for event in events if event["type"] == "error"]


def test_listener_reports_levels_and_threshold(engine, recordings):
    events = listen(Listener(engine, "ru"), microphone(recordings[-1]["path"]))
    levels = [event for event in events if event["type"] == "level"]
    assert len(levels) >= 10                                                       # пять раз в секунду
    assert all(event["threshold"] >= config.VAD_MIN_LEVEL_DB for event in levels)
    assert any(event["speaking"] for event in levels) and not levels[0]["speaking"]
    assert max(event["db"] for event in levels) > -35


def test_listener_does_not_depend_on_chunk_size(engine, recordings):
    item = next(r for r in recordings if r["file"] == "ru-egg.wav")
    pcm = microphone(item["path"])
    texts = set()
    for chunk in (320, 1000, 3200, 16000, len(pcm)):                               # в том числе куски не по кадрам
        events = listen(Listener(engine, "ru"), pcm, chunk)
        texts.add(next(event["text"] for event in events if event["type"] == "final"))
    assert texts == {"сколько стоит слон"}


def test_two_phrases_in_one_stream(engine, recordings):
    first = next(r for r in recordings if r["file"] == "ru-next.wav")
    second = next(r for r in recordings if r["file"] == "ru-egg.wav")
    events = listen(Listener(engine, "ru"), microphone(first["path"]) + microphone(second["path"]))
    finals = [event["text"] for event in events if event["type"] == "final"]
    assert finals == ["читай дальше", "сколько стоит слон"]
    assert kinds(events).count("speech_start") == 2


def test_silence_and_hum_give_no_phrases(engine):
    rng = np.random.default_rng(3)
    quiet = rng.normal(0, 30, config.SAMPLE_RATE * 3).astype("<i2").tobytes()
    assert kinds(listen(Listener(engine, "de"), quiet)) == []


def test_noise_burst_raises_the_threshold(engine):
    """Шум без слов открывает фразу один раз: распознаватель слов не находит — порог растёт."""
    rng = np.random.default_rng(4)
    calm = rng.normal(0, 30, config.SAMPLE_RATE).astype(np.int16)
    burst = rng.normal(0, 2500, config.SAMPLE_RATE).astype(np.int16)
    listener = Listener(engine, "ru")
    events = listen(listener, np.concatenate([calm, burst, calm, calm]).astype("<i2").tobytes())
    finals = [event for event in events if event["type"] == "final"]
    assert len(finals) == 1 and finals[0]["text"] == ""
    before = [event["threshold"] for event in events if event["type"] == "speech_start"][0]
    assert listener.vad.start_threshold > before or listener.vad.noise_db > -70


def test_reset_drops_the_phrase(engine, recordings):
    """Система заговорила сама: начатая фраза бросается."""
    item = next(r for r in recordings if r["file"] == "de-open.wav")
    pcm = microphone(item["path"])
    listener = Listener(engine, "de")
    half = len(pcm) // 2 - (len(pcm) // 2) % 2
    first = listen(listener, pcm[:half])
    assert "speech_start" in kinds(first) and "final" not in kinds(first)
    listener.reset()
    rest = listen(listener, microphone(next(r for r in recordings if r["file"] == "de-read.wav")["path"]))
    finals = [event["text"] for event in rest if event["type"] == "final"]
    assert len(finals) == 1 and word_errors("lies vor", finals[0]).errors <= 1


def test_language_change(engine, recordings):
    listener = Listener(engine, "de")
    listener.set_language("ru")
    assert listener.language == "ru"
    listener.set_language("fr")                                                    # неизвестный язык не принимается
    assert listener.language == "ru"
    events = listen(listener, microphone(next(r for r in recordings if r["file"] == "ru-egg.wav")["path"]))
    assert final_of(events)["text"] == "сколько стоит слон" and final_of(events)["language"] == "ru"


def test_configure_is_clamped(engine):
    listener = Listener(engine, "de")
    listener.configure(margin_db=100, pause_ms=10)
    assert listener.settings.start_margin_db == MARGIN_RANGE[1] and listener.settings.end_silence_ms == PAUSE_RANGE[0]
    listener.configure(margin_db=-5, pause_ms=99999)
    assert listener.settings.start_margin_db == MARGIN_RANGE[0] and listener.settings.end_silence_ms == PAUSE_RANGE[1]
    assert listener.settings.end_margin_db >= 3
    listener.configure(margin_db=12)
    assert listener.settings.start_margin_db == 12 and listener.settings.end_silence_ms == PAUSE_RANGE[1]
    assert listener.vad.settings is listener.settings                              # детектор видит новые настройки


def test_longer_pause_setting_delays_the_end(engine, recordings):
    item = next(r for r in recordings if r["file"] == "de-read.wav")
    spoken = audio.read_wav(item["path"])
    spoken = spoken[:np.nonzero(np.abs(spoken) > 500)[0][-1] + 1]                  # без тишины в конце записи
    samples = audio.add_noise(audio.pad(spoken, 600, 900), 50, np.random.default_rng(2))
    quick = Listener(engine, "de")
    quick.configure(pause_ms=400)
    slow = Listener(engine, "de")
    slow.configure(pause_ms=1500)
    pcm = samples.astype("<i2").tobytes()
    assert "final" in kinds(listen(quick, pcm))
    assert "final" not in kinds(listen(slow, pcm))                                 # 0,9 с тишины для него ещё не конец


def test_listener_without_models_reports_an_error(tmp_path, recordings):
    empty = VoskEngine(models_dir=tmp_path)
    events = listen(Listener(empty, "de"), microphone(recordings[0]["path"]))
    errors = [event for event in events if event["type"] == "error"]
    assert errors and ("get_models" in errors[0]["message"] or "vosk" in errors[0]["message"])
    assert "final" not in kinds(events)
