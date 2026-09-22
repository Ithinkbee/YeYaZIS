"""Веб-интерфейс ИПС «Арахна» — третий компонент системы (поисковый механизм).

Интерфейс и есть та часть, где по варианту 3 реализуются элементы
искусственного интеллекта: разбор естественно-языкового запроса, подсказки,
исправление опечаток, расширение синонимами, обратная связь по релевантности
и объяснение выдачи.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import (
    APP_NAME,
    __version__,
    companion,
    config,
    crawler,
    db,
    economy,
    indexer,
    jokers,
    mischief,
    modes,
)
from ..ai import feedback as fb
from ..ai import llm, suggest
from ..evaluation import plots, qrels, runner
from ..search import Search
from ..text import snippets
from ..text.morphology import lemma

app = FastAPI(title=f"ИПС «{APP_NAME}»", version=__version__)
app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))


def _plain_icon(value: str) -> str:
    """В режиме отказа от паука эмодзи заменяются на канцелярский прочерк."""
    return value if config.COMPANION_ENABLED else "[—]"


templates.env.filters["icon"] = _plain_icon


# --- Подключение к базе -----------------------------------------------------

def get_conn() -> sqlite3.Connection:
    conn = db.connect()
    db.init_db(conn)
    return conn


def _ui_flags(conn: sqlite3.Connection) -> dict:
    """Что клиентской части разрешено вытворять с интерфейсом.

    Каждая шутка снимается покупкой в лавке, флагом ARACHNE_CRUELTY=0 или
    общим рубильником. Честный путь тоже есть: разметив двадцать документов,
    пользователь получает прямой скролл без всякой покупки.
    """
    if not mischief.cruelty_enabled():
        return {}
    judged = int(db.get_setting(conn, "counter:judged", "0") or 0)
    return {
        "cobweb": not economy.owns(conn, "no-cobweb"),
        "invert_scroll": not economy.owns(conn, "normal-scroll") and judged < 20,
        "shifty_modals": not economy.owns(conn, "honest-modals"),
        "judged": judged,
    }


def render(
    request: Request,
    template: str,
    context: dict,
    conn: sqlite3.Connection | None = None,
) -> HTMLResponse:
    """Общий контекст всех страниц.

    При выключенном компаньоне (ARACHNE_COMPANION=0) игровая часть контекста
    не собирается вовсе: шаблоны видят пустой кошелёк, тему «канцелярия» и
    ни одной активной механики. Это режим для защиты лабораторной.
    """
    context.setdefault("app_name", APP_NAME)
    context.setdefault("version", __version__)
    context.setdefault("companion_enabled", config.COMPANION_ENABLED)
    context.setdefault("office_mode", not config.COMPANION_ENABLED)
    context.setdefault("companion_name", config.COMPANION_NAME)
    context.setdefault("llm", llm.status())
    context.setdefault("economy_enabled", economy.enabled())
    context.setdefault("cruelty_enabled", mischief.cruelty_enabled())

    if conn is not None:
        context.setdefault("skin", companion.active_skin(conn))
        context.setdefault("skins", companion.owned_skins(conn))
        context.setdefault("skin_names", companion.SKINS)
        if config.COMPANION_ENABLED:
            context.setdefault("spider", companion.spider_state(conn))
        if economy.enabled():
            context.setdefault("capital", economy.balance(conn))
        context.setdefault("ui", _ui_flags(conn))
    else:
        context.setdefault("skin", "office" if not config.COMPANION_ENABLED else "classic")
        context.setdefault("ui", {})

    context["request"] = request
    return templates.TemplateResponse(request, template, context)


# --- Состояние фоновой задачи (обход и индексация) --------------------------

TASK: dict = {
    "active": False,
    "kind": "",
    "done": 0,
    "total": 0,
    "message": "",
    "finished_at": "",
    "result": "",
}
TASK_LOCK = threading.Lock()


def _run_background(kind: str, function) -> None:
    def worker() -> None:
        conn = get_conn()
        try:
            result = function(conn)
            with TASK_LOCK:
                TASK.update(
                    active=False,
                    result=result,
                    message="готово",
                    finished_at=datetime.now().strftime("%H:%M:%S"),
                )
        except Exception as exc:  # noqa: BLE001 — сообщаем об ошибке в интерфейс
            with TASK_LOCK:
                TASK.update(
                    active=False,
                    result=f"ошибка: {type(exc).__name__}: {exc}",
                    message="ошибка",
                )
        finally:
            conn.close()

    with TASK_LOCK:
        if TASK["active"]:
            return
        TASK.update(
            active=True, kind=kind, done=0, total=0, message="запуск…",
            result="", finished_at="",
        )
    threading.Thread(target=worker, daemon=True).start()


def _progress(done: int, total: int, message: str = "") -> None:
    with TASK_LOCK:
        TASK.update(done=done, total=total, message=message)


# --- Главная страница -------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    conn = get_conn()
    try:
        statistics = db.stats(conn)
        economy.ensure_start_capital(conn)
        return render(
            request,
            "search.html",
            {
                "stats": statistics,
                "popular": suggest.popular_queries(conn, 6),
                "recent": suggest.recent_queries(conn, 6),
                "sources": crawler.list_sources(conn),
                "companion_line": companion.spider_line(conn, "welcome"),
                "collection_ready": config.COLLECTION_DIR.exists(),
                "jokers_offer": jokers.offer(conn),
                "jokers_active": jokers.active_list(conn),
                "lucky_ready": modes.lucky_ready(conn),
            },
            conn=conn,
        )
    finally:
        conn.close()


# --- Поиск ------------------------------------------------------------------

@app.get("/search", response_class=HTMLResponse)
def search(
    request: Request,
    q: str = Query("", description="естественно-языковой запрос"),
    all_words: bool = Query(False),
    synonyms: bool = Query(True),
    use_feedback: bool = Query(True),
    date_from: str = Query(""),
    date_to: str = Query(""),
    page: int = Query(1, ge=1),
    notice: str = Query(""),
):
    conn = get_conn()
    try:
        user_query = q.strip()
        if not user_query:
            return RedirectResponse("/", status_code=303)

        economy.ensure_start_capital(conn)

        # --- игровая обвязка вокруг обычного поиска -------------------------
        # Всё, что собирается ниже, влияет только на эту страницу. Оценка
        # качества (/metrics, tools/run_eval.py) идёт мимо: там своя чистая
        # конфигурация, без джокеров, проклятий и купленных стоп-слов.
        query_text, curse = mischief.maybe_curse(conn, user_query)
        active_jokers = jokers.active_jokers(conn)
        stopwords_bought = economy.bought_stopwords(conn)
        streak = mischief.bump_streak(conn)
        spider_mood = mischief.mood(conn)

        analysis = suggest.analyze(conn, query_text)
        expansions = suggest.expansion_lemmas(analysis, use_synonyms=synonyms)

        marks = fb.marks_for_query(conn, query_text) if use_feedback else {}
        positive = [doc_id for doc_id, mark in marks.items() if mark > 0]
        negative = [doc_id for doc_id, mark in marks.items() if mark < 0]

        engine = Search(
            conn=conn,
            search_query=query_text,
            all_words_together=all_words,
            date_start_string=date_from,
            date_end_string=date_to,
            expansions=expansions,
            limit=200,
            allowed_stopwords=stopwords_bought,
            alphabetical=spider_mood == "sulking",
            snippet_noise=mischief.snippet_noise(conn, streak),
        )
        jokers.apply_to(engine, active_jokers, conn)
        if positive or negative:
            base_vector = engine.get_search_query_vector()
            engine.rocchio_vector = fb.rocchio_vector(conn, base_vector, positive, negative)

        results = engine.get_search_result()

        per_page = config.RESULTS_PER_PAGE
        pages = max(1, (len(results) + per_page - 1) // per_page)
        page = min(page, pages)
        betrayed = mischief.betrays_page(conn, page)
        if betrayed:
            page_results = mischief.shuffled_first_page(results, per_page)
        else:
            page_results = results[(page - 1) * per_page : page * per_page]

        suggest.log_query(conn, query_text, " ".join(analysis.lemmas),
                          len(results), engine.took_ms)

        repeated = any(
            row["raw_query"].strip().lower() == query_text.lower()
            for row in suggest.recent_queries(conn, 6)[1:]
        )
        new_achievements = companion.check_after_search(
            conn, query_text, len(results), bool(analysis.corrections)
        )

        # --- последствия запроса --------------------------------------------
        mischief.note_search(conn)
        jokers.consume(conn)
        used_stopwords = {
            word for word in engine.kept_stopwords if word in stopwords_bought
        }
        economy.burn_stopwords(conn, used_stopwords)
        reward = companion.reward_for_query(conn, analysis, repeated)
        offended = mischief.react_to_rudeness(conn, user_query)
        moult = companion.maybe_moult(conn)
        if economy.enabled() and len(
            conn.execute("SELECT code FROM purchases WHERE code NOT LIKE 'skin:%'").fetchall()
        ) >= 3:
            companion.unlock(conn, "shopper")

        empty_hints = []
        if not results:
            if all_words:
                empty_hints.append("отключите режим «все слова обязательны»")
            if analysis.corrections:
                empty_hints.append("проверьте исправленный вариант запроса")
            if date_from or date_to:
                empty_hints.append("снимите ограничение по дате")
            if len(analysis.lemmas) > 1:
                empty_hints.append("оставьте в запросе одно-два ключевых слова")
            if not analysis.lemmas:
                empty_hints.append("запрос состоит только из служебных слов")

        companion_line = (
            companion.line("offended")
            if offended
            else companion.react_to_search(
                query_text, len(results), bool(analysis.corrections), repeated
            )
        )

        return render(
            request,
            "results.html",
            {
                "query": query_text,
                "analysis": analysis,
                "corrected_query": suggest.corrected_query(query_text, analysis.corrections),
                "results": page_results,
                "total": len(results),
                "took_ms": round(engine.took_ms, 1),
                "page": page,
                "pages": pages,
                "per_page": per_page,
                "all_words": all_words,
                "synonyms": synonyms,
                "use_feedback": use_feedback,
                "date_from": date_from,
                "date_to": date_to,
                "marks": marks,
                "rocchio_applied": bool(positive or negative),
                "expansions": expansions,
                "empty_hints": empty_hints,
                "companion_line": companion_line,
                "new_achievements": new_achievements,
                # игровая часть страницы
                "jokers_active": jokers.active_list(conn),
                "jokers_offer": jokers.offer(conn),
                "kept_stopwords": engine.kept_stopwords,
                "bought_stopwords": used_stopwords,
                "cursed": bool(curse),
                "mood": spider_mood,
                "betrayed": betrayed,
                "drunk": bool(engine.snippet_noise),
                "streak": streak,
                "reward": reward,
                "offended": offended,
                "moult": moult,
                "synonym_tip": companion.suggest_synonym(conn, analysis),
                "lucky_ready": modes.lucky_ready(conn),
                "notice": notice,
            },
            conn=conn,
        )
    finally:
        conn.close()


@app.get("/api/suggest")
def api_suggest(q: str = Query("")):
    conn = get_conn()
    try:
        return JSONResponse({"suggestions": suggest.autocomplete(conn, q)})
    finally:
        conn.close()


@app.get("/api/analyze")
def api_analyze(q: str = Query("")):
    """Морфологический разбор запроса — используется всплывающей подсказкой."""
    conn = get_conn()
    try:
        analysis = suggest.analyze(conn, q)
        return JSONResponse(
            {
                "lemmas": analysis.lemmas,
                "stopwords": analysis.stopwords,
                "morphology": analysis.morphology,
                "corrections": analysis.corrections,
                "synonyms": analysis.synonyms,
            }
        )
    finally:
        conn.close()


# --- Документ ---------------------------------------------------------------

@app.get("/doc/{doc_id}", response_class=HTMLResponse)
def document(request: Request, doc_id: int, q: str = Query(""), lucky: str = Query("")):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if row is None:
            return render(request, "message.html",
                          {"title": "Документ не найден",
                           "message": "Возможно, файл удалён из локальной сети."})

        lemmas = {lemma(word) for word in q.lower().split()} if q else set()
        highlighted = snippets.highlight(row["text"], lemmas)
        weights = sorted(
            indexer.get_document_vector_by_lemma(conn, doc_id).items(),
            key=lambda item: -item[1],
        )[:15]
        new_achievements = companion.check_after_open_document(conn)
        # документ открыли: паук сыт и больше не дуется
        mischief.note_document_open(conn)
        companion.feed(conn, "open")
        blitz = modes.blitz_check(conn, doc_id)
        if blitz.get("won") and int(db.get_setting(conn, "blitz:combo", "0") or 0) >= 5:
            companion.unlock(conn, "sniper")

        return render(
            request,
            "document.html",
            {
                "doc": row,
                "query": q,
                "text_html": highlighted,
                "keywords": weights,
                "similar": fb.similar_documents(conn, doc_id, 5),
                "exists": Path(row["path"]).exists(),
                "companion_line": companion.spider_line(conn, "document", seed=str(doc_id)),
                "new_achievements": new_achievements,
                "blitz": blitz,
                "lucky": lucky,
            },
            conn=conn,
        )
    finally:
        conn.close()


@app.post("/doc/{doc_id}/delete")
def delete_document(doc_id: int):
    """Удаление документа из базы (DeleteDocumentFromBase, рис. 1).

    Индекс после удаления перестраивается: число документов N изменилось, а с ним
    и все инверсные частоты B_i, то есть веса A_ij всех остальных документов.
    """
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT title FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        if row is None:
            return RedirectResponse("/admin?message=Документ не найден", status_code=303)
        indexer.delete_document_from_base(conn, doc_id)
        statistics = indexer.build_index(conn)
        return RedirectResponse(
            f"/admin?message=Документ «{row['title']}» удалён, "
            f"индекс перестроен ({statistics['documents']} документов)",
            status_code=303,
        )
    finally:
        conn.close()


@app.get("/raw/{doc_id}")
def raw_document(doc_id: int):
    """Активная ссылка на исходный файл документа в локальной сети."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT path, title FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        if row is None or not Path(row["path"]).exists():
            return JSONResponse({"error": "файл недоступен"}, status_code=404)
        return FileResponse(row["path"], filename=Path(row["path"]).name)
    finally:
        conn.close()


# --- Обратная связь по релевантности ----------------------------------------

def _search_url(
    q: str,
    all_words: bool,
    synonyms: bool,
    use_feedback: bool = True,
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
    anchor: str = "",
) -> str:
    """Ссылка на выдачу с сохранением всех параметров поиска.

    Раньше редирект собирался из трёх параметров, и после отметки
    релевантности терялись фильтры по дате, номер страницы и флаг учёта
    отметок: пользователь возвращался на первую страницу без своих настроек.
    """
    params = {
        "q": q,
        "all_words": str(bool(all_words)).lower(),
        "synonyms": str(bool(synonyms)).lower(),
        "use_feedback": str(bool(use_feedback)).lower(),
        "date_from": date_from or "",
        "date_to": date_to or "",
        "page": str(max(1, page)),
    }
    query = "&".join(f"{key}={quote(value)}" for key, value in params.items())
    return f"/search?{query}{anchor}"


@app.post("/feedback")
def post_feedback(
    q: str = Form(...),
    doc_id: int = Form(...),
    mark: int = Form(...),
    all_words: bool = Form(False),
    synonyms: bool = Form(True),
    use_feedback: bool = Form(True),
    date_from: str = Form(""),
    date_to: str = Form(""),
    page: int = Form(1),
):
    conn = get_conn()
    try:
        fb.record(conn, q, doc_id, mark)
        return RedirectResponse(
            _search_url(
                q, all_words, synonyms, use_feedback, date_from, date_to, page,
                anchor=f"#doc-{doc_id}",
            ),
            status_code=303,
        )
    finally:
        conn.close()


@app.post("/feedback/clear")
def clear_feedback(
    q: str = Form(...),
    all_words: bool = Form(False),
    synonyms: bool = Form(True),
    use_feedback: bool = Form(True),
    date_from: str = Form(""),
    date_to: str = Form(""),
):
    conn = get_conn()
    try:
        fb.clear(conn, q)
        return RedirectResponse(
            _search_url(q, all_words, synonyms, use_feedback, date_from, date_to),
            status_code=303,
        )
    finally:
        conn.close()


# --- Управление индексом ----------------------------------------------------

@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request, message: str = Query("")):
    conn = get_conn()
    try:
        return render(
            request,
            "admin.html",
            {
                "stats": db.stats(conn),
                "sources": crawler.list_sources(conn),
                "top_terms": indexer.top_terms(conn, 25),
                "crawl_log": conn.execute(
                    "SELECT * FROM crawl_log ORDER BY id DESC LIMIT 5"
                ).fetchall(),
                "hosts": conn.execute(
                    """SELECT host, COUNT(*) AS documents, SUM(size_bytes) AS size
                       FROM documents GROUP BY host ORDER BY documents DESC"""
                ).fetchall(),
                "formats": conn.execute(
                    "SELECT ext, COUNT(*) AS documents FROM documents "
                    "GROUP BY ext ORDER BY documents DESC"
                ).fetchall(),
                "achievements": companion.unlocked(conn),
                "message": message,
                "task": dict(TASK),
                "collection_dir": str(config.COLLECTION_DIR),
            },
            conn=conn,
        )
    finally:
        conn.close()


@app.post("/admin/sources/add")
def add_source(root_path: str = Form(...), label: str = Form("")):
    conn = get_conn()
    try:
        path = root_path.strip()
        if not path:
            return RedirectResponse("/admin?message=Путь не указан", status_code=303)
        if not Path(path).exists():
            return RedirectResponse(
                f"/admin?message=Ресурс недоступен: {path}", status_code=303
            )
        crawler.add_source(conn, path, label.strip())
        return RedirectResponse(f"/admin?message=Источник добавлен: {path}", status_code=303)
    finally:
        conn.close()


@app.post("/admin/sources/demo")
def add_demo_sources():
    """Добавляет тестовую коллекцию как три узла локальной сети."""
    conn = get_conn()
    try:
        added = 0
        for node in sorted(p for p in config.COLLECTION_DIR.glob("NODE-*") if p.is_dir()):
            crawler.add_source(conn, str(node), node.name)
            added += 1
        if not added:
            return RedirectResponse(
                "/admin?message=Коллекция не найдена, выполните tools/make_collection.py",
                status_code=303,
            )
        return RedirectResponse(
            f"/admin?message=Добавлено узлов: {added}", status_code=303
        )
    finally:
        conn.close()


@app.post("/admin/sources/{source_id}/remove")
def remove_source(source_id: int):
    conn = get_conn()
    try:
        crawler.remove_source(conn, source_id)
        return RedirectResponse("/admin?message=Источник удалён", status_code=303)
    finally:
        conn.close()


@app.post("/admin/crawl")
def start_crawl():
    def job(conn: sqlite3.Connection) -> str:
        report = crawler.crawl(conn, progress=_progress)
        statistics = indexer.build_index(conn, progress=_progress)
        companion.check_after_index(conn, statistics["documents"])
        # новый документ — жирный разовый бонус: коллекция статична, и без
        # него паук голодал бы вечно
        companion.feed(conn, "new_document" if report.added else "reindex", report.added or 1)
        economy.ensure_start_capital(conn)
        return (
            f"добавлено {report.added}, обновлено {report.updated}, "
            f"пропущено {report.skipped}, удалено {report.removed}, "
            f"ошибок {report.errors}; в индексе {statistics['terms']} терминов"
        )

    _run_background("crawl", job)
    return RedirectResponse("/admin?message=Обход запущен", status_code=303)


@app.post("/admin/reindex")
def start_reindex():
    def job(conn: sqlite3.Connection) -> str:
        statistics = indexer.build_index(conn, progress=_progress)
        companion.check_after_index(conn, statistics["documents"])
        companion.feed(conn, "reindex")
        economy.ensure_start_capital(conn)
        return (
            f"документов {statistics['documents']}, терминов {statistics['terms']}, "
            f"весов {statistics['postings']}, {statistics['took_ms']:.0f} мс"
        )

    _run_background("index", job)
    return RedirectResponse("/admin?message=Переиндексация запущена", status_code=303)


@app.post("/admin/clear")
def clear_index():
    conn = get_conn()
    try:
        db.clear_all(conn)
        return RedirectResponse("/admin?message=База документов очищена", status_code=303)
    finally:
        conn.close()


@app.get("/api/task")
def task_status():
    with TASK_LOCK:
        return JSONResponse(dict(TASK))


# --- Оценка качества --------------------------------------------------------

@app.get("/metrics", response_class=HTMLResponse)
def metrics_page(
    request: Request,
    top_k: int = Query(20, ge=1, le=100),
    synonyms: bool = Query(False),
    all_words: bool = Query(False),
    message: str = Query(""),
):
    conn = get_conn()
    try:
        run = runner.RunConfig(
            name="Текущая конфигурация",
            use_synonyms=synonyms,
            all_words_together=all_words,
            top_k=top_k,
        )
        outcome = runner.evaluate(conn, run)
        new_achievements = []
        if outcome["per_query"]:
            new_achievements = companion.check_after_evaluation(conn, outcome["per_query"])

        return render(
            request,
            "metrics.html",
            {
                "queries": qrels.list_queries(conn),
                "per_query": outcome["per_query"],
                "summary": outcome["summary"],
                "error": outcome.get("error", ""),
                "top_k": top_k,
                "synonyms": synonyms,
                "all_words": all_words,
                "message": message,
                "companion_line": companion.line("metrics"),
                "new_achievements": new_achievements,
                "documents_indexed": db.stats(conn)["indexed"],
                "suspects": qrels.suspect_ids(conn),
            },
            conn=conn,
        )
    finally:
        conn.close()


@app.get("/metrics/compare", response_class=HTMLResponse)
def metrics_compare(
    request: Request,
    top_k: int = Query(20, ge=1, le=100),
    jokers_too: bool = Query(False, alias="jokers"),
):
    conn = get_conn()
    try:
        comparison = runner.compare_configurations(
            conn, top_k=top_k, jokers=jokers_too
        )
        return render(
            request,
            "compare.html",
            {"comparison": comparison, "top_k": top_k, "with_jokers": jokers_too,
             "companion_line": companion.line("metrics")},
            conn=conn,
        )
    finally:
        conn.close()


@app.get("/metrics/export.csv")
def metrics_export(top_k: int = Query(20, ge=1, le=100), synonyms: bool = Query(False)):
    conn = get_conn()
    try:
        outcome = runner.evaluate(
            conn, runner.RunConfig(use_synonyms=synonyms, top_k=top_k)
        )
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";")
        columns = [
            "query_id", "query", "relevant_total", "relevant_retrieved",
            "precision", "recall", "f1", "p@5", "p@10", "p@20",
            "r_precision", "ap", "ndcg", "ndcg@10", "bpref",
        ]
        writer.writerow(columns)
        for item in outcome["per_query"]:
            writer.writerow(
                [item.get(column, "") if not isinstance(item.get(column), float)
                 else f"{item[column]:.4f}" for column in columns]
            )
        summary = outcome["summary"]
        writer.writerow([])
        writer.writerow(["Средние значения"])
        for key in ("precision", "recall", "f1", "p@5", "p@10", "p@20",
                    "r_precision", "map", "ndcg", "ndcg@10", "bpref"):
            writer.writerow([key, f"{summary.get(key, 0):.4f}"])
        writer.writerow([])
        writer.writerow(["Полнота", "Интерполированная точность"])
        for level, value in summary.get("curve", []):
            writer.writerow([f"{level:.1f}", f"{value:.4f}"])

        buffer.seek(0)
        return StreamingResponse(
            iter([buffer.getvalue()]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=arachne_metrics.csv"},
        )
    finally:
        conn.close()


@app.post("/metrics/plots")
def metrics_plots(top_k: int = Form(20), synonyms: bool = Form(False)):
    conn = get_conn()
    try:
        outcome = runner.evaluate(
            conn, runner.RunConfig(use_synonyms=synonyms, top_k=top_k)
        )
        if not outcome["per_query"]:
            return RedirectResponse("/metrics?message=Нет эталонных запросов", status_code=303)
        plots.precision_recall_curve(outcome["summary"]["curve"])
        plots.per_query_bars(outcome["per_query"], "ap")
        plots.per_query_bars(outcome["per_query"], "p@10")
        plots.configurations_chart(runner.compare_configurations(conn, top_k=top_k))
        return RedirectResponse(
            f"/metrics?message=Графики сохранены в {config.REPORT_DIR}", status_code=303
        )
    finally:
        conn.close()


@app.post("/metrics/qrels/load")
def load_qrels():
    conn = get_conn()
    try:
        result = qrels.load_from_csv(conn)
        return RedirectResponse(
            f"/metrics?message=Загружено запросов {result['queries']}, "
            f"оценок {result['judgements']}",
            status_code=303,
        )
    finally:
        conn.close()


@app.post("/metrics/qrels/save")
def save_qrels():
    conn = get_conn()
    try:
        result = qrels.save_to_csv(conn)
        return RedirectResponse(
            f"/qrels?message=Сохранено: запросов {result['queries']}, "
            f"оценок {result['judgements']}",
            status_code=303,
        )
    finally:
        conn.close()


# --- Ручная разметка релевантности ------------------------------------------

@app.get("/qrels", response_class=HTMLResponse)
def qrels_page(
    request: Request,
    query_id: int = Query(0),
    message: str = Query(""),
    top_k: int = Query(15, ge=1, le=50),
):
    conn = get_conn()
    try:
        queries = qrels.list_queries(conn)
        current = None
        if query_id:
            current = conn.execute(
                "SELECT * FROM eval_queries WHERE id = ?", (query_id,)
            ).fetchone()
        elif queries:
            current = conn.execute(
                "SELECT * FROM eval_queries WHERE id = ?", (queries[0]["id"],)
            ).fetchone()

        pool: list[dict] = []
        judgements: dict[int, int] = {}
        quality: dict = {}
        if current is not None:
            judgements = qrels.rel_map(conn, current["id"])
            quality = _query_quality(conn, current["id"])
            engine = Search(conn=conn, search_query=current["text"], limit=top_k)
            results = engine.get_search_result()
            seen = set()
            for result in results:
                seen.add(result.document_id)
                pool.append(
                    {
                        "doc_id": result.document_id,
                        "title": result.title,
                        "rank": result.rank,
                        "host": result.host,
                        "snippet": result.snippet,
                        "rel": judgements.get(result.document_id),
                    }
                )
            # уже оценённые документы, не попавшие в текущую выдачу
            for doc_id, rel in judgements.items():
                if doc_id in seen:
                    continue
                row = conn.execute(
                    "SELECT id, title, host FROM documents WHERE id = ?", (doc_id,)
                ).fetchone()
                if row:
                    pool.append(
                        {
                            "doc_id": doc_id, "title": row["title"], "rank": 0.0,
                            "host": row["host"], "snippet": "— вне текущей выдачи —",
                            "rel": rel,
                        }
                    )

        return render(
            request,
            "qrels.html",
            {
                "queries": queries,
                "current": current,
                "pool": pool,
                "message": message,
                "top_k": top_k,
                "judged": len(judgements),
                "quality": quality,
                "suspect": current is not None and qrels.is_suspect(conn, current["id"]),
                "scroll_fixed": economy.owns(conn, "normal-scroll")
                or int(db.get_setting(conn, "counter:judged", "0") or 0) >= 20,
            },
            conn=conn,
        )
    finally:
        conn.close()


#: метрики, которые показываются на странице разметки
QUALITY_KEYS = ("precision", "recall", "f1", "ap", "ndcg", "bpref")


def _query_quality(conn: sqlite3.Connection, query_id: int) -> dict:
    """Качество по одному запросу с дельтой к значениям до последней оценки.

    Общий MAP на одну оценку сдвигается примерно на две тысячных — глазом это
    не читается, поэтому рядом показывается и вклад в MAP, и то, что реально
    изменилось у самого запроса.
    """
    result = runner.evaluate_single(conn, query_id)
    if not result:
        return {}

    key = f"qrels:last:{query_id}"
    raw = db.get_setting(conn, key, "")
    try:
        previous = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        previous = {}

    rows = []
    for name in QUALITY_KEYS:
        current = float(result.get(name, 0.0))
        before = float(previous.get(name, current))
        rows.append(
            {
                "key": name,
                "value": current,
                "previous": before,
                "delta": companion.score_delta(before, current),
                "up": current > before,
            }
        )

    summary = runner.evaluate(conn, runner.RunConfig(top_k=20))["summary"]
    return {
        "rows": rows,
        "map": summary.get("map", 0.0),
        "map_share": (
            (result.get("ap", 0.0) - previous.get("ap", result.get("ap", 0.0)))
            / max(1, summary.get("queries", 1))
        ),
        "judged": len(qrels.rel_map(conn, query_id)),
    }


def _remember_quality(conn: sqlite3.Connection, query_id: int) -> None:
    """Снимок метрик запроса до очередной оценки — база для дельты."""
    result = runner.evaluate_single(conn, query_id)
    if not result:
        return
    snapshot = {name: float(result.get(name, 0.0)) for name in QUALITY_KEYS}
    db.set_setting(conn, f"qrels:last:{query_id}", json.dumps(snapshot))


def _apply_judgement(
    conn: sqlite3.Connection, query_id: int, doc_id: int, rel: int
) -> list[dict]:
    """Сохраняет оценку и подтягивает всё, что от неё зависит."""
    _remember_quality(conn, query_id)
    if rel < 0:
        qrels.remove_judgement(conn, query_id, doc_id)
    else:
        qrels.set_judgement(conn, query_id, doc_id, rel)

    new_achievements: list[dict] = []
    if rel >= 0:
        companion.feed(conn, "judge")
        companion.bump(conn, "judged")
        # разметка — самая скучная часть лабораторной, поэтому за неё платят
        economy.earn(conn, 10, "qrels:judged")
    if qrels.check_suspect(conn, query_id) and companion.unlock(conn, "fake-expert"):
        new_achievements.append(
            {"code": "fake-expert", **companion.ACHIEVEMENTS["fake-expert"]}
        )
    return new_achievements


@app.post("/qrels/judge")
def judge(query_id: int = Form(...), doc_id: int = Form(...), rel: int = Form(...)):
    conn = get_conn()
    try:
        _apply_judgement(conn, query_id, doc_id, rel)
        # якорь возвращает страницу на ту же строку пула: без него браузер
        # вставал в начало страницы, и казалось, что оценка не сохранилась
        return RedirectResponse(
            f"/qrels?query_id={query_id}#doc-{doc_id}", status_code=303
        )
    finally:
        conn.close()


@app.post("/api/qrels/judge")
def api_judge(query_id: int = Form(...), doc_id: int = Form(...), rel: int = Form(...)):
    """Та же оценка без перезагрузки страницы — для прогрессивного улучшения.

    Формы на странице остаются рабочими и без JavaScript: скрипт лишь
    перехватывает их submit.
    """
    conn = get_conn()
    try:
        achievements = _apply_judgement(conn, query_id, doc_id, rel)
        quality = _query_quality(conn, query_id)
        return JSONResponse(
            {
                "rel": rel,
                "doc_id": doc_id,
                "judged": quality.get("judged", 0),
                "map": round(quality.get("map", 0.0), 4),
                "map_share": round(quality.get("map_share", 0.0), 4),
                "suspect": qrels.is_suspect(conn, query_id),
                "rows": [
                    {
                        "key": item["key"],
                        "value": round(item["value"], 3),
                        "previous": round(item["previous"], 3),
                        "delta": item["delta"],
                        "up": item["up"],
                    }
                    for item in quality.get("rows", [])
                ],
                "achievements": achievements,
                "capital": economy.balance(conn) if economy.enabled() else 0,
            }
        )
    finally:
        conn.close()


@app.post("/qrels/query/add")
def add_eval_query(text: str = Form(...), note: str = Form("")):
    conn = get_conn()
    try:
        if not text.strip():
            return RedirectResponse("/qrels?message=Пустой запрос", status_code=303)
        query_id = qrels.ensure_query(conn, text, note)
        return RedirectResponse(f"/qrels?query_id={query_id}", status_code=303)
    finally:
        conn.close()


@app.post("/qrels/query/{query_id}/delete")
def delete_eval_query(query_id: int):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM eval_queries WHERE id = ?", (query_id,))
        conn.commit()
        return RedirectResponse("/qrels?message=Запрос удалён", status_code=303)
    finally:
        conn.close()


# --- Языковой помощник ------------------------------------------------------

@app.post("/api/llm/answer")
def llm_answer(q: str = Form(...), top: int = Form(5)):
    if not llm.available():
        return JSONResponse({"error": llm.status()["reason"]}, status_code=503)
    conn = get_conn()
    try:
        engine = Search(conn=conn, search_query=q, limit=top)
        results = engine.get_search_result()
        documents = []
        for result in results:
            row = conn.execute(
                "SELECT title, text FROM documents WHERE id = ?", (result.document_id,)
            ).fetchone()
            if row:
                documents.append(
                    {"title": row["title"], "text": row["text"], "id": result.document_id}
                )
        answer = llm.answer_over_documents(q, documents)
        return JSONResponse(
            {
                "answer": answer,
                "sources": [
                    {"n": index, "id": document["id"], "title": document["title"]}
                    for index, document in enumerate(documents, 1)
                ],
            }
        )
    except llm.LLMUnavailable as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
    finally:
        conn.close()


@app.post("/api/llm/rephrase")
def llm_rephrase(q: str = Form(...)):
    if not llm.available():
        return JSONResponse({"error": llm.status()["reason"]}, status_code=503)
    conn = get_conn()
    try:
        vocabulary = [
            row["lemma"]
            for row in conn.execute(
                "SELECT lemma FROM terms ORDER BY df DESC LIMIT 60"
            )
        ]
        return JSONResponse({"variants": llm.rephrase_query(q, vocabulary)})
    except llm.LLMUnavailable as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
    finally:
        conn.close()


@app.post("/api/llm/explain")
def llm_explain(q: str = Form(...), doc_id: int = Form(...)):
    if not llm.available():
        return JSONResponse({"error": llm.status()["reason"]}, status_code=503)
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT title, text FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        if row is None:
            return JSONResponse({"error": "документ не найден"}, status_code=404)
        return JSONResponse(
            {"explanation": llm.explain_relevance(q, row["title"], row["text"][:2000])}
        )
    except llm.LLMUnavailable as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
    finally:
        conn.close()


# --- Компаньон и достижения -------------------------------------------------

@app.get("/api/companion")
def companion_reaction(event: str = Query("welcome"), seed: str = Query("")):
    return JSONResponse({"line": companion.line(event, seed)})


@app.get("/achievements", response_class=HTMLResponse)
def achievements_page(request: Request):
    conn = get_conn()
    try:
        companion.expire_pawned(conn)
        return render(
            request,
            "achievements.html",
            {
                "achievements": companion.unlocked(conn),
                "stats": db.stats(conn),
                "pawn_prices": {
                    code: companion.pawn_price(conn, code)
                    for code in companion.ACHIEVEMENTS
                },
            },
            conn=conn,
        )
    finally:
        conn.close()


@app.post("/skin")
def set_skin(skin: str = Form(...), back: str = Form("/")):
    conn = get_conn()
    try:
        companion.choose_skin(conn, skin)
        return RedirectResponse(back or "/", status_code=303)
    finally:
        conn.close()


# --- Лавка и ломбард --------------------------------------------------------

@app.get("/shop", response_class=HTMLResponse)
def shop_page(request: Request, message: str = Query("")):
    if not economy.enabled():
        return RedirectResponse("/", status_code=303)
    conn = get_conn()
    try:
        economy.ensure_start_capital(conn)
        wallet = economy.positions(conn)
        for item in wallet:
            item["personal"] = economy.personal_price(conn, item["lemma"])
            item["discount"] = economy.discount_percent(conn, item["lemma"])
        return render(
            request,
            "shop.html",
            {
                "reliefs": economy.relief_state(conn),
                "jokers": jokers.offer(conn),
                "jokers_active": jokers.active_list(conn),
                "stopwords": [
                    {
                        "word": word,
                        "price": economy.STOPWORD_PRICE,
                        "owned": economy.owns(conn, economy.stopword_code(word)),
                    }
                    for word in economy.STOPWORDS_FOR_SALE
                ],
                "wallet": sorted(wallet, key=lambda item: -item["total"]),
                "ledger": economy.ledger(conn, 15),
                "coupon": economy.owns(conn, "coupon"),
                "message": message,
                "companion_line": companion.line("shop"),
            },
            conn=conn,
        )
    finally:
        conn.close()


@app.post("/shop/buy")
def shop_buy(code: str = Form(...), price: int = Form(...)):
    conn = get_conn()
    try:
        if not economy.enabled():
            return RedirectResponse("/", status_code=303)
        if economy.owns(conn, code):
            return RedirectResponse("/shop?message=Это уже куплено", status_code=303)
        if economy.buy(conn, code, price):
            message = f"Куплено: {code}"
        else:
            message = f"Не хватает слов: нужно {economy.coupon_value(conn, price)}"
        return RedirectResponse(f"/shop?message={quote(message)}", status_code=303)
    finally:
        conn.close()


@app.post("/shop/joker")
def shop_joker(code: str = Form(...), back: str = Form("/shop")):
    conn = get_conn()
    try:
        _, message = jokers.take(conn, code)
        separator = "&" if "?" in back else "?"
        return RedirectResponse(
            f"{back}{separator}message={quote(message)}", status_code=303
        )
    finally:
        conn.close()


@app.get("/shop/pawn", response_class=HTMLResponse)
def pawn_page(request: Request, message: str = Query("")):
    if not economy.enabled():
        return RedirectResponse("/", status_code=303)
    conn = get_conn()
    try:
        return render(
            request,
            "pawn.html",
            {
                "items": companion.pawn_list(conn),
                "days": companion.PAWN_DAYS,
                "share": int(companion.PAWN_SHARE * 100),
                "message": message,
                "companion_line": companion.line("shop"),
            },
            conn=conn,
        )
    finally:
        conn.close()


@app.post("/shop/pawn/{action}")
def pawn_action(action: str, code: str = Form(...)):
    conn = get_conn()
    try:
        if action == "take":
            _, message = companion.pawn(conn, code)
        elif action == "redeem":
            _, message = companion.redeem(conn, code)
        else:
            message = "неизвестное действие"
        return RedirectResponse(f"/shop/pawn?message={quote(message)}", status_code=303)
    finally:
        conn.close()


# --- Игровые режимы ---------------------------------------------------------

@app.get("/blind", response_class=HTMLResponse)
def blind_page(request: Request, message: str = Query("")):
    if not config.COMPANION_ENABLED:
        return RedirectResponse("/", status_code=303)
    conn = get_conn()
    try:
        state = modes.blind_round(conn)
        return render(
            request,
            "blind.html",
            {
                "state": state,
                "options": modes.blind_options(conn, state) if state else [],
                "hints": modes.HINTS,
                "used_hints": state.get("hints", []) if state else [],
                "hint_text": state.get("hint_text", "") if state else "",
                "streak": modes.blind_streak(conn),
                "message": message,
                "companion_line": companion.spider_line(conn, "metrics"),
            },
            conn=conn,
        )
    finally:
        conn.close()


@app.post("/blind/answer")
def blind_answer(doc_id: int = Form(...)):
    conn = get_conn()
    try:
        result = modes.blind_answer(conn, doc_id)
        if modes.blind_streak(conn) >= 5:
            companion.unlock(conn, "blind-eye")
        return RedirectResponse(
            f"/blind?message={quote(result.get('message', ''))}", status_code=303
        )
    finally:
        conn.close()


@app.post("/blind/hint")
def blind_hint(kind: str = Form(...)):
    conn = get_conn()
    try:
        result = modes.blind_hint(conn, kind)
        return RedirectResponse(
            f"/blind?message={quote(result.get('message', ''))}", status_code=303
        )
    finally:
        conn.close()


@app.post("/blind/skip")
def blind_skip():
    conn = get_conn()
    try:
        modes.new_blind_round(conn)
        return RedirectResponse("/blind?message=Новый вопрос", status_code=303)
    finally:
        conn.close()


@app.get("/blitz", response_class=HTMLResponse)
def blitz_page(request: Request, restart: bool = Query(False)):
    if not config.COMPANION_ENABLED:
        return RedirectResponse("/", status_code=303)
    conn = get_conn()
    try:
        state = modes.blitz_round(conn, restart=restart)
        return render(
            request,
            "blitz.html",
            {
                "state": state,
                "elapsed": modes.blitz_elapsed(state) if state else 0,
                "seconds": modes.BLITZ_SECONDS,
                "tick": modes.BLITZ_TICK_COST,
                "reward": modes.BLITZ_REWARD,
                "combo": modes.blitz_combo(conn),
                "companion_line": companion.spider_line(conn, "results"),
            },
            conn=conn,
        )
    finally:
        conn.close()


@app.post("/lucky")
def lucky():
    """«Мне повезёт»: случайный документ, джекпот — если он в top-10."""
    conn = get_conn()
    try:
        if not config.COMPANION_ENABLED:
            return RedirectResponse("/", status_code=303)
        result = modes.lucky_document(conn)
        if not result:
            return RedirectResponse("/?message=Индекс пуст", status_code=303)
        if result.get("jackpot"):
            companion.unlock(conn, "lucky")
        return RedirectResponse(
            f"/doc/{result['doc_id']}?lucky={quote(result['message'])}", status_code=303
        )
    finally:
        conn.close()


@app.post("/curse/lift")
def curse_lift(q: str = Form(""), all_words: bool = Form(False),
               synonyms: bool = Form(True)):
    """«Снять проклятие»: кнопка есть всегда, независимо от наличия проклятия."""
    conn = get_conn()
    try:
        result = mischief.lift_curse(conn)
        target = result.get("query") or q
        if not target:
            return RedirectResponse("/", status_code=303)
        url = _search_url(target, all_words, synonyms)
        return RedirectResponse(f"{url}&notice={quote(result['message'])}", status_code=303)
    finally:
        conn.close()


# --- Заявление об отказе от паука (режим ARACHNE_COMPANION=0) ----------------

@app.get("/disclaimer", response_class=HTMLResponse)
def disclaimer_page(request: Request, message: str = Query("")):
    if config.COMPANION_ENABLED:
        return RedirectResponse("/", status_code=303)
    conn = get_conn()
    try:
        return render(request, "disclaimer.html", {"message": message}, conn=conn)
    finally:
        conn.close()


@app.post("/disclaimer")
def disclaimer_submit(name: str = Form(""), reason: str = Form(""), sign: str = Form("")):
    conn = get_conn()
    try:
        # достижение пишется в базу молча и всплывёт, когда паука вернут
        companion.unlock(conn, "paperwork")
        return RedirectResponse(
            "/disclaimer?message=" + quote(
                "Заявление принято к рассмотрению. "
                "Срок рассмотрения — 30 календарных дней."
            ),
            status_code=303,
        )
    finally:
        conn.close()


# --- Пасьянс ----------------------------------------------------------------

@app.get("/spider", response_class=HTMLResponse)
def spider_page(request: Request):
    """Пасьянс «Паук» — отдельная вкладка и ничего больше.

    Сервер только отдаёт страницу: и раскладка, и правила, и состояние партии
    живут в браузере. Пасьянс намеренно ни с чем не связан — он не начисляет
    слов, не открывает достижений и не попадает в статистику, поэтому хранить
    его состояние на сервере не за чем.
    """
    if not config.COMPANION_ENABLED:
        return RedirectResponse("/", status_code=303)
    conn = get_conn()
    try:
        return render(
            request,
            "spider.html",
            {"companion_line": companion.spider_line(conn, "solitaire")},
            conn=conn,
        )
    finally:
        conn.close()


# --- Справка ----------------------------------------------------------------

@app.get("/help", response_class=HTMLResponse)
def help_page(request: Request):
    conn = get_conn()
    try:
        return render(
            request, "help.html", {"patch": companion.patch_notes(conn)}, conn=conn
        )
    finally:
        conn.close()
