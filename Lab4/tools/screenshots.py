"""Снимки экрана интерфейса и тира для отчёта.

    python tools/screenshots.py              снять все страницы
    python tools/screenshots.py --only game  только снимки тира

Система (python run.py) должна быть запущена. Используется Edge (или Chrome)
без окна через протокол отладки DevTools. Трёхмерная сцена тира рисуется
программным WebGL (SwiftShader), поэтому снимки игры снимаются с паузами:
сцена строится, волна выходит из ворот. Для снимков тира страница
открывается с ?debug=1 — так доступен window.ShooterDebug (пропустить волну,
выиграть сразу). Ошибки JavaScript, если они были, печатаются: так этим же
инструментом проверяется, что игра запускается.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dragoman import config, console  # noqa: E402

console.setup()

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "msedge", "google-chrome", "chromium",
]
APP = f"http://{config.HOST}:{config.PORT}"

#: шаги игровых снимков: (пауза, выражение JavaScript) — выполняются до снимка
START_GAME = [
    (2.0, "document.getElementById('shooter-waves').value = 5;"
          "document.getElementById('shooter-waves').dispatchEvent(new Event('input'));"),
    (2.5, "document.getElementById('shooter-form').requestSubmit();"),
    (4.0, "document.getElementById('start-play').click();"),
]
TABS = "document.getElementById('tabs').scrollIntoView();"
#: повернуть Пафнутия к ближайшему живому слову
AIM_NEAREST = ("(() => { const g = ShooterDebug.game, p = g.player;"
               "const alive = g.enemies.filter(e => e.alive);"
               "if (!alive.length) return;"
               "alive.sort((a, b) => a.group.position.distanceTo(p.position) - b.group.position.distanceTo(p.position));"
               "const d = alive[Math.min(1, alive.length - 1)].group.position;"
               "p.yaw = Math.atan2(d.x - p.position.x, d.z - p.position.z); p.pitch = 0.05; })();")

#: (имя файла, адрес, ширина, высота, пауза в секундах, шаги)
SHOTS = [
    ("ui_index", f"{APP}/", 1300, 1150, 1, []),
    ("ui_result", f"{APP}/doc/cs-compiler", 1300, 2000, 3, []),
    ("ui_words", f"{APP}/t/{{uid:cs-compiler}}?tab=words", 1300, 1700, 1, [(0.5, TABS)]),
    ("ui_tree", f"{APP}/t/{{uid:lit-pride}}?tab=tree&s=0", 1300, 1500, 1, [(0.5, TABS)]),
    ("ui_compare", f"{APP}/t/{{uid:lit-gatsby}}?tab=compare", 1300, 1700, 1, [(0.5, TABS)]),
    ("ui_unknown", f"{APP}/t/{{uid:lit-frankenstein}}?tab=unknown", 1300, 1500, 1, [(0.5, TABS)]),
    ("ui_collection", f"{APP}/collection", 1300, 1250, 1, []),
    ("ui_dictionary", f"{APP}/dictionary?q=network", 1300, 1250, 1, []),
    ("ui_replenish", f"{APP}/dictionary/replenish", 1300, 1250, 1, []),
    ("ui_evaluation", f"{APP}/evaluation", 1300, 2400, 1, []),
    ("ui_help", f"{APP}/help", 1300, 1400, 1, []),
    ("ui_print", f"{APP}/print/{{uid:cs-nn}}", 1300, 1500, 1, []),
    ("game_setup", f"{APP}/shooter?doc=lit-hamlet&debug=1", 1300, 1100, 3, START_GAME[:1]),
    ("game_wave", f"{APP}/shooter?doc=lit-hamlet&debug=1", 1300, 900, 3,
     START_GAME + [(1.0, "ShooterDebug.spawnNow(7);"), (7.0, AIM_NEAREST), (0.6, AIM_NEAREST), (0.4, "")]),
    ("game_boss", f"{APP}/shooter?doc=lit-hamlet&debug=1", 1300, 900, 3,
     START_GAME + [(1.0, "ShooterDebug.skipWave();"), (1.0, "ShooterDebug.skipWave();"),
                   (6.0, "ShooterDebug.game.enemies.filter(e => e.alive && e.data.kind !== 'boss')"
                         ".forEach(e => { while (e.alive) e.hit(1); });"),
                   (1.5, "const b = ShooterDebug.game.enemies.find(e => e.alive && e.data.kind === 'boss');"
                         "if (b) { const p = ShooterDebug.game.player; const d = b.group.position;"
                         "p.yaw = Math.atan2(d.x - p.position.x, d.z - p.position.z); p.pitch = 0.02; }"),
                   (1.0, "")]),
    ("game_victory", f"{APP}/shooter?doc=lit-hamlet&debug=1", 1300, 1500, 3,
     START_GAME + [(2.0, "ShooterDebug.win();"), (1.5, "document.getElementById('overlay-end').scrollIntoView();")]),
]


def browser() -> str:
    for candidate in BROWSERS:
        if Path(candidate).exists() or shutil.which(candidate):
            return candidate
    raise SystemExit("не найден Edge или Chrome")


def resolve(url: str) -> str:
    """{uid:doc} в адресе — номер перевода документа коллекции (страница /doc/... перенаправляет на него)."""
    if "{uid:" not in url:
        return url
    head, rest = url.split("{uid:", 1)
    doc, tail = rest.split("}", 1)
    with urllib.request.urlopen(f"{APP}/doc/{doc}", timeout=300) as response:
        uid = response.geturl().split("/t/")[-1].split("?")[0]
    return head + uid + tail


async def capture(ws_url: str, url: str, width: int, height: int, pause: float, steps: list,
                  target: Path) -> list[str]:
    import websockets

    problems: list[str] = []
    async with websockets.connect(ws_url, max_size=64 * 1024 * 1024) as ws:
        counter = 0

        def event(message: dict) -> None:
            method = message.get("method", "")
            params = message.get("params", {})
            if method == "Runtime.exceptionThrown":
                details = params.get("exceptionDetails", {})
                problems.append(details.get("exception", {}).get("description") or details.get("text", ""))
            elif method == "Runtime.consoleAPICalled" and params.get("type") == "error":
                problems.append(" ".join(str(a.get("value", a.get("description", ""))) for a in params.get("args", [])))
            elif method == "Log.entryAdded" and params.get("entry", {}).get("level") == "error":
                problems.append(params["entry"].get("text", ""))

        async def call(method: str, params: dict | None = None) -> dict:
            nonlocal counter
            counter += 1
            ident = counter
            await ws.send(json.dumps({"id": ident, "method": method, "params": params or {}}))
            while True:
                message = json.loads(await ws.recv())
                if message.get("id") == ident:
                    return message.get("result", {})
                event(message)

        async def wait(seconds: float) -> None:
            # события страницы (ошибки) читаются и во время пауз
            end = time.monotonic() + seconds
            while (left := end - time.monotonic()) > 0:
                try:
                    event(json.loads(await asyncio.wait_for(ws.recv(), left)))
                except asyncio.TimeoutError:
                    break

        await call("Emulation.setDeviceMetricsOverride",
                   {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})
        await call("Page.enable")
        await call("Runtime.enable")
        await call("Log.enable")
        await call("Page.navigate", {"url": url})
        await wait(pause + 1.0)
        for delay, script in steps:
            if script:
                result = await call("Runtime.evaluate", {"expression": script})
                if "exceptionDetails" in result:
                    problems.append("шаг: " + result["exceptionDetails"].get("exception", {}).get(
                        "description", result["exceptionDetails"].get("text", "")))
            await wait(delay)
        shot = await call("Page.captureScreenshot", {"format": "png"})
        target.write_bytes(base64.b64decode(shot["data"]))
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="префикс имён снимков (ui, game)")
    parser.add_argument("--out", default=str(config.REPORT_DIR / "screens"))
    arguments = parser.parse_args()
    out = Path(arguments.out)
    out.mkdir(parents=True, exist_ok=True)

    profile = tempfile.mkdtemp(prefix="dragoman-edge-")
    with socket.socket() as probe:           # свободный порт для протокола отладки
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen([
        browser(), "--headless=new", "--hide-scrollbars", "--no-first-run", "--mute-audio",
        "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist",
        "--autoplay-policy=no-user-gesture-required",
        f"--remote-debugging-port={port}", f"--user-data-dir={profile}", "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    failures = 0
    try:
        for _ in range(50):
            try:
                pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2))
                ws_url = next(p["webSocketDebuggerUrl"] for p in pages if p.get("type") == "page")
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.2)
        else:
            raise SystemExit("браузер не запустился")
        for name, url, width, height, pause, steps in SHOTS:
            if arguments.only and not name.startswith(arguments.only):
                continue
            target = out / f"{name}.png"
            total = pause + sum(delay for delay, _ in steps)
            try:
                url = resolve(url)
                problems = asyncio.run(asyncio.wait_for(
                    capture(ws_url, url, width, height, pause, steps, target), total + 60))
                print(f"  {target.name:22} {url.replace(APP, '')}", flush=True)
                for problem in problems:
                    failures += 1
                    print(f"      ошибка на странице: {problem.splitlines()[0] if problem else '?'}", flush=True)
            except (asyncio.TimeoutError, OSError) as problem:
                failures += 1
                print(f"  {target.name:22} не снят: {type(problem).__name__}", flush=True)
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        shutil.rmtree(profile, ignore_errors=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
