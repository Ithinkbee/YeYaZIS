"""Веб-интерфейс «Глашатая»: страницы и API синтеза.

    /                      чтец: ввод текста, буфер обмена, файлы; чтение с подсветкой
    /articles, /articles/… научные статьи; чтение под указателем мыши
    /elsewhere             чтение из других программ: буфер обмена, горячие клавиши, закладка
    /lexicon               словарь произношения
    /evaluation            результаты проверки
    /talking               «Мой говорящий Пафнутий»
    /help                  справка
    /demo                  страница «чужого сайта» для проверки закладки

    /api/voices            голоса
    /api/prepare           текст -> абзацы, предложения, что и как будет прочитано
    /api/speak             предложение -> WAV
    /api/render            весь текст -> WAV-файл
    /api/say.wav           текст -> WAV для закладки на чужих страницах (GET, CORS)
    /api/transcribe        транскрипция: собственные правила и eSpeak NG
    /api/extract, /api/fetch   текст из файла или по адресу
    /api/settings          настройки чтения для других программ
    /api/desktop, /api/events, /api/stop   буфер обмена, горячие клавиши, поток событий
    /api/lexicon…          словарь пользователя
    /api/talking/…         голос Пафнутия и повтор за игроком
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import threading
from contextlib import asynccontextmanager
from queue import Empty, Full, Queue
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from glashatai import APP_NAME, LAB_NUMBER, VARIANT, VERSION, config, dsp, pafnuty
from glashatai.articles import Collection
from glashatai.desktop import Desktop, LocalPlayer
from glashatai.engines import EngineError, Settings, formant
from glashatai.phonetics.g2p import to_espeak, transcribe
from glashatai.speaker import Speaker, wav_name
from glashatai.talking import VOICE_MODES, TalkingVoice
from glashatai.text import KINDS, ReadingOptions
from glashatai.text.extract import ExtractError, from_file, from_url
from glashatai.text.lexicon import LexiconError
from glashatai.voicefx import EFFECTS

log = logging.getLogger("glashatai.web")

EVALUATION_PATH = config.REPORT_DIR / "evaluation.json"


# --- состояние приложения ---------------------------------------------------------

class Bus:
    """События для страниц (Server-Sent Events): текст из другой программы, «замолчать»."""

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.listeners: list[tuple[asyncio.Queue, str]] = []

    def readers(self) -> int:
        return sum(1 for _, role in self.listeners if role == "reader")

    def publish(self, event: dict, to_reader: bool = False) -> bool:
        """Событие всем страницам; с to_reader — только последней открытой странице «Чтец»."""
        if self.loop is None:
            return False
        targets = [queue for queue, role in self.listeners if not to_reader or role == "reader"]
        if to_reader:
            targets = targets[-1:]
        for queue in targets:
            self.loop.call_soon_threadsafe(queue.put_nowait, event)
        return bool(targets)


class DesktopReader:
    """Чтение текста из другой программы без открытой страницы — из колонок компьютера.

    Синтез идёт на шаг впереди воспроизведения: пока звучит предложение,
    следующее уже готово.
    """

    def __init__(self, state: "State") -> None:
        self.state = state
        self.player = LocalPlayer()
        self._generation = 0
        self._lock = threading.Lock()

    def read(self, text: str) -> None:
        with self._lock:
            self._generation += 1
            generation = self._generation
        self.player.stop()
        threading.Thread(target=self._run, args=(text, generation), daemon=True).start()

    def stop(self) -> None:
        with self._lock:
            self._generation += 1
        self.player.stop()

    def _run(self, text: str, generation: int) -> None:
        import winsound

        settings, options = self.state.reading_settings()
        document = self.state.speaker.prepare(text, options)
        ready: Queue = Queue(maxsize=2)

        def put(item) -> bool:
            """В очередь — пока чтение не остановили (иначе поток ждал бы вечно)."""
            while generation == self._generation:
                try:
                    ready.put(item, timeout=0.5)
                    return True
                except Full:
                    continue
            return False

        def produce() -> None:
            for sentence in document.sentences:
                if generation != self._generation:
                    return
                try:
                    spoken = self.state.speaker.synthesize(sentence, settings)
                except EngineError as problem:
                    log.warning("не прочитано: %s", problem)
                    continue
                samples = dsp.apply_volume(spoken.audio.samples, settings.volume)
                pause = settings.sentence_pause if not sentence.continued else 0
                samples = dsp.concatenate([samples, dsp.silence(pause, spoken.audio.rate)])
                if not put(dsp.to_wav(samples, spoken.audio.rate)):
                    return
            put(None)

        threading.Thread(target=produce, daemon=True).start()
        folder = self.player.folder
        index = 0
        while generation == self._generation:
            try:
                wav = ready.get(timeout=60)
            except Empty:
                break
            if wav is None:
                break
            path = folder / f"desk-{index % 3}.wav"
            index += 1
            path.write_bytes(wav)
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_NODEFAULT)


class State:
    def __init__(self) -> None:
        self.speaker = Speaker()
        self.collection = Collection()
        self.talking = TalkingVoice(self.speaker)
        self.bus = Bus()
        self.desktop_reader = DesktopReader(self)
        self.desktop = Desktop(self.on_desktop_text, self.on_desktop_stop)
        self.evaluation: dict | None = None
        self.evaluation_mtime = 0.0
        self.saved = self._load_settings()

    # --- настройки чтения для других программ ------------------------------------------

    def _load_settings(self) -> dict:
        try:
            raw = json.loads(config.SETTINGS_PATH.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_settings(self, settings: Settings, options: ReadingOptions) -> None:
        self.saved = {"settings": settings.to_dict(), "options": options.to_dict()}
        try:
            config.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            config.SETTINGS_PATH.write_text(json.dumps(self.saved, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as problem:
            log.warning("настройки не сохранены: %s", problem)

    def reading_settings(self) -> tuple[Settings, ReadingOptions]:
        settings = Settings.from_dict(self.saved.get("settings"))
        if settings.voice.startswith("browser:"):
            settings.voice = self.speaker.default_voice()
        return settings, ReadingOptions.from_dict(self.saved.get("options"))

    # --- другие программы ------------------------------------------------------------------

    def on_desktop_text(self, text: str, source: str) -> None:
        event = {"type": "read", "text": text, "source": source}
        if self.bus.readers():
            self.bus.publish(event, to_reader=True)
        else:
            self.desktop_reader.read(text)
        self.bus.publish({"type": "desktop", "state": self.desktop.state.to_dict()})

    def on_desktop_stop(self) -> None:
        self.desktop_reader.stop()
        self.bus.publish({"type": "stop"})

    def refresh_evaluation(self) -> dict | None:
        try:
            mtime = EVALUATION_PATH.stat().st_mtime
        except OSError:
            return self.evaluation
        if mtime > self.evaluation_mtime:
            try:
                self.evaluation = json.loads(EVALUATION_PATH.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.evaluation = None
            self.evaluation_mtime = mtime
        return self.evaluation


state = State()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    state.bus.loop = asyncio.get_running_loop()
    # голос по умолчанию и реплики Пафнутия готовятся заранее: первая фраза не ждёт
    default = state.speaker.default_voice()
    if default.startswith("piper:"):
        threading.Thread(target=state.speaker.piper.preload, args=(default.split(":", 1)[1].split("#")[0],),
                         daemon=True).start()
    if config.COMPANION_ENABLED:
        threading.Thread(target=state.talking.prewarm, args=(pafnuty.all_talk(),), daemon=True).start()
    yield
    state.desktop.close()
    state.desktop_reader.stop()
    state.speaker.sapi.close()


app = FastAPI(title=f"«{APP_NAME}» — синтез речи", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))


def static_url(name: str) -> str:
    """Адрес статического файла с версией — иначе браузер держит старые сценарии в кэше."""
    try:
        version = f"{(config.STATIC_DIR / name).stat().st_mtime_ns:x}"
    except OSError:
        return f"/static/{name}"
    return f"/static/{name}?v={version}"


def client_config() -> dict:
    return {"companion": config.COMPANION_ENABLED, "voice": state.speaker.default_voice(),
            "port": config.PORT, "worklet": static_url("capture-worklet.js")}


def _num(value, digits: int = 1) -> str:
    if value is None:
        return "—"
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}".replace(",", " ")
    return f"{float(value):,.{digits}f}".replace(",", " ").replace(".", ",")


def _pct(value, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{100 * float(value):.{digits}f}".replace(".", ",") + " %"


def _ms(value) -> str:
    if value is None:
        return "—"
    value = float(value)
    if value >= 1000:
        return f"{value / 1000:.2f}".replace(".", ",") + " с"
    return f"{value:.0f} мс"


templates.env.filters.update(num=_num, pct=_pct, ms=_ms)
templates.env.globals.update(
    app_name=APP_NAME, version=VERSION, variant=VARIANT, lab_number=LAB_NUMBER, config=config,
    companion_enabled=config.COMPANION_ENABLED, companion_name=config.COMPANION_NAME,
    companion_genitive=pafnuty.NAME_GENITIVE, static_url=static_url, client_config=client_config,
)


def render(request: Request, template: str, active: str, status_code: int = 200, **context) -> HTMLResponse:
    context.setdefault("companion_line", pafnuty.line(active) if config.COMPANION_ENABLED else "")
    return templates.TemplateResponse(request, template, {"active": active, **context}, status_code=status_code)


def boot() -> dict:
    """То, с чего начинают работу страницы с чтением."""
    voices = [voice.to_dict() for voice in state.speaker.voices()]
    settings, options = state.reading_settings()
    return {
        "voices": voices, "default": state.speaker.default_voice(),
        "settings": settings.to_dict(), "options": options.to_dict(),
        "ranges": {"rate": config.RATE_RANGE, "pitch": config.PITCH_RANGE, "volume": config.VOLUME_RANGE,
                   "sentence_pause": config.SENTENCE_PAUSE_RANGE, "paragraph_pause": config.PARAGRAPH_PAUSE_RANGE},
        "kinds": KINDS, "language": config.LANGUAGE_TAG, "maxChars": config.MAX_TEXT_CHARS,
        "maxUpload": config.MAX_UPLOAD_BYTES, "voiceName": config.COMPANION_NAME if config.COMPANION_ENABLED
        else "Глашатай",
    }


SAMPLE = """# Übersetzerbau

Ein Compiler übersetzt ein Programm aus einer Quellsprache in eine Zielsprache, z. B. aus C++ in Maschinencode. Ab 1954 kam der Begriff „algebraic compiler“ auf; in den 1950er-Jahren war er noch nicht fest verankert.

Die Laufzeit der Syntaxanalyse beträgt meist O(n), im ungünstigsten Fall O(n³). Moderne JIT-Compiler nutzen die CPU und bis zu 12 GB RAM, d. h. rund 3,5 % mehr als 2019 [12].

Deep Learning und Machine Learning gelten heute als wichtigste Werkzeuge der KI. Am 3. Mai 2021 erschien die 2. Auflage (vgl. S. 12 f.)."""


# --- страницы -------------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return render(request, "index.html", "reader", boot=boot(), sample=SAMPLE)


@app.get("/articles", response_class=HTMLResponse)
def articles_page(request: Request):
    return render(request, "articles.html", "articles", articles=[a.summary() for a in state.collection])


@app.get("/articles/{article_id}", response_class=HTMLResponse)
def article_page(request: Request, article_id: str):
    article = state.collection.get(article_id)
    if article is None:
        raise HTTPException(404, f"Статьи «{article_id}» нет.")
    return render(request, "article.html", "articles", article=article.summary(), boot=boot(),
                  text=article.text)


@app.get("/elsewhere", response_class=HTMLResponse)
def elsewhere_page(request: Request):
    host = request.headers.get("host") or f"{config.HOST}:{config.PORT}"
    return render(request, "elsewhere.html", "elsewhere", desktop=state.desktop.state.to_dict(), boot=boot(),
                  origin=f"http://{host}")


@app.get("/lexicon", response_class=HTMLResponse)
def lexicon_page(request: Request):
    lexicon = state.speaker.reader.lexicon
    return render(request, "lexicon.html", "lexicon", english=lexicon.english, acronyms=lexicon.acronyms,
                  abbreviations=lexicon.abbreviations, boot=boot())


@app.get("/evaluation", response_class=HTMLResponse)
def evaluation_page(request: Request):
    images = sorted(p.name for p in config.REPORT_DIR.glob("eval_*.png")) if config.REPORT_DIR.exists() else []
    return render(request, "evaluation.html", "evaluation", data=state.refresh_evaluation(), images=images)


@app.get("/talking", response_class=HTMLResponse)
def talking_page(request: Request):
    if not config.COMPANION_ENABLED:
        raise HTTPException(404, "Пафнутий выключен (GLASHATAI_COMPANION=0) — вместе с ним и его вкладка.")
    data = {"lines": pafnuty.talk_lines(), "hints": pafnuty.HINTS, "effects": EFFECTS,
            "modes": VOICE_MODES, "mode": state.talking.mode()}
    return render(request, "talking.html", "talking", game=data)


@app.get("/help", response_class=HTMLResponse)
def help_page(request: Request):
    return render(request, "help.html", "help", voices=state.speaker.voices(), kinds=KINDS)


@app.get("/demo", response_class=HTMLResponse)
def demo_page(request: Request):
    article = state.collection.get("de-cs-semweb") or next(iter(state.collection), None)
    paragraphs = []
    if article is not None:
        paragraphs = [block.strip() for block in article.text.split("\n\n") if block.strip()][:14]
    return templates.TemplateResponse(request, "demo.html", {"paragraphs": paragraphs,
                                                             "title": article.title if article else ""})


@app.get("/report/{name}")
def report_file(name: str):
    path = (config.REPORT_DIR / name).resolve()
    if path.parent != config.REPORT_DIR.resolve() or path.suffix != ".png" or not path.exists():
        raise HTTPException(404)
    return Response(path.read_bytes(), media_type="image/png")


# --- синтез ---------------------------------------------------------------------------------

class TextBody(BaseModel):
    text: str = Field("", max_length=config.MAX_TEXT_CHARS)
    options: dict | None = None


class SpeakBody(BaseModel):
    text: str = Field("", max_length=config.MAX_SENTENCE_CHARS * 4)
    options: dict | None = None
    settings: dict | None = None
    heading: bool = False
    continued: bool = False
    #: без нормализации — текст уходит синтезатору как есть (для сравнения)
    raw: bool = False


class RenderBody(BaseModel):
    text: str = Field("", max_length=config.MAX_TEXT_CHARS)
    options: dict | None = None
    settings: dict | None = None


def _wav(samples, rate, headers: dict | None = None, filename: str | None = None) -> Response:
    extra = dict(headers or {})
    if filename:
        extra["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(filename)}"
    return Response(dsp.to_wav(samples, rate), media_type="audio/wav", headers=extra)


@app.get("/api/voices")
def voices():
    return JSONResponse({"voices": [v.to_dict() for v in state.speaker.voices(refresh=True)],
                         "default": state.speaker.default_voice()})


@app.post("/api/prepare")
def prepare(body: TextBody):
    document = state.speaker.prepare(body.text, ReadingOptions.from_dict(body.options))
    return JSONResponse(document.to_dict())


@app.post("/api/speak")
def speak(body: SpeakBody):
    """Одно предложение -> WAV. Громкость не применяется: её регулирует страница."""
    options = ReadingOptions.raw() if body.raw else ReadingOptions.from_dict(body.options)
    settings = Settings.from_dict(body.settings)
    sentence = state.speaker.sentence(body.text, options, body.heading, body.continued)
    try:
        spoken = state.speaker.synthesize(sentence, settings, phonetic=not body.raw)
    except EngineError as problem:
        raise HTTPException(503, str(problem))
    audio = spoken.audio
    return _wav(audio.samples, audio.rate, {
        "X-Voice": spoken.voice, "X-Fallback": "1" if spoken.fallback else "0",
        "X-Engine-Ms": f"{spoken.engine_ms:.0f}", "X-Cached": "1" if spoken.cached else "0",
        "X-Duration": f"{audio.seconds:.3f}", "Cache-Control": "no-store",
    })


@app.post("/api/render")
def render_file(body: RenderBody):
    """Весь текст одной записью — «Сохранить в файл»."""
    settings = Settings.from_dict(body.settings)
    if settings.voice.startswith("browser:"):
        settings.voice = state.speaker.default_voice()
    try:
        spoken = state.speaker.render(body.text, settings, ReadingOptions.from_dict(body.options))
    except EngineError as problem:
        raise HTTPException(503, str(problem))
    if not len(spoken.audio.samples):
        raise HTTPException(400, "в тексте нечего читать")
    return _wav(spoken.audio.samples, spoken.audio.rate, {"X-Voice": spoken.voice}, wav_name(body.text))


@app.get("/api/say.wav")
def say_wav(text: str = "", voice: str = "", rate: float | None = None):
    """Короткий текст -> WAV, для закладки на чужих страницах.

    Чужая страница просит звук как обычный аудиофайл (элемент <audio>), поэтому
    запрос — GET, а ответ разрешён любому сайту. Настройки — сохранённые на
    «Чтеце».
    """
    text = text.strip()[:2000]
    if not text:
        raise HTTPException(400, "нет текста")
    settings, options = state.reading_settings()
    if voice:
        settings.voice = voice
    if rate:
        settings.rate = min(config.RATE_RANGE[1], max(config.RATE_RANGE[0], rate))
    try:
        spoken = state.speaker.speak(text, settings, options)
    except EngineError as problem:
        raise HTTPException(503, str(problem))
    return _wav(spoken.audio.samples, spoken.audio.rate, {"Access-Control-Allow-Origin": "*",
                                                          "Access-Control-Allow-Private-Network": "true",
                                                          "Cache-Control": "no-store"})


@app.options("/api/say.wav")
def say_preflight():
    return Response(headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET",
                             "Access-Control-Allow-Private-Network": "true", "Access-Control-Allow-Headers": "*"})


@app.post("/api/transcribe")
def transcribe_text(body: TextBody):
    """Как система произносит каждое слово — и как его произнёс бы eSpeak NG."""
    document = state.speaker.prepare(body.text[:3000], ReadingOptions.from_dict(body.options))
    words = []
    for sentence in document.sentences[:40]:
        for token in sentence.tokens:
            if token.kind in {"space", "punct", "quote", "pause"} or not token.say.strip():
                continue
            for word in token.say.replace("-", " ").split():
                clean = word.strip(".,;:!?()")
                if not any(ch.isalpha() for ch in clean):
                    continue
                pron = transcribe(clean)
                words.append({"source": token.text, "word": clean.replace("'", ""), "ipa": pron.ipa(),
                              "espeak_style": to_espeak(pron), "kind": token.kind,
                              "kind_ru": KINDS.get(token.kind, token.kind), "rule": pron.source})
    reference = None
    try:
        if state.speaker.piper.models():
            plain = " ".join(s.render("plain") for s in document.sentences[:40])
            reference = state.speaker.piper.phonemes(plain)
    except EngineError:
        reference = None
    score = []
    if document.sentences:
        score = formant.describe(document.sentences[0].render("say"))
    return JSONResponse({"words": words, "espeak": reference, "score": score})


@app.post("/api/extract")
async def extract(file: UploadFile = File(...)):
    data = await file.read(config.MAX_UPLOAD_BYTES + 1)
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "файл больше 20 МБ")
    try:
        title, text = from_file(file.filename or "text.txt", data)
    except ExtractError as problem:
        raise HTTPException(400, str(problem))
    return JSONResponse({"title": title, "text": text[: config.MAX_TEXT_CHARS],
                         "truncated": len(text) > config.MAX_TEXT_CHARS})


class UrlBody(BaseModel):
    url: str = Field("", max_length=2000)


@app.post("/api/fetch")
def fetch(body: UrlBody):
    try:
        title, text = from_url(body.url)
    except ExtractError as problem:
        raise HTTPException(400, str(problem))
    return JSONResponse({"title": title, "text": text[: config.MAX_TEXT_CHARS],
                         "truncated": len(text) > config.MAX_TEXT_CHARS})


@app.get("/api/articles/{article_id}")
def article_api(article_id: str):
    article = state.collection.get(article_id)
    if article is None:
        raise HTTPException(404, "нет такой статьи")
    return JSONResponse({**article.summary(), "text": article.text})


# --- настройки и другие программы -------------------------------------------------------------

class SettingsBody(BaseModel):
    settings: dict | None = None
    options: dict | None = None


@app.get("/api/settings")
def settings_get():
    settings, options = state.reading_settings()
    return JSONResponse({"settings": settings.to_dict(), "options": options.to_dict()})


@app.post("/api/settings")
def settings_save(body: SettingsBody):
    settings = Settings.from_dict(body.settings)
    options = ReadingOptions.from_dict(body.options)
    state.save_settings(settings, options)
    return JSONResponse({"settings": settings.to_dict(), "options": options.to_dict()})


class DesktopBody(BaseModel):
    clipboard: bool | None = None
    hotkeys: bool | None = None


@app.get("/api/desktop")
def desktop_get():
    return JSONResponse(state.desktop.state.to_dict())


@app.post("/api/desktop")
def desktop_set(body: DesktopBody):
    if not config.DESKTOP_ENABLED:
        raise HTTPException(403, "чтение из других программ выключено при запуске (--no-desktop)")
    if body.clipboard is not None:
        state.desktop.set_clipboard(body.clipboard)
    if body.hotkeys is not None:
        state.desktop.set_hotkeys(body.hotkeys)
    snapshot = state.desktop.state.to_dict()
    state.bus.publish({"type": "desktop", "state": snapshot})
    return JSONResponse(snapshot)


@app.post("/api/stop")
def stop():
    state.on_desktop_stop()
    return JSONResponse({"stopped": True})


@app.get("/api/events")
async def events(request: Request, role: str = "status"):
    """Поток событий для страницы: текст из другой программы, «замолчать», состояние."""
    queue: asyncio.Queue = asyncio.Queue()
    entry = (queue, "reader" if role == "reader" else "status")
    state.bus.listeners.append(entry)

    async def stream():
        try:
            yield f"data: {json.dumps({'type': 'hello', 'state': state.desktop.state.to_dict()})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            if entry in state.bus.listeners:
                state.bus.listeners.remove(entry)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


# --- словарь ------------------------------------------------------------------------------------

class LexiconBody(BaseModel):
    written: str = Field("", max_length=200)
    reading: str = Field("", max_length=300)


def _lexicon() -> dict:
    user = state.speaker.reader.lexicon.user
    return {"entries": [entry.to_dict() for entry in (user.all() if user else [])]}


@app.get("/api/lexicon")
def lexicon_list():
    return JSONResponse(_lexicon())


@app.post("/api/lexicon")
def lexicon_add(body: LexiconBody):
    try:
        state.speaker.reader.lexicon.user.add(body.written, body.reading)
    except LexiconError as problem:
        return JSONResponse({"error": str(problem), **_lexicon()}, status_code=400)
    return JSONResponse(_lexicon())


@app.put("/api/lexicon/{entry_id}")
def lexicon_update(entry_id: str, body: LexiconBody):
    try:
        state.speaker.reader.lexicon.user.update(entry_id, body.written, body.reading)
    except LexiconError as problem:
        return JSONResponse({"error": str(problem), **_lexicon()}, status_code=400)
    return JSONResponse(_lexicon())


@app.delete("/api/lexicon/{entry_id}")
def lexicon_remove(entry_id: str):
    if not state.speaker.reader.lexicon.user.remove(entry_id):
        return JSONResponse({"error": "такого слова в словаре нет", **_lexicon()}, status_code=404)
    return JSONResponse(_lexicon())


# --- «Мой говорящий Пафнутий» -----------------------------------------------------------------

class TalkBody(BaseModel):
    text: str = Field("", max_length=config.MAX_TALK_CHARS * 2)
    emotion: str = Field("neutral", max_length=20)
    mode: str | None = Field(None, max_length=20)


def _companion() -> None:
    if not config.COMPANION_ENABLED:
        raise HTTPException(404, "Пафнутий выключен")


@app.post("/api/talking/say")
def talking_say(body: TalkBody):
    _companion()
    if not body.text.strip():
        raise HTTPException(400, "нечего сказать")
    try:
        wav = state.talking.say(body.text, body.emotion, body.mode)
    except EngineError as problem:
        raise HTTPException(503, str(problem))
    return Response(wav, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@app.post("/api/talking/echo")
async def talking_echo(request: Request, effect: str = "squeak"):
    """Запись игрока (PCM 16 кГц, 16 бит) -> передразнивание."""
    _companion()
    data = await request.body()
    if len(data) < 3200:
        raise HTTPException(400, "запись слишком короткая")
    data = data[: config.MAX_ECHO_SECONDS * 16000 * 2]
    wav = await asyncio.to_thread(state.talking.echo, data, effect)
    return Response(wav, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@app.get("/api/talking/read")
def talking_read():
    """Случайное предложение из статей — Пафнутий читает его вслух в очках."""
    _companion()
    articles = list(state.collection)
    if not articles:
        raise HTTPException(404, "нет статей")
    article = random.choice(articles)
    document = state.speaker.prepare(article.text)
    candidates = [s for s in document.sentences if 40 <= len(s.text) <= 160 and not s.heading]
    sentence = random.choice(candidates or document.sentences)
    return JSONResponse({"text": sentence.text, "say": sentence.render("plain"), "title": article.title})


# --- ошибки --------------------------------------------------------------------------------------

@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, problem: StarletteHTTPException):
    if request.url.path.startswith("/api"):
        return JSONResponse({"error": str(problem.detail)}, status_code=problem.status_code)
    if request.url.path.startswith(("/report", "/static")):
        return PlainTextResponse(str(problem.detail), status_code=problem.status_code)
    return render(request, "message.html", "message", status_code=problem.status_code,
                  title="Страница не найдена" if problem.status_code == 404 else "Ошибка",
                  message=problem.detail)
