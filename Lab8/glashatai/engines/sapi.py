"""Голоса Windows (Microsoft Speech API, System.Speech).

Немецкие голоса Windows — Hedda, Katja, Stefan — ставятся в «Параметрах» →
«Время и язык» → «Речь». Синтезатор вызывается через PowerShell: один
процесс живёт всё время работы системы и получает задания построчно (запуск
PowerShell на каждое предложение занимал бы секунду). Каждое задание —
текст, голос и темп; ответ — WAV-файл.

Темп System.Speech задаётся числом от −10 до 10: 10 — примерно втрое
быстрее, −10 — втрое медленнее. Высоту и «живость» голоса Windows не
меняют; высоту меняет dsp.py.
"""

from __future__ import annotations

import json
import logging
import math
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from pathlib import Path

from glashatai import dsp
from glashatai.engines import Audio, EngineError, Settings, Voice

log = logging.getLogger("glashatai.sapi")

_WORKER = r"""
Add-Type -AssemblyName System.Speech
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(22050, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
[Console]::Out.WriteLine("ready")
[Console]::Out.Flush()
while ($true) {
  $line = [Console]::In.ReadLine()
  if ($line -eq $null) { break }
  try {
    $job = $line | ConvertFrom-Json
    $synth.SelectVoice($job.voice)
    $synth.Rate = [int]$job.rate
    $synth.SetOutputToWaveFile($job.path, $format)
    $synth.Speak($job.text)
    $synth.SetOutputToNull()
    [Console]::Out.WriteLine("ok")
  } catch {
    $synth.SetOutputToNull()
    [Console]::Out.WriteLine("fail " + $_.Exception.Message)
  }
  [Console]::Out.Flush()
}
$synth.Dispose()
"""

_LIST = r"""
Add-Type -AssemblyName System.Speech
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
foreach ($voice in $synth.GetInstalledVoices()) {
  if ($voice.Enabled) { [Console]::Out.WriteLine($voice.VoiceInfo.Culture.Name + "|" + $voice.VoiceInfo.Name + "|" + $voice.VoiceInfo.Gender) }
}
$synth.Dispose()
"""

GENDERS = {"Female": "женский", "Male": "мужской"}


def _powershell() -> str | None:
    if sys.platform != "win32":
        return None
    return shutil.which("pwsh") or shutil.which("powershell")


def rate_value(rate: float) -> int:
    """Темп-множитель -> число System.Speech: 3 -> 10, 1/3 -> −10."""
    return int(max(-10, min(10, round(10 * math.log(max(rate, 0.01)) / math.log(3)))))


class SapiEngine:
    name = "sapi"

    def __init__(self) -> None:
        self._voices: list[tuple[str, str, str]] | None = None   # (культура, имя, пол)
        self._process: subprocess.Popen | None = None
        self._lines: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self._folder = Path(tempfile.mkdtemp(prefix="glashatai-sapi-"))

    def available(self) -> bool:
        return _powershell() is not None

    def _list(self) -> list[tuple[str, str, str]]:
        if self._voices is not None:
            return self._voices
        found: list[tuple[str, str, str]] = []
        executable = _powershell()
        if executable:
            script = self._folder / "list.ps1"
            script.write_text(_LIST, encoding="utf-8-sig")
            try:
                result = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                         "-File", str(script)], capture_output=True, text=True, encoding="utf-8",
                                        errors="replace", timeout=60)
                for line in result.stdout.splitlines():
                    parts = line.strip().split("|")
                    if len(parts) == 3:
                        found.append((parts[0], parts[1], parts[2]))
            except (OSError, subprocess.TimeoutExpired) as problem:
                log.warning("голоса Windows не получены: %s", problem)
        self._voices = found
        return found

    def voices(self) -> list[Voice]:
        if not self.available():
            return [Voice("sapi:", "sapi", "Голоса Windows", "", False, "есть только в Windows")]
        german = [(c, n, g) for c, n, g in self._list() if c.lower().startswith("de")]
        if not german:
            others = ", ".join(n.replace("Microsoft ", "").replace(" Desktop", "") for _, n, _ in self._list())
            note = "немецких голосов нет: «Параметры» → «Время и язык» → «Речь» → «Добавить голоса»"
            if others:
                note += f" (сейчас установлены: {others})"
            return [Voice("sapi:", "sapi", "Голоса Windows", "", False, note)]
        return [Voice(f"sapi:{name}", "sapi", name.replace("Microsoft ", "").replace(" Desktop", ""),
                      GENDERS.get(gender, ""), True, "Microsoft Speech API", ["rate"]) for _, name, gender in german]

    def _start(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        executable = _powershell()
        if executable is None:
            raise EngineError("голоса Windows доступны только в Windows")
        script = self._folder / "worker.ps1"
        script.write_text(_WORKER, encoding="utf-8-sig")
        self._process = subprocess.Popen(
            [executable, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
            errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._lines = queue.Queue()
        threading.Thread(target=self._read, args=(self._process,), daemon=True).start()
        if self._wait(30) != "ready":
            raise EngineError("PowerShell с синтезатором Windows не запустился")

    def _read(self, process: subprocess.Popen) -> None:
        for line in process.stdout:
            self._lines.put(line.strip())

    def _wait(self, timeout: float) -> str:
        try:
            return self._lines.get(timeout=timeout)
        except queue.Empty:
            return ""

    def synthesize_text(self, text: str, voice_name: str, settings: Settings) -> Audio:
        if not text.strip():
            return Audio(dsp.silence(0, 22050), 22050)
        path = self._folder / f"{uuid.uuid4().hex}.wav"
        job = {"voice": voice_name, "text": text, "rate": rate_value(settings.rate), "path": str(path)}
        with self._lock:
            self._start()
            self._process.stdin.write(json.dumps(job, ensure_ascii=True) + "\n")
            self._process.stdin.flush()
            answer = self._wait(60 + len(text) / 5)
        if answer != "ok":
            raise EngineError(f"голос Windows не произнёс текст: {answer[5:] or 'нет ответа'}")
        try:
            samples, rate = dsp.read_wav(path.read_bytes())
        finally:
            path.unlink(missing_ok=True)
        return Audio(samples, rate)

    def close(self) -> None:
        if self._process is not None and self._process.poll() is None:
            try:
                self._process.stdin.close()
                self._process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                self._process.kill()
        shutil.rmtree(self._folder, ignore_errors=True)
