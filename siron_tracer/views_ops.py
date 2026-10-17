"""Routes: background jobs, activity log, settings, screen inventory, coverage
and the migration package."""
from __future__ import annotations

import os
import re
from datetime import datetime

from flask import Response, abort, flash, jsonify, redirect, render_template, request, send_from_directory, url_for

from .catalog import label
from .coverage import SCREEN_STATUSES, compute as compute_coverage, screen_status
from .migration import COLUMN_MODES, QueryStep, build_plan, extract, package_zip, query_steps
from .views import bp, csv_response
from .views_reports import mapping_rows
from .web import (ann, capture_analysis, ctx, ext, get_catalog, known_schemas, known_users, log, project_analysis,
                  project_relations, remember)


# --------------------------------------------------------------------------- jobs

@bp.route("/jobs")
def jobs():
    return render_template("jobs.html", jobs=ctx()[2].list_jobs(200))


@bp.route("/jobs/<int:job_id>")
def job(job_id):
    j = ctx()[2].get_job(job_id)
    if j is None:
        abort(404)
    return render_template("job.html", job=j)


@bp.route("/jobs/<int:job_id>.json")
def job_json(job_id):
    j = ctx()[2].get_job(job_id)
    if j is None:
        abort(404)
    return jsonify({k: j[k] for k in ("id", "status", "progress", "message", "title")})


@bp.route("/jobs/active.json")
def jobs_active():
    active = [j for j in ctx()[2].list_jobs(20) if j["status"] in ("queued", "running")]
    return jsonify([{k: j[k] for k in ("id", "title", "progress", "message")} for j in active])


@bp.post("/jobs/<int:job_id>/cancel")
def job_cancel(job_id):
    ext()["jobs"].cancel(job_id)
    flash("İptal isteği gönderildi.", "ok")
    return redirect(url_for(".job", job_id=job_id))


# --------------------------------------------------------------------------- activity

@bp.route("/activity")
def activity():
    action = request.args.get("action") or None
    rows = ctx()[2].activity(1000, action)
    if request.args.get("format") == "csv":
        return csv_response([[r["ts"][:19], r["os_user"], r["host"], r["action"], r["detail"], r["rows"],
                              r["sql_text"]] for r in rows],
                            ["zaman", "kullanici", "makine", "islem", "detay", "satir", "sql"], "etkinlik_gunlugu.csv")
    return render_template("activity.html", rows=rows, action=action, actions=ACTIONS)


ACTIONS = {"query": "Sorgu çalıştırma", "export_csv": "CSV dışa aktarma", "export_html": "HTML dışa aktarma",
           "export_xlsx": "Excel dışa aktarma", "import_xlsx": "Excel içe aktarma", "report": "Rapor",
           "snapshot": "Rapora ekleme", "export_zip": "Taşıma paketi", "extract": "Veri çıkarma",
           "catalog": "Veri sözlüğü", "profile": "Veri profili", "relcheck": "İlişki doğrulama",
           "search": "Değer arama", "export_er": "ER dışa aktarma", "settings": "Ayarlar",
           "capture_delete": "Yakalama silme", "capture_reset": "Yakalama sıfırlama", "research": "Araştırma belgesi",
           "capture_sources": "Kaynak ayıklama", "extract_query": "Ekran sorgusu"}


# --------------------------------------------------------------------------- settings

@bp.route("/settings", methods=["GET", "POST"])
def settings_page():
    settings, _, store = ctx()
    if request.method == "POST":
        form = request.form
        users = [u for u in form.get("db_users", "").replace(",", "\n").splitlines() if u.strip()]
        schemas = [s for s in form.get("schemas", "").replace(",", "\n").splitlines() if s.strip()]
        store.set_list("db_users", users)
        store.set_list("schemas", schemas)
        log("settings", "DB kullanıcıları: %s; şemalar: %s" % (", ".join(users) or "-", ", ".join(schemas) or "-"))
        flash("Ayarlar kaydedildi. Yeni şemalar için veri sözlüğünü yenileyin.", "ok")
        return redirect(url_for(".settings_page"))
    return render_template("settings.html", saved_users=store.get_list("db_users"),
                           saved_schemas=store.get_list("schemas"), users=known_users(), schemas=known_schemas())


# --------------------------------------------------------------------------- inventory

@bp.route("/inventory", methods=["GET", "POST"])
def inventory():
    _, _, store = ctx()
    form = request.form
    if request.method == "POST":
        action = form.get("action")
        if action == "add":
            store.add_screen(form.get("name", "").strip() or "Adsız", form.get("module"), form.get("description"),
                             form.get("priority"))
            flash("Ekran envantere eklendi.", "ok")
        elif action == "bulk":
            added = 0
            for line in form.get("lines", "").splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = re.split(r"\s*(?:>|\t|;)\s*", line, maxsplit=1)
                module, name = (parts[0], parts[1]) if len(parts) == 2 else (None, parts[0])
                store.add_screen(name, module)
                added += 1
            flash("%d ekran işlendi (var olanlar tekrar eklenmez)." % added, "ok")
        elif action == "update":
            sid = form.get("id", type=int)
            store.update_screen(sid, module=form.get("module"), name=form.get("name"),
                                description=form.get("description"), priority=form.get("priority"),
                                status=form.get("status"), notes=form.get("notes"))
            flash("Ekran güncellendi.", "ok")
        elif action == "delete":
            store.delete_screen(form.get("id", type=int))
            flash("Ekran envanterden silindi.", "ok")
            return redirect(url_for(".inventory"))
        referrer = request.referrer or ""
        if action == "update" and "/inventory/" in referrer:      # edited from the screen page: stay there
            return redirect(referrer)
        return redirect(url_for(".inventory", module=request.args.get("module")))
    captures = store.list_captures()
    screens = store.list_screens()
    module = request.args.get("module")
    by_screen = {}
    for c in captures:
        if c.get("screen_id"):
            by_screen.setdefault(c["screen_id"], []).append(c)
    links = {}
    for link in store.screen_sqls():
        links.setdefault(link["screen_id"], []).append(link)
    rows = []
    for s in screens:
        if module and (s["module"] or "") != module:
            continue
        rows.append({"s": s, "status": screen_status(s, captures), "links": links.get(s["id"], []),
                     "captures": sorted(by_screen.get(s["id"], []), key=lambda c: c["start_local"], reverse=True)})
    modules = sorted({s["module"] for s in screens if s["module"]})
    return render_template("inventory.html", rows=rows, modules=modules, module=module, total=len(screens),
                           unlinked=[c for c in captures if not c.get("screen_id") and not c["is_noise"]])


@bp.route("/inventory/<int:screen_id>")
def screen_page(screen_id):
    """Everything known about one Siron screen: captures, linked SQLs, tables."""
    _, _, store = ctx()
    screen = store.get_screen(screen_id)
    if screen is None:
        abort(404)
    captures = sorted([c for c in store.list_captures() if c.get("screen_id") == screen_id],
                      key=lambda c: c["start_local"], reverse=True)
    links = store.screen_sqls(screen_id=screen_id)
    annotations = store.annotations()
    tables = {}
    for c in captures:
        if c["status"] != "done":
            continue
        ca = capture_analysis(c)
        for t in ca.tables:
            entry = tables.setdefault(t.key, {"key": t.key, "captures": [], "sql_ids": set(), "indirect": True})
            entry["captures"].append(c)
            entry["sql_ids"] |= {st.sql_id for st in t.statements}
            entry["indirect"] = entry["indirect"] and t.indirect
    linked_ids = {(l["capture_id"], l["sql_id"]) for l in links}
    for entry in tables.values():
        entry["linked"] = any((c["id"], sid) in linked_ids for c in entry["captures"] for sid in entry["sql_ids"])
        entry["status"] = ann(annotations, entry["key"]).get("status") or ""
    return render_template("screen.html", screen=screen, status=screen_status(screen, store.list_captures()),
                           modules=sorted({s["module"] for s in store.list_screens() if s["module"]}),
                           extract_queries=store.extract_queries(screen_id),
                           captures=captures, links=links, tables=sorted(tables.values(), key=lambda e: e["key"][1]))


@bp.post("/inventory/sql")
def screen_sql_link():
    """Link one captured SQL to an inventory screen (optionally creating the screen)."""
    _, _, store = ctx()
    form = request.form
    capture_id, sql_id = form.get("capture_id", type=int), (form.get("sql_id") or "").strip()
    capture = store.get_capture(capture_id) if capture_id else None
    if not capture or not sql_id:
        flash("Yakalama ve SQL_ID gerekli.", "error")
        return redirect(request.referrer or url_for(".inventory"))
    screen_id = form.get("screen_id", type=int)
    new_name = (form.get("new_screen") or "").strip()
    if new_name:
        module, _, name = new_name.rpartition(">")
        screen_id = store.add_screen(name.strip(), module.strip() or None)
    if not screen_id or not store.get_screen(screen_id):
        flash("Bir ekran seçin veya yeni ekran adı yazın.", "error")
        return redirect(request.referrer or url_for(".inventory"))
    store.link_sql(screen_id, capture_id, sql_id, form.get("note"))
    if not capture.get("screen_id"):
        store.update_capture(capture_id, screen_id=screen_id)
    flash("SQL %s ekrana bağlandı: %s" % (sql_id, store.get_screen(screen_id)["name"]), "ok")
    return redirect(request.referrer or url_for(".screen_page", screen_id=screen_id))


@bp.post("/inventory/sql/<int:link_id>/delete")
def screen_sql_unlink(link_id):
    ctx()[2].unlink_sql(link_id)
    flash("SQL bağlantısı kaldırıldı.", "ok")
    return redirect(request.referrer or url_for(".inventory"))


@bp.post("/inventory/link")
def inventory_link():
    """Link existing captures to inventory screens (creating screens from capture names if asked)."""
    _, _, store = ctx()
    for c in store.list_captures():
        if c.get("screen_id") or c["is_noise"]:
            continue
        if request.form.get("create"):
            store.update_capture(c["id"], screen_id=store.add_screen(c["name"]))
    flash("Yakalamalar envantere bağlandı.", "ok")
    return redirect(url_for(".inventory"))


# --------------------------------------------------------------------------- coverage

@bp.route("/coverage")
def coverage():
    _, _, store = ctx()
    catalog = get_catalog()
    pa = project_analysis()
    cov = compute_coverage(pa, catalog, store.annotations(), store.list_screens(), store.list_captures(),
                           project_relations())
    min_rows = request.args.get("min_rows", 1, type=int)
    untouched = [u for u in cov.untouched if (u["table"].num_rows or 0) >= min_rows]
    return render_template("coverage.html", cov=cov, untouched=untouched[:500], untouched_total=len(untouched),
                           min_rows=min_rows, has_catalog=bool(catalog))


# --------------------------------------------------------------------------- migration package

def _plan(mode, with_queries: bool = True):
    settings, _, store = ctx()
    catalog = get_catalog()
    pa = project_analysis()
    used = {}
    for col in pa.columns:
        used.setdefault(col[:2], set()).add(col[2])
    rels = project_relations()
    steps = build_plan(catalog, store.annotations(), rels, used, mode)
    if with_queries:
        steps += query_steps(_extract_queries(), len(steps) + 1, settings.current_schema)
    return steps, catalog, pa


def _extract_queries():
    """Saved screen queries with the schema their capture ran in."""
    store = ctx()[2]
    captures = {c["id"]: c for c in store.list_captures()}
    out = []
    for q in store.extract_queries():
        c = captures.get(q["capture_id"])
        q["schema"] = (c or {}).get("schema_name")
        out.append(q)
    return out


@bp.route("/migration", methods=["GET", "POST"])
def migration():
    settings, _, store = ctx()
    mode = request.values.get("mode", "decided")
    if request.method == "POST" and request.form.get("action") == "filters":
        for key, value in request.form.items():
            if key.startswith("filter__"):
                owner, _, table = key[len("filter__"):].partition("__")
                store.save_annotation(owner or None, table, "", extract_filter=value)
        flash("Filtreler kaydedildi.", "ok")
        return redirect(url_for(".migration", mode=mode))
    steps, catalog, pa = _plan(mode)
    runs = [j for j in store.list_jobs(50, "extract")]
    table_steps = [s for s in steps if not isinstance(s, QueryStep)]
    return render_template("migration.html", steps=table_steps, query_steps=[s for s in steps if isinstance(s, QueryStep)],
                           all_steps=steps, mode=mode, modes=COLUMN_MODES, runs=runs, catalog=catalog,
                           total_rows=sum(s.num_rows or 0 for s in table_steps))


@bp.route("/migration.zip")
def migration_zip():
    mode = request.args.get("mode", "decided")
    steps, catalog, pa = _plan(mode)
    store = ctx()[2]
    import csv as _csv
    import io as _io
    buf = _io.StringIO()
    w = _csv.writer(buf, delimiter=";")
    w.writerow(["sema", "tablo", "kolon", "tip", "durum", "hassas", "hedef_alan", "not"])
    for r in mapping_rows(pa, store.annotations()):
        w.writerow([r["col"][0] or "", r["col"][1], r["col"][2], r["info"].type_label if r["info"] else "",
                    r["ann"].get("status") or r["table_ann"].get("status") or "", "evet" if r["sensitive"] else "",
                    r["ann"].get("target") or "", r["ann"].get("note") or ""])
    data = package_zip(steps, catalog, "﻿" + buf.getvalue(), datetime.now().strftime("%Y-%m-%d %H:%M"))
    log("export_zip", "Taşıma paketi: %d adım (%s)" % (len(steps), mode))
    return Response(data, mimetype="application/zip", headers={
        "Content-Disposition": "attachment; filename=siron_tasima_paketi_%s.zip" % datetime.now().strftime("%Y%m%d_%H%M")})


@bp.post("/migration/extract")
def migration_extract():
    settings, oracle, store = ctx()
    mode = request.form.get("mode", "decided")
    steps, catalog, _ = _plan(mode)
    if not steps:
        flash("Taşınacak işaretli tablo veya kayıtlı ekran sorgusu yok.", "error")
        return redirect(url_for(".migration"))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(os.path.abspath(settings.export_dir), stamp)

    def work(job):
        result = extract(steps, lambda sql, n, schema=None: oracle.stream_select(sql, n, batch=5000, schema=schema),
                         out_dir, catalog,
                         settings.extract_max_rows, lambda p, m: job.progress(p, m))
        result["run"] = stamp
        store.log("extract", "Veri çıkarma %s: %d tablo, %d satır" % (stamp, len(result["files"]),
                                                                    result["total_rows"]), rows=result["total_rows"])
        job.message = "%d tablo, %s satır → %s" % (len(result["files"]), result["total_rows"], out_dir)
        return result

    job_id = ext()["jobs"].submit("extract", "Veri çıkarma: %d adım" % len(steps), work, {"mode": mode, "run": stamp})
    return redirect(url_for(".job", job_id=job_id))


@bp.route("/exports/<run>/<path:filename>")
def export_file(run, filename):
    settings = ctx()[0]
    if not re.match(r"^\d{8}_\d{6}$", run):
        abort(404)
    log("export_csv", "Çıkarılan dosya indirildi: %s/%s" % (run, filename))
    return send_from_directory(os.path.join(os.path.abspath(settings.export_dir), run), filename, as_attachment=True)
