"""Веб-интерфейс «Драгомана».

    /                         перевод текста: ввод, файл, документ коллекции
    /t/<uid>                  результат: перевод, статистика, вкладки 1–3
    /doc/<id>                 перевод документа коллекции
    /collection               тестовая коллекция
    /dictionary               словарь: поиск, правка, добавление
    /dictionary/replenish     пополнение словаря: неизвестные слова и догадки
    /export/<uid>.txt         сохранение в TXT (Unicode)
    /print/<uid>              версия для печати
    /evaluation               оценка качества перевода и анализатора
    /shooter                  тир Пафнутия (план волн — /api/shooter/plan)
    /help                     справка
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from dragoman import APP_NAME, LAB_NUMBER, VARIANT, VERSION, config, export, game, pafnuty, trees
from dragoman.collection import Collection
from dragoman.english import tags as tagset
from dragoman.german import morphology as gm
from dragoman.lexicon import db, ding, guess
from dragoman.lexicon.db import COLUMNS, POS_NAMES, SOURCES, Entry, clean
from dragoman.text.extract import ExtractError, extract
from dragoman.translate import output
from dragoman.translate.pipeline import STATUS_NAMES, Translation, Translator, german_grammar

log = logging.getLogger("dragoman.web")

EVALUATION_PATH = config.REPORT_DIR / "evaluation.json"
ANALYZER_PATH = config.REPORT_DIR / "analyzer.json"
MAX_TRANSLATIONS = 40


class State:
    def __init__(self) -> None:
        self.collection = Collection()
        self._translator: Translator | None = None
        self.translations: OrderedDict[str, Translation] = OrderedDict()
        self.lock = threading.Lock()
        self.ready = False
        self.warmup_ms: float | None = None
        self.evaluation_running = False
        self.evaluation_error: str | None = None
        self.ding_status = ""

    @property
    def translator(self) -> Translator:
        if self._translator is None:
            self._translator = Translator(db.get())
        return self._translator

    @property
    def lexicon(self) -> db.Lexicon:
        return self.translator.lexicon

    def keep(self, translation: Translation) -> Translation:
        with self.lock:
            self.translations[translation.uid] = translation
            self.translations.move_to_end(translation.uid)
            while len(self.translations) > MAX_TRANSLATIONS:
                self.translations.popitem(last=False)
        return translation

    def warm_up(self) -> None:
        started = time.perf_counter()
        try:
            self.translator.translate("The compiler translates the program.", log_unknown=False)
            self.ready = True
            self.warmup_ms = 1000 * (time.perf_counter() - started)
            log.info("модели загружены за %.0f мс", self.warmup_ms)
        except Exception:  # noqa: BLE001
            log.exception("модели не загрузились")


state = State()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    threading.Thread(target=state.warm_up, name="dragoman-warm-up", daemon=True).start()
    yield


app = FastAPI(title=f"«{APP_NAME}» — машинный перевод", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))


def static_url(name: str) -> str:
    """Адрес статического файла с версией — браузер не держит старый скрипт в кэше."""
    try:
        version = f"{(config.STATIC_DIR / name).stat().st_mtime_ns:x}"
    except OSError:
        return f"/static/{name}"
    return f"/static/{name}?v={version}"


def _num(value, digits: int = 3) -> str:
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
    return f"{value:.1f}".replace(".", ",") + " мс"


templates.env.filters.update(num=_num, pct=_pct, ms=_ms)
templates.env.globals.update(
    app_name=APP_NAME, version=VERSION, variant=VARIANT, lab_number=LAB_NUMBER, config=config,
    domain_name=config.domain_name, modes=config.MODES, pos_names=POS_NAMES, sources=SOURCES,
    status_names=STATUS_NAMES, describe_tag=tagset.describe, describe_deprel=tagset.describe_deprel,
    upos_names=tagset.UPOS_NAMES, companion_enabled=config.COMPANION_ENABLED,
    companion_name=config.COMPANION_NAME, companion_instrumental=pafnuty.NAME_INSTRUMENTAL,
    companion_genitive=pafnuty.NAME_GENITIVE, static_url=static_url, encodings=export.ENCODINGS,
    export_parts=export.PARTS, phrase_names=trees.PHRASE_NAMES, gender_names=gm.GENDER_NAMES,
)


def render(request: Request, template: str, active: str, status_code: int = 200, **context) -> HTMLResponse:
    context.setdefault("companion_line", pafnuty.line(active) if config.COMPANION_ENABLED else "")
    context.setdefault("companion_speaks", False)
    return templates.TemplateResponse(request, template, {"active": active, "ready": state.ready, **context},
                                      status_code=status_code)


def _translation(uid: str) -> Translation:
    translation = state.translations.get(uid)
    if translation is None:
        raise HTTPException(404, "Перевод не найден — возможно, сервер перезапускался. Переведите текст ещё раз.")
    return translation


# --- главная: перевод ------------------------------------------------------------------------

EXAMPLE = ("A compiler is a program that translates source code written in a high-level programming language "
           "into machine code. In this paper, we present a new method that does not require a dictionary.")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    recent = list(state.translations.values())[::-1][:8]
    return render(request, "index.html", "index", form={"text": "", "domain": "auto", "mode": config.DEFAULT_MODE},
                  error=None, recent=recent, documents=list(state.collection), example=EXAMPLE,
                  lexicon_total=state.lexicon.stats()["total"])


@app.post("/translate")
async def translate(request: Request, text: str = Form(""), title: str = Form(""), domain: str = Form("auto"),
                    mode: str = Form(config.DEFAULT_MODE), document: str = Form(""),
                    upload: UploadFile | None = File(None)):
    form = {"text": text, "title": title, "domain": domain, "mode": mode}
    source = ""
    try:
        if document:
            entry = state.collection.get(document)
            if entry is None:
                raise ExtractError("такого документа в коллекции нет")
            return RedirectResponse(f"/doc/{entry.id}?mode={mode}", status_code=303)
        if upload is not None and upload.filename:
            data = await upload.read()
            if len(data) > config.MAX_UPLOAD_SIZE:
                raise ExtractError(f"файл больше {config.MAX_UPLOAD_SIZE // (1024 * 1024)} МиБ")
            text = extract(upload.filename, data)
            title = title or upload.filename
            source = f"файл {upload.filename}"
        text = (text or "").strip()
        if not text:
            raise ExtractError("введите английский текст или выберите файл")
        if len(text) > config.MAX_TEXT_CHARS:
            raise ExtractError(f"текст длиннее {config.MAX_TEXT_CHARS:,} знаков — разделите его на части".replace(",", " "))
        if not any(ch.isascii() and ch.isalpha() for ch in text):
            raise ExtractError("в тексте нет латинских букв — система переводит с английского")
    except ExtractError as problem:
        recent = list(state.translations.values())[::-1][:8]
        return render(request, "index.html", "index", form=form, error=str(problem), recent=recent,
                      documents=list(state.collection), example=EXAMPLE, status_code=400,
                      lexicon_total=state.lexicon.stats()["total"])
    translation = state.translator.translate(text, title, domain, mode, source=source)
    state.keep(translation)
    return RedirectResponse(f"/t/{translation.uid}", status_code=303)


@app.get("/doc/{doc_id}")
def document(doc_id: str, mode: str = config.DEFAULT_MODE):
    entry = state.collection.get(doc_id)
    if entry is None:
        raise HTTPException(404, f"В коллекции нет документа «{doc_id}»")
    translation = state.translator.translate(state.collection.text(doc_id), entry.title, entry.domain, mode,
                                             source=entry.source_url)
    state.keep(translation)
    return RedirectResponse(f"/t/{translation.uid}", status_code=303)


@app.get("/raw/{doc_id}", response_class=PlainTextResponse)
def raw(doc_id: str):
    if state.collection.get(doc_id) is None:
        raise HTTPException(404)
    return PlainTextResponse(state.collection.text(doc_id), media_type="text/plain; charset=utf-8")


def _sentence_view(t: Translation, index: int) -> dict:
    index = max(0, min(index, len(t.sentences) - 1))
    english = t.analysis.sentences[index]
    german = t.sentences[index]
    return {
        "index": index,
        "english": english,
        "german": german,
        "dependency": trees.dependency_svg(english),
        "constituency": trees.constituency_svg(english),
        "pieces": output.spans(german.tokens),
        "status": t.statuses[index],
    }


@app.get("/t/{uid}", response_class=HTMLResponse)
def result(request: Request, uid: str, s: int = 0, tab: str = "words", sort: str = "freq"):
    t = _translation(uid)
    other_mode = "direct" if t.mode == "transfer" else "transfer"
    comparison = state.translator.translate(t.text, t.title, t.domain if not t.domain_auto else "auto", other_mode,
                                            log_unknown=False, source=t.source)
    words = t.words
    if sort == "alpha":
        words = sorted(words, key=lambda w: w.lemma.lower())
    elif sort == "pos":
        words = sorted(words, key=lambda w: (w.pos, -w.count, w.lemma.lower()))
    entry_doc = next((e for e in state.collection if e.source_url and e.source_url == t.source), None)
    return render(request, "result.html", "result", t=t, comparison=comparison, words=words, sort=sort,
                  tab=tab if tab in {"words", "tree", "compare", "unknown"} else "words",
                  view=_sentence_view(t, s), output=output, doc=entry_doc,
                  suggestions=_suggestions(t.stats["unknown_words"], t))


def _suggestions(words: list[str], t: Translation | None = None) -> list[dict]:
    """Неизвестные слова и догадки о переводе: правила словообразования и словарь Ding."""
    lexicon = state.lexicon
    result = []
    for word_ in words[:200]:
        pos = "NOUN"
        if t is not None:
            item = next((w for w in t.words if w.lemma == word_), None)
            if item is not None:
                pos = item.pos if item.pos in POS_NAMES else "NOUN"
        candidates = []
        rule = guess.guess(word_, pos, lexicon, t.domain if t else None)
        if rule is not None:
            candidates.append(rule)
        candidates += ding.suggest(word_, pos)[:3]
        result.append({"en": word_, "pos": pos, "candidates": candidates})
    return result


@app.get("/t/{uid}/tree", response_class=HTMLResponse)
def tree_fragment(request: Request, uid: str, s: int = 0):
    t = _translation(uid)
    return templates.TemplateResponse(request, "tree.html", {"t": t, "view": _sentence_view(t, s), "output": output})


# --- сохранение и печать ---------------------------------------------------------------------------

@app.get("/export/{name}")
def export_file(name: str, enc: str = "utf-16", parts: str = "all", source: int = 1):
    if not name.endswith(".txt"):
        raise HTTPException(404)
    t = _translation(name[:-4])
    text = export.render_text(t, parts if parts in export.PARTS else "all", with_source=bool(source))
    data = export.encode(text, enc)
    charset = "utf-16" if enc == "utf-16" else "utf-8"
    filename = export.filename(t, enc)
    return Response(data, media_type=f"text/plain; charset={charset}",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_quote(filename)}"})


def _quote(text: str) -> str:
    from urllib.parse import quote

    return quote(text)


@app.get("/print/{uid}", response_class=HTMLResponse)
def print_view(request: Request, uid: str, parts: str = "all"):
    t = _translation(uid)
    return render(request, "print.html", "print", t=t, parts=parts if parts in export.PARTS else "all",
                  companion_line="")


# --- коллекция -------------------------------------------------------------------------------

@app.get("/collection", response_class=HTMLResponse)
def collection_page(request: Request):
    groups = [(code, [e for e in state.collection if e.domain == code]) for code in config.DOMAIN_CODES]
    return render(request, "collection.html", "collection", groups=groups, total=len(state.collection))


# --- словарь ------------------------------------------------------------------------------------

@app.get("/dictionary", response_class=HTMLResponse)
def dictionary(request: Request, q: str = "", pos: str = "", source: str = "", domain: str = "", page: int = 1,
               edit: int | None = None, message: str = ""):
    page = max(1, page)
    per_page = 60
    entries, total = state.lexicon.search(q, pos, source, domain, per_page, (page - 1) * per_page)
    editing = state.lexicon.get(edit) if edit else None
    return render(request, "dictionary.html", "dictionary", entries=entries, total=total, q=q, pos=pos,
                  source=source, domain=domain, page=page, pages=max(1, (total + per_page - 1) // per_page),
                  editing=editing, stats=state.lexicon.stats(), message=message, grammar=german_grammar)


def _entry_from_form(en: str, pos: str, de: str, gender: str, plural: str, extra: str, domain: str) -> Entry:
    en, de = en.strip(), de.strip()
    if not en or not de:
        raise HTTPException(400, "Нужны английское слово и немецкий перевод.")
    if pos not in POS_NAMES:
        raise HTTPException(400, f"Неизвестная часть речи: {pos}")
    if pos in {"NOUN", "PROPN"} and gender not in {"m", "f", "n", "pl"}:
        raise HTTPException(400, "У существительного должен быть указан род: m, f, n или pl.")
    return Entry(en, pos, de, gender if pos in {"NOUN", "PROPN", "NUM"} else "", plural.strip(), extra.strip(),
                 domain if domain in config.DOMAIN_CODES else config.GENERAL_DOMAIN)


@app.post("/dictionary/add")
def dictionary_add(en: str = Form(...), pos: str = Form(...), de: str = Form(...), gender: str = Form(""),
                   plural: str = Form(""), extra: str = Form(""), domain: str = Form("gen"), back: str = Form(""),
                   source: str = Form("user")):
    entry = _entry_from_form(en, pos, de, gender, plural, extra, domain)
    added = state.lexicon.add(entry, source=source if source in SOURCES else "user")
    target = back or f"/dictionary?q={entry.en}"
    separator = "&" if "?" in target else "?"
    return RedirectResponse(f"{target}{separator}message=добавлено: {added.en} → {clean(added.de)}", status_code=303)


@app.post("/dictionary/{entry_id}/edit")
def dictionary_edit(entry_id: int, en: str = Form(...), pos: str = Form(...), de: str = Form(...),
                    gender: str = Form(""), plural: str = Form(""), extra: str = Form(""), domain: str = Form("gen")):
    entry = _entry_from_form(en, pos, de, gender, plural, extra, domain)
    values = {k: getattr(entry, k) for k in COLUMNS}
    updated = state.lexicon.update(entry_id, values)
    if updated is None:
        raise HTTPException(404, "Записи нет")
    return RedirectResponse(f"/dictionary?q={updated.en}&message=исправлено: {updated.en}", status_code=303)


@app.post("/dictionary/{entry_id}/delete")
def dictionary_delete(entry_id: int, q: str = Form("")):
    if not state.lexicon.delete(entry_id):
        raise HTTPException(404, "Записи нет")
    return RedirectResponse(f"/dictionary?q={q}&message=запись удалена", status_code=303)


@app.get("/dictionary/replenish", response_class=HTMLResponse)
def replenish(request: Request, message: str = ""):
    # слова, которые уже появились в словаре (добавлены вручную или обновлением таблиц), в журнале не нужны
    unknown = [item for item in state.lexicon.unknown(300) if not state.lexicon.knows(item["en"])][:200]
    suggestions = []
    for item in unknown:
        pos = item["pos"] if item["pos"] in POS_NAMES else "NOUN"
        candidates = []
        rule = guess.guess(item["en"], pos, state.lexicon)
        if rule is not None:
            candidates.append(rule)
        candidates += ding.suggest(item["en"], pos)[:3]
        suggestions.append({**item, "pos": pos, "candidates": candidates})
    return render(request, "replenish.html", "dictionary", suggestions=suggestions, message=message,
                  ding_ready=ding.available(), ding_status=state.ding_status, stats=state.lexicon.stats())


@app.post("/dictionary/auto")
def dictionary_auto(threshold: float = Form(0.75)):
    """Автоматическое пополнение: уверенные догадки по правилам и записи Ding — в словарь."""
    added = 0
    for item in state.lexicon.unknown(500):
        if state.lexicon.knows(item["en"]):
            continue
        pos = item["pos"] if item["pos"] in POS_NAMES else "NOUN"
        rule = guess.guess(item["en"], pos, state.lexicon)
        candidate = rule if rule is not None and rule.confidence >= threshold else None
        if candidate is None:
            options = ding.suggest(item["en"], pos)
            candidate = options[0] if options and options[0].confidence >= threshold else None
        if candidate is None:
            continue
        candidate.en = item["en"]
        state.lexicon.add(candidate, source=candidate.source)
        added += 1
    return RedirectResponse(f"/dictionary/replenish?message=добавлено записей: {added}", status_code=303)


@app.post("/dictionary/forget")
def dictionary_forget(en: str = Form(...), pos: str = Form("")):
    state.lexicon.forget_unknown(en, pos or None)
    return RedirectResponse("/dictionary/replenish?message=слово убрано из журнала", status_code=303)


@app.post("/dictionary/ding")
def dictionary_ding():
    def worker() -> None:
        try:
            state.ding_status = "загрузка…"
            ding.download()
            ding.index()
            state.ding_status = "словарь Ding загружен"
        except Exception as problem:  # noqa: BLE001
            state.ding_status = f"не удалось загрузить: {problem}"

    threading.Thread(target=worker, daemon=True).start()
    time.sleep(0.2)
    return RedirectResponse("/dictionary/replenish", status_code=303)


@app.get("/dictionary/export.tsv")
def dictionary_export(source: str = ""):
    data = state.lexicon.export_tsv(source)
    return Response(data.encode("utf-8"), media_type="text/tab-separated-values; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="dragoman-dictionary.tsv"'})


@app.post("/dictionary/import")
async def dictionary_import(upload: UploadFile = File(...)):
    data = await upload.read()
    count = state.lexicon.import_tsv(data.decode("utf-8-sig", errors="replace"))
    return RedirectResponse(f"/dictionary?message=загружено записей: {count}", status_code=303)


@app.post("/dictionary/reset")
def dictionary_reset():
    count = state.lexicon.reset()
    return RedirectResponse(f"/dictionary?message=словарь возвращён к исходному ({count} записей)", status_code=303)


# --- оценка --------------------------------------------------------------------------------------------

def _load(path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _run_evaluation() -> None:
    try:
        from dragoman import evaluation

        data = evaluation.run(state.translator, state.collection)
        config.REPORT_DIR.mkdir(parents=True, exist_ok=True)
        EVALUATION_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        state.evaluation_error = None
    except Exception as problem:  # noqa: BLE001
        log.exception("оценка не выполнена")
        state.evaluation_error = f"{type(problem).__name__}: {problem}"
    finally:
        state.evaluation_running = False


@app.get("/evaluation", response_class=HTMLResponse)
def evaluation_page(request: Request):
    images = sorted(p.name for p in config.REPORT_DIR.glob("eval_*.png")) if config.REPORT_DIR.exists() else []
    return render(request, "evaluation.html", "evaluation", data=_load(EVALUATION_PATH),
                  analyzer=_load(ANALYZER_PATH), running=state.evaluation_running, error=state.evaluation_error,
                  images=images)


@app.post("/evaluation/run")
def evaluation_run():
    if not state.evaluation_running:
        state.evaluation_running = True
        threading.Thread(target=_run_evaluation, name="dragoman-evaluation", daemon=True).start()
    return RedirectResponse("/evaluation", status_code=303)


@app.get("/report/{name}")
def report_file(name: str):
    path = (config.REPORT_DIR / name).resolve()
    if path.parent != config.REPORT_DIR.resolve() or path.suffix != ".png" or not path.exists():
        raise HTTPException(404)
    return Response(path.read_bytes(), media_type="image/png")


# --- тир Пафнутия ------------------------------------------------------------------------------------

def _games_allowed() -> None:
    if not config.COMPANION_ENABLED:
        raise HTTPException(404, "Игра Пафнутия выключена вместе с ним (DRAGOMAN_COMPANION=0).")


@app.get("/shooter", response_class=HTMLResponse)
def shooter(request: Request, uid: str = "", doc: str = ""):
    _games_allowed()
    recent = list(state.translations.values())[::-1][:10]
    return render(request, "shooter.html", "shooter", documents=list(state.collection), recent=recent,
                  chosen_uid=uid, chosen_doc=doc, lines=pafnuty.client_lines("shooter"),
                  kinds=game.KINDS, waves_default=config.SHOOTER_WAVES, waves_range=config.SHOOTER_WAVES_RANGE)


@app.get("/api/shooter/plan")
def shooter_plan(doc: str = "", uid: str = "", waves: int = config.SHOOTER_WAVES, seed: int = 7):
    if not config.COMPANION_ENABLED:
        return JSONResponse({"error": "игра Пафнутия выключена"}, status_code=404)
    if doc:
        entry = state.collection.get(doc)
        if entry is None:
            return JSONResponse({"error": f"нет документа {doc}"}, status_code=404)
        t = state.translator.translate(state.collection.text(doc), entry.title, entry.domain, "transfer",
                                       source=entry.source_url)
        state.keep(t)
    elif uid:
        t = state.translations.get(uid)
        if t is None:
            return JSONResponse({"error": "перевод не найден — переведите текст ещё раз"}, status_code=404)
        if t.mode != "transfer":
            t = state.translator.translate(t.text, t.title, t.domain, "transfer", source=t.source)
            state.keep(t)
    else:
        return JSONResponse({"error": "выберите текст"}, status_code=400)
    plan = game.plan(t, waves, seed)
    return JSONResponse({
        "uid": t.uid, "title": t.title, "domain": t.domain,
        "plan": plan.to_dict(),
        "document": game.document_tokens(t),
        "translation": [{"heading": heading, "text": " ".join(s.text for s in sentences)}
                        for heading, sentences in t.paragraphs],
        "kinds": game.KINDS,
        "link": f"/t/{t.uid}",
        "export": f"/export/{t.uid}.txt",
    })


# --- справка и ошибки ------------------------------------------------------------------------------------

FAVICON = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
           "<text y='.9em' font-size='90'>🕸</text></svg>")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(FAVICON, media_type="image/svg+xml")


@app.get("/help", response_class=HTMLResponse)
def help_page(request: Request):
    return render(request, "help.html", "help", penn=tagset.PENN, deprels=tagset.DEPRELS)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, problem: StarletteHTTPException):
    if request.url.path.startswith("/api"):
        return JSONResponse({"error": str(problem.detail)}, status_code=problem.status_code)
    if request.url.path.startswith(("/export", "/raw", "/report", "/static")):
        return PlainTextResponse(str(problem.detail), status_code=problem.status_code)
    return render(request, "message.html", "message", status_code=problem.status_code,
                  title="Страница не найдена" if problem.status_code == 404 else "Ошибка", message=problem.detail)
