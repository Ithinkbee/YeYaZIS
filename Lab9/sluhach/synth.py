"""Озвучивание фраз синтезатором Windows — материал для проверки распознавания.

Чтобы измерить, как система распознаёт речь, нужны записи с известным
текстом. Записывать их голосом долго, да и сравнивать потом не с чем: запись
не повторить. Поэтому проверочные фразы озвучивает синтезатор речи Windows
(Microsoft Speech API, System.Speech) — несколькими голосами на каждом
языке. Синтезированная речь чище живой, поэтому к ней потом примешивается шум
(см. evaluation.py); числа, полученные так, — верхняя оценка качества.

Синтезатор вызывается через PowerShell одним процессом на весь список фраз.
Записи складываются в data/speech и повторно не создаются.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sluhach import config

_SCRIPT = r"""
param([string]$Manifest)
Add-Type -AssemblyName System.Speech
$items = Get-Content -Raw -Encoding UTF8 $Manifest | ConvertFrom-Json
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voice = ""
foreach ($item in $items) {
  try {
    if ($item.voice -ne $voice) { $synth.SelectVoice($item.voice); $voice = $item.voice }
    $synth.SetOutputToWaveFile($item.path, $format)
    $synth.Speak($item.text)
    $synth.SetOutputToNull()
    [Console]::Out.WriteLine("ok")
  } catch {
    [Console]::Out.WriteLine("fail " + $item.path + " " + $_.Exception.Message)
  }
}
$synth.Dispose()
"""

_VOICES = r"""
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
foreach ($voice in $synth.GetInstalledVoices()) {
  if ($voice.Enabled) { [Console]::Out.WriteLine($voice.VoiceInfo.Culture.Name + "|" + $voice.VoiceInfo.Name + "|" + $voice.VoiceInfo.Gender) }
}
$synth.Dispose()
"""


@dataclass(frozen=True)
class Voice:
    name: str               # «Microsoft Hedda Desktop»
    language: str           # de | ru
    gender: str             # Female | Male

    @property
    def speaker(self) -> str:
        """Имя диктора без слов «Microsoft» и «Desktop»: Hedda, Pavel."""
        return self.name.replace("Microsoft", "").replace("Desktop", "").strip()

    @property
    def gender_ru(self) -> str:
        return {"Female": "женский", "Male": "мужской"}.get(self.gender, "")


def _powershell() -> str | None:
    """PowerShell 7, если он есть: ему видны и новые голоса Windows (Katja, Stefan, Pavel).

    Windows PowerShell 5.1 видит только голоса старого образца — по одному на
    язык (Hedda, Irina); проверка с ним работает, но голосов меньше.
    """
    if sys.platform != "win32":
        return None
    return shutil.which("pwsh") or shutil.which("powershell")


def available() -> bool:
    return _powershell() is not None


def _run(script: str, *arguments: str, timeout: float = 1800) -> list[str]:
    executable = _powershell()
    if executable is None:
        raise RuntimeError("синтезатор речи Windows недоступен: нужен Windows с PowerShell")
    with tempfile.TemporaryDirectory(prefix="sluhach-synth-") as folder:
        path = Path(folder) / "script.ps1"
        path.write_text(script, encoding="utf-8-sig")       # BOM: Windows PowerShell иначе читает как ANSI
        result = subprocess.run(
            [executable, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(path), *arguments],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if result.returncode != 0 and not result.stdout.strip():
        raise RuntimeError(f"синтезатор речи не запустился: {result.stderr.strip()[:300]}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def voices() -> dict[str, list[Voice]]:
    """Голоса системы по языкам варианта: по одному на диктора."""
    found: dict[str, list[Voice]] = {code: [] for code in config.LANGUAGE_CODES}
    if not available():
        return found
    seen: set[tuple[str, str]] = set()
    for line in _run(_VOICES, timeout=120):
        parts = line.split("|")
        if len(parts) != 3:
            continue
        language = parts[0][:2].lower()
        voice = Voice(parts[1], language, parts[2])
        # «Microsoft Hedda Desktop» и «Microsoft Hedda» — один диктор в двух движках
        if language in found and (language, voice.speaker) not in seen:
            seen.add((language, voice.speaker))
            found[language].append(voice)
    return found


def speech_path(text: str, voice: Voice, directory: Path | None = None) -> Path:
    """Где лежит запись фразы этим голосом."""
    digest = hashlib.sha1(f"{voice.name}\n{text}".encode("utf-8")).hexdigest()[:16]
    slug = re.sub(r"[^a-z0-9]+", "-", voice.speaker.lower()).strip("-") or "voice"
    return (directory or config.SPEECH_DIR) / voice.language / slug / f"{digest}.wav"


def synthesize(items: list[tuple[str, Voice]], directory: Path | None = None) -> dict[tuple[str, str], Path]:
    """Озвучивает фразы: [(текст, голос)] -> {(текст, имя голоса): файл}.

    Уже озвученные фразы берутся с диска. Фраза, которую синтезатор не смог
    произнести, в результат не попадает.
    """
    paths = {(text, voice.name): speech_path(text, voice, directory) for text, voice in items}
    missing = [(text, voice) for text, voice in items if not paths[(text, voice.name)].exists()]
    if missing:
        manifest = []
        for text, voice in sorted(set(missing), key=lambda item: (item[1].name, item[0])):
            path = paths[(text, voice.name)]
            path.parent.mkdir(parents=True, exist_ok=True)
            manifest.append({"voice": voice.name, "text": text, "path": str(path)})
        with tempfile.TemporaryDirectory(prefix="sluhach-synth-") as folder:
            listing = Path(folder) / "manifest.json"
            listing.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8-sig")
            _run(_SCRIPT, str(listing))
    return {key: path for key, path in paths.items() if path.exists() and path.stat().st_size > 1000}
