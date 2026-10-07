"""Нейросетевые голоса Piper (VITS, ONNX).

Piper — открытый синтезатор речи проекта Rhasspy: нейросеть VITS
превращает последовательность фонем сразу в звук, без отдельного вокодера.
Модели обучены на записях одного диктора (Thorsten Müller, Kerstin, Eva K)
или нескольких; работают на процессоре без сети, быстрее реального
времени. Фонемы для сети строит встроенный eSpeak NG.

Система отдаёт Piper уже нормализованное предложение: числа словами,
сокращения раскрыты. Слова из словарей произношения — английские термины,
аббревиатуры, записи пользователя — уходят готовыми фонемами в скобках
[[ … ]]: их транскрипцию строит g2p.py по записи немецкими буквами и
переводит в обозначения eSpeak. Так «Cloud» звучит как «Клауд», а не
«Клут», как прочёл бы eSpeak сам.

Темп и «живость» Piper меняет сам (length_scale, noise_scale, noise_w);
высоту — нет, её меняет dsp.py.
"""

from __future__ import annotations

import ctypes
import json
import logging
import re
import shutil
import sys
import threading
import unicodedata
from pathlib import Path

import numpy as np

from glashatai import config
from glashatai.engines import Audio, EngineError, Settings, Voice
from glashatai.phonetics.g2p import to_espeak, transcribe
from glashatai.text.normalize import Sentence, tidy

log = logging.getLogger("glashatai.piper")

#: токены, которые уходят Piper фонемами
PHONETIC_KINDS = {"english", "user", "acronym"}


def installed() -> bool:
    try:
        import piper  # noqa: F401
    except ImportError:
        return False
    return True


def _ascii_path(path: Path) -> Path:
    """Путь без кириллицы: eSpeak NG внутри Piper не открывает данные по пути «C:\\Users\\Никита\\…».

    Сначала пробуется короткое имя Windows (8.3), потом — копия данных в
    каталоге голосов.
    """
    text = str(path)
    if text.isascii():
        return path
    if sys.platform == "win32":
        buffer = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.GetShortPathNameW(text, buffer, 1024) and buffer.value.isascii():
            return Path(buffer.value)
    copy = config.VOICES_DIR / "espeak-ng-data"
    if str(copy).isascii():
        if not (copy / "phontab").exists():
            shutil.copytree(path, copy, dirs_exist_ok=True)
        return copy
    return path


class PiperEngine:
    name = "piper"

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or config.VOICES_DIR
        self._voices: dict[str, object] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._load_lock = threading.Lock()
        self._espeak_dir: Path | None = None

    # --- голоса ---------------------------------------------------------------------------

    def model_path(self, name: str) -> Path:
        return self.directory / f"{name}.onnx"

    def has(self, name: str) -> bool:
        return self.model_path(name).exists() and Path(str(self.model_path(name)) + ".json").exists()

    def models(self) -> list[str]:
        """Модели в каталоге голосов: известные первыми, потом любые другие немецкие."""
        found = [name for name in config.PIPER_VOICES if self.has(name)]
        if self.directory.exists():
            for path in sorted(self.directory.glob("de_*.onnx")):
                if path.stem not in found and self.has(path.stem):
                    found.append(path.stem)
        return found

    def voices(self) -> list[Voice]:
        ready = installed()
        result = []
        names = list(config.PIPER_VOICES) + [m for m in self.models() if m not in config.PIPER_VOICES]
        for name in names:
            info = config.PIPER_VOICES.get(name, {"title": name, "gender": "", "note": ""})
            available = ready and self.has(name)
            if not ready:
                note = "нужен пакет piper-tts: pip install piper-tts"
            elif not self.has(name):
                note = "не скачан: python tools/get_voices.py"
            else:
                note = info.get("note", "")
            speakers = info.get("speakers")
            if speakers:
                for speaker, manner in speakers.items():
                    result.append(Voice(f"piper:{name}#{speaker}", "piper", f"{info['title']} — {manner}",
                                        info.get("gender", ""), available, note, ["rate", "liveliness"]))
            else:
                result.append(Voice(f"piper:{name}", "piper", info["title"], info.get("gender", ""), available, note,
                                    ["rate", "liveliness"]))
        return result

    def _voice(self, name: str):
        with self._load_lock:
            if name in self._voices:
                return self._voices[name]
            if not installed():
                raise EngineError("нет пакета piper-tts (pip install piper-tts)")
            if not self.has(name):
                raise EngineError(f"голос {name} не скачан: python tools/get_voices.py")
            from piper import PiperVoice
            from piper.voice import ESPEAK_DATA_DIR

            if self._espeak_dir is None:
                self._espeak_dir = _ascii_path(Path(ESPEAK_DATA_DIR))
            voice = PiperVoice.load(str(self.model_path(name)), espeak_data_dir=str(self._espeak_dir))
            self._voices[name] = voice
            self._locks[name] = threading.Lock()
            log.info("голос Piper %s загружен", name)
            return voice

    def preload(self, name: str) -> None:
        try:
            self._voice(name)
        except Exception as problem:            # noqa: BLE001 — фоновая загрузка не должна ронять сервер
            log.warning("голос Piper %s не загружен: %s", name, problem)

    def loaded(self, name: str) -> bool:
        return name in self._voices

    # --- синтез -----------------------------------------------------------------------------

    @staticmethod
    def text(sentence: Sentence, phonetic: bool = True) -> str:
        """Предложение для Piper: слова из словарей — фонемами в [[ … ]]."""
        if sentence.raw:
            return sentence.text
        parts = []
        for token in sentence.tokens:
            if phonetic and token.kind in PHONETIC_KINDS and token.say.strip():
                words = [w for w in re.split(r"[\s-]+", token.say) if re.search(r"\w", w)]
                ipa = " ".join(to_espeak(transcribe(word)) for word in words)
                parts.append(f" [[ {ipa} ]] ")
            else:
                parts.append(token.say.replace("'", ""))
        return tidy("".join(parts), final=not sentence.continued)

    def synthesize(self, sentence: Sentence, name: str, speaker: str | None, settings: Settings,
                   phonetic: bool = True) -> Audio:
        text = self.text(sentence, phonetic)
        return self.synthesize_text(self._adapt(text, name), name, speaker, settings)

    def _adapt(self, text: str, name: str) -> str:
        """Фонемы в [[ … ]] — в той же форме Юникода, на которой обучен голос.

        Новые модели Piper обучены на разложенной форме (eSpeak отдаёт «ç» как
        «c» + седиль), старые — на составной; знак, которого модель не знает,
        она пропускает.
        """
        mapping = self._voice(name).config.phoneme_id_map or {}

        def block(match: re.Match) -> str:
            body = match.group(1)
            decomposed = unicodedata.normalize("NFD", body)
            if all(ch in mapping or ch == " " for ch in decomposed):
                return f"[[{decomposed}]]"
            return f"[[{unicodedata.normalize('NFC', body)}]]"

        return re.sub(r"\[\[(.*?)\]\]", block, text)

    def synthesize_text(self, text: str, name: str, speaker: str | None, settings: Settings) -> Audio:
        from piper import SynthesisConfig

        voice = self._voice(name)
        speaker_id = None
        if speaker:
            mapping = voice.config.speaker_id_map or {}
            speaker_id = mapping.get(speaker)
            if speaker_id is None:
                raise EngineError(f"у голоса {name} нет манеры «{speaker}»")
        liveliness = settings.liveliness
        synthesis = SynthesisConfig(
            speaker_id=speaker_id,
            length_scale=1.0 / max(0.3, settings.rate),
            noise_scale=0.2 + 0.95 * liveliness,          # 0,5 -> 0,675: как по умолчанию у Piper
            noise_w_scale=0.3 + 1.0 * liveliness,         # 0,5 -> 0,8
            normalize_audio=True,
        )
        if not text.strip():
            return Audio(np.zeros(0, dtype=np.float32), voice.config.sample_rate)
        mapping = voice.config.phoneme_id_map or {}
        parts = []
        with self._locks[name]:
            try:
                for phonemes in voice.phonemize(text):
                    if not phonemes:
                        continue
                    ids = voice.phonemes_to_ids(compose(phonemes, mapping))
                    audio = voice.phoneme_ids_to_audio(ids, synthesis)
                    if isinstance(audio, tuple):
                        audio = audio[0]
                    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
                    parts.append((audio / peak if peak > 1e-8 else audio).astype(np.float32))
            except Exception as problem:                # noqa: BLE001
                raise EngineError(f"Piper не произнёс текст: {problem}") from problem
        samples = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
        return Audio(samples, voice.config.sample_rate)

    def phonemes(self, text: str, name: str | None = None) -> str:
        """Фонемы eSpeak NG для текста — для сравнения с собственными правилами."""
        models = self.models()
        if not models:
            raise EngineError("нет ни одного голоса Piper")
        voice = self._voice(name or models[0])
        return " ".join("".join(sentence) for sentence in voice.phonemize(text))


def compose(phonemes: list[str], mapping: dict) -> list[str]:
    """Собрать обратно знаки, которых модель не знает в разложенном виде.

    eSpeak NG отдаёт «ç» разложенным: «c» и седиль. Новые модели Piper обучены
    на такой записи, старые (Kerstin, Eva K) — на составной: седиль они
    пропускают и вместо [ç] говорят [c]. Если модели неизвестен знак, но
    известна буква вместе с ним, они склеиваются.
    """
    result: list[str] = []
    for phoneme in phonemes:
        if phoneme not in mapping and result and unicodedata.combining(phoneme):
            joined = unicodedata.normalize("NFC", result[-1] + phoneme)
            if joined in mapping:
                result[-1] = joined
                continue
        result.append(phoneme)
    return result


def voice_config(path: Path) -> dict:
    try:
        return json.loads(Path(str(path) + ".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
