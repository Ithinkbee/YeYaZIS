"""Снимки экрана интерфейса и sc-web для отчёта.

    python tools/screenshots.py                  снять страницы интерфейса
    python tools/screenshots.py --scweb          снять и страницы sc-web

Система (python run.py) и, для снимков sc-web, ostis-система должны быть
запущены. Используется Chrome (или Edge) без окна через протокол отладки
DevTools: sc-web — одностраничное приложение, которое дорисовывает граф
после загрузки, поэтому перед снимком выдерживается пауза.

Снимки sc-web выключены по умолчанию: при закрытии вкладки браузера посреди
запроса sc-сервер NIKA (sc-machine 0.8) однажды завис — перестал отвечать,
не закрывая соединения, и помог только перезапуск контейнера. Если они
нужны, после снятия проверьте страницу «OSTIS».
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

from izbornik import config, console  # noqa: E402

console.setup()

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "google-chrome", "chromium", "msedge",
]
APP = f"http://{config.HOST}:{config.PORT}"

#: (имя файла, адрес, ширина, высота, пауза в секундах)
SHOTS = [
    ("ui_index", f"{APP}/", 1300, 1250, 1),
    ("ui_summary", f"{APP}/doc/ru-cs-ostis", 1300, 2050, 2),
    ("ui_summary_de", f"{APP}/doc/de-cs-compiler", 1300, 1900, 2),
    ("ui_source", f"{APP}/doc/de-lit-werther/source", 1300, 1250, 1),
    ("ui_explain", f"{APP}/doc/ru-lit-onegin?n=10#explain", 1300, 2400, 2),
    ("ui_text", f"{APP}/text", 1300, 1000, 1),
    ("ui_evaluation", f"{APP}/evaluation", 1300, 2600, 1),
    ("ui_ostis", f"{APP}/ostis", 1300, 1300, 1),
    ("ui_help", f"{APP}/help", 1300, 1400, 1),
    ("ui_print", f"{APP}/print/doc/de-lit-effi", 1300, 1500, 1),
    ("scweb_section", f"{config.SC_WEB_URL}/?sys_id=section_subject_domain_of_summarization", 1500, 1000, 14),
    ("scweb_document", f"{config.SC_WEB_URL}/?sys_id=doc_ru_cs_ostis", 1500, 1000, 14),
    ("scweb_action", f"{config.SC_WEB_URL}/?sys_id=action_build_summary", 1500, 1000, 14),
]


def browser() -> str:
    for candidate in BROWSERS:
        if Path(candidate).exists() or shutil.which(candidate):
            return candidate
    raise SystemExit("не найден Chrome или Edge")


async def capture(ws_url: str, url: str, width: int, height: int, pause: float, target: Path) -> None:
    import websockets

    async with websockets.connect(ws_url, max_size=64 * 1024 * 1024) as ws:
        counter = 0

        async def call(method: str, params: dict | None = None) -> dict:
            nonlocal counter
            counter += 1
            ident = counter
            await ws.send(json.dumps({"id": ident, "method": method, "params": params or {}}))
            while True:
                message = json.loads(await ws.recv())
                if message.get("id") == ident:
                    return message.get("result", {})

        await call("Emulation.setDeviceMetricsOverride",
                   {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})
        await call("Page.enable")
        await call("Page.navigate", {"url": url})
        await asyncio.sleep(pause + 1.5)
        if "#explain" in url:
            await call("Runtime.evaluate", {"expression":
                       "document.querySelectorAll('details.explain').forEach(d => d.open = true);"
                       "document.querySelector('details.explain').scrollIntoView();"})
            await asyncio.sleep(0.5)
        shot = await call("Page.captureScreenshot", {"format": "png"})
        target.write_bytes(base64.b64decode(shot["data"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="префикс имён снимков (ui, scweb)")
    parser.add_argument("--scweb", action="store_true", help="снимать и страницы sc-web")
    parser.add_argument("--out", default=str(config.REPORT_DIR / "screens"))
    arguments = parser.parse_args()
    out = Path(arguments.out)
    out.mkdir(parents=True, exist_ok=True)

    profile = tempfile.mkdtemp(prefix="izbornik-chrome-")
    with socket.socket() as probe:           # свободный порт для протокола отладки
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen([
        browser(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
        f"--remote-debugging-port={port}", f"--user-data-dir={profile}", "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        for name, url, width, height, pause in SHOTS:
            if arguments.only and not name.startswith(arguments.only):
                continue
            if name.startswith("scweb") and not (arguments.scweb or arguments.only == "scweb"):
                continue
            target = out / f"{name}.png"
            try:
                asyncio.run(asyncio.wait_for(capture(ws_url, url, width, height, pause, target), pause + 30))
                print(f"  {target.name:24} {url}", flush=True)
            except (asyncio.TimeoutError, OSError) as problem:
                # sc-web держит открытые соединения и иногда не отдаёт снимок —
                # такой снимок пропускается, остальные продолжаются
                print(f"  {target.name:24} не снят: {type(problem).__name__}", flush=True)
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        shutil.rmtree(profile, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
