"""«Мой говорящий Пафнутий»: голос паука и повтор за игроком.

Сама игра — потребности паука, тычки, мухи, свет, гардероб — идёт на
странице (talking.js). Сервер делает то, что требует синтеза и обработки
звука:

* **реплики Пафнутия.** Немецкая фраза синтезируется голосом Thorsten с
  нужной манерой (весело, сердито, сонно, «пьяно» — когда голова кружится)
  и поднимается на шесть полутонов: голос маленького существа. Нет моделей
  Piper — говорит собственный формантный голос «Пафнутий». Готовые фразы
  хранятся на диске (data/cache/talk) и при следующем запуске не
  синтезируются заново;
* **повтор.** Запись с микрофона (16 кГц, 16 бит) проходит выбранный
  эффект из voicefx.py.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from pathlib import Path

import numpy as np

from glashatai import config, dsp, voicefx
from glashatai.engines import Settings
from glashatai.speaker import Speaker

log = logging.getLogger("glashatai.talking")

EMOTIONAL = "de_DE-thorsten_emotional-medium"
#: на сколько полутонов поднят нейросетевой голос, чтобы стать голосом паука
SPIDER_PITCH = 6.0
VOICE_MODES = {"neural": "нейросетевой Thorsten, выше на полоктавы", "formant": "собственный формантный голос"}
#: самая короткая и самая длинная запись для повтора, отсчётов при 16 кГц
ECHO_RATE = 16000


class TalkingVoice:
    def __init__(self, speaker: Speaker, directory: Path | None = None) -> None:
        self.speaker = speaker
        self.directory = directory or config.CACHE_DIR / "talk"
        self._lock = threading.Lock()

    def neural(self) -> bool:
        """Есть ли голос Thorsten с манерами — им Пафнутий говорит охотнее всего."""
        voice = self.speaker.voice(f"piper:{EMOTIONAL}#neutral")
        return voice is not None and voice.available

    def mode(self, wanted: str | None = None) -> str:
        if wanted == "formant":
            return "formant"
        return "neural" if self.neural() else "formant"

    def settings(self, emotion: str, mode: str) -> Settings:
        if mode == "neural":
            emotion = emotion if emotion in config.PIPER_VOICES[EMOTIONAL]["speakers"] else "neutral"
            return Settings(voice=f"piper:{EMOTIONAL}#{emotion}", rate=1.05, pitch=SPIDER_PITCH, liveliness=0.6)
        intonation = {"angry": 0.9, "amused": 0.8, "surprised": 0.95, "sleepy": 0.2, "drunk": 0.75,
                      "whisper": 0.3}.get(emotion, 0.5)
        rate = {"sleepy": 0.85, "drunk": 0.8, "angry": 1.1, "surprised": 1.1}.get(emotion, 1.0)
        return Settings(voice="formant:pafnuty", rate=rate, pitch=0, liveliness=intonation)

    def _path(self, text: str, emotion: str, mode: str) -> Path:
        digest = hashlib.sha1(f"{mode}|{emotion}|{SPIDER_PITCH}|{text}".encode("utf-8")).hexdigest()[:20]
        return self.directory / f"{digest}.wav"

    def say(self, text: str, emotion: str = "neutral", mode: str | None = None) -> bytes:
        """Фраза голосом Пафнутия -> WAV."""
        text = " ".join(str(text).split())[: config.MAX_TALK_CHARS]
        mode = self.mode(mode)
        path = self._path(text, emotion, mode)
        if path.exists():
            try:
                return path.read_bytes()
            except OSError:
                pass
        spoken = self.speaker.speak(text, self.settings(emotion, mode), volume=False)
        samples = spoken.audio.samples
        if emotion == "whisper" and mode == "formant":
            samples = voicefx.apply(samples, spoken.audio.rate, "whisper")
        wav = dsp.to_wav(samples, spoken.audio.rate)
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path.write_bytes(wav)
        except OSError:
            pass
        return wav

    def prewarm(self, phrases: list[tuple[str, str]]) -> None:
        """Заранее синтезирует реплики игры (в фоне при запуске системы)."""
        for text, emotion in phrases:
            try:
                self.say(text, emotion)
            except Exception as problem:        # noqa: BLE001 — фон не должен ронять сервер
                log.warning("реплика «%s» не синтезирована: %s", text, problem)
                return

    @staticmethod
    def echo(pcm: bytes, effect: str) -> bytes:
        """Запись игрока (16 кГц, 16 бит) -> передразнивание выбранным голосом."""
        samples = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2").astype(np.float32) / 32768
        samples = samples[: config.MAX_ECHO_SECONDS * ECHO_RATE]
        processed = voicefx.apply(samples, ECHO_RATE, effect if effect in voicefx.EFFECTS else "squeak")
        return dsp.to_wav(processed, ECHO_RATE)
