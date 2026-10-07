"""Браузер без окна для проверок и снимков экрана: Chrome или Edge по протоколу DevTools.

    with Browser() as browser:
        page = browser.open("http://127.0.0.1:8083/")
        page.evaluate("document.title")
        page.screenshot(Path("shot.png"))

Браузер запускается с ключом --headless=new и отдельным временным профилем;
страница управляется через WebSocket DevTools. Микрофон заменяется
искусственным (--use-fake-device-for-media-stream), а разрешение на него
выдаётся без вопроса — так проверяется и «Мой говорящий Пафнутий».
"""

from __future__ import annotations

import asyncio
import base64
import json
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "google-chrome", "chromium", "chromium-browser", "msedge",
]


def find_browser() -> str | None:
    for candidate in BROWSERS:
        path = shutil.which(candidate) or (candidate if Path(candidate).exists() else None)
        if path:
            return path
    return None


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class Page:
    def __init__(self, browser: "Browser", ws_url: str) -> None:
        self.browser = browser
        self.ws_url = ws_url
        self.loop = browser.loop
        self.socket = self.loop.run_until_complete(self._connect())
        self.counter = 0
        self.console: list[str] = []
        self.errors: list[str] = []
        self.call("Runtime.enable")
        self.call("Page.enable")

    async def _connect(self):
        import websockets

        return await websockets.connect(self.ws_url, max_size=64 * 1024 * 1024)

    async def _call(self, method: str, params: dict | None = None, timeout: float = 60):
        self.counter += 1
        number = self.counter
        await self.socket.send(json.dumps({"id": number, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while True:
            raw = await asyncio.wait_for(self.socket.recv(), timeout=max(0.1, deadline - time.time()))
            message = json.loads(raw)
            if message.get("method") == "Runtime.consoleAPICalled":
                args = message["params"].get("args", [])
                self.console.append(" ".join(str(a.get("value", a.get("description", ""))) for a in args))
            elif message.get("method") == "Runtime.exceptionThrown":
                details = message["params"]["exceptionDetails"]
                self.errors.append(details.get("exception", {}).get("description") or details.get("text", ""))
            if message.get("id") == number:
                if "error" in message:
                    raise RuntimeError(message["error"])
                return message.get("result", {})

    def call(self, method: str, params: dict | None = None, timeout: float = 60) -> dict:
        return self.loop.run_until_complete(self._call(method, params, timeout))

    def goto(self, url: str, wait: float = 1.5) -> None:
        self.call("Page.navigate", {"url": url})
        self.wait_for("document.readyState === 'complete'", 20)
        time.sleep(wait)

    def evaluate(self, expression: str, timeout: float = 60):
        """Выражение JavaScript; обещания дожидаются."""
        result = self.call("Runtime.evaluate", {"expression": expression, "awaitPromise": True,
                                                "returnByValue": True}, timeout)
        if "exceptionDetails" in result:
            details = result["exceptionDetails"]
            raise RuntimeError(details.get("exception", {}).get("description") or details.get("text"))
        return result.get("result", {}).get("value")

    def wait_for(self, condition: str, timeout: float = 15) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.evaluate(f"!!({condition})", timeout=5):
                    return True
            except RuntimeError:
                pass
            time.sleep(0.2)
        return False

    def size(self, width: int, height: int) -> None:
        self.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height,
                                                         "deviceScaleFactor": 1, "mobile": False})

    def screenshot(self, path: Path, full: bool = False) -> None:
        params = {"format": "png"}
        if full:
            metrics = self.call("Page.getLayoutMetrics")
            size = metrics["contentSize"]
            params["clip"] = {"x": 0, "y": 0, "width": size["width"], "height": size["height"], "scale": 1}
            params["captureBeyondViewport"] = True
        data = self.call("Page.captureScreenshot", params)["data"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(data))

    def click(self, x: float, y: float) -> None:
        for kind in ("mousePressed", "mouseReleased"):
            self.call("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1})

    def close(self) -> None:
        self.loop.run_until_complete(self.socket.close())


class Browser:
    def __init__(self, width: int = 1360, height: int = 900, audio_file: str | None = None) -> None:
        self.executable = find_browser()
        if self.executable is None:
            raise RuntimeError("нет Chrome или Edge")
        self.port = _free_port()
        self.profile = tempfile.mkdtemp(prefix="glashatai-browser-")
        arguments = [
            self.executable, "--headless=new", f"--remote-debugging-port={self.port}", f"--user-data-dir={self.profile}",
            f"--window-size={width},{height}", "--no-first-run", "--no-default-browser-check", "--disable-extensions",
            "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required",
            "--hide-scrollbars", "--mute-audio", "about:blank",
        ]
        if audio_file:
            arguments.insert(-1, f"--use-file-for-fake-audio-capture={audio_file}")
        self.process = subprocess.Popen(arguments, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.loop = asyncio.new_event_loop()
        self._wait()

    def _wait(self) -> None:
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=1).read()
                return
            except OSError:
                time.sleep(0.2)
        raise RuntimeError("браузер не запустился")

    def open(self, url: str, wait: float = 1.5) -> Page:
        targets = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list").read())
        page_target = next(t for t in targets if t.get("type") == "page")
        page = Page(self, page_target["webSocketDebuggerUrl"])
        page.goto(url, wait)
        return page

    def close(self) -> None:
        try:
            self.process.terminate()
            self.process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            self.process.kill()
        self.loop.close()
        shutil.rmtree(self.profile, ignore_errors=True)

    def __enter__(self) -> "Browser":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
