"""Веб-интерфейс ИПС «Арахна» — третий компонент системы (поисковый механизм).

Интерфейс и есть та часть, где по варианту 3 реализуются элементы
искусственного интеллекта: разбор естественно-языкового запроса, подсказки,
исправление опечаток, расширение синонимами, обратная связь по релевантности
и объяснение выдачи.
"""

from __future__ import annotations

import csv
import io
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

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

from .. import APP_NAME, __version__, companion, config, crawler, db, indexer
from ..ai import feedback as fb
from ..ai import llm, suggest
from ..evaluation import plots, qrels, runner
from ..search import Search
from ..text import snippets
from ..text.morphology import lemma

app = FastAPI(title=f"ИПС «{APP_NAME}»", version=__version__)
app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))


# --- Подключение к базе -----------------------------------------------------

def get_conn() -> sqlite3.Connection:
    conn = db.connect()
    db.init_db(conn)
    return conn


def render(request: Request, template: str, context: dict) -> HTMLResponse:
    """Общий контекст всех страниц."""
    context.setdefault("app_name", APP_NAME)
    context.setdefault("version", __version__)
    context.setdefault("companion_enabled", config.COMPANION_ENABLED)
    context.setdefault("companion_name", config.COMPANION_NAME)
    context.setdefault("llm", llm.status())
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
        return render(
            request,
            "search.html",
            {
                "stats": statistics,
                "popular": suggest.popular_queries(conn, 6),
                "recent": suggest.recent_queries(conn, 6),
                "sources": crawler.list_sources(conn),
                "companion_line": companion.line("welcome"),
                "collection_ready": config.COLLECTION_DIR.exists(),
            },
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
):
    conn = get_conn()
    try:
        query_text = q.strip()
        if not query_text:
            return RedirectResponse("/", status_code=303)

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
        )
        if positive or negative:
            base_vector = engine.get_search_query_vector()
            engine.rocchio_vector = fb.rocchio_vector(conn, base_vector, positive, negative)

        results = engine.get_search_result()

        per_page = config.RESULTS_PER_PAGE
        pages = max(1, (len(results) + per_page - 1) // per_page)
        page = min(page, pages)
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
                "companion_line": companion.react_to_search(
                    query_text, len(results), bool(analysis.corrections), repeated
                ),
                "new_achievements": new_achievements,
            },
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
def document(request: Request, doc_id: int, q: str = Query("")):
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
        companion.check_after_open_document(conn)

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
                "companion_line": companion.line("document", seed=str(doc_id)),
            },
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

@app.post("/feedback")
def post_feedback(
    q: str = Form(...),
    doc_id: int = Form(...),
    mark: int = Form(...),
    all_words: bool = Form(False),
    synonyms: bool = Form(True),
):
    conn = get_conn()
    try:
        fb.record(conn, q, doc_id, mark)
        params = f"?q={q}&all_words={str(all_words).lower()}&synonyms={str(synonyms).lower()}"
        return RedirectResponse(f"/search{params}", status_code=303)
    finally:
        conn.close()


@app.post("/feedback/clear")
def clear_feedback(q: str = Form(...)):
    conn = get_conn()
    try:
        fb.clear(conn, q)
        return RedirectResponse(f"/search?q={q}", status_code=303)
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
            },
        )
    finally:
        conn.close()


@app.get("/metrics/compare", response_class=HTMLResponse)
def metrics_compare(request: Request, top_k: int = Query(20, ge=1, le=100)):
    conn = get_conn()
    try:
        comparison = runner.compare_configurations(conn, top_k=top_k)
        return render(
            request,
            "compare.html",
            {"comparison": comparison, "top_k": top_k,
             "companion_line": companion.line("metrics")},
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
        if current is not None:
            judgements = qrels.rel_map(conn, current["id"])
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
            },
        )
    finally:
        conn.close()


@app.post("/qrels/judge")
def judge(query_id: int = Form(...), doc_id: int = Form(...), rel: int = Form(...)):
    conn = get_conn()
    try:
        if rel < 0:
            qrels.remove_judgement(conn, query_id, doc_id)
        else:
            qrels.set_judgement(conn, query_id, doc_id, rel)
        return RedirectResponse(f"/qrels?query_id={query_id}", status_code=303)
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
        return render(
            request,
            "achievements.html",
            {"achievements": companion.unlocked(conn), "stats": db.stats(conn)},
        )
    finally:
        conn.close()


# --- Справка ----------------------------------------------------------------

@app.get("/help", response_class=HTMLResponse)
def help_page(request: Request):
    return render(request, "help.html", {})
