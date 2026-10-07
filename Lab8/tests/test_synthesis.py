"""Просодия и собственный формантный синтезатор."""

from __future__ import annotations

import numpy as np
import pytest

from glashatai import dsp
from glashatai.engines import formant
from glashatai.phonetics.prosody import Phone, Score, score


def vowels(sc):
    return [p for p in sc.phones if p.is_vowel]


def test_score_has_pauses_and_phones():
    sc = score("Das ist ein Haus, sagt er.")
    symbols = [p.symbol for p in sc.phones]
    assert symbols[0] == "_" and symbols[-1] == "_"
    assert any(p.symbol == "_" and p.duration >= 150 for p in sc.phones)       # пауза на запятой
    assert "h" in symbols and "aʊ" in symbols


def test_rate_scales_durations():
    slow, fast = score("Ein Compiler übersetzt Programme.", rate=0.5), score("Ein Compiler übersetzt Programme.", rate=2)
    assert slow.duration == pytest.approx(4 * fast.duration, rel=1e-6)


def test_stressed_vowels_are_longer_and_final_syllable_lengthens():
    sc = score("Daten Daten")
    long_vowels = [p for p in sc.phones if p.symbol == "aː"]
    schwas = [p for p in sc.phones if p.symbol == "ə"]
    assert long_vowels[0].stress == 1 and long_vowels[0].duration > schwas[0].duration
    # последний слог перед паузой растянут
    assert schwas[1].duration > schwas[0].duration


def test_question_rises_statement_falls():
    statement = vowels(score("Das ist ein Haus.", kind="statement"))[-1]
    question = vowels(score("Ist das ein Haus?", kind="question"))[-1]
    assert statement.f0[-1][1] < statement.f0[0][1]
    assert question.f0[-1][1] > question.f0[0][1]


def test_function_words_get_no_accent():
    sc = score("der Compiler und das Programm")
    peaks = {}
    for phone in vowels(sc):
        peaks.setdefault(phone.word, max(v for _, v in phone.f0))
    # «der» (0) ниже, чем ударный слог «Compiler» (1)
    assert peaks[0] < peaks[1]


def test_intonation_zero_is_flat():
    sc = score("Das ist ein sehr schönes Haus.", intonation=0)
    accents = [max(v for _, v in p.f0) - min(v for _, v in p.f0) for p in vowels(sc)]
    assert max(accents) < 0.02


@pytest.mark.parametrize("voice", list(formant.VOICES))
def test_voices_speak_at_their_pitch(voice):
    audio, rate = formant.synthesize("Das ist ein Haus.", voice)
    assert rate == formant.SAMPLE_RATE and np.isfinite(audio).all() and np.abs(audio).max() <= 1.0
    f0 = dsp.estimate_f0(audio, rate)
    assert f0 == pytest.approx(formant.VOICES[voice].f0, rel=0.15)


def test_pitch_and_rate_settings():
    base, rate = formant.synthesize("Das ist ein schönes Haus.", "karl")
    high, _ = formant.synthesize("Das ist ein schönes Haus.", "karl", pitch=6)
    fast, _ = formant.synthesize("Das ist ein schönes Haus.", "karl", rate=2)
    assert dsp.estimate_f0(high, rate) / dsp.estimate_f0(base, rate) == pytest.approx(2 ** 0.5, rel=0.08)
    assert len(fast) / len(base) == pytest.approx(0.5, rel=0.08)


def formants(samples, rate):
    """Форманты по LPC в середине гласной."""
    x = dsp.resample(samples, rate, 10000)
    middle = x[len(x) // 2 - 400: len(x) // 2 + 400] * np.hamming(800)
    a, _ = dsp.lpc(dsp.preemphasis(middle, 0.9), 14)
    roots = [r for r in np.roots(a) if np.imag(r) > 0.01]
    found = sorted((np.angle(r) * 10000 / (2 * np.pi), -10000 / np.pi * np.log(abs(r))) for r in roots)
    return [f for f, bandwidth in found if bandwidth < 400 and f > 150]


@pytest.mark.parametrize("vowel", ["aː", "iː", "uː", "eː", "oː", "ə"])
def test_vowel_formants_match_targets(vowel):
    voice = formant.VOICES["karl"]
    sc = Score([Phone("_", 50), Phone(vowel, 400, 1, f0=[(0, 1), (1, 1)]), Phone("_", 50)])
    audio = formant.render(formant.build_track(sc, voice), voice)
    measured = formants(audio, formant.SAMPLE_RATE)
    for target, value in zip(formant.VOWEL_TARGETS[vowel][:2], measured[:2]):
        assert value == pytest.approx(target, rel=0.15)


def segment_level(consonant: str) -> float:
    """Уровень согласной относительно соседней гласной, дБ."""
    voice = formant.VOICES["karl"]
    phones = [Phone("_", 60), Phone("a", 180, 1, f0=[(0, 1), (1, 1)]), Phone(consonant, 120, 0, f0=[(0, 1), (1, 1)]),
              Phone("a", 180, 0, f0=[(0, 1), (1, 1)]), Phone("_", 60)]
    audio = formant.render(formant.build_track(Score(phones), voice), voice).astype(float)
    ms = lambda t: int(t * formant.SAMPLE_RATE / 1000)                     # noqa: E731
    level = lambda x: 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9)       # noqa: E731
    return level(audio[ms(250):ms(350)]) - level(audio[ms(90):ms(220)])


@pytest.mark.parametrize("consonant, expected", [("s", -12), ("ʃ", -10), ("f", -22), ("h", -20), ("ç", -15), ("x", -16)])
def test_noise_consonants_are_calibrated(consonant, expected):
    """Шумные согласные тише гласных — как в живой речи (калибровка FRICATION_GAIN)."""
    assert segment_level(consonant) == pytest.approx(expected, abs=4)


def test_noise_spectra_differ_by_place():
    def centroid(consonant):
        voice = formant.VOICES["karl"]
        phones = [Phone("_", 40), Phone(consonant, 200, 0, f0=[(0, 1), (1, 1)]), Phone("_", 40)]
        audio = formant.render(formant.build_track(Score(phones), voice), voice)
        spectrum = np.abs(np.fft.rfft(audio * np.hanning(len(audio))))
        frequencies = np.fft.rfftfreq(len(audio), 1 / formant.SAMPLE_RATE)
        return (spectrum * frequencies).sum() / spectrum.sum()
    assert centroid("s") > centroid("ʃ") > centroid("x")


def test_describe_returns_score_for_page():
    items = formant.describe("Hallo Welt.")
    assert items[0]["symbol"] == "_" and any(i["symbol"] == "l" for i in items)
    assert all(isinstance(i["ms"], int) for i in items)
