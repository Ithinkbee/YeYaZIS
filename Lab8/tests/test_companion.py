"""Пафнутий: реплики, голос, выключатель."""

from __future__ import annotations

import os
import random
import subprocess
import sys
import tempfile

import pytest

from glashatai import config, dsp, pafnuty
from glashatai.talking import EMOTIONAL, TalkingVoice

from .conftest import ROOT


def test_talk_lines_are_complete():
    manners = set(config.PIPER_VOICES[EMOTIONAL]["speakers"])
    for occasion, variants in pafnuty.TALK.items():
        assert variants, occasion
        for german, russian, manner in variants:
            assert german.strip() and russian.strip(), occasion
            assert manner in manners, (occasion, manner)
    assert len(pafnuty.all_talk()) == sum(len(v) for v in pafnuty.TALK.values())


def test_page_lines_avoid_repeats():
    rng = random.Random(1)
    first = pafnuty.line("reader", rng)
    assert first in pafnuty.LINES["reader"]
    assert pafnuty.line("reader", rng, avoid=[first]) != first
    assert pafnuty.line("unknown-page", rng) in pafnuty.LINES["idle"]


def test_talking_voice_formant_and_cache(tmp_path, speaker):
    voice = TalkingVoice(speaker, tmp_path)
    wav = voice.say("Mmm, lecker!", "amused", mode="formant")
    samples, rate = dsp.read_wav(wav)
    assert rate == 22050 and dsp.estimate_f0(samples, rate) > 200
    assert len(list(tmp_path.glob("*.wav"))) == 1
    assert voice.say("Mmm, lecker!", "amused", mode="formant") == wav          # с диска, без синтеза
    whisper = voice.say("Pssst, ich schlafe.", "whisper", mode="formant")
    assert whisper != wav


def test_talking_voice_settings(speaker):
    voice = TalkingVoice(speaker)
    neural = voice.settings("angry", "neural")
    assert neural.voice == f"piper:{EMOTIONAL}#angry" and neural.pitch == 6
    assert voice.settings("furious", "neural").voice.endswith("#neutral")
    sleepy = voice.settings("sleepy", "formant")
    assert sleepy.voice == "formant:pafnuty" and sleepy.rate < 1 and sleepy.liveliness < 0.5
    assert voice.mode("formant") == "formant"


SCRIPT = r"""
from fastapi.testclient import TestClient
from glashatai.web.app import app
client = TestClient(app)
html = client.get("/").text
print("SPIDER" if 'id="companion"' in html or "pafnuty.js" in html else "CLEAN")
print("GAME" if 'href="/talking"' in html else "NO-GAME")
print("CODES", *[client.get(url).status_code for url in ("/talking", "/elsewhere", "/evaluation", "/help")])
print("SAY", client.post("/api/talking/say", json={"text": "Hallo"}).status_code)
print("SPEAK", client.post("/api/speak", json={"text": "Hallo.", "settings": {"voice": "formant:karl"}}).status_code)
"""


def run(companion: str) -> dict[str, str]:
    env = {**os.environ, "GLASHATAI_COMPANION": companion, "PYTHONIOENCODING": "utf-8",
           "GLASHATAI_STATE_DIR": tempfile.mkdtemp(prefix="glashatai-tests-"),
           "GLASHATAI_CACHE_DIR": tempfile.mkdtemp(prefix="glashatai-cache-")}
    result = subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT, env=env, capture_output=True, text=True,
                            encoding="utf-8", timeout=180)
    assert result.returncode == 0, result.stderr
    lines = [line.split(maxsplit=1) for line in result.stdout.splitlines() if line.strip()]
    return {line[0]: line[1] if len(line) > 1 else "" for line in lines}


@pytest.mark.parametrize("companion", ["0", "1"])
def test_companion_switch(companion):
    out = run(companion)
    if companion == "0":
        assert "CLEAN" in out and "NO-GAME" in out
        assert out["CODES"] == "404 200 200 200" and out["SAY"] == "404"
    else:
        assert "SPIDER" in out and "GAME" in out
        assert out["CODES"] == "200 200 200 200" and out["SAY"] == "200"
    assert out["SPEAK"] == "200"                                    # чтение работает в обоих случаях
