"""Снимки экрана интерфейса.

    python tools/screenshots.py                снять все страницы
    python tools/screenshots.py --only talk    только снимки, имя которых начинается с «talk»

Система (python run.py) должна быть запущена. Используется Chrome или Edge
без окна (tools/browser.py). Страницы живые, поэтому перед снимком на них
выполняется сценарий: «Чтец» начинает читать, в статье включается чтение под
указателем, паук получает муху и торт. Микрофон браузеру заменяет
искусственный (непрерывный тон) — так снимается и паук, который слушает.
Снимки — report/screens/*.png.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from browser import Browser  # noqa: E402

from glashatai import config, console  # noqa: E402

console.setup()

APP = f"http://{config.HOST}:{config.PORT}"
OUT = config.REPORT_DIR / "screens"


def shot(page, name: str, full: bool = False) -> None:
    path = OUT / f"{name}.png"
    page.screenshot(path, full=full)
    print(f"  {path.relative_to(ROOT)}")


def reader(page) -> None:
    page.goto(APP + "/", 2)
    shot(page, "ui_reader_text")
    page.evaluate("Glashatai.reader.start(0)")
    page.wait_for("Glashatai.reader.player.state === 'speaking'", 30)
    time.sleep(2.5)
    shot(page, "ui_reader_reading")
    page.evaluate("Glashatai.reader.player.stop(); document.querySelector('[data-tab=spoken]').click()")
    time.sleep(1.2)
    shot(page, "ui_reader_spoken")
    page.evaluate("document.querySelector('[data-tab=phonetics]').click()")
    page.wait_for("document.querySelector('#phonetics table')", 20)
    time.sleep(0.5)
    shot(page, "ui_reader_phonetics")
    page.evaluate("document.getElementById('settings').scrollIntoView()")
    time.sleep(0.4)
    shot(page, "ui_settings")


def articles(page) -> None:
    page.goto(APP + "/articles", 1.5)
    shot(page, "ui_articles")
    page.goto(APP + "/articles/de-cs-semweb", 2)
    page.wait_for("document.querySelectorAll('.sent').length > 30", 15)
    page.evaluate("document.getElementById('hover-mode').checked = true; document.getElementById('hover-mode').dispatchEvent(new Event('change'))")
    page.evaluate("window.scrollTo(0, 260); document.querySelectorAll('.sent')[6].dispatchEvent(new MouseEvent('mouseover', {bubbles: true}))")
    page.wait_for("Glashatai.article.player.state === 'speaking'", 20)
    time.sleep(1)
    shot(page, "ui_article_pointer")
    page.evaluate("Glashatai.article.player.stop(); document.getElementById('hover-mode').checked = false;"
                  "document.getElementById('hover-mode').dispatchEvent(new Event('change'))")


def elsewhere(page) -> None:
    page.goto(APP + "/elsewhere", 1.5)
    shot(page, "ui_elsewhere")
    page.goto(APP + "/demo", 1.5)
    page.evaluate("document.getElementById('inject').click()")
    page.wait_for("window.__glashataiPointer", 10)
    page.evaluate("const p = document.querySelectorAll('main p')[3]; p.dispatchEvent(new MouseEvent('mousemove', {bubbles: true}));"
                  "p.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}))")
    time.sleep(2.5)
    shot(page, "ui_bookmarklet")
    page.evaluate("__glashataiPointer.hide()")


def other(page) -> None:
    for path, name in (("/lexicon", "ui_lexicon"), ("/evaluation", "ui_evaluation"), ("/help", "ui_help")):
        page.goto(APP + path, 2)
        shot(page, name)


def talking(page) -> None:
    # состояние паука пишется с другой страницы: вкладка игры при уходе сохранила бы своё поверх
    page.goto(APP + "/help", 1)
    saved = {"food": 62, "energy": 74, "mood": 81, "xp": 150, "asleep": False, "wearing": ["glasses", "bowtie"],
             "webs": 3, "time": int(time.time() * 1000),
             "stats": {"pokes": 23, "legs": 6, "flies": 9, "echoes": 7, "says": 4, "webs": 3, "pies": 2,
                       "cymbals": 1, "strokes": 5}}
    page.evaluate(f"localStorage.setItem('glashatai-pafnuty', {json.dumps(json.dumps(saved))})")
    page.goto(APP + "/talking", 3)
    shot(page, "talk_idle")
    page.evaluate("Glashatai.talking.poke('leg', 1)")
    time.sleep(0.25)
    shot(page, "talk_leg")
    time.sleep(2)
    page.evaluate("Glashatai.talking.actions.fly()")
    time.sleep(1.6)
    shot(page, "talk_fly")
    time.sleep(3)
    page.evaluate("Glashatai.talking.actions.pie()")
    time.sleep(1.1)
    shot(page, "talk_pie")
    time.sleep(4)
    page.evaluate("Glashatai.talking.actions.cymbal()")
    time.sleep(0.5)
    shot(page, "talk_cymbal")
    time.sleep(2.5)
    page.evaluate("document.getElementById('mic').click()")
    page.wait_for("document.getElementById('mic').classList.contains('is-hearing')", 8)
    time.sleep(0.6)
    shot(page, "talk_listening")
    page.evaluate("document.getElementById('mic').click()")
    time.sleep(3)
    page.evaluate("Glashatai.talking.actions.light()")
    time.sleep(2.5)
    shot(page, "talk_sleep")
    page.evaluate("Glashatai.talking.actions.light()")


def main() -> None:
    parser = argparse.ArgumentParser(description="Снимки экрана «Глашатая»")
    parser.add_argument("--only", default="", help="начало имени снимков")
    arguments = parser.parse_args()
    try:
        urllib.request.urlopen(APP + "/api/voices", timeout=5).read()
    except OSError:
        print(f"Система не отвечает по адресу {APP}: запустите python run.py")
        sys.exit(1)
    OUT.mkdir(parents=True, exist_ok=True)
    steps = [("ui_reader", reader), ("ui_article", articles), ("ui_elsewhere", elsewhere), ("ui_other", other),
             ("talk", talking)]
    with Browser(width=1360, height=900) as browser:
        page = browser.open(APP + "/", 1)
        for prefix, step in steps:
            if arguments.only and not prefix.startswith(arguments.only) and not arguments.only.startswith(prefix[:3]):
                continue
            step(page)
        if page.errors:
            print("Ошибки на страницах:", *page.errors, sep="\n  ")
        page.close()


if __name__ == "__main__":
    main()
