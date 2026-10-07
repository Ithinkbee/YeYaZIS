"""Синтезаторы, диктор, настройки."""

from __future__ import annotations

import numpy as np
import pytest

from glashatai import config, dsp
from glashatai.engines import Settings, split_voice
from glashatai.engines.piper import PiperEngine, compose
from glashatai.engines.sapi import SapiEngine, rate_value
from glashatai.text import ReadingOptions


def test_settings_are_clamped():
    settings = Settings.from_dict({"voice": "formant:karl", "rate": 9, "pitch": -50, "volume": "70",
                                   "liveliness": float("nan"), "sentence_pause": -5, "paragraph_pause": "x"})
    assert settings.rate == config.RATE_RANGE[1] and settings.pitch == config.PITCH_RANGE[0]
    assert settings.volume == 70 and settings.liveliness == 0.5 and settings.sentence_pause == 0
    assert settings.paragraph_pause == Settings().paragraph_pause
    assert Settings.from_dict({"voice": ""}).voice == config.DEFAULT_VOICE


def test_settings_key_ignores_volume_and_pauses():
    a = Settings(voice="formant:karl", volume=10, sentence_pause=0)
    b = Settings(voice="formant:karl", volume=90, sentence_pause=900)
    assert a.key() == b.key() and a.key() != Settings(voice="formant:karl", rate=1.5).key()


def test_split_voice():
    assert split_voice("piper:de_DE-thorsten_emotional-medium#angry") == ("piper", "de_DE-thorsten_emotional-medium", "angry")
    assert split_voice("formant:karl") == ("formant", "karl", None)


def test_voice_list_covers_all_engines(speaker):
    engines = {voice.engine for voice in speaker.voices()}
    assert {"piper", "formant", "sapi", "browser"} <= engines
    formant_voices = [v for v in speaker.voices() if v.engine == "formant"]
    assert [v.id for v in formant_voices] == ["formant:karl", "formant:klara", "formant:pafnuty"]
    assert all(v.available for v in formant_voices)
    emotional = [v for v in speaker.voices() if "#" in v.id]
    assert len(emotional) == 8


def test_missing_piper_voice_is_listed_but_unavailable(tmp_path):
    engine = PiperEngine(tmp_path)
    voices = engine.voices()
    assert voices and not any(v.available for v in voices)
    assert all("get_voices" in v.note or "piper-tts" in v.note for v in voices)


def test_unavailable_voice_falls_back(speaker, reader):
    sentence = reader.sentence("Ein kurzer Satz.")
    spoken = speaker.synthesize(sentence, Settings(voice="piper:de_DE-nobody-low"))
    assert spoken.fallback and spoken.voice == speaker.default_voice()
    assert len(spoken.audio.samples) > 0


def test_formant_voice_through_speaker(speaker, reader):
    sentence = reader.sentence("Ab 1954 nutzt die CPU 12 GB.")
    settings = Settings(voice="formant:karl")
    first = speaker.synthesize(sentence, settings)
    again = speaker.synthesize(sentence, settings)
    assert not first.cached and again.cached and not first.fallback
    assert dsp.speech_level(first.audio.samples, first.audio.rate) == pytest.approx(config.TARGET_LEVEL_DB, abs=0.6)
    higher = speaker.synthesize(sentence, Settings(voice="formant:karl", pitch=5))
    assert not higher.cached


def test_speak_joins_sentences_with_pauses(speaker):
    settings = Settings(voice="formant:karl", sentence_pause=500, paragraph_pause=1500, volume=100)
    one = speaker.speak("Erster Satz.", settings)
    two = speaker.speak("Erster Satz. Erster Satz.", settings)
    para = speaker.speak("Erster Satz.\n\nErster Satz.", settings)
    assert two.audio.seconds == pytest.approx(2 * one.audio.seconds + 0.5, abs=0.05)
    assert para.audio.seconds == pytest.approx(2 * one.audio.seconds + 1.5, abs=0.05)
    quiet = speaker.speak("Erster Satz.", Settings(voice="formant:karl", volume=50))
    assert dsp.speech_level(quiet.audio.samples, quiet.audio.rate) == pytest.approx(
        dsp.speech_level(one.audio.samples, one.audio.rate) - 6.02, abs=0.3)


def test_silent_sentence_gives_short_silence(speaker, reader):
    spoken = speaker.synthesize(reader.sentence("[12]"), Settings(voice="formant:karl"))
    assert 0 < len(spoken.audio.samples) < spoken.audio.rate * 0.1 and not spoken.audio.samples.any()


def test_compose_restores_precomposed_letters():
    mapping = {"ɪ": [1], "ç": [2], "c": [3]}
    assert compose(["ɪ", "c", "̧"], mapping) == ["ɪ", "ç"]
    assert compose(["ɪ", "c", "̧"], {**mapping, "̧": [4]}) == ["ɪ", "c", "̧"]


def test_piper_text_injects_phonemes(reader):
    sentence = reader.sentence("Deep Learning nutzt die GPU und 12 GB RAM.")
    text = PiperEngine.text(sentence)
    assert text.startswith("[[ dˈiːp lˈœɾnɪŋ ]]")
    assert "[[ ɡˈeː pˈeː ˈuː ]]" in text and "zwölf" in text and "[[ rˈam ]]" in text
    raw = reader.sentence("Ab 1954 z. B.", ReadingOptions.raw())
    assert PiperEngine.text(raw) == "Ab 1954 z. B."


def test_piper_voices_speak(piper, reader):
    sentence = reader.sentence("Ein Compiler übersetzt Programme.")
    audio = piper.synthesize(sentence, "de_DE-thorsten-medium", None, Settings())
    slow = piper.synthesize(sentence, "de_DE-thorsten-medium", None, Settings(rate=0.5))
    assert audio.rate == 22050 and 1.0 < audio.seconds < 4.0
    assert slow.seconds == pytest.approx(2 * audio.seconds, rel=0.15)
    angry = piper.synthesize(sentence, "de_DE-thorsten_emotional-medium", "angry", Settings())
    assert angry.seconds > 0.5 and np.isfinite(angry.samples).all()


def test_piper_rejects_unknown_manner(piper, reader):
    from glashatai.engines import EngineError

    with pytest.raises(EngineError):
        piper.synthesize(reader.sentence("Hallo."), "de_DE-thorsten_emotional-medium", "furious", Settings())


def test_piper_phonemes_for_comparison(piper):
    assert piper.phonemes("Tag").replace("ˈ", "") == "tɑːk"


def test_sapi_rate_mapping():
    assert rate_value(1.0) == 0 and rate_value(3.0) == 10 and rate_value(1 / 3) == -10
    assert rate_value(2.0) == 6 and rate_value(100) == 10


def test_sapi_lists_only_german_voices():
    engine = SapiEngine()
    voices = engine.voices()
    assert voices
    for voice in voices:
        assert voice.engine == "sapi"
        if voice.available:
            assert voice.id.startswith("sapi:Microsoft")
        else:
            assert voice.id == "sapi:" and voice.note
    engine.close()
