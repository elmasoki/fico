"""Query notebook: hand-written migration queries, their history and verification cases.

The migration is expected to be done by hand from queries. Each notebook entry is
one such query ("customer master", "account balances" ...), versioned on every
change, with verification cases taken from Siron screens: bind values for one
record plus what the screen showed for it. Running the cases tells whether the
query still returns what Siron shows, and the report is the evidence for the
business unit.
"""
from __future__ import annotations

from datetime import datetime

from flask import Response, abort, flash, redirect, render_template, request, url_for

from .notebook import diff_html, expectations_from_row, parse_binds, parse_expectations, run_case
from .sqlutil import find_placeholders
from .views import bp
from .web import capture_analysis, capture_schema, ctx, ext, literal_for, log

MAX_ROWS = 1000


def _placeholders(sql: str):
    return list(dict.fromkeys(p.name for p in find_placeholders(sql or "")))


def _runner(oracle, schema):
    def run(sql, binds):
        args = binds
        if binds and all(k.isdigit() for k in binds):        # :1, :2 ... bind by position
            args = [binds[k] for k in sorted(binds, key=int)]
        return oracle.run_select(sql, max_rows=MAX_ROWS, binds=args, timeout_sec=120, schema=schema)[:2]
    return run


def _run_one(oracle, store, query, case, default_schema):
    result = run_case(_runner(oracle, query["schema_name"] or default_schema), query["sql_text"], case["binds"] or "",
                      case["expect"] or "", _placeholders(query["sql_text"]))
    store.record_case_result(case["id"], result.status, result.as_dict())
    return result


def _screen_refs(store):
    """Linked screen SQLs to take expectations from: what Siron itself ran for a recorded record."""
    return [l for l in store.screen_sqls() if (l.get("action") or "SELECT").upper() == "SELECT"][:300]


@bp.route("/notebook")
def notebook():
    settings, _, store = ctx()
    queries = store.notebook_queries()
    totals = {k: sum(q[k] for q in queries) for k in ("cases", "passed", "failed", "errors")}
    targets = sorted({q["target"] for q in queries if q["target"]})
    return render_template("notebook.html", queries=queries, totals=totals, targets=targets,
                           runs=store.list_jobs(5, "notebook"))


@bp.post("/notebook/new")
def notebook_new():
    """New query, from the notebook page or carried over from a record trace / extract page / SQL console."""
    settings, _, store = ctx()
    form = request.form
    name = (form.get("name") or form.get("title") or "").strip() or "Yeni sorgu"
    sql = (form.get("sql") or "").strip().rstrip(";")
    qid = store.add_notebook_query(name, sql, form.get("target", "").strip(), form.get("description", "").strip(),
                                   (form.get("schema") or "").strip().upper() or None)
    if form.get("case_binds") or form.get("case_expect"):
        store.add_notebook_case(qid, (form.get("case_name") or "Senaryo 1").strip(), form.get("case_binds", ""),
                                form.get("case_expect", ""))
    log("notebook", "Sorgu defterine eklendi: %s" % name, sql or None)
    flash("Sorgu defterine eklendi: %s" % name, "ok")
    return redirect(url_for(".notebook_query", query_id=qid))


@bp.route("/notebook/<int:query_id>", methods=["GET", "POST"])
def notebook_query(query_id):
    settings, oracle, store = ctx()
    query = store.get_notebook_query(query_id) or abort(404)
    form = request.form
    do = form.get("do")
    schema = query["schema_name"] or settings.current_schema
    preview = error = suggestion = None
    open_case = form.get("case_id", type=int)
    if do == "save":
        name = (form.get("name") or "").strip() or query["name"]
        sql = (form.get("sql") or "").strip().rstrip(";")
        changed = store.save_notebook_query(query_id, name, sql, form.get("target", "").strip(),
                                            form.get("description", "").strip(),
                                            (form.get("schema") or "").strip().upper() or None, form.get("note", "").strip())
        log("notebook", "Sorgu kaydedildi: %s" % name, sql if changed else None)
        flash("Kaydedildi%s." % (" · yeni sürüm oluştu, senaryoları yeniden çalıştırın" if changed else ""), "ok")
        return redirect(url_for(".notebook_query", query_id=query_id))
    if do == "restore":
        version = next((v for v in store.notebook_versions(query_id) if v["id"] == form.get("version_id", type=int)), None)
        if version:
            store.save_notebook_query(query_id, query["name"], version["sql_text"], query["target"], query["description"],
                                      query["schema_name"], "Sürüm geri yüklendi (%s)" % version["created_at"][:16])
            flash("Sürüm geri yüklendi.", "ok")
        return redirect(url_for(".notebook_query", query_id=query_id))
    if do == "delete":
        store.delete_notebook_query(query_id)
        log("notebook", "Sorgu silindi: %s" % query["name"])
        flash("Sorgu defterden silindi: %s" % query["name"], "ok")
        return redirect(url_for(".notebook"))
    if do == "preview":
        sql = query["sql_text"]
        try:
            given = parse_binds(form.get("try_binds", ""))
            wanted = _placeholders(sql)
            missing = [p for p in wanted if p not in given]
            if missing:
                raise ValueError("Bind değeri eksik: %s" % ", ".join(":" + m for m in missing))
            cols, rows = _runner(oracle, schema)(sql, {p: given[p] for p in wanted})
            preview = (cols, rows, len(rows) >= MAX_ROWS)
            log("query", "Sorgu defteri: %s" % query["name"], sql, len(rows))
        except Exception as exc:
            error = str(exc)[:500]
    if do in ("case_add", "case_save"):
        name = (form.get("case_name") or "").strip() or "Senaryo"
        _, bad = parse_expectations(form.get("case_expect", ""))
        if bad:
            flash("Okunamayan beklenti satırı: %s" % "; ".join(bad), "error")
        if do == "case_add":
            open_case = store.add_notebook_case(query_id, name, form.get("case_binds", ""), form.get("case_expect", ""),
                                                form.get("case_note", ""))
        else:
            store.update_notebook_case(open_case, name, form.get("case_binds", ""), form.get("case_expect", ""),
                                       form.get("case_note", ""))
        if form.get("and_run"):
            case = next(c for c in store.notebook_cases(query_id) if c["id"] == open_case)
            _run_one(oracle, store, query, case, settings.current_schema)
        return redirect(url_for(".notebook_query", query_id=query_id) + "#case-%d" % open_case)
    if do == "case_delete":
        store.delete_notebook_case(open_case)
        flash("Senaryo silindi.", "ok")
        return redirect(url_for(".notebook_query", query_id=query_id) + "#cases")
    if do in ("case_run", "run_all"):
        cases = [c for c in store.notebook_cases(query_id) if do == "run_all" or c["id"] == open_case]
        results = [_run_one(oracle, store, query, c, settings.current_schema) for c in cases]
        log("notebook", "Doğrulama: %s" % query["name"], rows=sum(r.status == "pass" for r in results))
        anchor = "#case-%d" % open_case if do == "case_run" else "#cases"
        if do == "run_all":
            flash("%d senaryodan %d geçti." % (len(results), sum(r.status == "pass" for r in results)),
                  "ok" if all(r.status == "pass" for r in results) else "error")
        return redirect(url_for(".notebook_query", query_id=query_id) + anchor)
    if do == "suggest":
        # Run the screen SQL with the binds Siron used and turn its first row into expectation lines.
        capture_id, _, sql_id = (form.get("ref") or "").partition(":")
        capture = store.get_capture(int(capture_id)) if capture_id.isdigit() else None
        link = next(iter(store.screen_sqls(capture_id=capture["id"], sql_id=sql_id)), None) if capture else None
        st = capture_analysis(capture, exclude_noise=False).statement(sql_id) if link else None
        if not st:
            error = "Seçilen ekran SQL'i bulunamadı."
        else:
            try:
                literal, slots = literal_for(st.sql_text, st.executions[0].sql_binds)
                cols, rows, _ = oracle.run_select(literal, max_rows=50, timeout_sec=120, schema=capture_schema(capture))
                suggestion = {"ref": link, "expect": expectations_from_row(cols, rows), "columns": cols,
                              "rows": rows[:5], "binds": [(s.label, s.value) for s in slots if not s.missing]}
            except Exception as exc:
                error = "Ekran SQL'i çalıştırılamadı: %s" % str(exc)[:300]
    query = store.get_notebook_query(query_id)
    cases = store.notebook_cases(query_id)
    versions = store.notebook_versions(query_id)
    diffs = {v["id"]: diff_html(versions[i + 1]["sql_text"], v["sql_text"]) for i, v in enumerate(versions[:-1])}
    return render_template("notebook_query.html", query=query, cases=cases, versions=versions, diffs=diffs,
                           placeholders=_placeholders(query["sql_text"]), preview=preview, error=error,
                           suggestion=suggestion, refs=_screen_refs(store), open_case=open_case, schema=schema,
                           form=form if do == "preview" else {})


@bp.post("/notebook/run")
def notebook_run():
    """Run every case of every query (or one query) as a background job."""
    settings, oracle, store = ctx()
    only = request.form.get("query_id", type=int)
    queries = [q for q in store.notebook_queries() if q["cases"] and (only is None or q["id"] == only)]
    if not queries:
        flash("Çalıştırılacak senaryo yok.", "error")
        return redirect(url_for(".notebook"))

    def work(job):
        counts = {"passed": 0, "failed": 0, "errors": 0, "queries": len(queries)}
        total = sum(q["cases"] for q in queries)
        done = 0
        for q in queries:
            for case in store.notebook_cases(q["id"]):
                job.progress(100.0 * done / max(total, 1), "%s · %s" % (q["name"], case["name"]))
                status = _run_one(oracle, store, q, case, settings.current_schema).status
                counts[{"pass": "passed", "fail": "failed"}.get(status, "errors")] += 1
                done += 1
        job.message = "%d senaryodan %d geçti" % (done, counts["passed"])
        store.log("notebook", "Sorgu defteri doğrulaması: %s" % job.message)
        return counts

    title = "Sorgu doğrulama: %s" % (queries[0]["name"] if only else "tüm defter")
    job_id = ext()["jobs"].submit("notebook", title, work, {"query_id": only})
    return redirect(url_for(".job", job_id=job_id))


@bp.route("/notebook/report.html")
def notebook_report():
    """Self-contained verification report: each query, its SQL and how its cases did."""
    _, _, store = ctx()
    only = request.args.get("query_id", type=int)
    queries = [q for q in store.notebook_queries() if only is None or q["id"] == only]
    for q in queries:
        q["case_list"] = store.notebook_cases(q["id"])
        q["version_count"] = q["versions"]
    html = render_template("notebook_report.html", queries=queries, generated=datetime.now().strftime("%Y-%m-%d %H:%M"))
    log("notebook", "Doğrulama raporu indirildi (%d sorgu)" % len(queries))
    return Response(html, mimetype="text/html", headers={
        "Content-Disposition": "attachment; filename=dogrulama_raporu_%s.html" % datetime.now().strftime("%Y%m%d_%H%M")})
