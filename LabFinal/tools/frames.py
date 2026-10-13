"""Кадры ролика: снимки ключевых моментов без просмотра целиком.

    python tools/frames.py                    ключевые моменты → frames/*.png
    python tools/frames.py --at 12 40.5 95    кадры названных секунд
    python tools/frames.py --out папка --url http://127.0.0.1:8101

Ролик (python run.py --no-browser) должен быть запущен. Используется Chrome
или Edge без окна (tools/browser.py). Кадр ролика — функция секунды, поэтому
страница открывается один раз с ключом ?t=0 и дальше только перематывается.
Ключевые моменты берутся из расписания самой страницы: начало, этажи,
тёмный зал, вступление хора, выход, страница благодарности.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from browser import Browser  # noqa: E402

from poklon import config, console  # noqa: E402

MOMENTS = """(() => {
  const plan = Poklon.show.plan, beams = Poklon.show.troupe.beams;
  const list = [[-1, 'wait'], [5, 'solo'], [12, 'rise']];
  beams.forEach(beam => list.push([beam.time, 'floor' + beam.label.replace('·', '-')]));
  list.push([(16 + plan.choir - 9) / 2, 'crowd'], [plan.choir - 3.5, 'dusk'], [plan.choir - 0.6, 'before'],
    [plan.choir + 0.12, 'flash'], [plan.choir + 2.5, 'choir'], [(plan.choir + plan.leave) / 2, 'hall'],
    [plan.leave - 1, 'hall_end'], [plan.leave + 2.2, 'goodbye'], [plan.leave + 7, 'leave'],
    [plan.arrive - 1.6, 'light'], [plan.arrive + 3.5, 'thanks'], [plan.arrive + 11, 'words'],
    [plan.arrive + 22, 'credits']);
  return list.sort((a, b) => a[0] - b[0]);
})()"""


def main() -> None:
    console.setup()
    parser = argparse.ArgumentParser(description="Кадры ролика «Поклон»")
    parser.add_argument("--url", default=f"http://{config.HOST}:{config.PORT}")
    parser.add_argument("--out", type=Path, default=ROOT / "frames")
    parser.add_argument("--at", type=float, nargs="*", help="секунды; без ключа — ключевые моменты")
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--rehearsal", action="store_true", help="с открытой лентой репетиции")
    arguments = parser.parse_args()
    height = arguments.width * 9 // 16

    with Browser(arguments.width, height) as browser:
        page = browser.open(arguments.url + "/?t=0" + ("&rehearsal=1" if arguments.rehearsal else ""))
        page.size(arguments.width, height)
        if not page.wait_for("window.Poklon && Poklon.mode() === 'running'", 90):
            raise SystemExit("страница не подготовила ролик: " + "; ".join(page.errors or page.console))
        info = page.evaluate("({track: Poklon.show.track, cues: Poklon.show.cues, origin: Poklon.show.origin,"
                             " count: Poklon.show.troupe.count, arrive: Poklon.show.plan.arrive})")
        track = info["track"]
        print(f"запись: {track['name']} ({track['duration']:.1f} с)" if track else "запись: нет, ролик в тишине")
        print(f"хор: {info['cues']['choir']:.1f}–{info['cues']['leave']:.1f} с ({info['origin']}), "
              f"выход на {info['arrive']:.1f} с, в труппе {info['count']}")
        if arguments.at:
            moments = [[seconds, "at"] for seconds in arguments.at]
        else:
            moments = page.evaluate(MOMENTS)
        for number, (seconds, name) in enumerate(moments, 1):
            page.evaluate(f"Poklon.seek({seconds})")
            time.sleep(0.35)
            path = arguments.out / f"{number:02d}_{name}_{seconds:06.1f}.png"
            page.screenshot(path)
            print(f"  {seconds:6.1f} с  {path}")
        page.close()
        if page.errors:
            print("ошибки страницы:")
            for error in page.errors:
                print("  " + error)
            raise SystemExit(1)


if __name__ == "__main__":
    main()
