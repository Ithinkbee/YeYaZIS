"""Обработка звука и голоса Пафнутия."""

from __future__ import annotations

import numpy as np
import pytest

from glashatai import dsp, voicefx
from glashatai.engines import formant

RATE = 16000


def tone(frequency=150.0, seconds=1.5, rate=RATE):
    t = np.arange(int(rate * seconds)) / rate
    # периодический сигнал с гармониками — ближе к голосу, чем чистый синус
    return (0.4 * np.sin(2 * np.pi * frequency * t) + 0.2 * np.sin(4 * np.pi * frequency * t)
            + 0.1 * np.sin(6 * np.pi * frequency * t)).astype(np.float32)


@pytest.fixture(scope="module")
def speech():
    audio, rate = formant.synthesize("Ein Compiler übersetzt das Programm in Maschinensprache.", "karl")
    return dsp.resample(audio, rate, RATE)


def test_wav_roundtrip():
    x = tone()
    samples, rate = dsp.read_wav(dsp.to_wav(x, RATE))
    assert rate == RATE and np.allclose(samples, x, atol=1e-4)


def test_estimate_f0():
    assert dsp.estimate_f0(tone(150), RATE) == pytest.approx(150, rel=0.01)
    assert dsp.estimate_f0(np.zeros(RATE, dtype=np.float32), RATE) is None


@pytest.mark.parametrize("semitones", [-6, -3, 4, 7, 12])
def test_pitch_shift_keeps_length(semitones):
    shifted = dsp.pitch_shift(tone(150), RATE, semitones)
    assert len(shifted) == int(1.5 * RATE)
    assert dsp.estimate_f0(shifted, RATE) == pytest.approx(150 * 2 ** (semitones / 12), rel=0.02)


@pytest.mark.parametrize("tempo", [0.5, 0.8, 1.25, 2.0])
def test_wsola_keeps_pitch(tempo):
    stretched = dsp.stretch(tone(150), RATE, tempo)
    assert len(stretched) / (1.5 * RATE) == pytest.approx(1 / tempo, rel=0.02)
    assert dsp.estimate_f0(stretched, RATE) == pytest.approx(150, rel=0.02)


def test_normalize_and_volume(speech):
    normalized = dsp.normalize(speech, RATE, -18)
    assert dsp.speech_level(normalized, RATE) == pytest.approx(-18, abs=0.5)
    half = dsp.apply_volume(normalized, 50)
    assert dsp.speech_level(half, RATE) - dsp.speech_level(normalized, RATE) == pytest.approx(-6.02, abs=0.3)
    assert not dsp.apply_volume(normalized, 0).any()


def test_soft_limit_keeps_small_signals():
    x = np.array([0.1, -0.5, 0.7, 1.5, -3.0], dtype=np.float32)
    y = dsp.soft_limit(x)
    assert np.allclose(y[:3], x[:3]) and np.abs(y).max() <= 0.97


def test_trim_and_fade():
    x = np.concatenate([np.zeros(RATE), tone(seconds=0.5), np.zeros(RATE)])
    trimmed = dsp.trim(x, RATE, keep_ms=40)
    assert 0.5 * RATE <= len(trimmed) <= 0.5 * RATE + 0.1 * RATE
    faded = dsp.fade(tone(seconds=0.2), RATE, 10)
    assert faded[0] == 0 and abs(faded[-1]) < 1e-6


def test_resample_and_concatenate():
    assert len(dsp.resample(tone(seconds=1.0), RATE, 22050)) == 22050
    assert len(dsp.concatenate([tone(seconds=0.5), None, dsp.silence(500, RATE)])) == RATE


def test_envelope_follows_loudness():
    x = np.concatenate([np.zeros(RATE // 2, dtype=np.float32), tone(seconds=0.5)])
    envelope = dsp.envelope(x, RATE)
    assert max(envelope[:20]) == 0 and min(envelope[-20:]) > 0.5


def test_lpc_finds_resonance():
    # шум через резонатор 1000 Гц: LPC находит полюс рядом
    from scipy.signal import lfilter

    r, theta = 0.97, 2 * np.pi * 1000 / RATE
    x = lfilter([1], [1, -2 * r * np.cos(theta), r * r], np.random.default_rng(1).standard_normal(4000))
    a, _ = dsp.lpc(x, 2)
    frequency = abs(np.angle(np.roots(a)[0])) * RATE / (2 * np.pi)
    assert frequency == pytest.approx(1000, rel=0.03)


@pytest.mark.parametrize("effect, shift", [("squeak", 7), ("bass", -5), ("echo", 3)])
def test_effects_shift_pitch(speech, effect, shift):
    processed = voicefx.apply(speech, RATE, effect)
    before, after = dsp.estimate_f0(speech, RATE), dsp.estimate_f0(processed, RATE)
    assert 12 * np.log2(after / before) == pytest.approx(shift, abs=1.0)


def test_robot_is_monotone_and_whisper_is_unvoiced(speech):
    robot = voicefx.apply(speech, RATE, "robot")
    assert dsp.estimate_f0(robot, RATE) == pytest.approx(120, rel=0.05)
    whisper = voicefx.apply(speech, RATE, "whisper")
    assert np.isfinite(whisper).all() and -22 < dsp.speech_level(whisper, RATE) < -14


def test_effect_on_silence_is_empty():
    assert len(voicefx.apply(np.zeros(RATE, dtype=np.float32), RATE, "squeak")) == 0
