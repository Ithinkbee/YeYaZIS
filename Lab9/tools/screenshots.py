"""Снимки экрана интерфейса для отчёта.

    python tools/screenshots.py                снять все страницы
    python tools/screenshots.py --only walk    только снимки, имя которых начинается с «walk»

Система (python run.py) должна быть запущена. Используется Chrome (или Edge)
без окна через протокол отладки DevTools. Страницы «Слухача» живые, поэтому
перед снимком на них выполняется сценарий: на пульт подаются фразы, в игре
паук идёт и прыгает. Микрофон браузеру заменяет запись из tests/audio —
так снимается и состояние «Слышу речь».

Настоящие настройки сценарии не меняют: список операций и пасхалки только
читаются. Для снимка тайника сценарий входит администратором — с тем именем и
паролем, что заданы в его собственном окружении (SLUHACH_ADMIN_LOGIN,
SLUHACH_ADMIN_PASSWORD); они должны совпадать с теми, с которыми запущена
система.
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

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sluhach import audio, config, console  # noqa: E402

console.setup()

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "google-chrome", "chromium", "msedge",
]
APP = f"http://{config.HOST}:{config.PORT}"


def wait(ms: int) -> str:
    return f"new Promise(resolve => setTimeout(resolve, {ms}))"


def phrases(*items: str) -> str:
    """Подаёт на пульт фразы по одной, как с клавиатуры."""
    steps = "".join(f".then(() => {{ Sluhach.console.submit({json.dumps(text)}); return {wait(1300)}; }})"
                    for text in items)
    return f"Promise.resolve(){steps}"


def keys(sequence: list[tuple[str, bool, int]], level: int = 0) -> str:
    """Игра: клавиши вместо голоса. sequence — (клавиша, нажата, пауза после, мс)."""
    steps = "".join(f".then(() => {{ Sluhach.walk.keys.{key} = {str(down).lower()}; return {wait(pause)}; }})"
                    for key, down, pause in sequence)
    return (f"Sluhach.walk.begin({level}); window.scrollTo(0, document.getElementById('walk-play').offsetTop - 12); "
            f"{wait(500)}{steps}")


#: игрок, который проходит карту: идёт и кричит перед каждым препятствием
PILOT = """
new Promise(function (resolve) {
  var rules = WalkRules, held = Sluhach.walk.keys, until = 0, started = performance.now();
  held.quiet = true;
  var timer = setInterval(function () {
    var run = Sluhach.walk.state(), now = performance.now();
    if (!run) { return; }
    if (run.over || now - started > 70000) { clearInterval(timer); held.quiet = held.loud = false; resolve(run.over); return; }
    if (now < until) { held.loud = true; return; }
    held.loud = false;
    if (!run.grounded || run.respawn > 0 || !run.armed) { return; }
    var ahead = rules.segmentAt(run.level, run.x + rules.FOOT + 6);
    if (!ahead || ahead.top > run.y + rules.STEP_UP || (ahead.ravine && ahead.top < run.y - rules.STEP_UP)) {
      until = now + 120; held.loud = true;
    }
  }, 8);
})
"""

#: лист с позами и выражениями новой модели паука — рисуется прямо на странице
MODEL_SHEET = """
(function () {
  var poses = [
    ['висит', { mode: 'hang' }, {}, 'idle'],
    ['слушает', { mode: 'hang' }, { facing: -0.35, look: { x: -0.6, y: 0.5 } }, 'listening'],
    ['слышит речь', { mode: 'hang' }, { raise: 1, facing: -0.35, look: { x: -0.5, y: 0.5 } }, 'hearing'],
    ['распознаёт', { mode: 'hang' }, { facing: 0.2, look: { x: 0.7, y: -0.9 } }, 'thinking'],
    ['отвечает', { mode: 'hang' }, { raise: 0.25, facing: -0.35 }, 'speaking'],
    ['спит', { mode: 'hang' }, {}, 'sleeping'],
    ['стоит', { mode: 'stand' }, { mode: 'stand' }, 'idle'],
    ['идёт', { mode: 'stand' }, { mode: 'stand', walk: 0.1, moving: 1, facing: 1 }, 'idle'],
    ['идёт', { mode: 'stand' }, { mode: 'stand', walk: 0.6, moving: 1, facing: 1 }, 'idle'],
    ['испуган', { mode: 'stand' }, { mode: 'stand', lean: 7, facing: 1 }, 'startled'],
    ['прыгает', { mode: 'stand' }, { mode: 'stand', air: 1, lean: -3, facing: 1 }, 'startled'],
    ['в воде', { mode: 'stand' }, { mode: 'swim', sway: 1.2 }, 'dizzy'],
    ['на финише', { mode: 'stand' }, { mode: 'stand' }, 'happy']
  ];
  var main = document.querySelector('main');
  main.innerHTML = '<h1>Пафнутий: модель</h1><p class="lead">Одна модель во всех позах: ноги не нарисованы, а ' +
    'вычисляются по точкам, куда ставятся стопы.</p><div id="sheet" style="display: grid; ' +
    'grid-template-columns: repeat(7, 1fr); gap: 12px"></div>';
  document.getElementById('companion').remove();
  poses.forEach(function (item) {
    var cell = document.createElement('div');
    cell.className = 'card';
    cell.style.textAlign = 'center';
    var model = Pafnuty.create(item[1]);
    model.set(item[2]).mood(item[3]);
    if (item[3] === 'speaking') { model.talk(0.8); }
    cell.appendChild(model.el);
    var label = document.createElement('div');
    label.className = 'note';
    label.textContent = item[0];
    cell.appendChild(label);
    document.getElementById('sheet').appendChild(cell);
  });
  return 'ok';
})()
"""

#: окно входа администратора — как его видит обычный пользователь
LOGIN = f"""
(function () {{
  document.querySelector('footer [data-admin-open]').click();
  return {wait(500)};
}})()
"""

#: и тайник после входа; имя и пароль — те, с которыми запущен этот сценарий
SECRET = f"""
(function () {{
  Sluhach.secret.open();
  return {wait(500)}.then(function () {{
    document.getElementById('secret-name').value = {json.dumps(config.ADMIN_LOGIN)};
    document.getElementById('secret-password').value = {json.dumps(config.ADMIN_PASSWORD)};
    document.getElementById('secret-login-form').requestSubmit();
    return {wait(700)};
  }});
}})()
"""

#: выход — чтобы следующие снимки снова были страницами обычного пользователя
LOGOUT = f"Sluhach.api('POST', '/api/admin/logout').then(function () {{ return {wait(200)}; }})"

HEARING = """
(function () {
  document.querySelector('[data-language=de]').click();      /* запись-«микрофон» — немецкая */
  Sluhach.console.start();
  return new Promise(function (resolve) {
    var timer = setInterval(function () {
      if (Sluhach.console.state().phase === 'hearing' && document.getElementById('heard').textContent.length > 12) {
        clearInterval(timer);
        resolve('hearing');
      }
    }, 40);
    setTimeout(function () { clearInterval(timer); resolve('timeout'); }, 20000);
  });
})()
"""

#: (имя файла, адрес, ширина, высота, сценарий перед снимком[, сценарий после снимка])
SHOTS = [
    ("ui_console", "/", 1300, 1250,
     "document.querySelector('[data-language=de]').click(); " +
     phrases("öffne den aufsatz über die räuber", "suche das wort räuber", "lies vor")),
    ("ui_console_ru", "/", 1300, 1250,
     "document.querySelector('[data-language=ru]').click(); " +
     phrases("открой сочинение про онегина", "сколько стоит слон", "сегодня хорошая погода")),
    ("ui_hearing", "/", 1300, 760, HEARING),
    ("ui_operations", "/operations", 1300, 1500, ""),
    ("ui_login", "/", 1300, 900, LOGIN),
    ("ui_secret", "/", 1300, 900, SECRET, LOGOUT),
    ("ui_evaluation", "/evaluation", 1300, 2600, ""),
    ("ui_help", "/help", 1300, 1500, ""),
    ("ui_pafnuty", "/help", 1300, 620, MODEL_SHEET),
    ("walk_intro", "/walk", 1300, 1080, ""),
    ("walk_step", "/walk", 1300, 780, keys([("quiet", True, 1500)])),
    ("walk_jump", "/walk", 1300, 780, keys([("quiet", True, 1700), ("loud", True, 330)])),
    ("walk_water", "/walk", 1300, 780, keys([("quiet", True, 2330)])),
    ("walk_ravine", "/walk", 1300, 780,
     "Sluhach.walk.begin(1); window.scrollTo(0, document.getElementById('walk-play').offsetTop - 12); " +
     PILOT.replace("run.over || now - started > 70000", "run.inRavine || run.over || now - started > 30000")
          .replace("|| (ahead.ravine && ahead.top < run.y - rules.STEP_UP)", "")),
    ("walk_finish", "/walk", 1300, 780,
     "Sluhach.walk.begin(0); window.scrollTo(0, document.getElementById('walk-play').offsetTop - 12); " + PILOT),
]


def browser() -> str:
    for candidate in BROWSERS:
        if Path(candidate).exists() or shutil.which(candidate):
            return candidate
    raise SystemExit("не найден Chrome или Edge")


def microphone(folder: Path) -> Path:
    """Запись, которую браузер получит вместо микрофона: тишина, фраза, тишина."""
    source = ROOT / "tests" / "audio" / "de-open.wav"
    spoken = audio.read_wav(source) if source.exists() else np.zeros(config.SAMPLE_RATE, dtype=np.int16)
    samples = audio.add_noise(audio.pad(spoken, 2500, 6000), 45, np.random.default_rng(1))
    path = folder / "microphone.wav"
    audio.write_wav(path, samples)
    return path


async def capture(ws_url: str, url: str, width: int, height: int, script: str, target: Path,
                  after: str = "") -> None:
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
        await asyncio.sleep(2.0)
        if script:
            await call("Runtime.evaluate", {"expression": script, "awaitPromise": True, "userGesture": True})
            await asyncio.sleep(0.15)
        shot = await call("Page.captureScreenshot", {"format": "png"})
        target.write_bytes(base64.b64decode(shot["data"]))
        if after:
            await call("Runtime.evaluate", {"expression": after, "awaitPromise": True})


def main() -> int:
    parser = argparse.ArgumentParser(description="Снимки экрана интерфейса")
    parser.add_argument("--only", help="начало имён снимков (ui, walk)")
    parser.add_argument("--out", default=str(config.REPORT_DIR / "screens"))
    arguments = parser.parse_args()
    out = Path(arguments.out)
    out.mkdir(parents=True, exist_ok=True)

    try:
        urllib.request.urlopen(f"{APP}/api/status", timeout=3)
    except OSError:
        print(f"Система не отвечает по адресу {APP} — запустите её: python run.py --no-browser")
        return 1

    profile = Path(tempfile.mkdtemp(prefix="sluhach-chrome-"))
    with socket.socket() as probe:           # свободный порт для протокола отладки
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen([
        browser(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--mute-audio",
        "--remote-allow-origins=*", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
        f"--use-file-for-fake-audio-capture={microphone(profile)}",
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
        for name, address, width, height, script, *rest in SHOTS:
            if arguments.only and not name.startswith(arguments.only):
                continue
            target = out / f"{name}.png"
            after = rest[0] if rest else ""
            try:
                asyncio.run(asyncio.wait_for(
                    capture(ws_url, APP + address, width, height, script, target, after), 120))
                print(f"  {target.name:20} {address}", flush=True)
            except (asyncio.TimeoutError, OSError) as problem:
                print(f"  {target.name:20} не снят: {type(problem).__name__}", flush=True)
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
