"""Проверка правил тира (tests/shooter_rules.test.js) без node — в браузере Edge или Chrome.

    python tools/run_js_tests.py                 node, если он есть; иначе Edge/Chrome без окна
    python tools/run_js_tests.py --browser       только браузер

Набор написан для node: правила подключаются через require, итог — через
process.exit. В браузере тот же файл выполняется в движке V8 по протоколу
DevTools: require, process и console подменяются, а правила
(static/shooter_rules.js) загружаются как модуль CommonJS. Код возврата — 0,
если все проверки пройдены.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES = ROOT / "dragoman" / "web" / "static" / "shooter_rules.js"
TESTS = ROOT / "tests" / "shooter_rules.test.js"
BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "msedge", "google-chrome", "chromium", "chromium-browser",
]


def browser() -> str | None:
    for candidate in BROWSERS:
        if Path(candidate).exists() or shutil.which(candidate):
            return candidate
    return None


def program() -> str:
    """Тестовый набор, обёрнутый так, чтобы он выполнялся в браузере и возвращал вывод и код."""
    rules = RULES.read_text(encoding="utf-8")
    tests = TESTS.read_text(encoding="utf-8")
    return (
        "(() => { const out = []; let code = null;"
        "const console = { log: (...a) => out.push(a.join(' ')) };"
        "const module = { exports: {} };"
        "(function (module) {" + rules + "\n})(module);"
        "const rulesExport = module.exports;"
        "const require = (name) => name === 'path' ? { join: (...p) => p.join('/') } : rulesExport;"
        "const __dirname = '.';"
        "const process = { exit: (c) => { code = c; throw 'exit'; } };"
        "try { (function (require, __dirname, process, console) {" + tests +
        "\n})(require, __dirname, process, console); }"
        "catch (e) { if (e !== 'exit') { out.push('ИСКЛЮЧЕНИЕ ' + e + ' ' + (e.stack || '')); code = 1; } }"
        "return JSON.stringify({ code, out }); })()"
    )


async def evaluate(ws_url: str, expression: str) -> dict:
    import websockets

    async with websockets.connect(ws_url, max_size=64 * 1024 * 1024) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                  "params": {"expression": expression, "returnByValue": True}}))
        while True:
            message = json.loads(await ws.recv())
            if message.get("id") == 1:
                result = message["result"]
                if "exceptionDetails" in result:
                    return {"code": 1, "out": [json.dumps(result["exceptionDetails"], ensure_ascii=False)]}
                return json.loads(result["result"]["value"])


def run_in_browser(executable: str) -> int:
    profile = tempfile.mkdtemp(prefix="dragoman-js-")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen([executable, "--headless=new", "--no-first-run", f"--remote-debugging-port={port}",
                                f"--user-data-dir={profile}", "about:blank"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2))
                ws_url = next(p["webSocketDebuggerUrl"] for p in pages if p.get("type") == "page")
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.2)
        else:
            print("браузер не запустился")
            return 2
        result = asyncio.run(evaluate(ws_url, program()))
        print("\n".join(result["out"]))
        return 0 if result["code"] == 0 else 1
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        shutil.rmtree(profile, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--browser", action="store_true", help="не пробовать node")
    arguments = parser.parse_args()
    if not arguments.browser and shutil.which("node"):
        return subprocess.run(["node", str(TESTS)], cwd=ROOT).returncode
    executable = browser()
    if executable is None:
        print("нет ни node, ни Edge/Chrome — проверка правил тира пропущена")
        return 3
    return run_in_browser(executable)


if __name__ == "__main__":
    sys.exit(main())
