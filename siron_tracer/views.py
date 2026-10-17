"""Flask routes."""
from __future__ import annotations

import csv
import io
from datetime import datetime

from flask import (Blueprint, Response, abort, current_app, flash, jsonify, redirect,
                   render_template, request, url_for)

from .analysis import analyse
from .sources import AuditFilter
from .sqlutil import BindSlot, build_slots, find_placeholders, parse_audit_binds, substitute_binds
from .store import parse_ts

bp = Blueprint("siron", __name__)


def _ctx():
    ext = current_app.extensions["siron"]
    return ext["settings"], ext["oracle"], ext["store"]


@bp.app_context_processor
def _inject():
    settings, _, _ = _ctx()
    return {"settings": settings}


def _filter_for(capture, end_utc=None, end_local=None, max_rows=None) -> AuditFilter:
    settings, _, _ = _ctx()
    return AuditFilter(
        db_user=capture["db_user"],
        start_utc=parse_ts(capture["start_utc"]),
        end_utc=end_utc or parse_ts(capture["end_utc"]),
        start_local=parse_ts(capture["start_local"]),
        end_local=end_local or parse_ts(capture["end_local"]),
        os_user=capture["os_user"], host=capture["host"], program=capture["program"],
        client_id=capture["client_id"], max_rows=max_rows or settings.max_audit_rows)


def _load_and_store(capture_id: int, flush: bool) -> None:
    settings, oracle, store = _ctx()
    capture = store.get_capture(capture_id)
    records = oracle.fetch_records(_filter_for(capture), flush=flush)
    store.replace_records(capture_id, records)
    msg = None
    if len(records) >= settings.max_audit_rows:
        msg = "Kayıt sınırına (%d) ulaşıldı; zaman aralığını daraltın." % settings.max_audit_rows
    store.update_capture(capture_id, message=msg)
    flash("%d audit kaydı alındı." % len(records), "ok")


def _get_capture_or_404(capture_id):
    capture = _ctx()[2].get_capture(capture_id)
    if capture is None:
        abort(404)
    return capture


# --------------------------------------------------------------------------- pages

@bp.route("/")
def index():
    _, _, store = _ctx()
    captures = store.list_captures()
    recording = [c for c in captures if c["status"] == "recording"]
    return render_template("index.html", captures=captures, recording=recording,
                           object_count=len(store.objects()))


@bp.route("/check")
def check():
    _, oracle, _ = _ctx()
    return render_template("check.html", checks=oracle.diagnostics())


@bp.post("/objects/refresh")
def refresh_objects():
    settings, oracle, store = _ctx()
    try:
        objects = oracle.load_objects(settings.schemas)
        store.replace_objects(objects)
        flash("%d nesne yüklendi (%s)." % (len(objects), ", ".join(settings.schemas)), "ok")
    except Exception as exc:
        flash("Nesne listesi alınamadı: %s" % exc, "error")
    return redirect(request.referrer or url_for(".index"))


@bp.post("/captures")
def start_capture():
    settings, oracle, store = _ctx()
    form = request.form
    name = form.get("name", "").strip() or "Adsız ekran"
    try:
        now_utc, now_local = oracle.now()
    except Exception as exc:
        flash("Oracle'a bağlanılamadı: %s" % exc, "error")
        return redirect(url_for(".index"))
    capture_id = store.create_capture(
        name=name, notes=form.get("notes"), source=settings.audit_source,
        db_user=form.get("db_user", "").strip().upper() or settings.siron_db_user,
        os_user=form.get("os_user", "").strip(), host=form.get("host", "").strip(),
        program=form.get("program", "").strip(), client_id=form.get("client_id", "").strip(),
        start_utc=now_utc, start_local=now_local)
    return redirect(url_for(".capture", capture_id=capture_id))


def _parse_local(text: str) -> datetime:
    text = text.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    raise ValueError(text)


@bp.post("/captures/range")
def capture_from_range():
    """Create a capture for a past time window (DB local time)."""
    settings, oracle, store = _ctx()
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
    settings, _, store = _ctx()
    capture = _get_capture_or_404(capture_id)
    if capture["status"] == "recording":
        return render_template("recording.html", capture=capture)
    exclude_noise = request.args.get("noise", "1") == "1" and not capture["is_noise"]
    noise = store.noise_sql_ids() if exclude_noise else None
    objects = store.objects()
    records = store.records(capture_id)
    statements, tables = analyse(records, objects, settings.current_schema, noise)
    actions = {}
    for r in records:
        actions[r["action"] or "?"] = actions.get(r["action"] or "?", 0) + 1
    return render_template("capture.html", capture=capture, statements=statements, tables=tables,
                           record_count=len(records), actions=sorted(actions.items()),
                           exclude_noise=exclude_noise, noise_count=len(noise or ()),
                           has_objects=bool(objects))


@bp.get("/captures/<int:capture_id>/live")
def capture_live(capture_id):
    """Preview of what the audit trail holds so far for a running capture."""
    _, oracle, _ = _ctx()
    capture = _get_capture_or_404(capture_id)
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
    settings, oracle, store = _ctx()
    capture = _get_capture_or_404(capture_id)
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
    settings, _, _ = _ctx()
    _get_capture_or_404(capture_id)
    try:
        _load_and_store(capture_id, flush=settings.flush_unified_on_stop)
    except Exception as exc:
        flash("Audit kayıtları alınamadı: %s" % exc, "error")
    return redirect(url_for(".capture", capture_id=capture_id))


@bp.post("/captures/<int:capture_id>/update")
def update_capture(capture_id):
    _, _, store = _ctx()
    capture = _get_capture_or_404(capture_id)
    form = request.form
    if "toggle_noise" in form:
        store.update_capture(capture_id, is_noise=0 if capture["is_noise"] else 1)
    else:
        store.update_capture(capture_id, name=form.get("name") or capture["name"],
                             notes=form.get("notes"))
    return redirect(url_for(".capture", capture_id=capture_id))


@bp.post("/captures/<int:capture_id>/delete")
def delete_capture(capture_id):
    _ctx()[2].delete_capture(capture_id)
    flash("Yakalama silindi.", "ok")
    return redirect(url_for(".index"))


# --------------------------------------------------------------------------- statement

def _slots_from_form(form, base_slots):
    slots = []
    for i, base in enumerate(base_slots):
        kind = form.get("kind_%d" % i, base.kind)
        value = form.get("value_%d" % i, base.value)
        slots.append(BindSlot(base.label, base.occurrences, value,
                              missing=False if "value_%d" % i in form else base.missing, kind=kind))
    return slots


@bp.route("/captures/<int:capture_id>/sql/<sql_id>", methods=["GET", "POST"])
def statement(capture_id, sql_id):
    settings, oracle, store = _ctx()
    capture = _get_capture_or_404(capture_id)
    statements, _ = analyse(store.records(capture_id), store.objects(), settings.current_schema)
    st = next((s for s in statements if s.sql_id == sql_id), None)
    if st is None:
        abort(404)

    rec_id = request.values.get("rec", type=int)
    execution = next((e for e in st.executions if e.record_id == rec_id), st.executions[0])
    placeholders = find_placeholders(st.sql_text)
    slots = build_slots(placeholders, parse_audit_binds(execution.sql_binds))
    if request.method == "POST":
        slots = _slots_from_form(request.form, slots)
    literal = substitute_binds(st.sql_text, placeholders, slots)
    form = request.form
    # Use the textarea only when the user edited it by hand; otherwise the
    # literal rebuilt from the (possibly changed) bind values wins.
    if (form.get("do") == "run" and form.get("sql_override")
            and form["sql_override"].strip() != form.get("literal_orig", "").strip()):
        literal = form["sql_override"]

    result = error = None
    if request.method == "POST" and request.form.get("do") == "run":
        try:
            result = oracle.run_select(literal)
        except Exception as exc:
            error = str(exc)

    cursor = cursor_error = None
    if request.args.get("cursor") == "1":
        try:
            cursor = oracle.cursor_info(sql_id)
        except Exception as exc:
            cursor_error = str(exc)

    return render_template("statement.html", capture=capture, st=st, execution=execution,
                           slots=slots, literal=literal, result=result, error=error,
                           cursor=cursor, cursor_error=cursor_error,
                           missing=any(s.missing for s in slots))


@bp.route("/sql", methods=["GET", "POST"])
def sql_runner():
    _, oracle, _ = _ctx()
    sql = request.form.get("sql", "")
    result = error = None
    if request.method == "POST" and sql.strip():
        try:
            result = oracle.run_select(sql)
        except Exception as exc:
            error = str(exc)
    return render_template("sql.html", sql=sql, result=result, error=error)


# --------------------------------------------------------------------------- table map

def _table_map():
    settings, _, store = _ctx()
    noise = store.noise_sql_ids()
    objects = store.objects()
    usage = {}
    for c in store.list_captures():
        if c["status"] != "done" or c["is_noise"]:
            continue
        statements, tables = analyse(store.records(c["id"]), objects, settings.current_schema, noise)
        for t in tables:
            entry = usage.setdefault(t.label, {"type": t.obj_type, "screens": [], "actions": set()})
            entry["screens"].append((c, len(t.statements), t.exec_count))
            entry["actions"] |= t.actions
    return sorted(usage.items(), key=lambda kv: (-len(kv[1]["screens"]), kv[0]))


@bp.route("/tables")
def tables():
    return render_template("tables.html", usage=_table_map())


def _csv(rows, header, filename):
    buf = io.StringIO()
    buf.write("﻿")  # Excel opens UTF-8 with Turkish characters correctly
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(header)
    writer.writerows(rows)
    return Response(buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=%s" % filename})


@bp.route("/tables.csv")
def tables_csv():
    rows = []
    for label, entry in _table_map():
        for capture, n_stmt, n_exec in entry["screens"]:
            rows.append([label, entry["type"] or "", capture["name"], n_stmt, n_exec,
                         ",".join(sorted(entry["actions"]))])
    return _csv(rows, ["tablo", "tip", "ekran", "sorgu_sayisi", "calisma_sayisi", "islemler"],
                "siron_tablo_haritasi.csv")


@bp.route("/captures/<int:capture_id>/statements.csv")
def capture_csv(capture_id):
    settings, _, store = _ctx()
    capture = _get_capture_or_404(capture_id)
    noise = store.noise_sql_ids() if not capture["is_noise"] else None
    statements, _ = analyse(store.records(capture_id), store.objects(), settings.current_schema, noise)
    rows = []
    for st in statements:
        ex = st.executions[0]
        placeholders = find_placeholders(st.sql_text)
        literal = substitute_binds(st.sql_text, placeholders,
                                   build_slots(placeholders, parse_audit_binds(ex.sql_binds)))
        rows.append([capture["name"], st.sql_id, st.action or "", st.exec_count,
                     ", ".join("%s.%s" % t if t[0] else t[1] for t in st.tables),
                     st.sql_text, ex.sql_binds or "", literal])
    return _csv(rows, ["ekran", "sql_id", "islem", "calisma_sayisi", "tablolar", "sql_text",
                       "bindler", "sql_bind_yerlestirilmis"],
                "capture_%d.csv" % capture_id)
