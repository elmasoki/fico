"""Flask routes: dashboard, captures, statements and the SQL console."""
from __future__ import annotations

import csv
import io
from datetime import datetime

from flask import (Blueprint, Response, abort, flash, jsonify, redirect, render_template, request,
                   stream_with_context, url_for)

from .catalog import ann, label
from .coverage import SCREEN_STATUSES, compute as compute_coverage
from .finder import MODES, sample_sql, scan_result, searchable_columns, table_search_sql
from .jobs import JOB_KINDS
from .privacy import MASK_MODES
from .sources import AuditFilter
from .sqlinsight import USAGE_LABELS, analyse_sql, map_result_columns
from .sqlutil import (BindSlot, bind_segments, build_slots, find_placeholders, format_sql, parse_audit_binds,
                      substitute_binds)
from . import knowledge
from .sessions import assess, breakdown, filter_records, is_mixed
from .trace import path_sql
from .store import parse_ts
from .web import (CAPTURE_KINDS, STATUSES, capture_analysis, capture_or_404, capture_schema, ctx, ext,
                  find_in_binds, get_catalog, is_sensitive, known_schemas, known_users, literal_for, log, masked,
                  project_analysis, project_relations, relations_for, remember)

bp = Blueprint("siron", __name__)


@bp.record_once
def _globals(state):
    state.app.jinja_env.globals.update(
        STATUSES=STATUSES, USAGE_LABELS=USAGE_LABELS, label=label, format_sql=format_sql, ann=ann,
        CAPTURE_KINDS=CAPTURE_KINDS, SCREEN_STATUSES=SCREEN_STATUSES, MASK_MODES=MASK_MODES,
        JOB_KINDS=JOB_KINDS, RCONF=knowledge.CONFIDENCE, RCONF_HELP=knowledge.CONFIDENCE_HELP,
        research_of=knowledge.classify, explain_name=knowledge.explain_text, bind_segments_for=_unbound_segments,
        trace_sql=path_sql)


def _unbound_segments(sql):
    """Formatted SQL as segments with every placeholder marked (for showing which parts are binds)."""
    return bind_segments(sql, build_slots(find_placeholders(sql), []), formatted=True)


@bp.app_context_processor
def _inject():
    store = ctx()[2]
    try:
        recording = sum(1 for c in store.list_captures() if c["status"] == "recording")
    except Exception:
        recording = 0
    return {"settings": ctx()[0], "recording_count": recording}


@bp.app_template_filter("thousands")
def _thousands(value):
    if value is None or value == "":
        return ""
    try:
        return format(int(value), ",").replace(",", ".")
    except (TypeError, ValueError):
        return value


@bp.app_template_filter("pct")
def _pct(value, digits=0):
    if value is None:
        return "—"
    return ("%%.%df" % digits % value).replace(".", ",") + "%"


@bp.app_template_filter("short_ts")
def _short_ts(value):
    return (value or "")[:16]


# --------------------------------------------------------------------------- helpers

def _filter_for(capture, end_utc=None, end_local=None, max_rows=None) -> AuditFilter:
    settings, _, _ = ctx()
    return AuditFilter(
        db_users=capture["db_users"] or [settings.siron_db_user],
        start_utc=parse_ts(capture["start_utc"]),
        end_utc=end_utc or parse_ts(capture["end_utc"]),
        start_local=parse_ts(capture["start_local"]),
        end_local=end_local or parse_ts(capture["end_local"]),
        os_user=capture["os_user"], host=capture["host"], program=capture["program"],
        client_id=capture["client_id"], max_rows=max_rows or settings.max_audit_rows)


def _load_and_store(capture_id: int, flush: bool) -> None:
    settings, oracle, store = ctx()
    capture = store.get_capture(capture_id)
    records = oracle.fetch_records(_filter_for(capture), flush=flush, source=capture["source"])
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


def _capture_fields(form) -> dict:
    """Capture options from the start / range forms (users, schema, kind, inventory link)."""
    settings, _, store = ctx()
    users = form.getlist("db_users") + [u for u in form.get("new_users", "").replace(";", ",").split(",")]
    users = list(dict.fromkeys(u.strip().upper() for u in users if u.strip())) or [settings.siron_db_user]
    schema = (form.get("new_schema") or form.get("schema") or "").strip().upper() or None
    remember("db_users", [u for u in users if u != settings.siron_db_user])
    if schema and schema not in settings.schemas:
        remember("schemas", [schema])
    name = form.get("name", "").strip()
    screen_id = form.get("screen_id", type=int)
    if screen_id:
        screen = store.get_screen(screen_id)
        name = name or (screen["name"] if screen else "")
    elif form.get("add_to_inventory") and name:
        screen_id = store.add_screen(name, form.get("module"))
    source = form.get("source") or settings.audit_source
    return {"name": name or "Adsız ekran", "notes": form.get("notes"), "source": source,
            "db_users": users, "schema": schema, "kind": form.get("kind") or "screen", "screen_id": screen_id,
            "os_user": form.get("os_user", "").strip(), "host": form.get("host", "").strip(),
            "program": form.get("program", "").strip(), "client_id": form.get("client_id", "").strip()}


def _capture_form_context():
    _, _, store = ctx()
    return {"users": known_users(), "schemas": known_schemas(), "screens": store.list_screens()}


# --------------------------------------------------------------------------- dashboard

@bp.route("/")
def index():
    settings, _, store = ctx()
    catalog = get_catalog()
    captures = store.list_captures()
    pa = project_analysis()
    rels = project_relations()
    cov = compute_coverage(pa, catalog, store.annotations(), store.list_screens(), captures, rels)
    jobs = store.list_jobs(8)
    return render_template("dashboard.html", cov=cov, pa=pa, captures=captures[:8],
                           recording=[c for c in captures if c["status"] == "recording"],
                           catalog=catalog, catalog_version=store.get_meta("catalog_version"),
                           jobs=jobs, capture_count=len(captures), relation_count=len(rels),
                           snapshot_count=len(store.snapshots()))


@bp.route("/check")
def check():
    _, oracle, _ = ctx()
    return render_template("check.html", checks=oracle.diagnostics(known_users(), known_schemas()))


@bp.post("/catalog/refresh")
def refresh_catalog():
    settings, oracle, store = ctx()
    schemas = known_schemas()

    def work(job):
        job.progress(5, "Veri sözlüğü okunuyor: %s" % ", ".join(schemas))
        data = oracle.load_catalog(schemas)
        job.progress(80, "Yerel depoya yazılıyor")
        store.replace_catalog(data)
        summary = {k: len(v) for k, v in data.items()}
        store.log("catalog", "Veri sözlüğü yüklendi (%s): %s" % (", ".join(schemas), summary))
        job.message = "%d tablo/view, %d kolon, %d constraint, %d bağımlılık" % (
            summary.get("tables", 0), summary.get("columns", 0), summary.get("constraints", 0),
            summary.get("dependencies", 0))
        return summary

    job_id = ext()["jobs"].submit("catalog", "Veri sözlüğü: %s" % ", ".join(schemas), work)
    return redirect(url_for(".job", job_id=job_id))


# --------------------------------------------------------------------------- captures

@bp.route("/captures")
def captures():
    _, _, store = ctx()
    items = store.list_captures()
    kind = request.args.get("kind", "")
    if kind == "noise":
        items = [c for c in items if c["is_noise"]]
    elif kind:
        items = [c for c in items if c["kind"] == kind and not c["is_noise"]]
    screens = {s["id"]: s for s in store.list_screens()}
    return render_template("captures.html", captures=items, kind=kind, screens_by_id=screens,
                           recording=[c for c in items if c["status"] == "recording"], **_capture_form_context())


@bp.post("/captures")
def start_capture():
    _, oracle, store = ctx()
    fields = _capture_fields(request.form)
    try:
        now_utc, now_local = oracle.now()
    except Exception as exc:
        flash("Oracle'a bağlanılamadı: %s" % exc, "error")
        return redirect(url_for(".captures"))
    capture_id = store.create_capture(start_utc=now_utc, start_local=now_local, **fields)
    return redirect(url_for(".capture", capture_id=capture_id))


@bp.post("/captures/range")
def capture_from_range():
    """Create a capture for a past time window (DB local time) - also used for batch windows."""
    _, oracle, store = ctx()
    form = request.form
    try:
        start_local, end_local = _parse_local(form["start"]), _parse_local(form["end"])
    except (KeyError, ValueError):
        flash("Başlangıç/bitiş zamanı YYYY-AA-GG SS:DD[:ss] biçiminde olmalı.", "error")
        return redirect(url_for(".captures"))
    fields = _capture_fields(form)
    try:
        start_utc, end_utc = oracle.local_to_utc(start_local), oracle.local_to_utc(end_local)
        capture_id = store.create_capture(start_utc=start_utc, start_local=start_local, end_utc=end_utc,
                                          end_local=end_local, status="done", **fields)
        _load_and_store(capture_id, flush=False)
    except Exception as exc:
        flash("Kayıtlar alınamadı: %s" % exc, "error")
        return redirect(url_for(".captures"))
    return redirect(url_for(".capture", capture_id=capture_id))


@bp.route("/captures/<int:capture_id>")
def capture(capture_id):
    _, _, store = ctx()
    capture = capture_or_404(capture_id)
    if capture["status"] == "recording":
        return render_template("recording.html", capture=capture, markers=store.markers(capture_id))
    exclude_noise = request.args.get("noise", "1") == "1" and not capture["is_noise"]
    grouped = request.args.get("group", "1") == "1"
    ca = capture_analysis(capture, exclude_noise)
    all_records = store.records(capture_id)
    sources = breakdown(all_records, capture.get("excluded_sources") or ())
    records = filter_records(all_records, capture.get("excluded_sources") or ())
    actions = {}
    for r in records:
        actions[r["action"] or "?"] = actions.get(r["action"] or "?", 0) + 1
    relations = relations_for([t.key for t in ca.tables if not t.indirect], ca.insights) if ca.tables else []
    screen = store.get_screen(capture["screen_id"]) if capture["screen_id"] else None
    return render_template("capture.html", capture=capture, ca=ca, record_count=len(records),
                           sources=sources, source_warnings=assess(sources), mixed=is_mixed(sources),
                           marker_count=len(store.markers(capture_id)),
                           actions=sorted(actions.items(), key=lambda kv: -kv[1]), exclude_noise=exclude_noise,
                           noise_count=len(store.noise_sql_ids()) if exclude_noise else 0, grouped=grouped,
                           has_catalog=bool(get_catalog()), relations=relations, screen=screen,
                           annotations=store.annotations(), tab="overview", screens=store.list_screens(),
                           schemas=known_schemas())


@bp.route("/captures/<int:capture_id>/columns")
def capture_columns(capture_id):
    capture = capture_or_404(capture_id)
    ca = capture_analysis(capture)
    catalog = get_catalog()
    annotations = ctx()[2].annotations()
    profiles = ctx()[2].profiles()
    by_table = {}
    for col, cu in sorted(ca.columns.items(), key=lambda kv: tuple(x or "" for x in kv[0])):
        info = catalog.column(col[:2], col[2]) if catalog else None
        by_table.setdefault(col[:2], []).append((col, cu, info, profiles.get(col),
                                                is_sensitive(col[:2], col[2], annotations)))
    stars = sorted({label(k) for st in ca.statements for k in st.insight.star_tables})
    return render_template("capture_columns.html", capture=capture, ca=ca, by_table=by_table,
                           stars=stars, annotations=annotations, tab="columns")


@bp.get("/captures/<int:capture_id>/live")
def capture_live(capture_id):
    """Preview of what the audit trail holds so far for a running capture."""
    _, oracle, _ = ctx()
    capture = capture_or_404(capture_id)
    try:
        now_utc, now_local = oracle.now()
        rows = oracle.fetch_records(_filter_for(capture, now_utc, now_local, max_rows=500), source=capture["source"])
    except Exception as exc:
        return jsonify({"error": str(exc)})
    with_sql = [r for r in rows if r.get("sql_text")]
    sources = breakdown(rows)
    return jsonify({
        "sources": [{"label": src.label, "records": src.records} for src in sources],
        "mixed": is_mixed(sources),
        "elapsed": max(0, int((now_utc - parse_ts(capture["start_utc"])).total_seconds())),
        "count": len(rows), "capped": len(rows) >= 500, "statements": len({r["sql_id"] for r in with_sql}),
        "last": [{"ts": r["ts"][11:19], "user": r.get("db_user"), "action": r["action"],
                  "sql": (r["sql_text"] or "")[:180]} for r in with_sql[-20:]][::-1],
    })


@bp.post("/captures/<int:capture_id>/reset")
def reset_capture(capture_id):
    """Forget everything captured so far and keep recording from the current DB time."""
    _, oracle, store = ctx()
    capture = capture_or_404(capture_id)
    if capture["status"] != "recording":
        flash("Yalnız devam eden bir yakalama sıfırlanabilir.", "error")
        return redirect(url_for(".capture", capture_id=capture_id))
    try:
        now_utc, now_local = oracle.now()
    except Exception as exc:
        flash("Oracle'a bağlanılamadı: %s" % exc, "error")
        return redirect(url_for(".capture", capture_id=capture_id))
    store.reset_capture(capture_id, now_utc, now_local)
    log("capture_reset", "%s: %s öncesi atıldı" % (capture["name"], now_local.strftime("%H:%M:%S")))
    flash("Sıfırlandı. %s öncesindeki SQL'ler atıldı, kayıt devam ediyor." % now_local.strftime("%H:%M:%S"), "ok")
    return redirect(url_for(".capture", capture_id=capture_id))


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
        schema = (form.get("schema") or "").strip().upper() or None
        store.update_capture(capture_id, name=form.get("name") or capture["name"], notes=form.get("notes"),
                             kind=form.get("kind") or capture["kind"], screen_id=form.get("screen_id", type=int),
                             schema_name=schema)
        flash("Yakalama güncellendi.", "ok")
    return redirect(url_for(".capture", capture_id=capture_id))


@bp.post("/captures/<int:capture_id>/delete")
def delete_capture(capture_id):
    store = ctx()[2]
    capture = store.get_capture(capture_id)
    if capture:
        store.delete_capture(capture_id)
        log("capture_delete", "%s (%d kayıt)" % (capture["name"], capture["record_count"] or 0))
        flash("Yakalama silindi: %s" % capture["name"], "ok")
    return redirect(url_for(".captures"))


@bp.post("/captures/delete")
def delete_captures():
    store = ctx()[2]
    ids = request.form.getlist("c", type=int)
    found = [c for c in (store.get_capture(i) for i in ids) if c]
    if not found:
        flash("Önce yakalama seçin.", "error")
        return redirect(request.referrer or url_for(".captures"))
    store.delete_captures([c["id"] for c in found])
    log("capture_delete", ", ".join(c["name"] for c in found)[:500])
    flash("%d yakalama silindi." % len(found), "ok")
    return redirect(request.referrer or url_for(".captures"))


# --------------------------------------------------------------------------- value finder

def search_tables_job(keys, needle, mode, include_big, title):
    """Submit a background job that searches `keys` for `needle`."""
    settings, oracle, store = ctx()
    catalog = get_catalog()

    def work(job):
        findings, notes = [], []
        for n, key in enumerate(keys):
            job.progress(100.0 * n / max(len(keys), 1), "%s taranıyor" % label(key))
            found, error, skipped = search_table(oracle, settings, catalog, key, needle, mode, include_big)
            if skipped or error:
                notes.append([label(key), skipped or error])
            findings.extend(found)
        store.log("search", "Değer araması '%s' (%d tablo, %d eşleşme)" % (needle, len(keys), len(findings)))
        job.message = "%d tabloda %d eşleşme" % (len(keys), len(findings))
        return {"needle": needle, "mode": mode, "findings": findings, "notes": notes, "tables": len(keys)}

    return ext()["jobs"].submit("tablesearch", title, work, {"needle": needle, "mode": mode})


def search_table(oracle, settings, catalog, key, needle, mode, include_big=False):
    """([findings], error, skipped_reason) for one table."""
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
        _, rows, _ = oracle.run_select(sql, binds=binds, max_rows=50, timeout_sec=120)
    except Exception as exc:
        return [], str(exc), None
    out = []
    for i, col in enumerate(cols):
        count = sum(1 for r in rows if r[i] == 1)
        if count:
            out.append({"table": label(key), "owner": key[0], "name": key[1], "column": col.name, "count": count,
                        "capped": len(rows) >= 50, "sample_sql": sample_sql(key, col, needle, mode)})
    return out, None, None


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
    if request.method == "POST" and needle and strategy == "tables":
        keys = [t.key for t in ca.tables]
        job_id = search_tables_job(keys, needle, mode, bool(form.get("include_big")),
                                   "Değer arama: '%s' — %s" % (needle, capture["name"]))
        return redirect(url_for(".job", job_id=job_id))
    if request.method == "POST" and needle:
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
                    cols, rows, _ = oracle.run_select(literal, max_rows=settings.finder_rows, timeout_sec=30,
                                                      schema=capture_schema(capture))
                except Exception as exc:
                    errors.append((st.sql_id, str(exc)))
                    break
                sources = map_result_columns(st.insight, cols, catalog)
                for c, first, count in scan_result(cols, rows, needle, mode):
                    findings.append({"sql_id": st.sql_id, "rec": ex.record_id, "column": cols[c],
                                     "source": sources[c], "count": count, "rows": len(rows),
                                     "sample": rows[first][c]})
        log("search", "Ekrandaki değer araması '%s' (%s): %d eşleşme" % (needle, capture["name"], len(findings)))
    bind_hits = find_in_binds(needle, capture_id, exact=mode == "exact") if needle and request.method == "POST" else []
    return render_template("capture_find.html", capture=capture, ca=ca, needle=needle, mode=mode, bind_hits=bind_hits,
                           strategy=strategy, findings=findings, errors=errors, searched=searched,
                           modes=MODES, posted=request.method == "POST", tab="find")


# --------------------------------------------------------------------------- statement

def _slots_from_form(form, base_slots):
    slots = []
    for i, base in enumerate(base_slots):
        kind = form.get("kind_%d" % i, base.kind)
        value = form.get("value_%d" % i, base.value)
        slots.append(BindSlot(base.label, base.occurrences, value,
                              missing=False if "value_%d" % i in form else base.missing, kind=kind))
    return slots


def export_html(title, sql, cols, rows, sources, truncated, mode, extra=None):
    rows, idx, mode = masked(cols, rows, sources, mode)
    html = render_template("export_result.html", title=title, sql=sql, cols=cols, rows=rows, sources=sources,
                           truncated=truncated, mask_mode=mode, masked_cols=[cols[i] for i in sorted(idx)],
                           extra=extra or {}, created=datetime.now().strftime("%Y-%m-%d %H:%M"))
    log("export_html", "%s (%d satır, maske: %s)" % (title, len(rows), mode), sql, len(rows))
    name = "".join(ch if ch.isalnum() else "_" for ch in title)[:60] or "sonuc"
    return Response(html, mimetype="text/html; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=%s.html" % name})


def stream_csv(sql: str, filename: str, schema=None, mode=None):
    settings, oracle, _ = ctx()
    catalog = get_catalog()
    insight = analyse_sql(sql, catalog, schema or settings.current_schema)

    def generate():
        yield "﻿"
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=";")
        stream = oracle.stream_select(sql, settings.max_export_rows, schema=schema)
        header = next(stream)
        sources = [label(s) if s else "" for s in map_result_columns(insight, header, catalog)]
        writer.writerow(header)
        total = 0
        for batch in stream:
            rows, _, _ = masked(header, batch, sources, mode)
            writer.writerows(rows)
            total += len(rows)
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)
        yield buf.getvalue()
        log("export_csv", "%s (%d satır, maske: %s)" % (filename, total, mode or settings.mask_default), sql, total)

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
    schema = capture_schema(capture)

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
    edited = False
    if (form.get("do") in ("run", "snapshot", "html", "csv") and form.get("sql_override")
            and form["sql_override"].strip() != form.get("literal_orig", "").strip()):
        literal = form["sql_override"]
        edited = True

    do = form.get("do")
    if do == "csv":
        return stream_csv(literal, "%s.csv" % sql_id, schema, form.get("mask"))
    result = error = None
    sources = []
    if do in ("run", "snapshot", "html"):
        try:
            result = oracle.run_select(literal, schema=schema)
            insight = st.insight if literal == substitute_binds(st.sql_text, placeholders, slots) \
                else analyse_sql(literal, catalog, schema)
            sources = map_result_columns(insight, result[0], catalog)
            log("query", "SQL_ID %s (%s)" % (sql_id, capture["name"]), literal, len(result[1]))
        except Exception as exc:
            error = str(exc)
    if result and do == "html":
        return export_html("%s - %s" % (capture["name"], sql_id), literal, result[0], list(result[1]),
                           _labels(sources), result[2], form.get("mask"),
                           {"Ekran": capture["name"], "SQL_ID": sql_id})
    if result and do == "snapshot":
        cols, rows, truncated = result
        title = form.get("title") or "%s - %s" % (capture["name"], sql_id)
        store.add_snapshot(title, literal, cols, rows[:settings.snapshot_rows],
                           truncated or len(rows) > settings.snapshot_rows, capture_id, sql_id,
                           form.get("note"), _labels(sources))
        log("snapshot", title, literal, min(len(rows), settings.snapshot_rows))
        flash("Sonuç rapora eklendi (%d satır)." % min(len(rows), settings.snapshot_rows), "ok")

    cursor = cursor_error = None
    if request.args.get("cursor") == "1":
        try:
            cursor = oracle.cursor_info(sql_id)
        except Exception as exc:
            cursor_error = str(exc)

    relations = relations_for(st.insight.tables, [(st.sql_id, st.insight)], infer=False) \
        if st.insight.joins else []
    variants = [s for s in ca.statements if s.signature == st.signature and s.sql_id != st.sql_id]
    return render_template("statement.html", capture=capture, st=st, execution=execution, edited=edited,
                           segments=bind_segments(st.sql_text, slots, formatted=True),
                           links=store.screen_sqls(sql_id=sql_id), screens=store.list_screens(),
                           slots=slots, literal=literal, result=result, error=error, sources=_labels(sources),
                           cursor=cursor, cursor_error=cursor_error, relations=relations, variants=variants,
                           columns=sorted(st.insight.columns.items(), key=lambda kv: tuple(x or "" for x in kv[0])),
                           missing=any(s.missing for s in slots), schema=schema)


@bp.route("/sql", methods=["GET", "POST"])
def sql_runner():
    settings, oracle, store = ctx()
    form = request.form
    sql = form.get("sql", request.args.get("sql", ""))
    schema = (form.get("schema") or request.args.get("schema") or settings.current_schema).upper()
    do = form.get("do", "run")
    result = error = None
    sources = []
    if request.method == "POST" and sql.strip() and do != "edit":
        if do == "csv":
            return stream_csv(sql, "sorgu.csv", schema, form.get("mask"))
        try:
            result = oracle.run_select(sql, schema=schema)
            catalog = get_catalog()
            sources = _labels(map_result_columns(analyse_sql(sql, catalog, schema), result[0], catalog))
            log("query", "SQL konsolu", sql, len(result[1]))
        except Exception as exc:
            error = str(exc)
        if result and do == "html":
            return export_html(form.get("title") or "Sorgu sonucu", sql, result[0], list(result[1]),
                               sources, result[2], form.get("mask"))
        if result and do == "snapshot":
            cols, rows, truncated = result
            store.add_snapshot(form.get("title") or "Sorgu", sql, cols, rows[:settings.snapshot_rows],
                               truncated or len(rows) > settings.snapshot_rows, note=form.get("note"),
                               sources=sources)
            log("snapshot", form.get("title") or "Sorgu", sql, min(len(rows), settings.snapshot_rows))
            flash("Sonuç rapora eklendi.", "ok")
    return render_template("sql.html", sql=sql, result=result, error=error, sources=sources,
                           schema=schema, schemas=known_schemas())


# --------------------------------------------------------------------------- csv

def csv_response(rows, header, filename):
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
    log("export_csv", "SQL listesi: %s" % capture["name"], rows=len(rows))
    return csv_response(rows, ["ekran", "sql_id", "islem", "calisma_sayisi", "tablolar", "kolonlar", "sql_text",
                               "bindler", "sql_bind_yerlestirilmis"], "capture_%d.csv" % capture_id)


from . import views_catalog, views_explore, views_notebook, views_ops, views_reports, views_research  # noqa: E402,F401  (register their routes on bp)
