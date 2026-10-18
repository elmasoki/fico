"""Routes that help map a screen to its SQL: capture timeline, capture comparison,
linking several SQLs to an inventory screen at once."""
from __future__ import annotations

import json
import re
from datetime import timedelta

from flask import abort, flash, jsonify, redirect, render_template, request, url_for

from . import knowledge
from .generalize import Generalized, generalize
from .sessions import breakdown, filter_records
from .sqlutil import format_sql
from .sources import AuditFilter
from .store import fmt_ts, parse_ts
from .timeline import build_steps
from .trace import trace
from .views import bp, stream_csv
from .web import (capture_analysis, capture_or_404, capture_schema, ctx, ext, get_catalog, log, parse_key,
                  project_analysis, schema_relations)


def _wants_json() -> bool:
    return request.headers.get("X-Requested-With") == "fetch" or request.accept_mimetypes.best == "application/json"


def marker_now(capture) -> str:
    """Current DB time on the same clock as the capture's audit records (UTC, local for the cursor cache)."""
    now_utc, now_local = ctx()[1].now()
    return fmt_ts(now_local if capture["source"] == "cursor_cache" else now_utc)


# --------------------------------------------------------------------------- markers

@bp.post("/captures/<int:capture_id>/markers")
def capture_marker_add(capture_id):
    """Drop a note on the capture's clock: live while recording, or before a timeline step afterwards."""
    _, _, store = ctx()
    capture = capture_or_404(capture_id)
    label = (request.form.get("label") or "").strip()[:200]
    if not label:
        if _wants_json():
            return jsonify({"error": "İşaret metni boş."}), 400
        flash("İşaret metni boş.", "error")
        return redirect(request.referrer or url_for(".capture_timeline", capture_id=capture_id))
    before = request.form.get("before")
    try:
        if before:
            ts = fmt_ts(parse_ts(before) - timedelta(microseconds=1))   # just before the step's first SQL
        else:
            ts = marker_now(capture)
    except Exception as exc:
        if _wants_json():
            return jsonify({"error": "Veritabanı saati alınamadı: %s" % exc}), 502
        flash("Veritabanı saati alınamadı: %s" % exc, "error")
        return redirect(request.referrer or url_for(".capture", capture_id=capture_id))
    marker_id = store.add_marker(capture_id, ts, label)
    if _wants_json():
        return jsonify({"id": marker_id, "ts": ts, "label": label, "time": ts[11:19]})
    return redirect(request.referrer or url_for(".capture_timeline", capture_id=capture_id))


@bp.post("/captures/markers/<int:marker_id>")
def capture_marker_edit(marker_id):
    _, _, store = ctx()
    marker = store.get_marker(marker_id) or abort(404)
    if request.form.get("action") == "delete":
        store.delete_marker(marker_id)
    elif (request.form.get("label") or "").strip():
        store.update_marker(marker_id, request.form["label"].strip()[:200])
    if _wants_json():
        return jsonify({"ok": True})
    return redirect(request.referrer or url_for(".capture_timeline", capture_id=marker["capture_id"]))


# --------------------------------------------------------------------------- sources (other users mixing in)

@bp.post("/captures/<int:capture_id>/sources")
def capture_sources(capture_id):
    """Keep only the ticked sources in the capture's analysis."""
    _, _, store = ctx()
    capture = capture_or_404(capture_id)
    all_keys = [s.key for s in breakdown(store.records(capture_id))]
    keep = set(request.form.getlist("keep"))
    excluded = [k for k in all_keys if k not in keep]
    if all_keys and len(excluded) == len(all_keys):
        flash("En az bir kaynak analizde kalmalı.", "error")
        return redirect(url_for(".capture", capture_id=capture_id) + "#sources")
    store.update_capture(capture_id, excluded_sources=json.dumps(excluded, ensure_ascii=False))
    log("capture_sources", "%s: %d kaynak ayıklandı" % (capture["name"], len(excluded)))
    flash("Analiz %d kaynakla yenilendi%s." % (len(all_keys) - len(excluded),
                                              ", %d kaynak ayıklandı" % len(excluded) if excluded else ""), "ok")
    return redirect(url_for(".capture", capture_id=capture_id) + "#sources")


@bp.route("/captures/activity")
def capture_activity_check():
    """Before recording: has anyone used these DB users in the last few minutes?"""
    settings, oracle, _ = ctx()
    users = [u.strip().upper() for u in request.args.get("users", "").replace(";", ",").split(",") if u.strip()]
    users = users or [settings.siron_db_user]
    minutes = max(1, min(request.args.get("minutes", 5, type=int), 60))
    try:
        now_utc, now_local = oracle.now()
        span = timedelta(minutes=minutes)
        rows = oracle.fetch_records(AuditFilter(users, now_utc - span, now_utc, now_local - span, now_local,
                                                max_rows=5000), source=request.args.get("source") or settings.audit_source)
    except Exception as exc:
        return jsonify({"error": str(exc)})
    sources = breakdown(rows)
    return jsonify({"minutes": minutes, "users": users, "records": len(rows),
                    "sources": [{"label": s.label, "records": s.records, "sessions": len(s.sessions),
                                 "last": (s.last_ts or "")[11:19]} for s in sources]})


@bp.route("/captures/<int:capture_id>/timeline")
def capture_timeline(capture_id):
    _, _, store = ctx()
    capture = capture_or_404(capture_id)
    ca = capture_analysis(capture, exclude_noise=False)
    gap = max(0.2, min(request.args.get("gap", 2.0, type=float), 120.0))
    hide_noise = request.args.get("noise", "1") == "1" and not capture["is_noise"]
    noise_ids = store.noise_sql_ids() if not capture["is_noise"] else set()
    records = store.records(capture_id)
    kept = filter_records(records, capture.get("excluded_sources") or ())
    steps = build_steps(kept, {st.sql_id: st.tables for st in ca.statements}, gap, noise_ids, hide_noise,
                        store.markers(capture_id))
    sources = breakdown(kept)
    main_source = sources[0].key if sources else ""
    return render_template("capture_timeline.html", capture=capture, ca=ca, steps=steps, gap=gap,
                           excluded_count=len(records) - len(kept), main_source=main_source,
                           source_labels={src.key: src.label for src in sources} if len(sources) > 1 else {},
                           hide_noise=hide_noise, noise_count=len(noise_ids), screens=store.list_screens(),
                           linked={l["sql_id"] for l in store.screen_sqls(capture_id=capture_id)}, tab="timeline")


@bp.post("/inventory/sql/bulk")
def screen_sql_link_bulk():
    """Link the ticked SQLs of one capture to a screen."""
    _, _, store = ctx()
    form = request.form
    capture = capture_or_404(form.get("capture_id", type=int) or 0)
    sql_ids = list(dict.fromkeys(s for s in form.getlist("sql") if s))
    screen_id = form.get("screen_id", type=int)
    new_name = (form.get("new_screen") or "").strip()
    if new_name:
        module, _, name = new_name.rpartition(">")
        screen_id = store.add_screen(name.strip(), module.strip() or None)
    if not sql_ids or not screen_id or not store.get_screen(screen_id):
        flash("SQL seçin ve bir ekran belirtin.", "error")
        return redirect(request.referrer or url_for(".capture_timeline", capture_id=capture["id"]))
    for sql_id in sql_ids:
        store.link_sql(screen_id, capture["id"], sql_id, form.get("note"))
    if not capture.get("screen_id"):
        store.update_capture(capture["id"], screen_id=screen_id)
    flash("%d SQL ekrana bağlandı: %s" % (len(sql_ids), store.get_screen(screen_id)["name"]), "ok")
    return redirect(request.referrer or url_for(".screen_page", screen_id=screen_id))


@bp.route("/captures/compare")
def captures_compare():
    """What differs between two captures: tables, SQL patterns and columns only one of them touched."""
    _, _, store = ctx()
    ids = request.args.getlist("c", type=int)[:2]
    done = [c for c in store.list_captures() if c["status"] == "done"]
    if len(ids) < 2:
        return render_template("capture_compare.html", a=None, b=None, captures=done, ids=ids)
    a, b = capture_or_404(ids[0]), capture_or_404(ids[1])
    ca_a, ca_b = capture_analysis(a), capture_analysis(b)

    def tables(ca):
        return {t.key: t for t in ca.tables}

    def patterns(ca):
        out = {}
        for st in ca.statements:
            out.setdefault(st.signature or st.sql_id, st)
        return out

    ta, tb = tables(ca_a), tables(ca_b)
    pa, pb = patterns(ca_a), patterns(ca_b)
    cols_a, cols_b = set(ca_a.columns), set(ca_b.columns)
    diff = {
        "tables": {"a": sorted(ta.keys() - tb.keys(), key=lambda k: k[1]),
                   "both": sorted(ta.keys() & tb.keys(), key=lambda k: k[1]),
                   "b": sorted(tb.keys() - ta.keys(), key=lambda k: k[1])},
        "sql": {"a": [pa[k] for k in pa.keys() - pb.keys()], "both": [pa[k] for k in pa.keys() & pb.keys()],
                "b": [pb[k] for k in pb.keys() - pa.keys()]},
        "columns": {"a": sorted(cols_a - cols_b, key=lambda c: tuple(x or "" for x in c)),
                    "b": sorted(cols_b - cols_a, key=lambda c: tuple(x or "" for x in c)),
                    "both": len(cols_a & cols_b)},
    }
    for side in ("a", "both", "b"):
        diff["sql"][side].sort(key=lambda st: st.first_ts)
    return render_template("capture_compare.html", a=a, b=b, diff=diff, captures=done, ids=ids)


# --------------------------------------------------------------------------- screen query -> extraction query

def _extract_page(gen, sql, schema, *, capture=None, st=None, query=None, defaults=None):
    """Shared by the 'from a captured SQL' and 'saved query' pages: count, preview, CSV, save."""
    settings, oracle, store = ctx()
    form = request.form
    do = form.get("do")
    result = count = error = None
    if do in ("count", "preview", "csv") and not sql.strip():
        error = "Sorgu boş."
    elif do == "csv":
        name = (form.get("name") or (st.sql_id if st else "sorgu")).strip()
        log("extract_query", "CSV: %s" % name, sql)
        return stream_csv(sql, "%s.csv" % re.sub(r"[^\w.-]+", "_", name)[:60], schema, form.get("mask"))
    elif do == "count":
        try:
            count = oracle.run_select("SELECT COUNT(*) AS satir FROM (%s)" % sql.strip().rstrip(";"), schema=schema)[1][0][0]
        except Exception as exc:
            error = str(exc)
    elif do == "preview":
        try:
            result = oracle.run_select(sql, max_rows=50, schema=schema)
            log("extract_query", "Önizleme", sql, len(result[1]))
        except Exception as exc:
            error = str(exc)
    elif do == "save":
        name = (form.get("name") or "").strip() or (st.sql_id if st else "Ekran sorgusu")
        screen_id = form.get("screen_id", type=int)
        if query:
            store.update_extract_query(query["id"], name, sql, form.get("note"))
            qid = query["id"]
        else:
            qid = store.add_extract_query(name, sql, screen_id, capture["id"] if capture else None,
                                          st.sql_id if st else None, gen.removed, form.get("note"))
        log("extract_query", "Taşıma paketine eklendi: %s" % name, sql)
        flash("Taşıma paketine eklendi: %s" % name, "ok")
        return redirect(url_for(".extract_query_page", query_id=qid))
    elif do == "delete" and query:
        store.delete_extract_query(query["id"])
        flash("Ekran sorgusu taşıma paketinden çıkarıldı.", "ok")
        return redirect(url_for(".migration") + "#queries")
    return render_template("extract_query.html", gen=gen, sql=sql, schema=schema, capture=capture, st=st,
                           query=query, defaults=defaults or {}, result=result, count=count, error=error,
                           screens=store.list_screens())


@bp.route("/captures/<int:capture_id>/sql/<sql_id>/extract", methods=["GET", "POST"])
def statement_extract(capture_id, sql_id):
    _, _, store = ctx()
    capture = capture_or_404(capture_id)
    st = capture_analysis(capture, exclude_noise=False).statement(sql_id) or abort(404)
    gen = generalize(st.sql_text)
    sql = request.form.get("sql") or (format_sql(gen.sql) if not gen.error else "")
    links = store.screen_sqls(capture_id=capture_id, sql_id=sql_id)
    screen_id = links[0]["screen_id"] if links else capture.get("screen_id")
    screen = store.get_screen(screen_id) if screen_id else None
    name = " · ".join(x for x in [(screen or {}).get("name"), (links[0]["note"] if links else None) or sql_id] if x)
    return _extract_page(gen, sql, capture_schema(capture), capture=capture, st=st,
                         defaults={"name": name, "screen_id": screen_id, "note": links[0]["note"] if links else ""})


@bp.route("/migration/queries/<int:query_id>", methods=["GET", "POST"])
def extract_query_page(query_id):
    settings, _, store = ctx()
    query = store.get_extract_query(query_id) or abort(404)
    capture = store.get_capture(query["capture_id"]) if query["capture_id"] else None
    st = capture_analysis(capture, exclude_noise=False).statement(query["sql_id"]) if capture and query["sql_id"] else None
    gen = generalize(st.sql_text) if st else Generalized(query["sql_text"], query["removed"], [], [])
    sql = request.form.get("sql") or query["sql_text"]
    schema = capture_schema(capture) if capture else settings.current_schema
    return _extract_page(gen, sql, schema, capture=capture, st=st, query=query,
                         defaults={"name": query["name"], "screen_id": query["screen_id"], "note": query["note"] or ""})


@bp.post("/inventory/<int:screen_id>/extract")
def screen_extract_all(screen_id):
    """Generalise every linked SELECT of a screen and add it to the migration package."""
    _, _, store = ctx()
    screen = store.get_screen(screen_id) or abort(404)
    added = skipped = 0
    for link in store.screen_sqls(screen_id=screen_id):
        gen = generalize(link["sql_text"] or "")
        if gen.error:
            skipped += 1
            continue
        name = "%s · %s" % (screen["name"], link["note"] or link["sql_id"])
        store.add_extract_query(name, format_sql(gen.sql), screen_id, link["capture_id"], link["sql_id"], gen.removed,
                                link["note"])
        added += 1
    log("extract_query", "%s: %d ekran sorgusu üretildi" % (screen["name"], added))
    flash("%d ekran sorgusu taşıma paketine eklendi%s." % (added, ", %d SELECT olmayan atlandı" % skipped if skipped else ""),
          "ok" if added else "error")
    return redirect(url_for(".screen_page", screen_id=screen_id) + "#extract")


# --------------------------------------------------------------------------- record trace

@bp.route("/trace", methods=["GET", "POST"])
def record_trace():
    """Find every table that holds data about one known record (customer, account ...)."""
    settings, oracle, store = ctx()
    catalog = get_catalog()
    if request.method == "POST":
        value = (request.form.get("value") or "").strip()
        if not value:
            flash("İzlenecek değeri yazın (ör. bir müşteri numarası).", "error")
            return redirect(url_for(".record_trace"))
        if not catalog:
            flash("Önce veri sözlüğünü yükleyin.", "error")
            return redirect(url_for(".record_trace"))
        depth = max(0, min(request.form.get("depth", 2, type=int), 3))
        include_big = bool(request.form.get("include_big"))
        start = (request.form.get("start") or "").strip().upper()
        only = None
        if start:
            owner_table, _, col = start.rpartition(".")
            owner, name = parse_key(owner_table) if owner_table else (None, "")
            key = catalog.resolve(owner, name, settings.current_schema) if name else None
            if not key or not col or not catalog.column(key, col):
                flash("Başlangıç kolonu TABLO.KOLON biçiminde olmalı ve veri sözlüğünde bulunmalı.", "error")
                return redirect(url_for(".record_trace"))
            only = [(key, col)]
        relations = schema_relations(50)
        captured = set(project_analysis().tables)

        def work(job):
            result = trace(lambda sql, binds, n: oracle.run_select(sql, max_rows=n, binds=binds, timeout_sec=60)[:2],
                           catalog, relations, value, depth=depth, big_rows=settings.big_table_rows,
                           include_big=include_big, only=only, progress=lambda p, m: job.progress(p, m))
            for h in result["hits"]:
                h["captured"] = (h["owner"], h["name"]) in captured or (None, h["name"]) in captured
            store.log("trace", "Kayıt izi '%s': %d tablo" % (value, len(result["hits"])))
            job.message = "%d tabloda bulundu (%d kolon arandı)" % (len(result["hits"]), result["searched"])
            return result

        job_id = ext()["jobs"].submit("trace", "Kayıt izi: %s" % value, work, {"value": value, "depth": depth})
        return redirect(url_for(".job", job_id=job_id))
    runs = store.list_jobs(30, "trace")
    return render_template("trace.html", runs=runs, has_catalog=bool(catalog),
                           indexed=bool(catalog and catalog.indexed))


@bp.route("/trace/<int:job_id>")
def record_trace_result(job_id):
    store = ctx()[2]
    job = store.get_job(job_id)
    if not job or job["kind"] != "trace":
        abort(404)
    if job["status"] != "done":
        return redirect(url_for(".job", job_id=job_id))
    result = job["result"] or {}
    hits = result.get("hits", [])
    for h in hits:
        h["research"] = knowledge.classify(h["name"])
    return render_template("trace_result.html", job=job, result=result, hits=hits,
                           by_depth=[[h for h in hits if h["depth"] == d] for d in range(result.get("depth", 2) + 1)])
