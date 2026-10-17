"""Flask routes: captures, statements and the SQL runner."""
from __future__ import annotations

import csv
import io
from datetime import datetime

from flask import (Blueprint, Response, abort, flash, jsonify, redirect, render_template, request,
                   stream_with_context, url_for)

from .catalog import label
from .finder import MODES, mask_rows, sample_sql, scan_result, searchable_columns, table_search_sql
from .sources import AuditFilter
from .sqlinsight import USAGE_LABELS, analyse_sql, map_result_columns
from .sqlutil import BindSlot, build_slots, find_placeholders, format_sql, parse_audit_binds, substitute_binds
from .store import parse_ts
from .web import (STATUSES, ann, capture_analysis, capture_or_404, ctx, get_catalog, literal_for,
                  relations_for)

bp = Blueprint("siron", __name__)


@bp.record_once
def _globals(state):
    state.app.jinja_env.globals.update(STATUSES=STATUSES, USAGE_LABELS=USAGE_LABELS, label=label,
                                       format_sql=format_sql, ann=ann)


@bp.app_context_processor
def _inject():
    return {"settings": ctx()[0]}


@bp.app_template_filter("thousands")
def _thousands(value):
    if value is None or value == "":
        return ""
    try:
        return format(int(value), ",").replace(",", ".")
    except (TypeError, ValueError):
        return value


def _filter_for(capture, end_utc=None, end_local=None, max_rows=None) -> AuditFilter:
    settings, _, _ = ctx()
    return AuditFilter(
        db_user=capture["db_user"],
        start_utc=parse_ts(capture["start_utc"]),
        end_utc=end_utc or parse_ts(capture["end_utc"]),
        start_local=parse_ts(capture["start_local"]),
        end_local=end_local or parse_ts(capture["end_local"]),
        os_user=capture["os_user"], host=capture["host"], program=capture["program"],
        client_id=capture["client_id"], max_rows=max_rows or settings.max_audit_rows)


def _load_and_store(capture_id: int, flush: bool) -> None:
    settings, oracle, store = ctx()
    capture = store.get_capture(capture_id)
    records = oracle.fetch_records(_filter_for(capture), flush=flush)
    store.replace_records(capture_id, records)
    msg = None
    if len(records) >= settings.max_audit_rows:
        msg = "Kayıt sınırına (%d) ulaşıldı; zaman aralığını daraltın." % settings.max_audit_rows
    store.update_capture(capture_id, message=msg)
    flash("%d audit kaydı alındı." % len(records), "ok")


def _parse_local(text: str) -> datetime:
    text = text.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    raise ValueError(text)


# --------------------------------------------------------------------------- home / setup

@bp.route("/")
def index():
    _, _, store = ctx()
    captures = store.list_captures()
    recording = [c for c in captures if c["status"] == "recording"]
    catalog = get_catalog()
    return render_template("index.html", captures=captures, recording=recording,
                           catalog_tables=len(catalog.tables) if catalog else 0,
                           catalog_version=store.get_meta("catalog_version"),
                           snapshot_count=len(store.snapshots()))


@bp.route("/check")
def check():
    _, oracle, _ = ctx()
    return render_template("check.html", checks=oracle.diagnostics())


@bp.post("/catalog/refresh")
def refresh_catalog():
    settings, oracle, store = ctx()
    try:
        data = oracle.load_catalog(settings.schemas)
        store.replace_catalog(data)
        flash("Veri sözlüğü yüklendi: %d nesne, %d tablo/view, %d kolon, %d constraint (%s)." % (
            len(data["objects"]), len(data["tables"]), len(data["columns"]), len(data["constraints"]),
            ", ".join(settings.schemas)), "ok")
    except Exception as exc:
        flash("Veri sözlüğü alınamadı: %s" % exc, "error")
    return redirect(request.referrer or url_for(".index"))


# --------------------------------------------------------------------------- captures

@bp.post("/captures")
def start_capture():
    settings, oracle, store = ctx()
    form = request.form
    try:
        now_utc, now_local = oracle.now()
    except Exception as exc:
        flash("Oracle'a bağlanılamadı: %s" % exc, "error")
        return redirect(url_for(".index"))
    capture_id = store.create_capture(
        name=form.get("name", "").strip() or "Adsız ekran", notes=form.get("notes"),
        source=settings.audit_source,
        db_user=form.get("db_user", "").strip().upper() or settings.siron_db_user,
        os_user=form.get("os_user", "").strip(), host=form.get("host", "").strip(),
        program=form.get("program", "").strip(), client_id=form.get("client_id", "").strip(),
        start_utc=now_utc, start_local=now_local)
    return redirect(url_for(".capture", capture_id=capture_id))


@bp.post("/captures/range")
def capture_from_range():
    """Create a capture for a past time window (DB local time)."""
    settings, oracle, store = ctx()
    form = request.form
    try:
        start_local, end_local = _parse_local(form["start"]), _parse_local(form["end"])
    except (KeyError, ValueError):
        flash("Başlangıç/bitiş zamanı YYYY-AA-GG SS:DD[:ss] biçiminde olmalı.", "error")
        return redirect(url_for(".index"))
    try:
        start_utc, end_utc = oracle.local_to_utc(start_local), oracle.local_to_utc(end_local)
        capture_id = store.create_capture(
            name=form.get("name", "").strip() or "Zaman aralığı", notes=form.get("notes"),
            source=settings.audit_source,
            db_user=form.get("db_user", "").strip().upper() or settings.siron_db_user,
            os_user=form.get("os_user", "").strip(), host=form.get("host", "").strip(),
            program=form.get("program", "").strip(), client_id=form.get("client_id", "").strip(),
            start_utc=start_utc, start_local=start_local, end_utc=end_utc,
            end_local=end_local, status="done")
        _load_and_store(capture_id, flush=False)
    except Exception as exc:
        flash("Kayıtlar alınamadı: %s" % exc, "error")
        return redirect(url_for(".index"))
    return redirect(url_for(".capture", capture_id=capture_id))


@bp.route("/captures/<int:capture_id>")
def capture(capture_id):
    _, _, store = ctx()
    capture = capture_or_404(capture_id)
    if capture["status"] == "recording":
        return render_template("recording.html", capture=capture)
    exclude_noise = request.args.get("noise", "1") == "1" and not capture["is_noise"]
    ca = capture_analysis(capture, exclude_noise)
    records = store.records(capture_id)
    actions = {}
    for r in records:
        actions[r["action"] or "?"] = actions.get(r["action"] or "?", 0) + 1
    relations = relations_for(ca.table_keys, ca.insights) if ca.tables else []
    return render_template("capture.html", capture=capture, ca=ca, record_count=len(records),
                           actions=sorted(actions.items()), exclude_noise=exclude_noise,
                           noise_count=len(store.noise_sql_ids()) if exclude_noise else 0,
                           has_catalog=bool(get_catalog()), relations=relations,
                           annotations=store.annotations(), tab="overview")


@bp.route("/captures/<int:capture_id>/columns")
def capture_columns(capture_id):
    capture = capture_or_404(capture_id)
    ca = capture_analysis(capture)
    catalog = get_catalog()
    by_table = {}
    for col, cu in sorted(ca.columns.items(), key=lambda kv: tuple(x or "" for x in kv[0])):
        info = catalog.column(col[:2], col[2]) if catalog else None
        by_table.setdefault(col[:2], []).append((col, cu, info))
    stars = sorted({label(k) for st in ca.statements for k in st.insight.star_tables})
    return render_template("capture_columns.html", capture=capture, ca=ca, by_table=by_table,
                           stars=stars, annotations=ctx()[2].annotations(), tab="columns")


@bp.get("/captures/<int:capture_id>/live")
def capture_live(capture_id):
    """Preview of what the audit trail holds so far for a running capture."""
    _, oracle, _ = ctx()
    capture = capture_or_404(capture_id)
    try:
        now_utc, now_local = oracle.now()
        rows = oracle.fetch_records(_filter_for(capture, now_utc, now_local, max_rows=500))
    except Exception as exc:
        return jsonify({"error": str(exc)})
    with_sql = [r for r in rows if r.get("sql_text")]
    return jsonify({
        "count": len(rows), "capped": len(rows) >= 500,
        "last": [{"ts": r["ts"][11:19], "action": r["action"], "sql": (r["sql_text"] or "")[:160]}
                 for r in with_sql[-15:]],
    })


@bp.post("/captures/<int:capture_id>/stop")
def stop_capture(capture_id):
    settings, oracle, store = ctx()
    capture = capture_or_404(capture_id)
    if capture["status"] == "recording":
        try:
            now_utc, now_local = oracle.now()
        except Exception as exc:
            flash("Oracle'a bağlanılamadı: %s" % exc, "error")
            return redirect(url_for(".capture", capture_id=capture_id))
        store.finish_capture(capture_id, now_utc, now_local)
    try:
        _load_and_store(capture_id, flush=settings.flush_unified_on_stop)
    except Exception as exc:
        flash("Audit kayıtları alınamadı: %s. 'Yeniden çek' ile tekrar deneyin." % exc, "error")
    return redirect(url_for(".capture", capture_id=capture_id))


@bp.post("/captures/<int:capture_id>/refetch")
def refetch_capture(capture_id):
    settings, _, _ = ctx()
    capture_or_404(capture_id)
    try:
        _load_and_store(capture_id, flush=settings.flush_unified_on_stop)
    except Exception as exc:
        flash("Audit kayıtları alınamadı: %s" % exc, "error")
    return redirect(url_for(".capture", capture_id=capture_id))


@bp.post("/captures/<int:capture_id>/update")
def update_capture(capture_id):
    _, _, store = ctx()
    capture = capture_or_404(capture_id)
    form = request.form
    if "toggle_noise" in form:
        store.update_capture(capture_id, is_noise=0 if capture["is_noise"] else 1)
    else:
        store.update_capture(capture_id, name=form.get("name") or capture["name"], notes=form.get("notes"))
    return redirect(url_for(".capture", capture_id=capture_id))


@bp.post("/captures/<int:capture_id>/delete")
def delete_capture(capture_id):
    ctx()[2].delete_capture(capture_id)
    flash("Yakalama silindi.", "ok")
    return redirect(url_for(".index"))


# --------------------------------------------------------------------------- value finder

@bp.route("/captures/<int:capture_id>/find", methods=["GET", "POST"])
def capture_find(capture_id):
    settings, oracle, _ = ctx()
    capture = capture_or_404(capture_id)
    ca = capture_analysis(capture)
    catalog = get_catalog()
    form = request.form
    needle = form.get("value", "").strip()
    mode = form.get("mode", "exact")
    strategy = form.get("strategy", "results")
    findings, errors, searched = [], [], 0
    if request.method == "POST" and needle:
        if strategy == "results":
            all_sets = bool(form.get("all_sets"))
            for st in ca.statements:
                if not st.is_select:
                    continue
                for ex in (st.bind_sets if all_sets else st.bind_sets[:1])[:5]:
                    literal, slots = literal_for(st.sql_text, ex.sql_binds)
                    if any(s.missing for s in slots):
                        continue
                    searched += 1
                    try:
                        cols, rows, _ = oracle.run_select(literal, max_rows=settings.finder_rows, timeout_sec=30)
                    except Exception as exc:
                        errors.append((st.sql_id, str(exc)))
                        break
                    sources = map_result_columns(st.insight, cols, catalog)
                    for c, first, count in scan_result(cols, rows, needle, mode):
                        findings.append({"sql_id": st.sql_id, "rec": ex.record_id, "column": cols[c],
                                         "source": sources[c], "count": count, "rows": len(rows),
                                         "sample": rows[first][c]})
        else:
            include_big = bool(form.get("include_big"))
            for t in ca.tables:
                findings_t, error, skipped = _search_table(t.key, needle, mode, include_big)
                if skipped:
                    errors.append((label(t.key), skipped))
                    continue
                searched += 1
                if error:
                    errors.append((label(t.key), error))
                findings.extend(findings_t)
    return render_template("capture_find.html", capture=capture, ca=ca, needle=needle, mode=mode,
                           strategy=strategy, findings=findings, errors=errors, searched=searched,
                           modes=MODES, posted=request.method == "POST", tab="find")


def _search_table(key, needle, mode, include_big=False):
    """([findings], error, skipped_reason) for one table."""
    settings, oracle, _ = ctx()
    catalog = get_catalog()
    table = catalog.tables.get(key) if catalog else None
    if table is None:
        return [], None, "veri sözlüğünde yok"
    if not include_big and (table.num_rows or 0) > settings.big_table_rows:
        return [], None, "büyük tablo (%s satır) atlandı" % format(table.num_rows, ",")
    cols = searchable_columns(table.columns, needle, mode)
    if not cols:
        return [], None, None
    sql, binds = table_search_sql(key, cols, needle, mode)
    try:
        _, rows, _ = oracle.run_select(sql, binds=binds, max_rows=50, timeout_sec=60)
    except Exception as exc:
        return [], str(exc), None
    out = []
    for i, col in enumerate(cols):
        count = sum(1 for r in rows if r[i] == 1)
        if count:
            out.append({"table": key, "column": col.name, "count": count, "capped": len(rows) >= 50,
                        "source": (key[0], key[1], col.name), "sample_sql": sample_sql(key, col, needle, mode)})
    return out, None, None


# --------------------------------------------------------------------------- statement

def _slots_from_form(form, base_slots):
    slots = []
    for i, base in enumerate(base_slots):
        kind = form.get("kind_%d" % i, base.kind)
        value = form.get("value_%d" % i, base.value)
        slots.append(BindSlot(base.label, base.occurrences, value,
                              missing=False if "value_%d" % i in form else base.missing, kind=kind))
    return slots


def _export_html(title, sql, cols, rows, sources, truncated, masked, extra=None):
    html = render_template("export_result.html", title=title, sql=sql, cols=cols,
                           rows=mask_rows(rows) if masked else rows, sources=sources, truncated=truncated,
                           masked=masked, extra=extra or {}, created=datetime.now().strftime("%Y-%m-%d %H:%M"))
    name = "".join(ch if ch.isalnum() else "_" for ch in title)[:60] or "sonuc"
    return Response(html, mimetype="text/html; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=%s.html" % name})


def _stream_csv(sql: str, filename: str):
    settings, oracle, _ = ctx()

    def generate():
        yield "﻿"
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=";")
        stream = oracle.stream_select(sql, settings.max_export_rows)
        writer.writerow(next(stream))
        for batch in stream:
            writer.writerows(batch)
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)
        yield buf.getvalue()

    return Response(stream_with_context(generate()), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=%s" % filename})


def _labels(sources):
    return [label(s) if s else "" for s in sources]


@bp.route("/captures/<int:capture_id>/sql/<sql_id>", methods=["GET", "POST"])
def statement(capture_id, sql_id):
    settings, oracle, store = ctx()
    capture = capture_or_404(capture_id)
    ca = capture_analysis(capture, exclude_noise=False)
    st = ca.statement(sql_id)
    if st is None:
        abort(404)
    catalog = get_catalog()

    rec_id = request.values.get("rec", type=int)
    execution = next((e for e in st.executions if e.record_id == rec_id), st.executions[0])
    placeholders = find_placeholders(st.sql_text)
    slots = build_slots(placeholders, parse_audit_binds(execution.sql_binds))
    form = request.form
    if request.method == "POST":
        slots = _slots_from_form(form, slots)
    literal = substitute_binds(st.sql_text, placeholders, slots)
    # Use the textarea only when the user edited it by hand; otherwise the
    # literal rebuilt from the (possibly changed) bind values wins.
    if (form.get("do") in ("run", "snapshot", "html", "csv") and form.get("sql_override")
            and form["sql_override"].strip() != form.get("literal_orig", "").strip()):
        literal = form["sql_override"]

    do = form.get("do")
    if do == "csv":
        return _stream_csv(literal, "%s.csv" % sql_id)
    result = error = None
    sources = []
    if do in ("run", "snapshot", "html"):
        try:
            result = oracle.run_select(literal)
            insight = st.insight if literal == substitute_binds(st.sql_text, placeholders, slots) \
                else analyse_sql(literal, catalog, settings.current_schema)
            sources = map_result_columns(insight, result[0], catalog)
        except Exception as exc:
            error = str(exc)
    if result and do == "html":
        return _export_html("%s - %s" % (capture["name"], sql_id), literal, result[0], list(result[1]),
                            _labels(sources), result[2], bool(form.get("mask")),
                            {"Ekran": capture["name"], "SQL_ID": sql_id})
    if result and do == "snapshot":
        cols, rows, truncated = result
        title = form.get("title") or "%s - %s" % (capture["name"], sql_id)
        store.add_snapshot(title, literal, cols, rows[:settings.snapshot_rows],
                           truncated or len(rows) > settings.snapshot_rows, capture_id, sql_id,
                           form.get("note"), _labels(sources))
        flash("Sonuç rapora eklendi (%d satır)." % min(len(rows), settings.snapshot_rows), "ok")

    cursor = cursor_error = None
    if request.args.get("cursor") == "1":
        try:
            cursor = oracle.cursor_info(sql_id)
        except Exception as exc:
            cursor_error = str(exc)

    relations = relations_for(st.insight.tables, [(st.sql_id, st.insight)], infer=False) \
        if st.insight.joins else []
    return render_template("statement.html", capture=capture, st=st, execution=execution,
                           slots=slots, literal=literal, result=result, error=error, sources=_labels(sources),
                           cursor=cursor, cursor_error=cursor_error, relations=relations,
                           columns=sorted(st.insight.columns.items(), key=lambda kv: tuple(x or "" for x in kv[0])),
                           missing=any(s.missing for s in slots))


@bp.route("/sql", methods=["GET", "POST"])
def sql_runner():
    settings, oracle, store = ctx()
    form = request.form
    sql = form.get("sql", request.args.get("sql", ""))
    do = form.get("do", "run")
    result = error = None
    sources = []
    if request.method == "POST" and sql.strip() and do != "edit":
        if do == "csv":
            return _stream_csv(sql, "sorgu.csv")
        try:
            result = oracle.run_select(sql)
            catalog = get_catalog()
            sources = _labels(map_result_columns(analyse_sql(sql, catalog, settings.current_schema),
                                                 result[0], catalog))
        except Exception as exc:
            error = str(exc)
        if result and do == "html":
            return _export_html(form.get("title") or "Sorgu sonucu", sql, result[0], list(result[1]),
                                sources, result[2], bool(form.get("mask")))
        if result and do == "snapshot":
            cols, rows, truncated = result
            store.add_snapshot(form.get("title") or "Sorgu", sql, cols, rows[:settings.snapshot_rows],
                               truncated or len(rows) > settings.snapshot_rows, note=form.get("note"),
                               sources=sources)
            flash("Sonuç rapora eklendi.", "ok")
    return render_template("sql.html", sql=sql, result=result, error=error, sources=sources)


# --------------------------------------------------------------------------- csv

def _csv(rows, header, filename):
    buf = io.StringIO()
    buf.write("﻿")  # Excel opens UTF-8 with Turkish characters correctly
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(header)
    writer.writerows(rows)
    return Response(buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=%s" % filename})


@bp.route("/captures/<int:capture_id>/statements.csv")
def capture_csv(capture_id):
    capture = capture_or_404(capture_id)
    ca = capture_analysis(capture)
    rows = []
    for st in ca.statements:
        ex = st.executions[0]
        literal, _ = literal_for(st.sql_text, ex.sql_binds)
        rows.append([capture["name"], st.sql_id, st.action or "", st.exec_count,
                     ", ".join(label(t) for t in st.tables),
                     ", ".join(sorted(label(c) for c in st.insight.columns)),
                     st.sql_text, ex.sql_binds or "", literal])
    return _csv(rows, ["ekran", "sql_id", "islem", "calisma_sayisi", "tablolar", "kolonlar", "sql_text",
                       "bindler", "sql_bind_yerlestirilmis"], "capture_%d.csv" % capture_id)


from . import views_catalog, views_reports  # noqa: E402,F401  (register their routes on bp)
