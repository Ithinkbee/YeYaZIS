"""Уровень сигнала, обнаружение речи, шум и файлы.

Детектор проверяется на сигналах, собранных вручную: шум комнаты, «речь»
(тон заданной громкости), щелчок, непрерывный гул. Так видно, что именно он
считает фразой.
"""

from __future__ import annotations

import numpy as np
import pytest

from sluhach import audio, config

RATE = config.SAMPLE_RATE


def tone(seconds: float, db: float, frequency: float = 220.0) -> np.ndarray:
    """Тон заданного среднеквадратичного уровня, дБ относительно полной шкалы."""
    t = np.arange(int(RATE * seconds)) / RATE
    amplitude = 10 ** (db / 20) * np.sqrt(2) * audio.FULL_SCALE
    return np.clip(amplitude * np.sin(2 * np.pi * frequency * t), -32768, 32767).astype(np.int16)


def hiss(seconds: float, db: float, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.clip(rng.normal(0, 10 ** (db / 20) * audio.FULL_SCALE, int(RATE * seconds)), -32768, 32767).astype(np.int16)


def run(samples: np.ndarray, settings: audio.VadSettings | None = None):
    vad = audio.Vad(settings)
    events = []
    for index, frame in enumerate(audio.split_frames(samples, vad.settings.frame_samples)):
        for event in vad.push(frame):
            events.append((index * vad.settings.frame_ms, event))
    return vad, events


def kinds(events) -> list[str]:
    return [event.kind for _, event in events if event.kind != "speech"]


# --- уровень -----------------------------------------------------------------------

def test_level_of_known_signals():
    assert audio.level_db(np.zeros(320, dtype=np.int16)) == audio.SILENCE_DB
    assert audio.level_db(np.array([], dtype=np.int16)) == audio.SILENCE_DB
    assert audio.level_db(tone(0.5, -20)) == pytest.approx(-20, abs=0.1)
    assert audio.level_db(tone(0.5, -45)) == pytest.approx(-45, abs=0.2)
    full = (np.sin(2 * np.pi * 200 * np.arange(RATE) / RATE) * 32767).astype(np.int16)
    assert audio.level_db(full) == pytest.approx(-3.01, abs=0.05)             # синус во всю шкалу
    assert audio.level_db(hiss(1, -50)) == pytest.approx(-50, abs=0.5)


def test_to_samples_ignores_a_torn_byte():
    assert list(audio.to_samples(b"\x01\x00\xff\xff\x07")) == [1, -1]


# --- детектор речи --------------------------------------------------------------------

def test_silence_is_not_speech():
    vad, events = run(hiss(3, -60))
    assert events == [] and not vad.speaking
    assert vad.noise_db == pytest.approx(-60, abs=3)                          # шум комнаты оценён
    assert vad.start_threshold == pytest.approx(-60 + config.VAD_START_MARGIN_DB, abs=3)


def test_phrase_is_found_with_its_boundaries():
    signal = np.concatenate([hiss(1.0, -60), tone(1.2, -25), hiss(1.5, -60, seed=2)])
    vad, events = run(signal)
    assert kinds(events) == ["start", "end"]
    started, first = events[0]
    ended, last = events[-1]
    assert 1000 <= started <= 1100                                            # начало замечено за три-пять кадров
    assert last.duration_ms == pytest.approx(1200 + config.VAD_PREROLL_MS, abs=80)
    assert ended == pytest.approx(1000 + 1200 + config.VAD_END_SILENCE_MS, abs=60)   # конец — после паузы
    assert last.level_db == pytest.approx(-25, abs=1.5) and not last.forced
    assert not vad.speaking


def test_preroll_keeps_sound_before_the_start():
    signal = np.concatenate([hiss(1.0, -60), tone(1.0, -25), hiss(1.2, -60)])
    _, events = run(signal)
    before = events[0][1].frames
    assert len(before) == config.VAD_PREROLL_MS // config.FRAME_MS
    assert audio.level_db(before[0]) < -50 < audio.level_db(before[-1])       # сначала тишина, в конце уже речь


def test_all_speech_frames_are_passed_on():
    signal = np.concatenate([hiss(1.0, -60), tone(1.0, -25), hiss(1.2, -60)])
    _, events = run(signal)
    passed = len(events[0][1].frames) + sum(1 for _, event in events if event.kind == "speech")
    heard = passed * config.FRAME_MS
    assert heard == pytest.approx(config.VAD_PREROLL_MS + 1000 + config.VAD_END_SILENCE_MS, abs=80)


def test_pause_inside_a_phrase_does_not_end_it():
    pause = hiss(config.VAD_END_SILENCE_MS / 1000 - 0.25, -60, seed=3)
    signal = np.concatenate([hiss(1.0, -60), tone(0.6, -25), pause, tone(0.6, -25), hiss(1.5, -60, seed=4)])
    assert kinds(run(signal)[1]) == ["start", "end"]


def test_long_pause_splits_phrases():
    pause = hiss(config.VAD_END_SILENCE_MS / 1000 + 0.3, -60, seed=3)
    signal = np.concatenate([hiss(1.0, -60), tone(0.6, -25), pause, tone(0.6, -25), hiss(1.5, -60, seed=4)])
    assert kinds(run(signal)[1]) == ["start", "end", "start", "end"]


def test_click_is_dropped():
    signal = np.concatenate([hiss(1.0, -60), tone(0.08, -15), hiss(1.5, -60, seed=2)])
    _, events = run(signal)
    assert kinds(events) == ["start", "drop"]
    assert events[-1][1].duration_ms < config.VAD_PREROLL_MS + 200


def test_single_loud_frame_does_not_open_a_phrase():
    signal = np.concatenate([hiss(1.0, -60), tone(0.02, -10), hiss(1.0, -60, seed=2)])
    assert run(signal)[1] == []


def test_threshold_follows_the_room():
    """В шумной комнате порог выше: тот же голос, что слышен в тишине, там теряется."""
    quiet_voice = tone(1.0, -42)
    assert kinds(run(np.concatenate([hiss(1.0, -65), quiet_voice, hiss(1.2, -65)]))[1]) == ["start", "end"]
    vad, events = run(np.concatenate([hiss(1.0, -40), quiet_voice, hiss(1.2, -40, seed=2)]))
    assert events == [] and vad.start_threshold > -42


def test_nothing_quieter_than_the_floor_is_speech():
    """В полной тишине шёпот на −58 дБ фразой не считается: порог не опускается ниже −50."""
    signal = np.concatenate([np.zeros(RATE, dtype=np.int16), tone(1.0, -58), np.zeros(RATE, dtype=np.int16)])
    vad, events = run(signal)
    assert events == [] and vad.start_threshold == config.VAD_MIN_LEVEL_DB


def test_noise_estimate_drops_fast_and_rises_slowly():
    vad, _ = run(np.concatenate([hiss(1.0, -40), hiss(0.5, -65, seed=2)]))
    assert vad.noise_db < -60                                                 # стихло — оценка упала за полсекунды
    vad, _ = run(np.concatenate([hiss(1.0, -65), hiss(0.5, -60, seed=2)]))
    assert -65.5 < vad.noise_db < -60                                         # шум подрос — оценка ползёт следом


def test_endless_sound_is_cut_and_becomes_the_new_floor():
    settings = audio.VadSettings(max_utterance_ms=3000)
    signal = np.concatenate([hiss(1.0, -60), tone(8.0, -30)])
    vad, events = run(signal, settings)
    assert kinds(events)[:2] == ["start", "end"] and events[[e.kind for _, e in events].index("end")][1].forced
    assert kinds(events).count("start") == 1                                  # тот же гул фразу больше не открывает
    assert vad.start_threshold > -30


def test_raise_floor():
    vad, _ = run(hiss(1.0, -60))
    vad.raise_floor(-35)
    assert vad.start_threshold > -35 and vad.noise_db <= audio.Vad.NOISE_RANGE[1]
    vad.raise_floor(-80)                                                      # вниз порог так не опускается
    assert vad.start_threshold > -35


def test_reset_forgets_the_phrase_but_keeps_the_noise():
    vad = audio.Vad()
    frames = audio.split_frames(np.concatenate([hiss(1.0, -60), tone(0.5, -25)]), vad.settings.frame_samples)
    for frame in frames:
        vad.push(frame)
    assert vad.speaking
    noise = vad.noise_db
    vad.reset()
    assert not vad.speaking and vad.noise_db == noise
    assert vad.push(audio.split_frames(hiss(0.1, -60), vad.settings.frame_samples)[0]) == []


def test_warmup_ignores_sound_right_after_start():
    """Первые 300 мс идут на оценку шума: шумный микрофон не открывает фразу при включении."""
    vad, events = run(hiss(0.25, -30))
    assert events == []


# --- файлы и шум -----------------------------------------------------------------------

def test_wav_roundtrip(tmp_path):
    samples = tone(0.5, -20)
    audio.write_wav(tmp_path / "tone.wav", samples)
    assert np.array_equal(audio.read_wav(tmp_path / "tone.wav"), samples)


def test_read_wav_resamples_and_mixes_channels(tmp_path):
    import wave

    t = np.arange(48000) / 48000
    stereo = np.stack([np.sin(2 * np.pi * 200 * t), np.sin(2 * np.pi * 200 * t)], axis=1)
    with wave.open(str(tmp_path / "stereo.wav"), "wb") as target:
        target.setnchannels(2)
        target.setsampwidth(2)
        target.setframerate(48000)
        target.writeframes((stereo * 10000).astype("<i2").tobytes())
    samples = audio.read_wav(tmp_path / "stereo.wav")
    assert len(samples) == RATE and audio.level_db(samples) == pytest.approx(-13.3, abs=0.5)


def test_read_wav_refuses_other_sample_widths(tmp_path):
    import wave

    with wave.open(str(tmp_path / "byte.wav"), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(1)
        target.setframerate(8000)
        target.writeframes(b"\x80" * 800)
    with pytest.raises(ValueError, match="16-разрядный"):
        audio.read_wav(tmp_path / "byte.wav")


def test_pad():
    padded = audio.pad(tone(0.5, -20), 500, 1000)
    assert len(padded) == RATE * 2 and not padded[:RATE // 2].any() and not padded[-RATE:].any()


@pytest.mark.parametrize("snr", [20.0, 10.0, 5.0])
def test_add_noise_gives_the_requested_ratio(snr):
    signal = audio.pad(tone(1.0, -20), 500, 500)
    noisy = audio.add_noise(signal, snr, np.random.default_rng(7))
    noise = noisy[:RATE // 2].astype(np.float64)              # там, где была тишина, остался один шум
    assert audio.level_db(noise) == pytest.approx(-20 - snr, abs=0.6)   # мощность сигнала — по звучащей части
    assert len(noisy) == len(signal) and noisy.dtype == np.int16


def test_add_noise_edge_cases():
    silence = np.zeros(RATE, dtype=np.int16)
    assert np.array_equal(audio.add_noise(silence, 10, np.random.default_rng(1)), silence)
    assert len(audio.add_noise(np.array([], dtype=np.int16), 10, np.random.default_rng(1))) == 0
    loud = audio.add_noise(tone(0.5, -1), 0, np.random.default_rng(1))
    assert loud.max() <= 32767 and loud.min() >= -32768       # без переполнения


def test_resample():
    assert len(audio.resample(tone(1.0, -20), RATE, 8000)) == 8000
    assert len(audio.resample(tone(1.0, -20), RATE, RATE)) == RATE
    assert len(audio.resample(np.array([], dtype=np.int16), 48000, RATE)) == 0
