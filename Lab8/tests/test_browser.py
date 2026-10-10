"""Интерфейс в настоящем браузере: Chrome или Edge без окна (протокол DevTools).

Сервер поднимается в этом же процессе на свободном порту. Проверяются
правила, написанные на JavaScript (деление текста закладкой, паузы
проигрывателя, потребности и уровни паука, попадание по частям тела), и
живые страницы: чтение с подсветкой, пауза, чтение под указателем мыши,
тычки и действия в игре, закладка на «чужой» странице, словарь.
Без браузера или пакета websockets тесты пропускаются.
"""

from __future__ import annotations

import socket
import sys
import threading
import time

import pytest

from .conftest import ROOT

sys.path.insert(0, str(ROOT / "tools"))


@pytest.fixture(scope="module")
def server():
    import uvicorn

    from glashatai.web.app import app

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    instance = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=instance.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while not instance.started and time.time() < deadline:
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    instance.should_exit = True
    thread.join(10)


@pytest.fixture(scope="module")
def browser():
    pytest.importorskip("websockets")
    from browser import Browser, find_browser

    if find_browser() is None:
        pytest.skip("нет Chrome или Edge")
    instance = Browser()
    yield instance
    instance.close()


@pytest.fixture()
def page(browser, server):
    opened = {}

    def open_page(path: str, wait: float = 1.5):
        if "page" not in opened:
            opened["page"] = browser.open(server + path, wait)
        else:
            opened["page"].goto(server + path, wait)
        opened["page"].errors.clear()
        return opened["page"]

    yield open_page
    if "page" in opened:
        assert opened["page"].errors == [], opened["page"].errors
        opened["page"].close()


# --- правила -----------------------------------------------------------------------------------

def test_player_rules(page):
    p = page("/")
    assert p.evaluate("""(() => {
      const r = Glashatai.Player.rules, s = {sentence_pause: 300, paragraph_pause: 900};
      const list = [{paragraph: 0}, {paragraph: 0, continued: true}, {paragraph: 0}, {paragraph: 1}];
      return [r.pauseAfter(list, 0, s), r.pauseAfter(list, 1, s), r.pauseAfter(list, 2, s), r.pauseAfter(list, 3, s),
              r.browserPitch(0), r.browserPitch(12), r.browserPitch(24)].join(',');
    })()""") == "300,40,900,0,1,2,2"


def test_bookmarklet_chunks(page):
    p = page("/demo")
    p.evaluate("document.getElementById('inject').click()")
    assert p.wait_for("window.__glashataiPointer", 10)
    parts = p.evaluate("""__glashataiPointer.chunks(
      'Das gilt z. B. für Compiler. Im 19. Jahrhundert begann es. ' + 'Ein langer Satz, '.repeat(40) + 'Ende.', 320)""")
    assert parts[0].startswith("Das gilt z. B. für Compiler. Im 19. Jahrhundert begann es.")
    assert all(len(part) <= 330 for part in parts) and parts[-1].endswith("Ende.")


def test_talking_rules(page):
    p = page("/talking")
    result = p.evaluate("""(() => {
      const r = TalkingRules, s = r.fresh(0);
      const hungry = r.decay(s, 60, false), slept = r.decay({...s, energy: 10}, 10, true);
      const up = r.gain({...s, xp: 24}, 'fly');
      return {food: hungry.food, energy: slept.energy, cap: r.decay(s, 1e9, false).food,
              level: r.level(25).level, last: r.level(5000).to, up: up.levelUp, food2: up.state.food,
              wardrobe: r.unlocked(3).map(w => w.id).join(','), mood: r.baseline({...s, food: 5}),
              asleep: r.baseline({...s, asleep: true})};
    })()""")
    assert result["food"] == pytest.approx(34) and result["energy"] == pytest.approx(60)
    assert result["cap"] == 0 and result["level"] == 2 and result["last"] is None
    assert result["up"] is True and result["food2"] == 95
    assert result["wardrobe"] == "hat,glasses" and result["mood"] == "sad" and result["asleep"] == "sleeping"
    detector = p.evaluate("""(() => {
      const d = new TalkingRules.Detector(), out = [];
      for (let i = 0; i < 50; i++) out.push(d.feed(-60));
      for (let i = 0; i < 20; i++) out.push(d.feed(-25));
      for (let i = 0; i < 40; i++) out.push(d.feed(-60));
      return out.filter(Boolean).join(',');
    })()""")
    assert detector == "start,end"


# --- страницы --------------------------------------------------------------------------------

def test_reader_reads_highlights_pauses(page):
    p = page("/")
    p.evaluate("Glashatai.reader.settings.setVoice('formant:karl')")
    p.evaluate("Glashatai.reader.start(0)")
    assert p.wait_for("Glashatai.reader.player.state === 'speaking'", 30)
    assert p.evaluate("document.querySelectorAll('.sent.is-current').length") == 1
    p.evaluate("Glashatai.reader.player.pause()")
    assert p.evaluate("Glashatai.reader.player.state") == "paused"
    p.evaluate("Glashatai.reader.player.resume()")
    assert p.wait_for("Glashatai.reader.player.state === 'speaking' || Glashatai.reader.player.index > 0", 10)
    p.evaluate("Glashatai.reader.player.next()")
    assert p.wait_for("Glashatai.reader.player.index >= 1", 10)
    p.evaluate("document.getElementById('stop').click()")
    assert p.evaluate("Glashatai.reader.player.state") == "idle"
    p.evaluate("document.querySelector('[data-tab=spoken]').click()")
    assert p.wait_for("document.querySelectorAll('#spoken .chg-out').length > 10", 10)
    assert "neunzehnhundertvierundfünfzig" in p.evaluate("document.getElementById('spoken').textContent")


def test_reader_options_reparse(page):
    p = page("/")
    p.evaluate("document.getElementById('text').value = 'Ab 1954 z. B.'; document.getElementById('text').dispatchEvent(new Event('input'))")
    p.evaluate("document.querySelector('[data-tab=spoken]').click()")
    assert p.wait_for("document.getElementById('spoken').textContent.includes('neunzehnhundert')", 10)
    p.evaluate("{ const box = document.querySelector('[data-option=numbers]'); box.checked = false; box.dispatchEvent(new Event('change')); }")
    assert p.wait_for("document.getElementById('spoken').textContent.includes('1954')", 10)
    p.evaluate("{ const box = document.querySelector('[data-option=numbers]'); box.checked = true; box.dispatchEvent(new Event('change')); }")


def test_article_reads_under_pointer(page):
    p = page("/articles/de-cs-compiler")
    assert p.wait_for("document.querySelectorAll('.sent').length > 50", 15)
    p.evaluate("Glashatai.article.settings.setVoice('formant:karl')")
    p.evaluate("document.getElementById('hover-mode').checked = true; document.getElementById('hover-mode').dispatchEvent(new Event('change'))")
    p.evaluate("document.querySelectorAll('.sent')[5].dispatchEvent(new MouseEvent('mouseover', {bubbles: true}))")
    assert p.wait_for("Glashatai.article.player.state !== 'idle' && Glashatai.article.player.index === 5", 15)
    assert p.wait_for("Glashatai.article.player.state === 'idle'", 40)            # одно предложение — и тишина
    p.evaluate("document.getElementById('hover-mode').checked = false; document.getElementById('hover-mode').dispatchEvent(new Event('change'))")


def test_talking_pokes_and_actions(page):
    p = page("/talking", 2)
    p.evaluate("localStorage.removeItem('glashatai-pafnuty')")
    p.goto(p.evaluate("location.href"), 2)
    p.evaluate("document.getElementById('voice-mode').value = 'formant'")
    hits = p.evaluate("""(() => {
      const m = Glashatai.talking.model, ctm = m.el.getScreenCTM(), pt = m.el.createSVGPoint(), out = [];
      for (const [x, y] of [[60, 74], [60, 40], [52.5, 68], [60, 5]]) {
        pt.x = x; pt.y = y; const s = pt.matrixTransform(ctm), b = Glashatai.talking.toModel(s.x, s.y);
        out.push(TalkingRules.hitTest(b.x, b.y, m.joints(), {dx: 0, dy: 0}).part);
      }
      return out.join(',');
    })()""")
    assert hits == "head,belly,eye,thread"
    p.evaluate("Glashatai.talking.poke('leg', 4)")
    assert p.evaluate("Glashatai.talking.motion.lift[4]") > 0.5
    for action in ("fly", "cymbal", "pie", "web", "read"):
        p.evaluate(f"Glashatai.talking.actions.{action}()")
        time.sleep(0.4)
    assert p.wait_for("Glashatai.talking.state().stats.flies === 1", 8)
    stats = p.evaluate("Glashatai.talking.state().stats")
    assert stats["legs"] == 1 and stats["pies"] == 1 and stats["webs"] == 1 and stats["cymbals"] == 1
    for _ in range(7):
        p.evaluate("Glashatai.talking.poke('belly')")
    assert p.wait_for("Glashatai.talking.motion.hidden", 8)                      # обиделся и ушёл
    p.evaluate("Glashatai.talking.actions.light()")
    assert not p.evaluate("Glashatai.talking.state().asleep")                   # пока его нет — не уложить
    assert p.wait_for("!Glashatai.talking.motion.hidden", 12)                    # вернулся
    p.evaluate("Glashatai.talking.actions.light()")
    assert p.evaluate("Glashatai.talking.state().asleep") and p.evaluate("document.getElementById('room').classList.contains('is-dark')")
    p.evaluate("Glashatai.talking.actions.light()")
    xp = p.evaluate("Glashatai.talking.state().xp")
    p.goto(p.evaluate("location.href"), 2)
    assert p.evaluate("Glashatai.talking.state().xp") == xp                     # помнит после перезагрузки


def test_bookmarklet_reads_paragraph(page):
    p = page("/demo")
    p.evaluate("{ window.__played = []; const Original = window.Audio; window.Audio = function () { const a = new Original(); "
               "const play = a.play.bind(a); a.play = () => { window.__played.push(a.src); return play(); }; return a; }; }")
    p.evaluate("document.getElementById('inject').click()")
    assert p.wait_for("window.__glashataiPointer", 10)
    p.evaluate("document.querySelectorAll('main p')[2].dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}))")
    assert p.wait_for("window.__played.length > 0", 10)
    assert "/api/say.wav?text=" in p.evaluate("window.__played[0]")
    p.evaluate("__glashataiPointer.hide()")


def test_lexicon_page_adds_word(page):
    p = page("/lexicon")
    p.evaluate("document.getElementById('lex-written').value = 'Kubernetes'; document.getElementById('lex-reading').value = \"Kuber'netis\";"
               "document.getElementById('lex-add').dispatchEvent(new Event('submit', {cancelable: true}))")
    assert p.wait_for("document.querySelectorAll('#lex-rows tr').length === 1", 10)
    p.evaluate("document.getElementById('probe').value = 'Mit Kubernetes.'; document.getElementById('probe-form').dispatchEvent(new Event('submit', {cancelable: true}))")
    assert p.wait_for("document.getElementById('probe-result').textContent.includes('Kubernetis')", 10)
    p.evaluate("document.querySelector('#lex-rows button:last-child').click()")
    assert p.wait_for("document.querySelectorAll('#lex-rows tr').length === 0", 10)
