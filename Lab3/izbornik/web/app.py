"""Веб-интерфейс «Изборника»: страницы, сохранение в файл, печать, справка.

    /                         тестовая коллекция
    /doc/<id>                 реферат документа коллекции
    /doc/<id>/source          исходный документ с отмеченными предложениями реферата
    /raw/<id>                 исходный текст файлом
    /text                     свой документ: ввод текста или загрузка файла
    /mine/<uid>               реферат своего документа (и /source, /raw)
    /export/<вид>/<id>.<fmt>  сохранение: txt, html, docx, json, scs
    /print/<вид>/<id>         версия для печати
    /evaluation               оценка точности и быстродействия
    /ostis                    состояние интеграции с OSTIS
    /manual                   реферат вручную: человек против системы
    /sweeper                  сапёр с паучатами Пафнутия
    /battle                   бой с Пафнутием (поля букв — /api/battle/grid)
    /help                     справка
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from izbornik import APP_NAME, LAB_NUMBER, VARIANT, VERSION, config, evaluation as ev, export, pafnuty, practice
from izbornik.collection import Collection, detect_language
from izbornik.ostis.connection import ONTOLOGY_FILES, ONTOLOGY_DIR, OstisError
from izbornik.ostis.service import Service
from izbornik.summary import Result, Summary
from izbornik.text.extract import ExtractError, extract
from izbornik.wordgrid import WordBank

log = logging.getLogger("izbornik.web")

EVALUATION_PATH = config.REPORT_DIR / "evaluation.json"
MAX_USER_DOCS = 30
MAX_SENTENCES = 50
ENGINES = {"auto": "автоматически", "ostis": "OSTIS (sc-агент)", "local": "локально"}


# --- состояние приложения ---------------------------------------------------------

@dataclass
class UserDoc:
    uid: str
    title: str
    language: str
    text: str
    filename: str = ""
    created: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))


class State:
    def __init__(self) -> None:
        self.collection = Collection()
        self.ostis = Service(self.collection)
        self.word_bank = WordBank(self.collection)
        self.user_docs: OrderedDict[str, UserDoc] = OrderedDict()
        self.warmup_ms: float | None = None
        self.evaluation: dict | None = None
        self.evaluation_mtime = 0.0
        self.evaluation_running = False
        self.evaluation_error: str | None = None
        self.refresh_evaluation()

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

    def warm_up(self) -> None:
        try:
            self.warmup_ms = self.collection.warm_up()
            log.info("коллекция разобрана за %.0f мс", self.warmup_ms)
        except Exception:  # noqa: BLE001
            log.exception("разбор коллекции не удался")


state = State()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    threading.Thread(target=state.warm_up, name="izbornik-warm-up", daemon=True).start()
    if config.OSTIS_MODE != "off":
        state.ostis.start_in_background()
    yield
    state.ostis.stop()


app = FastAPI(title=f"«{APP_NAME}» — автоматическое реферирование документов", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))


def static_url(name: str) -> str:
    """Адрес статического файла с версией: /static/battle.js?v=….

    Без версии браузер держит старые скрипты в кэше, и после обновления
    страница вызывала бы функции, которых в старом скрипте нет (так было в
    «Толмаче»). Версия — время изменения файла.
    """
    try:
        version = f"{(config.STATIC_DIR / name).stat().st_mtime_ns:x}"
    except OSError:
        return f"/static/{name}"
    return f"/static/{name}?v={version}"


# --- оформление чисел ----------------------------------------------------------------

def _num(value, digits: int = 3) -> str:
    """Число по-русски: запятая в дробной части, тонкий пробел между разрядами."""
    if value is None:
        return "—"
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}".replace(",", " ")
    return f"{float(value):,.{digits}f}".replace(",", " ").replace(".", ",")


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
    return f"{value:.1f}".replace(".", ",") + " мс"


def _duration(seconds) -> str:
    """Сколько писал человек: «48 с», «2 мин 14 с»."""
    if seconds is None:
        return "—"
    seconds = round(float(seconds))
    if seconds < 60:
        return f"{seconds} с"
    minutes, rest = divmod(seconds, 60)
    return f"{minutes} мин {rest} с" if rest else f"{minutes} мин"


templates.env.filters.update(num=_num, pct=_pct, ms=_ms, duration=_duration)
templates.env.globals.update(
    app_name=APP_NAME,
    version=VERSION,
    variant=VARIANT,
    lab_number=LAB_NUMBER,
    config=config,
    language_name=config.language_name,
    domain_name=config.domain_name,
    formats=export.FORMATS,
    engines=ENGINES,
    companion_enabled=config.COMPANION_ENABLED,
    companion_name=config.COMPANION_NAME,
    companion_instrumental=pafnuty.NAME_INSTRUMENTAL,
    companion_genitive=pafnuty.NAME_GENITIVE,
    method_names=ev.METHOD_NAMES,
    static_url=static_url,
)


def render(request: Request, template: str, active: str, status_code: int = 200, **context) -> HTMLResponse:
    status = state.ostis
    context.setdefault("companion_line", pafnuty.line(active) if config.COMPANION_ENABLED else "")
    #: реплика сказана сама, без наведения на паука: вердикт, начало игры
    context.setdefault("companion_speaks", False)
    return templates.TemplateResponse(
        request,
        template,
        {
            "active": active,
            "ostis_state": status.state,
            "ostis_text": Service.STATES.get(status.state, status.state),
            "ostis_available": status.available(),
            **context,
        },
        status_code=status_code,
    )


def render_string(template: str, **context) -> str:
    return templates.get_template(template).render(**context)


# --- получение реферата -------------------------------------------------------------

def _count(n: int | None) -> int:
    if n is None:
        return config.SUMMARY_SENTENCES
    return max(1, min(MAX_SENTENCES, int(n)))


def _engine(value: str | None) -> str:
    return value if value in ENGINES else "auto"


@dataclass
class Page:
    """Реферат и всё, что нужно странице о документе."""

    kind: str                  # doc | mine
    key: str
    title: str
    summary: Summary
    local: Result
    engine: str
    notice: str | None = None
    consistent: bool | None = None
    meta: dict = field(default_factory=dict)

    @property
    def base(self) -> str:
        return f"/doc/{self.key}" if self.kind == "doc" else f"/mine/{self.key}"

    @property
    def source_link(self) -> str:
        return f"{self.base}/source"

    @property
    def raw_link(self) -> str:
        return f"/raw/{self.key}" if self.kind == "doc" else f"/mine/{self.key}/raw"


def _user_doc(uid: str) -> UserDoc:
    doc = state.user_docs.get(uid)
    if doc is None:
        raise HTTPException(404, "Документ не найден — возможно, сервер перезапускался. Загрузите текст ещё раз.")
    return doc


def build_page(kind: str, key: str, count: int, engine: str, force: bool = False) -> Page:
    collection = state.collection
    if kind == "doc":
        entry = collection.get(key)
        if entry is None:
            raise HTTPException(404, f"В коллекции нет документа «{key}»")
        local = collection.summarize(key, count)
        title = entry.title
        meta = {
            "entry": entry,
            "source_site": entry.source.get("site", ""),
            "license": entry.source.get("license", ""),
            "authors": ", ".join(entry.source.get("authors", [])),
        }
    else:
        doc = _user_doc(key)
        local = collection.summarize_text(doc.text, doc.language, doc.title, count, doc_id=key)
        title = doc.title
        meta = {"user_doc": doc, "source_site": "", "license": "", "authors": ""}

    page = Page(kind, key, title, local.summary, local, engine, meta=meta)
    wants_ostis = engine == "ostis" or (engine == "auto" and state.ostis.available())
    if not wants_ostis:
        return page
    if not state.ostis.available():
        page.notice = (f"OSTIS недоступна ({Service.STATES.get(state.ostis.state, state.ostis.state)}), "
                       "реферат построен локально по тем же формулам.")
        return page
    try:
        if kind == "doc":
            summary = state.ostis.summarize_entry(meta["entry"], count, force=force)
        else:
            doc = meta["user_doc"]
            summary = state.ostis.summarize_text(doc.text, doc.language, doc.title, count, doc_id=key)
    except OstisError as problem:
        page.notice = f"Реферат построен локально: {problem}"
        return page
    except Exception as problem:  # noqa: BLE001
        log.exception("ошибка режима OSTIS")
        page.notice = f"Реферат построен локально: ошибка обращения к базе знаний ({type(problem).__name__})."
        return page

    layout = local.document.layout
    for sentence in summary.sentences:
        if 0 <= sentence.index < len(layout.sentences):
            sentence.paragraph = layout.sentences[sentence.index].paragraph
    summary.stats.setdefault("sentences", local.summary.stats.get("sentences"))
    page.summary = summary
    page.consistent = [s.index for s in summary.sentences] == [s.index for s in local.summary.sentences]
    return page


def export_context(request: Request, page: Page, compressed: bool = True) -> export.Context:
    return export.Context(
        source_link=str(request.base_url).rstrip("/") + page.source_link,
        source_site=page.meta.get("source_site", ""),
        license=page.meta.get("license", ""),
        authors=page.meta.get("authors", ""),
        compressed=compressed,
    )


# --- страницы --------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    collection = state.collection
    groups = []
    for language in config.LANGUAGE_CODES:
        for domain in config.DOMAIN_CODES:
            items = [e for e in collection if e.language == language and e.domain == domain]
            groups.append({"language": language, "domain": domain, "entries": items})
    sizes = [e.chars for e in collection]
    return render(request, "index.html", "index", groups=groups, total=len(collection),
                  sizes=sizes, meta=collection.meta, user_docs=list(state.user_docs.values())[::-1])


def _document_view(request: Request, kind: str, key: str, n: int | None, engine: str | None,
                   view: str | None, force: bool = False) -> HTMLResponse:
    count = _count(n)
    page = build_page(kind, key, count, _engine(engine), force=force)
    local = page.local
    scores = sorted(local.scores, key=lambda s: (-s.weight, s.index))[:20]
    return render(
        request, "document.html", "doc" if kind == "doc" else "text",
        page=page, summary=page.summary, count=count, engine=_engine(engine),
        view=view if view in {"compressed", "original"} else "compressed",
        top_terms=local.top_terms(25), top_scores=scores, selected=local.selected,
        layout=local.document.layout,
    )


@app.get("/doc/{doc_id}", response_class=HTMLResponse)
def document(request: Request, doc_id: str, n: int | None = None, engine: str | None = None,
             view: str | None = None):
    return _document_view(request, "doc", doc_id, n, engine, view)


@app.post("/doc/{doc_id}/rebuild")
def rebuild(doc_id: str, n: int = Form(config.SUMMARY_SENTENCES)):
    count = _count(n)
    entry = state.collection.get(doc_id)
    if entry is None:
        raise HTTPException(404)
    if state.ostis.available():
        try:
            state.ostis.summarize_entry(entry, count, force=True)
        except OstisError:
            pass
    return RedirectResponse(f"/doc/{doc_id}?n={count}&engine=ostis", status_code=303)


def _source_view(request: Request, kind: str, key: str, n: int | None) -> HTMLResponse:
    count = _count(n)
    page = build_page(kind, key, count, "local")
    local = page.local
    ranks = local.ranks
    order = {index: position for position, index in enumerate(sorted(local.selected), start=1)}
    weights = {s.index: s for s in local.scores}
    total = max(1, len(local.scores))
    return render(request, "source.html", "source", page=page, count=count, layout=local.document.layout,
                  order=order, ranks=ranks, weights=weights, total=total)


@app.get("/doc/{doc_id}/source", response_class=HTMLResponse)
def document_source(request: Request, doc_id: str, n: int | None = None):
    return _source_view(request, "doc", doc_id, n)


@app.get("/raw/{doc_id}", response_class=PlainTextResponse)
def raw(doc_id: str):
    entry = state.collection.get(doc_id)
    if entry is None:
        raise HTTPException(404)
    return PlainTextResponse(state.collection.text(doc_id), media_type="text/plain; charset=utf-8")


# --- свой документ ---------------------------------------------------------------------

@app.get("/text", response_class=HTMLResponse)
def text_form(request: Request):
    return render(request, "text.html", "text", error=None, form={}, user_docs=list(state.user_docs.values())[::-1])


@app.post("/text", response_class=HTMLResponse)
async def text_submit(
    request: Request,
    text: str = Form(""),
    title: str = Form(""),
    language: str = Form("auto"),
    n: int = Form(config.SUMMARY_SENTENCES),
    upload: UploadFile | None = File(None),
):
    form = {"text": text, "title": title, "language": language, "n": n}
    filename = ""
    try:
        if upload is not None and upload.filename:
            data = await upload.read()
            if len(data) > config.MAX_UPLOAD_SIZE:
                raise ExtractError(f"файл больше {config.MAX_UPLOAD_SIZE // (1024 * 1024)} МиБ")
            filename = upload.filename
            text = extract(filename, data)
        text = (text or "").strip()
        if len(text) < config.MIN_TEXT_CHARS:
            raise ExtractError(f"слишком короткий текст ({len(text)} символов): для реферата нужно хотя бы "
                               f"{config.MIN_TEXT_CHARS}")
    except ExtractError as problem:
        return render(request, "text.html", "text", error=str(problem), form=form,
                      user_docs=list(state.user_docs.values())[::-1])

    code = language if language in config.LANGUAGE_CODES else detect_language(text)
    uid = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
    if not title:
        first = text.strip().split("\n", 1)[0].lstrip("# ").strip()
        title = (filename or first[:80] or "Свой документ")
    state.user_docs[uid] = UserDoc(uid=uid, title=title, language=code, text=text, filename=filename)
    state.user_docs.move_to_end(uid)
    while len(state.user_docs) > MAX_USER_DOCS:
        state.user_docs.popitem(last=False)
    return RedirectResponse(f"/mine/{uid}?n={_count(n)}", status_code=303)


@app.get("/mine/{uid}", response_class=HTMLResponse)
def mine(request: Request, uid: str, n: int | None = None, engine: str | None = None, view: str | None = None):
    return _document_view(request, "mine", uid, n, engine, view)


@app.get("/mine/{uid}/source", response_class=HTMLResponse)
def mine_source(request: Request, uid: str, n: int | None = None):
    return _source_view(request, "mine", uid, n)


@app.get("/mine/{uid}/raw", response_class=PlainTextResponse)
def mine_raw(uid: str):
    return PlainTextResponse(_user_doc(uid).text, media_type="text/plain; charset=utf-8")


# --- сохранение и печать -----------------------------------------------------------------

@app.get("/export/{kind}/{name}")
def export_file(request: Request, kind: str, name: str, n: int | None = None, engine: str | None = None,
                view: str | None = None):
    if kind not in {"doc", "mine"} or "." not in name:
        raise HTTPException(404)
    key, fmt = name.rsplit(".", 1)
    if fmt not in export.FORMATS:
        raise HTTPException(404, f"формат {fmt} не поддерживается")
    page = build_page(kind, key, _count(n), _engine(engine))
    ctx = export_context(request, page, compressed=view != "original")
    data = export.render(page.summary, fmt, ctx, render_string)
    media = export.FORMATS[fmt][1]
    filename = export.filename(page.summary, fmt)
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/print/{kind}/{key}", response_class=HTMLResponse)
def print_view(request: Request, kind: str, key: str, n: int | None = None, engine: str | None = None,
               view: str | None = None):
    if kind not in {"doc", "mine"}:
        raise HTTPException(404)
    page = build_page(kind, key, _count(n), _engine(engine))
    ctx = export_context(request, page, compressed=view != "original")
    return render(request, "print.html", "print", page=page, summary=page.summary, ctx=ctx,
                  generated=datetime.now().strftime("%d.%m.%Y %H:%M"), companion_line="")


# --- оценка ------------------------------------------------------------------------------

def _run_evaluation() -> None:
    try:
        result = ev.run(state.collection, config.SUMMARY_SENTENCES, studies=True)
        data = result.to_dict()
        previous = state.evaluation or {}
        if previous.get("ostis"):
            data["ostis"] = previous["ostis"]
        config.REPORT_DIR.mkdir(parents=True, exist_ok=True)
        EVALUATION_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        state.evaluation = data
        state.evaluation_mtime = EVALUATION_PATH.stat().st_mtime
        state.evaluation_error = None
    except Exception as problem:  # noqa: BLE001
        log.exception("оценка не выполнена")
        state.evaluation_error = f"{type(problem).__name__}: {problem}"
    finally:
        state.evaluation_running = False


@app.get("/evaluation", response_class=HTMLResponse)
def evaluation_page(request: Request):
    images = sorted(p.name for p in config.REPORT_DIR.glob("eval_*.png")) if config.REPORT_DIR.exists() else []
    return render(request, "evaluation.html", "evaluation", data=state.refresh_evaluation(),
                  running=state.evaluation_running, error=state.evaluation_error,
                  methods=ev.METHODS, images=images)


@app.post("/evaluation/run")
def evaluation_run():
    if not state.evaluation_running:
        state.evaluation_running = True
        threading.Thread(target=_run_evaluation, name="izbornik-evaluation", daemon=True).start()
    return RedirectResponse("/evaluation", status_code=303)


@app.get("/report/{name}")
def report_file(name: str):
    path = (config.REPORT_DIR / name).resolve()
    if path.parent != config.REPORT_DIR.resolve() or path.suffix != ".png" or not path.exists():
        raise HTTPException(404)
    return Response(path.read_bytes(), media_type="image/png")


# --- OSTIS -----------------------------------------------------------------------------------

@app.get("/ostis", response_class=HTMLResponse)
def ostis_page(request: Request):
    return render(request, "ostis.html", "ostis", status=state.ostis.status(), files=ONTOLOGY_FILES)


@app.post("/ostis/reconnect")
def ostis_reconnect():
    if state.ostis.mode != "off":
        state.ostis.stop()
        state.ostis.start_in_background()
        time.sleep(0.3)
    return RedirectResponse("/ostis", status_code=303)


@app.get("/kb/{name}", response_class=PlainTextResponse)
def kb_file(name: str):
    if name not in ONTOLOGY_FILES:
        raise HTTPException(404)
    return PlainTextResponse((ONTOLOGY_DIR / name).read_text(encoding="utf-8"),
                             media_type="text/plain; charset=utf-8")


# --- реферат вручную -----------------------------------------------------------------------

#: откуда брать отрывок, если ничего не выбрано: русский текст понятнее большинству
PRACTICE_DEFAULT = "lang:ru"


def _practice_choices() -> list[tuple[str, list[tuple[str, str]]]]:
    """Пункты списка «Откуда отрывок»: случайный документ, документы по группам, свои."""
    groups = [("Случайный документ", [("lang:ru", "случайный русский"), ("lang:de", "случайный немецкий"),
                                      ("any", "случайный на любом языке")])]
    for language in config.LANGUAGE_CODES:
        for domain in config.DOMAIN_CODES:
            entries = [(e.id, e.title) for e in state.collection if e.language == language and e.domain == domain]
            groups.append((f"{config.language_name(language)} · {config.domain_name(domain, short=True)}", entries))
    if state.user_docs:
        groups.append(("Свои документы", [(f"mine:{d.uid}", d.title) for d in reversed(state.user_docs.values())]))
    return groups


def _practice_sources(choice: str) -> list[practice.Source]:
    collection = state.collection
    if choice.startswith("mine:"):
        doc = state.user_docs.get(choice[5:])
        return [practice.Source("mine", doc.uid, doc.title, doc.language, None, doc.text)] if doc else []
    if choice.startswith("lang:"):
        entries = collection.by_language(choice[5:])
    elif choice == "any":
        entries = list(collection)
    else:
        entries = [e for e in collection if e.id == choice]
    return [practice.Source("doc", e.id, e.title, e.language, e.domain, collection.text(e.id)) for e in entries]


def _practice_excerpt(key: str) -> practice.Excerpt:
    parsed = practice.parse_key(key)
    if parsed is None:
        raise HTTPException(404, "Такого отрывка нет.")
    kind, doc_id, first, last = parsed
    sources = _practice_sources(f"mine:{doc_id}" if kind == "mine" else doc_id)
    if not sources:
        raise HTTPException(404, "Документ отрывка не найден — возможно, сервер перезапускался.")
    try:
        return practice.excerpt(sources[0], first, last)
    except ValueError as problem:
        raise HTTPException(404, f"Такого отрывка нет: {problem}.") from None


def _manual_page(request: Request, item: practice.Excerpt | None, choice: str, **context) -> HTMLResponse:
    lo, hi = config.PRACTICE_GOOD_LENGTH
    return render(request, "manual.html", "manual", item=item, choice=choice, choices=_practice_choices(),
                  good_length=(round(lo * item.chars), round(hi * item.chars)) if item else None,
                  result=context.pop("result", None), text=context.pop("text", ""),
                  error=context.pop("error", None), **context)


@app.get("/manual", response_class=HTMLResponse)
def manual(request: Request, source: str = PRACTICE_DEFAULT, key: str | None = None):
    if key:
        item = _practice_excerpt(key)
        choice = f"mine:{item.source.doc_id}" if item.source.kind == "mine" else source
    else:
        choice = source
        item = practice.random_excerpt(_practice_sources(source))
    return _manual_page(request, item, choice)


@app.post("/manual", response_class=HTMLResponse)
def manual_check(request: Request, key: str = Form(...), text: str = Form(""), seconds: str = Form(""),
                 source: str = Form(PRACTICE_DEFAULT)):
    item = _practice_excerpt(key)
    if not text.strip():
        return _manual_page(request, item, source, error="Напишите реферат — хотя бы одно предложение.")
    try:
        elapsed = max(0.0, min(float(seconds), 86_400.0)) if seconds else None
    except ValueError:
        elapsed = None
    result = practice.compare(state.collection, item, text, elapsed)
    line = pafnuty.line(result.verdict.occasion) if config.COMPANION_ENABLED else ""
    return _manual_page(request, item, source, result=result, text=result.text,
                        excerpt_parts=practice.excerpt_parts(result.system),
                        companion_line=line, companion_speaks=bool(line))


# --- игры Пафнутия ---------------------------------------------------------------------------

def _games_allowed() -> None:
    """Сапёр и бой — игры паука: без него их нет."""
    if not config.COMPANION_ENABLED:
        raise HTTPException(404, "Игры Пафнутия выключены вместе с ним (IZBORNIK_COMPANION=0).")


@app.get("/sweeper", response_class=HTMLResponse)
def sweeper(request: Request):
    _games_allowed()
    return render(request, "sweeper.html", "sweeper", lines=pafnuty.client_lines("sweeper"))


@app.get("/battle", response_class=HTMLResponse)
def battle(request: Request):
    _games_allowed()
    return render(request, "battle.html", "battle", lines=pafnuty.client_lines("battle"),
                  grid_rows=config.BATTLE_GRID_ROWS, grid_cols=config.BATTLE_GRID_COLS)


@app.get("/api/battle/grid")
def battle_grid(language: str = "ru", exclude: str = ""):
    """Новое поле букв со спрятанными ключевыми словами реферата одного документа."""
    if not config.COMPANION_ENABLED:
        return JSONResponse({"error": "игры Пафнутия выключены"}, status_code=404)
    if language not in config.LANGUAGE_CODES:
        return JSONResponse({"error": f"язык не поддерживается: {language}"}, status_code=400)
    played = [doc_id for doc_id in exclude.split(",") if doc_id][:len(state.collection)]
    try:
        grid = state.word_bank.grid(language, exclude=played)
    except LookupError as problem:
        return JSONResponse({"error": str(problem)}, status_code=503)
    return JSONResponse(grid.to_dict())


# --- справка ---------------------------------------------------------------------------------

@app.get("/help", response_class=HTMLResponse)
def help_page(request: Request):
    return render(request, "help.html", "help", status=state.ostis.status())


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, problem: StarletteHTTPException):
    if request.url.path.startswith("/api"):
        return JSONResponse({"error": str(problem.detail)}, status_code=problem.status_code)
    if request.url.path.startswith(("/export", "/raw", "/kb", "/report", "/static")):
        return PlainTextResponse(str(problem.detail), status_code=problem.status_code)
    return render(request, "message.html", "message", status_code=problem.status_code,
                  title="Страница не найдена" if problem.status_code == 404 else "Ошибка",
                  message=problem.detail)
