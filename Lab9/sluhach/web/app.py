"""Веб-интерфейс «Слухача»: страницы, поток звука, реакция на фразы.

    /                     пульт: микрофон, распознавание, сочинения, журнал
    /ws/listen            звук с микрофона -> события распознавания (WebSocket)
    /api/react            распознанная фраза -> реакция системы
    /api/essay/<id>       сочинение целиком
    /api/dictations/<id>  удаление надиктованного сочинения
    /api/status           состояние распознавателя
    /operations           список операций: какие включены и на какие фразы откликаются
    /evaluation           проверка распознавания на озвученных фразах и своим голосом
    /api/selftest/…       фразы для чтения вслух и оценка прочитанного
    /walk                 прогулка с Пафнутием
    /help                 справка
    /admin                вход администратора (открывает его окно на пульте)
    /api/admin/…          вход и выход администратора
    /api/eggs…            фразы-пасхалки (только администратор)
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from sluhach import APP_NAME, LAB_NUMBER, VARIANT, VERSION, admin, config, dictation, evaluation as ev, pafnuty
from sluhach import selftest
from sluhach.eggs import EggError, EggStore
from sluhach.essays import Collection
from sluhach.listener import MARGIN_RANGE, PAUSE_RANGE, Listener
from sluhach.operations import DEFAULTS, GROUPS, OperationSet
from sluhach.reactions import Reactor, Session
from sluhach.recognizer import VoskEngine

log = logging.getLogger("sluhach.web")

EVALUATION_PATH = config.REPORT_DIR / "evaluation.json"
#: самый большой кусок звука в одном сообщении: две секунды
MAX_AUDIO_BYTES = 4 * config.SAMPLE_RATE


# --- состояние приложения ---------------------------------------------------------

class State:
    def __init__(self) -> None:
        #: сочинения каталога — по ним строится словарь заглавных букв и набор проверочных фраз
        self.catalog = Collection()
        #: всё, с чем работают операции: каталог и надиктованные сочинения
        self.collection = Collection()
        self.dictations = dictation.Dictations(self.collection)
        self.operations = OperationSet()
        self.eggs = EggStore()
        self.reactor = Reactor(self.collection, self.operations, self.eggs, self.dictations,
                               dictation.Lexicon(self.catalog))
        self.engine = VoskEngine()
        self.admin = admin.Admin()
        self.evaluation: dict | None = None
        self.evaluation_mtime = 0.0
        self._selftest: tuple[Reactor, dict] | None = None

    def selftest(self) -> tuple[Reactor, dict]:
        """Система с операциями по умолчанию и фразы для проверки своим голосом.

        Как и проверка на озвученных фразах, она не зависит от того, что
        пользователь переименовал, выключил или надиктовал.
        """
        if self._selftest is None:
            self._selftest = (ev.default_reactor(self.catalog), selftest.table(self.catalog))
        return self._selftest

    def refresh_evaluation(self) -> dict | None:
        """Перечитывает report/evaluation.json, если его обновил tools/evaluate.py."""
        try:
            mtime = EVALUATION_PATH.stat().st_mtime
        except OSError:
            return self.evaluation
        if mtime > self.evaluation_mtime:
            self.evaluation = ev.load(EVALUATION_PATH)
            self.evaluation_mtime = mtime
        return self.evaluation


state = State()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # модели загружаются заранее, чтобы первая фраза не ждала
    state.engine.start_in_background()
    yield


app = FastAPI(title=f"«{APP_NAME}» — распознавание речи и голосовое управление", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))


def static_url(name: str) -> str:
    """Адрес статического файла с версией: /static/walk.js?v=….

    Без версии браузер держит старые сценарии в кэше, и после обновления
    страница вызывала бы функции, которых в старом сценарии нет. Версия —
    время изменения файла.
    """
    try:
        version = f"{(config.STATIC_DIR / name).stat().st_mtime_ns:x}"
    except OSError:
        return f"/static/{name}"
    return f"/static/{name}?v={version}"


def client_config() -> dict:
    """То, что нужно сценариям любой страницы."""
    return {"worklet": static_url("capture-worklet.js"), "companion": config.COMPANION_ENABLED,
            "eggKeyLimit": config.MAX_EGG_KEY_CHARS, "eggAnswerLimit": config.MAX_EGG_ANSWER_CHARS}


# --- оформление чисел ----------------------------------------------------------------

def _num(value, digits: int = 3) -> str:
    """Число по-русски: запятая в дробной части, пробел между разрядами."""
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
    app_name=APP_NAME,
    version=VERSION,
    variant=VARIANT,
    lab_number=LAB_NUMBER,
    config=config,
    language_name=config.language_name,
    companion_enabled=config.COMPANION_ENABLED,
    companion_name=config.COMPANION_NAME,
    companion_instrumental=pafnuty.NAME_INSTRUMENTAL,
    companion_genitive=pafnuty.NAME_GENITIVE,
    static_url=static_url,
    client_config=client_config,
)


def is_admin(request: Request) -> bool:
    """Вошёл ли в этом браузере администратор."""
    return state.admin.check(request.cookies.get(admin.COOKIE))


def render(request: Request, template: str, active: str, status_code: int = 200, **context) -> HTMLResponse:
    context.setdefault("companion_line", pafnuty.line(active) if config.COMPANION_ENABLED else "")
    #: реплика сказана сама, без наведения на паука
    context.setdefault("companion_speaks", False)
    #: администратору страница показывает вход в тайник; сами пасхалки отдаёт только /api/eggs
    context.setdefault("is_admin", is_admin(request))
    return templates.TemplateResponse(request, template, {"active": active, **context}, status_code=status_code)


# --- пульт -------------------------------------------------------------------------------

def console_boot() -> dict:
    """Всё, с чего страница пульта начинает работу."""
    codes = config.LANGUAGE_CODES
    return {
        "language": config.DEFAULT_LANGUAGE,
        "languages": {code: {"name": config.language_name(code), "own": config.LANGUAGES[code][1],
                             "tag": config.language_tag(code)} for code in codes},
        "engine": config.DEFAULT_ENGINE,
        "engines": config.ENGINES,
        "status": state.engine.status(),
        "essays": {code: [essay.summary() for essay in state.collection.by_language(code)] for code in codes},
        "cheatsheet": {code: state.operations.cheatsheet(code) for code in codes},
        "examples": {code: {"open": state.operations.example("open", code),
                            "dictate": state.operations.example("dictate", code)} for code in codes},
        "groups": GROUPS,
        "vad": {"margin": config.VAD_START_MARGIN_DB, "pause": config.VAD_END_SILENCE_MS,
                "marginRange": list(MARGIN_RANGE), "pauseRange": list(PAUSE_RANGE)},
        "threshold": config.MATCH_THRESHOLD,
        "voice": config.COMPANION_NAME if config.COMPANION_ENABLED else "Система",
        "dictation": {"spoken": {code: [list(pair) for pair in dictation.SPOKEN[code]] for code in codes},
                      "limit": config.MAX_DRAFT_CHARS, "titleLimit": config.MAX_TITLE_CHARS},
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return render(request, "index.html", "console", boot=console_boot(), status=state.engine.status(),
                  essays_total=len(state.collection), operations_total=len(state.operations.entries()))


class Phrase(BaseModel):
    text: str = Field("", max_length=config.MAX_DICTATED_PHRASE_CHARS)
    session: dict | None = None
    source: str = Field("", max_length=20)
    confidence: float | None = None
    #: операция, вызванная кнопкой страницы («Диктовать», «Закончить и сохранить»), без фразы
    action: str = Field("", max_length=30)


@app.post("/api/react")
def react(phrase: Phrase):
    """Реакция системы на распознанную (или введённую) фразу."""
    session = Session.from_dict(phrase.session, state.collection)
    return JSONResponse(state.reactor.react(phrase.text, session, action=phrase.action).to_dict())


@app.get("/api/essay/{essay_id}")
def essay(essay_id: str):
    found = state.collection.get(essay_id)
    if found is None:
        raise HTTPException(404, f"нет сочинения «{essay_id}»")
    return JSONResponse(found.content())


@app.delete("/api/dictations/{essay_id}")
def dictation_remove(essay_id: str):
    """Удаляет надиктованное сочинение; сочинения каталога так не удалить."""
    removed = state.dictations.remove(essay_id)
    if removed is None:
        raise HTTPException(404, "такого надиктованного сочинения нет")
    return JSONResponse({"language": removed.language,
                         "essays": [item.summary() for item in state.collection.by_language(removed.language)]})


@app.get("/api/status")
def status():
    return JSONResponse(state.engine.status())


@app.websocket("/ws/listen")
async def listen(websocket: WebSocket):
    """Звук с микрофона: двоичные сообщения — PCM 16 кГц, текстовые — управление.

    Распознавание занимает процессор, поэтому идёт в отдельном потоке: цикл
    событий сервера остаётся свободен для других запросов.
    """
    await websocket.accept()
    listener = Listener(state.engine, config.DEFAULT_LANGUAGE)
    muted = False
    await websocket.send_json({"type": "hello", "rate": config.SAMPLE_RATE, "status": state.engine.status()})
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            data = message.get("bytes")
            if data is not None:
                if muted or len(data) > MAX_AUDIO_BYTES:
                    continue
                for event in await asyncio.to_thread(listener.feed, data):
                    await websocket.send_json(event)
                continue
            try:
                control = json.loads(message.get("text") or "{}")
            except ValueError:
                continue
            kind = control.get("type") if isinstance(control, dict) else None
            if kind == "language" and control.get("code") in config.LANGUAGES:
                listener.set_language(control["code"])
                await websocket.send_json({"type": "language", "code": listener.language,
                                           "state": state.engine.state(listener.language)})
            elif kind == "mute":
                # система заговорила сама: начатая фраза бросается, звук не слушается
                muted = bool(control.get("on"))
                listener.reset()
            elif kind == "config":
                try:
                    listener.configure(control.get("margin"), control.get("pause"))
                except (TypeError, ValueError):
                    pass
    except (WebSocketDisconnect, RuntimeError):
        pass


# --- операции ----------------------------------------------------------------------------

def _operations_page(request: Request, **context) -> HTMLResponse:
    entries = state.operations.entries()
    return render(request, "operations.html", "operations", entries=entries, groups=GROUPS,
                  enabled=sum(1 for entry in entries if entry.enabled), **context)


@app.get("/operations", response_class=HTMLResponse)
def operations_page(request: Request, saved: int = 0, reset: int = 0):
    return _operations_page(request, errors=[], form=None, saved=bool(saved), was_reset=bool(reset))


@app.post("/operations", response_class=HTMLResponse)
async def operations_save(request: Request):
    """Задание списка операций: какие включены и на какие фразы откликаются."""
    form = await request.form()
    changes = {}
    for entry in state.operations.entries():
        ident = entry.operation.id
        changes[ident] = {
            "enabled": form.get(f"enabled-{ident}") is not None,
            "phrases": {language: str(form.get(f"phrases-{ident}-{language}", "")).splitlines()
                        for language in config.LANGUAGE_CODES},
        }
    errors = state.operations.update(changes)
    if errors:
        return _operations_page(request, errors=errors, form=changes, saved=False, was_reset=False)
    return RedirectResponse("/operations?saved=1", status_code=303)


@app.post("/operations/reset")
def operations_reset():
    state.operations.reset()
    return RedirectResponse("/operations?reset=1", status_code=303)


# --- проверка ------------------------------------------------------------------------------

@app.get("/evaluation", response_class=HTMLResponse)
def evaluation_page(request: Request):
    images = sorted(p.name for p in config.REPORT_DIR.glob("eval_*.png")) if config.REPORT_DIR.exists() else []
    codes = config.LANGUAGE_CODES
    boot = {
        "language": config.DEFAULT_LANGUAGE,
        "languages": {code: {"name": config.language_name(code), "own": config.LANGUAGES[code][1]} for code in codes},
        "status": state.engine.status(),
        "pause": selftest.PAUSE_MS,
        "lines": pafnuty.client_lines("selftest") if config.COMPANION_ENABLED else {},
    }
    return render(request, "evaluation.html", "evaluation", data=state.refresh_evaluation(), images=images,
                  operations=DEFAULTS, selftest=selftest, selftest_boot=boot)


class Readings(BaseModel):
    #: прочитанные фразы: [{id, heard}]
    items: list[dict] = Field(default_factory=list, max_length=40)


@app.get("/api/selftest/phrases")
def selftest_phrases(language: str = config.DEFAULT_LANGUAGE, seed: int | None = None):
    """Набор фраз для чтения вслух; с `seed` — всегда один и тот же."""
    if language not in config.LANGUAGES:
        raise HTTPException(400, "нет такого языка")
    _reactor, phrases = state.selftest()
    return JSONResponse({"language": language,
                         "phrases": [selftest.describe(phrase) for phrase in selftest.pick(phrases, language, seed)]})


@app.post("/api/selftest/score")
def selftest_score(body: Readings):
    """Оценка прочитанного: ошибки по словам и реакция системы на каждую фразу."""
    reactor, phrases = state.selftest()
    return JSONResponse(selftest.score(reactor, state.catalog, phrases, body.items, state.refresh_evaluation()))


@app.get("/report/{name}")
def report_file(name: str):
    path = (config.REPORT_DIR / name).resolve()
    if path.parent != config.REPORT_DIR.resolve() or path.suffix != ".png" or not path.exists():
        raise HTTPException(404)
    return Response(path.read_bytes(), media_type="image/png")


# --- администратор и пасхалки ----------------------------------------------------------------

class Credentials(BaseModel):
    login: str = Field("", max_length=100)
    password: str = Field("", max_length=200)


class EggBody(BaseModel):
    key: str = Field("", max_length=1000)
    answer: str = Field("", max_length=2000)


class Probe(BaseModel):
    text: str = Field("", max_length=1000)


def _require_admin(request: Request) -> None:
    if not is_admin(request):
        raise HTTPException(401, "нужен вход администратора")


def _eggs() -> dict:
    return {"eggs": [egg.to_dict() for egg in state.eggs.all()]}


@app.get("/admin")
def admin_page():
    """Короткий адрес входа: открывает пульт с окном администратора."""
    return RedirectResponse("/#admin", status_code=303)


@app.get("/api/admin/state")
def admin_state(request: Request):
    return JSONResponse({"admin": is_admin(request)})


@app.post("/api/admin/login")
def admin_login(body: Credentials):
    try:
        token = state.admin.login(body.login, body.password)
    except admin.AdminError as problem:
        return JSONResponse({"error": str(problem)}, status_code=403)
    response = JSONResponse(_eggs())
    # cookie недоступна сценариям страницы и не уходит на чужие сайты
    response.set_cookie(admin.COOKIE, token, max_age=config.ADMIN_SESSION_HOURS * 3600, httponly=True,
                        samesite="strict", path="/")
    return response


@app.post("/api/admin/logout")
def admin_logout(request: Request):
    state.admin.logout(request.cookies.get(admin.COOKIE))
    response = JSONResponse({"admin": False})
    response.delete_cookie(admin.COOKIE, path="/")
    return response


@app.get("/api/eggs")
def eggs_list(request: Request):
    _require_admin(request)
    return JSONResponse(_eggs())


@app.post("/api/eggs")
def eggs_add(request: Request, body: EggBody):
    _require_admin(request)
    try:
        state.eggs.add(body.key, body.answer)
    except EggError as problem:
        return JSONResponse({"error": str(problem), **_eggs()}, status_code=400)
    return JSONResponse(_eggs())


@app.put("/api/eggs/{egg_id}")
def eggs_update(request: Request, egg_id: str, body: EggBody):
    _require_admin(request)
    try:
        state.eggs.update(egg_id, body.key, body.answer)
    except EggError as problem:
        return JSONResponse({"error": str(problem), **_eggs()}, status_code=400)
    return JSONResponse(_eggs())


@app.delete("/api/eggs/{egg_id}")
def eggs_remove(request: Request, egg_id: str):
    _require_admin(request)
    if not state.eggs.remove(egg_id):
        return JSONResponse({"error": "такой пасхалки нет", **_eggs()}, status_code=404)
    return JSONResponse(_eggs())


@app.post("/api/eggs/test")
def eggs_test(request: Request, body: Probe):
    """Проверка: какая пасхалка сработает на фразу — чтобы не говорить её в микрофон."""
    _require_admin(request)
    found = state.eggs.match(body.text)
    if found is None:
        return JSONResponse({"match": None})
    return JSONResponse({"match": found[0].to_dict(), "score": round(found[1], 3)})


# --- прогулка с Пафнутием ----------------------------------------------------------------------

@app.get("/walk", response_class=HTMLResponse)
def walk(request: Request):
    if not config.COMPANION_ENABLED:
        raise HTTPException(404, "Прогулка выключена вместе с Пафнутием (SLUHACH_COMPANION=0).")
    return render(request, "walk.html", "walk", lines=pafnuty.client_lines("walk"))


# --- справка -----------------------------------------------------------------------------------

@app.get("/help", response_class=HTMLResponse)
def help_page(request: Request):
    return render(request, "help.html", "help", status=state.engine.status(), groups=GROUPS,
                  entries=state.operations.entries())


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, problem: StarletteHTTPException):
    if request.url.path.startswith("/api"):
        return JSONResponse({"error": str(problem.detail)}, status_code=problem.status_code)
    if request.url.path.startswith(("/report", "/static")):
        return PlainTextResponse(str(problem.detail), status_code=problem.status_code)
    return render(request, "message.html", "message", status_code=problem.status_code,
                  title="Страница не найдена" if problem.status_code == 404 else "Ошибка",
                  message=problem.detail)
