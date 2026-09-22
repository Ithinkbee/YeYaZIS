"""Веб-интерфейс системы распознавания языка.

Интерфейс рассчитан на пользователя любого уровня: на каждой странице есть
пояснение, что именно показано, а раздел «Справка» описывает и работу с
программой, и сами методы. Все страницы печатаются: правила @media print
убирают навигацию и оставляют только содержательную часть.
"""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Any

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import (
    HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pydantic import BaseModel, Field

from .. import (
    APP_NAME, VARIANT, VERSION, config, corpus, evaluation, experiments, export,
    pafnuty, quiz as quiz_module,
)
from ..chess import START_FEN
from ..methods import METHOD_CODES, METHOD_REGISTRY, describe
from ..models import Report, Verdict
from ..recognizer import Recognizer
from . import game


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Готовит каталоги и профили языков до приёма первого запроса."""
    config.ensure_dirs()
    state.ensure_trained()
    yield


app = FastAPI(title=f"«{APP_NAME}» — распознавание языка текста", lifespan=lifespan)
templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))


class State:
    """Состояние приложения: обученные методы и последний прогон.

    Профили строятся один раз при старте и переиспользуются: обучение занимает
    несколько секунд, и выполнять его на каждый запрос бессмысленно.
    """

    def __init__(self) -> None:
        self.recognizer = Recognizer()
        self.from_disk = False
        self.report: Report | None = None
        self.length_study: experiments.LengthStudy | None = None
        self.mixture_study: experiments.MixtureStudy | None = None
        self.trained_at: datetime | None = None
        self.error: str | None = None
        #: банк слов для викторины при взятии фигуры
        self.bank: quiz_module.WordBank | None = None

    # --- обучение ------------------------------------------------------------

    def ensure_trained(self, force: bool = False) -> None:
        """Поднимает профили с диска или строит их заново."""
        if self.recognizer.trained and not force:
            return
        self.recognizer = Recognizer()
        try:
            if force:
                self.recognizer.fit()
                self.recognizer.save()
                self.from_disk = False
            else:
                self.from_disk = self.recognizer.load_or_fit()
            self.trained_at = datetime.now()
            self.error = None
        except (FileNotFoundError, ValueError) as problem:
            self.error = str(problem)
        self.invalidate()

    def invalidate(self) -> None:
        """Сбрасывает кэш результатов — например, после переобучения."""
        self.report = None
        self.length_study = None
        self.mixture_study = None

    # --- результаты ----------------------------------------------------------

    def ensure_report(self, force: bool = False) -> Report | None:
        """Прогоняет тестовую коллекцию, если это ещё не сделано."""
        self.ensure_trained()
        if self.error:
            return None
        if self.report is None or force:
            verdicts = self.recognizer.recognize_all(corpus.load_collection())
            self.report = evaluation.build_report(verdicts, METHOD_CODES)
        return self.report

    def ensure_studies(self) -> tuple[experiments.LengthStudy | None, experiments.MixtureStudy | None]:
        """Считает опыты по длине входа и по смешанному тексту."""
        self.ensure_trained()
        if self.error:
            return None, None
        documents = corpus.load_collection()
        if self.length_study is None:
            self.length_study = experiments.run_length_study(self.recognizer, documents)
        if self.mixture_study is None:
            self.mixture_study = experiments.run_mixture_study(self.recognizer, documents)
        return self.length_study, self.mixture_study

    def ensure_bank(self) -> quiz_module.WordBank | None:
        """Собирает банк слов викторины при первом обращении.

        Банк строится по обучающему корпусу и от профилей не зависит, поэтому
        ошибка обучения викторине не мешает.
        """
        if self.bank is None:
            try:
                self.bank = quiz_module.build_bank()
            except (FileNotFoundError, ValueError):
                return None
        return self.bank

    def verdict_for(self, name: str) -> Verdict | None:
        """Находит результат по имени файла."""
        report = self.ensure_report()
        if report is None:
            return None
        for verdict in report.verdicts:
            if verdict.document.doc_id == name:
                return verdict
        return None


state = State()


# --- общий контекст шаблонов ------------------------------------------------


def base_context(request: Request, active: str) -> dict[str, Any]:
    """Переменные, нужные каждому шаблону."""
    return {
        "request": request,
        "app_name": APP_NAME,
        "version": VERSION,
        "variant": VARIANT,
        "active": active,
        "languages": config.LANGUAGES,
        "language_codes": config.LANGUAGE_CODES,
        "methods": describe(),
        "method_codes": METHOD_CODES,
        "method_titles": {code: METHOD_REGISTRY[code].title for code in METHOD_CODES},
        "consensus_code": evaluation.CONSENSUS,
        "consensus_title": evaluation.CONSENSUS_TITLE,
        "language_name": config.language_name,
        "error": state.error,
        "from_disk": state.from_disk,
        "trained_at": state.trained_at,
        "companion_enabled": config.COMPANION_ENABLED,
        "companion_name": pafnuty.NAME,
        "companion_instrumental": pafnuty.NAME_INSTRUMENTAL,
        "companion_dative": pafnuty.NAME_DATIVE,
        "companion_line": pafnuty.greeting(active) if config.COMPANION_ENABLED else "",
    }


if config.STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")


# --- главная страница -------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> Response:
    """Обзор коллекции и корпуса, запуск распознавания."""
    report = state.ensure_report()
    context = base_context(request, "index")
    context.update(
        {
            "report": report,
            "corpus_stats": corpus.corpus_stats(),
            "train_limits": (config.TRAIN_MIN_BYTES, config.TRAIN_MAX_BYTES),
            "summary": evaluation.summary_lines(report) if report else [],
            "formats": export.FORMATS,
        }
    )
    return templates.TemplateResponse(request, "index.html", context)


@app.post("/run")
def run_collection() -> RedirectResponse:
    """Перепрогоняет тестовую коллекцию заново."""
    state.ensure_report(force=True)
    return RedirectResponse("/", status_code=303)


@app.post("/train")
def retrain() -> RedirectResponse:
    """Строит профили языков заново по обучающему корпусу."""
    state.ensure_trained(force=True)
    return RedirectResponse("/profiles", status_code=303)


# --- отдельный документ -----------------------------------------------------


@app.get("/document/{name}", response_class=HTMLResponse)
def document(request: Request, name: str) -> Response:
    """Разбор одного документа: решение каждого метода и чем оно обосновано."""
    verdict = state.verdict_for(name)
    context = base_context(request, "index")
    if verdict is None:
        context["message"] = f"Документ «{name}» в коллекции не найден."
        return templates.TemplateResponse(request, "message.html", context, status_code=404)
    context.update({"verdict": verdict, "document": verdict.document})
    return templates.TemplateResponse(request, "document.html", context)


@app.get("/raw/{name}")
def raw_document(name: str) -> Response:
    """Отдаёт исходный HTML-документ — та самая активная ссылка на документ."""
    path = (config.COLLECTION_DIR / name).resolve()
    # защита от выхода за пределы каталога коллекции через «..» в имени
    if not str(path).startswith(str(config.COLLECTION_DIR.resolve())) or not path.is_file():
        return PlainTextResponse(f"Документ «{name}» не найден.", status_code=404)
    return HTMLResponse(path.read_bytes().decode(errors="replace"))


# --- сравнение методов ------------------------------------------------------


@app.get("/compare", response_class=HTMLResponse)
def compare(request: Request) -> Response:
    """Точность, быстродействие и поведение методов в трудных условиях."""
    report = state.ensure_report()
    length_study, mixture_study = state.ensure_studies()
    context = base_context(request, "compare")
    context.update(
        {
            "report": report,
            "speed": evaluation.speed_comparison(report) if report else [],
            "length_study": length_study,
            "mixture_study": mixture_study,
            "length_lines": experiments.summary_lines(length_study) if length_study else [],
            "mixture_lines": experiments.mixture_lines(mixture_study) if mixture_study else [],
        }
    )
    return templates.TemplateResponse(request, "compare.html", context)


# --- профили языков ---------------------------------------------------------


@app.get("/profiles", response_class=HTMLResponse)
def profiles(request: Request) -> Response:
    """Поисковые образы языков, построенные по обучающему корпусу."""
    state.ensure_trained()
    context = base_context(request, "profiles")
    context.update(
        {
            "recognizer": state.recognizer,
            "corpus_stats": corpus.corpus_stats(),
            "top_count": 30,
        }
    )
    return templates.TemplateResponse(request, "profiles.html", context)


# --- проверка своего текста -------------------------------------------------


@app.get("/check", response_class=HTMLResponse)
def check_form(request: Request) -> Response:
    """Форма для проверки собственного текста или файла."""
    context = base_context(request, "check")
    context.update({"verdict": None, "source": ""})
    return templates.TemplateResponse(request, "check.html", context)


@app.post("/check", response_class=HTMLResponse)
async def check(
    request: Request,
    text: str = Form(default=""),
    upload: UploadFile | None = File(default=None),
) -> Response:
    """Распознаёт язык текста, введённого руками или загруженного файлом."""
    state.ensure_trained()
    context = base_context(request, "check")

    source = text or ""
    title = "Введённый текст"
    is_html = False

    if upload is not None and upload.filename:
        raw = await upload.read()
        if len(raw) > config.MAX_FILE_SIZE:
            context.update(
                {"verdict": None, "source": "", "message": "Файл слишком велик."}
            )
            return templates.TemplateResponse(request, "check.html", context)
        from .. import preprocess

        source = preprocess.decode(raw)
        title = upload.filename
        is_html = Path(upload.filename).suffix.lower() in config.COLLECTION_EXTENSIONS
    elif "<" in source and ">" in source:
        # вставленная разметка распознаётся как HTML и очищается от тегов
        is_html = True

    if not source.strip():
        context.update({"verdict": None, "source": "", "message": "Текст не задан."})
        return templates.TemplateResponse(request, "check.html", context)

    if state.error:
        context.update({"verdict": None, "source": source})
        return templates.TemplateResponse(request, "check.html", context)

    verdict = state.recognizer.recognize_text(source, title=title, is_html=is_html)
    context.update({"verdict": verdict, "source": source[:4000], "document": verdict.document})
    return templates.TemplateResponse(request, "check.html", context)


# --- печать и выгрузка ------------------------------------------------------


@app.get("/print", response_class=HTMLResponse)
def print_view(request: Request) -> Response:
    """Версия отчёта для печати: без навигации, в одну колонку."""
    report = state.ensure_report()
    context = base_context(request, "print")
    context.update(
        {
            "report": report,
            "speed": evaluation.speed_comparison(report) if report else [],
            "corpus_stats": corpus.corpus_stats(),
            "printed_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        }
    )
    return templates.TemplateResponse(request, "print.html", context)


@app.get("/export/{fmt}")
def export_report(fmt: str) -> Response:
    """Сохранение результатов в файл: CSV, JSON или текстовый протокол."""
    if fmt not in export.FORMATS:
        return PlainTextResponse(f"Неизвестный формат: {fmt}", status_code=400)
    report = state.ensure_report()
    if report is None:
        return PlainTextResponse(state.error or "Нет результатов для выгрузки.", status_code=503)

    titles = {code: METHOD_REGISTRY[code].title for code in METHOD_CODES}
    body = export.render(report, fmt, titles)
    _, media_type, _ = export.FORMATS[fmt]
    name = export.filename(fmt)
    return Response(
        content=body.encode("utf-8"),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.post("/export/{fmt}/save")
def export_to_disk(fmt: str) -> Response:
    """Сохраняет выгрузку в каталог отчёта на диске."""
    if fmt not in export.FORMATS:
        return PlainTextResponse(f"Неизвестный формат: {fmt}", status_code=400)
    report = state.ensure_report()
    if report is None:
        return PlainTextResponse(state.error or "Нет результатов.", status_code=503)
    titles = {code: METHOD_REGISTRY[code].title for code in METHOD_CODES}
    path = export.save(report, fmt, method_titles=titles)
    return HTMLResponse(
        f"<p>Сохранено: <code>{html.escape(str(path))}</code></p>"
        f'<p><a href="/">Вернуться</a></p>'
    )


# --- справка ----------------------------------------------------------------


# --- Пафнутий: шахматы и викторина ------------------------------------------
#
# Весь этот раздел подчинён config.COMPANION_ENABLED. При выключенной
# надстройке страница партии отвечает 404, а API — 403: игровой слой должен
# исчезать целиком, а не прятаться в разметке.


#: поле доски в алгебраической записи. Проверка стоит на границе, чтобы
#: некорректный ввод отсекался так же, как испорченный FEN, — ответом 422,
#: а не молчаливым «так эта фигура не ходит».
SQUARE = r"^[a-h][1-8]$"
PROMOTION = r"^[qrbn]?$"


class MoveRequest(BaseModel):
    """Ход игрока в партии."""

    fen: str = Field(min_length=10, max_length=120)
    frm: str = Field(pattern=SQUARE)
    to: str = Field(pattern=SQUARE)
    promotion: str = Field(default="", pattern=PROMOTION)
    #: None — викторина ещё не пройдена, ход выполнять рано
    quiz_passed: bool | None = None


class PuzzleRequest(BaseModel):
    """Попытка решить задачу «мат в два хода»."""

    index: int = Field(default=0, ge=0)
    frm: str = Field(pattern=SQUARE)
    to: str = Field(pattern=SQUARE)
    promotion: str = Field(default="", pattern=PROMOTION)
    attempts: int = Field(default=0, ge=0)


class QuizRequest(BaseModel):
    """Ответ на вопрос викторины."""

    word: str = Field(min_length=1, max_length=40)
    answer: str = Field(min_length=1, max_length=8)


def _companion_guard() -> Response | None:
    """Отказ, если игровая надстройка выключена."""
    if config.COMPANION_ENABLED:
        return None
    return JSONResponse({"error": "игровая надстройка выключена"}, status_code=403)


@app.get("/chess", response_class=HTMLResponse)
def chess_page(request: Request) -> Response:
    """Партия с Пафнутием."""
    context = base_context(request, "chess")
    if not config.COMPANION_ENABLED:
        context["message"] = "Игровая надстройка выключена (TOLMACH_COMPANION=0)."
        return templates.TemplateResponse(request, "message.html", context, status_code=404)
    context.update({"start_fen": START_FEN, "depth": config.CHESS_DEPTH})
    return templates.TemplateResponse(request, "chess.html", context)


@app.get("/api/chess/puzzle")
def api_puzzle(index: int | None = None) -> Response:
    """Выдаёт задачу «мат в два хода». Решение остаётся на сервере."""
    refusal = _companion_guard()
    if refusal:
        return refusal
    return JSONResponse(game.puzzle_payload(index))


@app.post("/api/chess/puzzle")
def api_puzzle_try(payload: PuzzleRequest) -> Response:
    """Проверяет первый ход задачи."""
    refusal = _companion_guard()
    if refusal:
        return refusal
    try:
        result = game.try_puzzle(
            payload.index, payload.frm, payload.to, payload.promotion, payload.attempts
        )
    except (ValueError, IndexError) as problem:
        return JSONResponse({"error": str(problem)}, status_code=400)
    return JSONResponse(result)


@app.post("/api/chess/move")
def api_chess_move(payload: MoveRequest) -> Response:
    """Ход игрока и ответ Пафнутия."""
    refusal = _companion_guard()
    if refusal:
        return refusal
    try:
        outcome = game.play(
            payload.fen, payload.frm, payload.to, payload.promotion, payload.quiz_passed
        )
    except (ValueError, IndexError) as problem:
        return JSONResponse({"error": str(problem)}, status_code=400)
    return JSONResponse(
        {
            "ok": outcome.ok,
            "fen": outcome.fen,
            "message": outcome.message,
            "kind": outcome.kind,
            "reply": outcome.reply,
            "reply_line": outcome.reply_line,
            "status": outcome.status,
            "highlight": list(outcome.highlight),
        }
    )


@app.get("/api/quiz/word")
def api_quiz_word() -> Response:
    """Слово для викторины: латиница, язык-эталон на сервере."""
    refusal = _companion_guard()
    if refusal:
        return refusal
    bank = state.ensure_bank()
    if bank is None or not bank.ready:
        return JSONResponse({"error": "банк слов пуст"}, status_code=503)
    return JSONResponse(game.quiz_payload(bank))


@app.post("/api/quiz/answer")
def api_quiz_answer(payload: QuizRequest) -> Response:
    """Проверяет ответ и показывает, что сказали бы методы системы."""
    refusal = _companion_guard()
    if refusal:
        return refusal
    bank = state.ensure_bank()
    if bank is None or not bank.ready:
        return JSONResponse({"error": "банк слов пуст"}, status_code=503)
    state.ensure_trained()
    recognizer = state.recognizer if not state.error else None
    return JSONResponse(game.quiz_answer(bank, payload.word, payload.answer, recognizer))


@app.get("/help", response_class=HTMLResponse)
def help_page(request: Request) -> Response:
    """Справка: как работать с программой и как устроены методы."""
    context = base_context(request, "help")
    context.update(
        {
            "lengths": experiments.LENGTHS,
            "formats": export.FORMATS,
            "ngram_size": config.NGRAM_PROFILE_SIZE,
            "ngram_max": config.NGRAM_MAX_N,
            "neural_features": config.NEURAL_FEATURES,
            "neural_hidden": config.NEURAL_HIDDEN,
        }
    )
    return templates.TemplateResponse(request, "help.html", context)
