"""Routes: result snapshots, mapping matrix, HTML reports and the Excel round trip."""
from __future__ import annotations

import json
from datetime import datetime

from flask import Response, flash, redirect, render_template, request, url_for

from . import knowledge
from .catalog import label
from .coverage import SCREEN_STATUSES, compute as compute_coverage, screen_status
from .excel import STATUS_LABELS, export_workbook, read_workbook
from .privacy import mask_rows, mask_value
from .sqlinsight import USAGE_LABELS
from .views import bp, csv_response
from .web import (STATUSES, ann, capture_analysis, capture_or_404, ctx, er_view, get_catalog, is_sensitive,
                  literal_for, log, privacy, project_analysis, project_relations, relations_for, table_like)


@bp.route("/snapshots")
def snapshots():
    _, _, store = ctx()
    captures = {c["id"]: c for c in store.list_captures()}
    return render_template("snapshots.html", snapshots=store.snapshots(), captures=captures)


@bp.post("/snapshots/<int:snapshot_id>/delete")
def delete_snapshot(snapshot_id):
    ctx()[2].delete_snapshot(snapshot_id)
    flash("Sonuç rapordan çıkarıldı.", "ok")
    return redirect(request.referrer or url_for(".snapshots"))


# --------------------------------------------------------------------------- mapping matrix

def mapping_rows(pa, annotations, include_unused_annotated=True):
    """One row per used (or annotated) column: the migration mapping matrix."""
    catalog = get_catalog()
    profiles = ctx()[2].profiles()
    keys = set(pa.columns)
    if include_unused_annotated:
        keys |= {(o or None, t, c) for (o, t, c) in annotations if c}
    rows = []
    for col in sorted(keys, key=lambda k: tuple(x or "" for x in k)):
        info = catalog.column(col[:2], col[2]) if catalog else None
        usage = pa.columns.get(col, {"kinds": set(), "screens": {}})
        a = ann(annotations, col[:2], col[2])
        rows.append({"col": col, "info": info, "kinds": usage["kinds"],
                     "screens": list(usage["screens"].values()), "ann": a,
                     "table_ann": ann(annotations, col[:2]), "profile": profiles.get(col),
                     "sensitive": privacy().is_sensitive(col[2], a)})
    return rows


@bp.route("/mapping")
def mapping():
    _, _, store = ctx()
    pa = project_analysis()
    rows = mapping_rows(pa, store.annotations())
    status = request.args.get("status", "")
    q = request.args.get("q", "").strip().upper()
    if status == "none":
        rows = [r for r in rows if not (r["ann"].get("status") or r["table_ann"].get("status"))]
    elif status:
        rows = [r for r in rows if (r["ann"].get("status") or r["table_ann"].get("status") or "") == status]
    if q:
        rows = [r for r in rows if q in label(r["col"]) or q in (r["ann"].get("target") or "").upper()]
    if request.args.get("sensitive") == "1":
        rows = [r for r in rows if r["sensitive"]]
    return render_template("mapping.html", rows=rows, status=status, q=q)


@bp.route("/mapping.csv")
def mapping_csv():
    _, _, store = ctx()
    pa = project_analysis()
    out = []
    for r in mapping_rows(pa, store.annotations()):
        info, a = r["info"], r["ann"]
        out.append([r["col"][0] or "", r["col"][1], r["col"][2], info.type_label if info else "",
                    (info.comment or "") if info else "",
                    ", ".join(sorted({USAGE_LABELS.get(k, k) for k in r["kinds"]})),
                    ", ".join(c["name"] for c in r["screens"]),
                    STATUSES.get(a.get("status") or r["table_ann"].get("status") or "", ""),
                    "Evet" if r["sensitive"] else "", a.get("target") or "", a.get("note") or ""])
    log("export_csv", "Kolon eşleme matrisi", rows=len(out))
    return csv_response(out, ["sema", "tablo", "kolon", "tip", "aciklama", "kullanim", "ekranlar", "durum",
                              "hassas", "hedef_alan", "not"], "siron_kolon_esleme.csv")


# --------------------------------------------------------------------------- excel

@bp.route("/excel")
def excel():
    _, _, store = ctx()
    backup = store.get_meta("annotations_backup")
    return render_template("excel.html", backup_at=json.loads(backup)["at"] if backup else None,
                           last_import=json.loads(store.get_meta("last_import", "null") or "null"))


@bp.route("/mapping.xlsx")
def mapping_xlsx():
    settings, _, store = ctx()
    catalog = get_catalog()
    pa = project_analysis()
    annotations = store.annotations()
    screens_inv = store.list_screens()
    captures = store.list_captures()
    rels = project_relations()
    cov = compute_coverage(pa, catalog, annotations, screens_inv, captures, rels)
    inv_by_id = {s["id"]: s for s in screens_inv}

    summary = [["Rapor", "Siron AML veri eşleme"], ["Oluşturulma", datetime.now().strftime("%Y-%m-%d %H:%M")],
               ["Şemalar", ", ".join(settings.schemas)], ["Ekran yakalaması", len(pa.captures)],
               ["Dokunulan tablo", len(pa.tables)], ["Kullanılan kolon", len(pa.columns)],
               ["Karar verilen kolon", "%d (%s%%)" % (cov.columns_decided, cov.columns_pct or 0)],
               ["İlişki", len(rels)],
               ["Nasıl doldurulur", "Sarı hücreleri doldurun: Durum (Taşınacak/İncelenecek/Gereksiz), Hedef, Not, "
                                    "Hassas (Evet/Hayır). Dosyayı uygulamadaki 'Excel' sayfasından geri yükleyin."]]
    screens = []
    for c, ca in pa.captures:
        inv = inv_by_id.get(c.get("screen_id")) or {}
        screens.append([c["name"], "Batch" if c["kind"] == "batch" else "Ekran", inv.get("module"),
                        c["start_local"][:16], len(ca.tables), len(ca.columns), len(ca.statements), c["notes"]])
    used = {}
    for col in pa.columns:
        used.setdefault(col[:2], set()).add(col[2])
    tables = []
    for key in table_like(pa.tables):
        t = catalog.tables.get(key) if catalog else None
        a = ann(annotations, key)
        entry = pa.tables[key]
        rs = knowledge.classify(key[1])
        tables.append([key[0], key[1], t.obj_type if t else "", t.num_rows if t else None, t.comment if t else "",
                       rs.module.name if rs else "", rs.meaning if rs else "",
                       knowledge.CONFIDENCE[rs.confidence] if rs else "",
                       ", ".join(c["name"] for c, _ in entry["screens"]), len(used.get(key, ())),
                       STATUS_LABELS.get(a.get("status"), ""), a.get("target"), a.get("extract_filter"), a.get("note")])
    columns = []
    for r in mapping_rows(pa, annotations):
        p, info, a = r["profile"] or {}, r["info"], r["ann"]
        top = ", ".join(str(v) for v, _ in (p.get("top") or [])[:5])
        if r["sensitive"] and top:
            top = ", ".join(str(mask_value(v)) for v, _ in p["top"][:5])
        columns.append([r["col"][0], r["col"][1], r["col"][2], info.type_label if info else "",
                        info.comment if info else "", ", ".join(sorted({USAGE_LABELS.get(k, k) for k in r["kinds"]})),
                        ", ".join(c["name"] for c in r["screens"]), p.get("fill_pct"), p.get("distinct"), top,
                        STATUS_LABELS.get(a.get("status"), ""),
                        {1: "Evet", 0: "Hayır"}.get(a.get("sensitive"), "Evet (tahmin)" if r["sensitive"] else ""),
                        a.get("target"), a.get("note")])
    relations = [[label(r.child), ", ".join(r.child_cols), label(r.parent), ", ".join(r.parent_cols), r.confidence,
                  ", ".join(r.sources), "%d/%d" % r.check if r.check else ""] for r in rels]
    inventory = [[s["id"], s["module"], s["name"], s["description"], s["priority"],
                  SCREEN_STATUSES.get(screen_status(s, captures), s["status"]),
                  sum(1 for c in captures if c.get("screen_id") == s["id"]), s["notes"]] for s in screens_inv]
    data = export_workbook(summary, screens, tables, columns, relations, inventory)
    log("export_xlsx", "Excel eşleme çalışma kitabı (%d kolon)" % len(columns), rows=len(columns))
    return Response(data, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=siron_esleme_%s.xlsx"
                             % datetime.now().strftime("%Y%m%d_%H%M")})


@bp.post("/excel/import")
def excel_import():
    _, _, store = ctx()
    upload = request.files.get("file")
    if not upload or not upload.filename:
        flash("Bir .xlsx dosyası seçin.", "error")
        return redirect(url_for(".excel"))
    try:
        parsed = read_workbook(upload.read())
    except Exception as exc:
        flash("Dosya okunamadı: %s" % exc, "error")
        return redirect(url_for(".excel"))
    if parsed["errors"] and not request.form.get("ignore_errors"):
        flash("Dosyada %d hata var, hiçbir değişiklik yapılmadı: %s" % (
            len(parsed["errors"]), "; ".join(parsed["errors"][:5])), "error")
        return redirect(url_for(".excel"))
    before = store.annotations()
    store.set_meta("annotations_backup", json.dumps({"at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                                     "rows": list(before.values())}, default=str))
    changed = {"tables": 0, "columns": 0, "screens": 0}
    for t in parsed["tables"]:
        if not t["table"]:
            continue
        cur = ann(before, (t["owner"], t["table"]))
        new = {"status": t["status"], "target": t["target"], "extract_filter": t["filter"], "note": t["note"]}
        if any((cur.get(k) or None) != v for k, v in new.items()):
            store.save_annotation(t["owner"], t["table"], "", **new)
            changed["tables"] += 1
    for c in parsed["columns"]:
        if not (c["table"] and c["column"]):
            continue
        cur = ann(before, (c["owner"], c["table"]), c["column"])
        new = {"status": c["status"], "target": c["target"], "note": c["note"]}
        sens = c["sensitive"]
        if sens is not None and cur.get("sensitive") != sens:
            new["sensitive"] = sens
        if any(cur.get(k) != v for k, v in new.items()):
            store.save_annotation(c["owner"], c["table"], c["column"], **new)
            changed["columns"] += 1
    status_codes = {v.casefold(): k for k, v in SCREEN_STATUSES.items()}
    for s in parsed["inventory"]:
        status = status_codes.get((s["status"] or "").casefold(), "todo")
        if s.get("id"):
            store.update_screen(int(s["id"]), module=s["module"], name=s["name"], description=s["description"],
                                priority=s["priority"], status=status, notes=s["notes"])
        else:
            store.add_screen(s["name"], s["module"], s["description"], s["priority"], status, s["notes"])
        changed["screens"] += 1
    store.set_meta("last_import", json.dumps({"at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                              "file": upload.filename, "changed": changed,
                                              "errors": parsed["errors"]}))
    log("import_xlsx", "%s: %d tablo, %d kolon, %d ekran güncellendi" % (
        upload.filename, changed["tables"], changed["columns"], changed["screens"]))
    flash("İçe aktarıldı: %d tablo, %d kolon, %d envanter satırı güncellendi." % (
        changed["tables"], changed["columns"], changed["screens"]), "ok")
    return redirect(url_for(".excel"))


@bp.post("/excel/undo")
def excel_undo():
    _, _, store = ctx()
    backup = store.get_meta("annotations_backup")
    if not backup:
        flash("Geri alınacak içe aktarma yok.", "error")
    else:
        store.replace_annotations(json.loads(backup)["rows"])
        store.set_meta("annotations_backup", "")
        log("import_xlsx", "Son Excel içe aktarması geri alındı")
        flash("Son içe aktarma geri alındı; notlar önceki haline döndü.", "ok")
    return redirect(url_for(".excel"))


# --------------------------------------------------------------------------- reports

@bp.route("/report")
def report_options():
    settings, _, store = ctx()
    return render_template("report_options.html", captures=[c for c in store.list_captures()
                                                            if c["status"] == "done" and not c["is_noise"]])


@bp.route("/report.html")
def report():
    settings, _, store = ctx()
    args = request.args
    capture_id = args.get("capture", type=int)
    mask_mode = args.get("mask") or settings.mask_default
    include_sql = args.get("sql", "1") == "1"
    include_snapshots = args.get("snapshots", "1") == "1"
    include_profiles = args.get("profiles", "1") == "1"
    include_research = args.get("research", "1") == "1"
    all_columns = args.get("cols") == "all"
    catalog = get_catalog()
    annotations = store.annotations()
    profiles = store.profiles() if include_profiles else {}

    pa = project_analysis()
    captures_all = store.list_captures()
    if capture_id:
        capture = capture_or_404(capture_id)
        selected = [(c, ca) for c, ca in pa.captures if c["id"] == capture_id] or \
            [(capture, capture_analysis(capture, exclude_noise=False))]
        title = "Ekran raporu: %s" % capture["name"]
        rels_scope = None
    else:
        selected = pa.captures
        title = "Siron AML veri eşleme raporu"
        rels_scope = project_relations(50)

    selected = sorted(selected, key=lambda x: x[0]["start_local"])
    keys, insights = [], []
    for _, ca in selected:
        keys.extend(k for k in table_like(ca.table_keys) if k not in keys)
        insights.extend(ca.insights)
    rank = {"migrate": 0, "review": 1, None: 2, "ignore": 3}
    keys.sort(key=lambda k: (rank.get(ann(annotations, k).get("status"), 2), k[1]))
    relations = rels_scope if rels_scope is not None else (relations_for(keys, insights, min_confidence=50) if keys else [])
    er = er_view(keys, relations) if keys else None

    col_usage = {}
    for c, ca in selected:
        for col, cu in ca.columns.items():
            entry = col_usage.setdefault(col, {"kinds": set(), "screens": []})
            entry["kinds"] |= cu.kinds
            if c not in entry["screens"]:
                entry["screens"].append(c)

    def show(value, key, column):
        if mask_mode == "all" or (mask_mode == "sensitive" and is_sensitive(key, column, annotations)):
            return mask_value(value)
        return value

    sections = []
    for key in keys:
        info = catalog.tables.get(key) if catalog else None
        cols = [c for c in info.columns if all_columns or (key[0], key[1], c.name) in col_usage
                or ann(annotations, key, c.name)] if info else []
        used_unknown = [col for col in col_usage if col[:2] == key and not (info and catalog.column(key, col[2]))]
        indirect = all(t.indirect for _, ca in selected for t in ca.tables if t.key == key)
        sections.append({"key": key, "info": info, "cols": cols, "used_unknown": used_unknown, "indirect": indirect,
                         "screens": [c for c, ca in selected if key in ca.table_keys],
                         "relations": [r for r in relations if key in (r.child, r.parent)],
                         "pk": set(catalog.primary_key(key)) if catalog else set(),
                         "fk": catalog.fk_columns(key) if catalog else set(),
                         "profiles": {c.name: profiles.get((key[0], key[1], c.name)) for c in cols},
                         "sensitive": {c.name: is_sensitive(key, c.name, annotations) for c in cols}})

    screens = []
    for c, ca in selected:
        stmts = []
        for st in ca.statements:
            literal = literal_for(st.sql_text, st.executions[0].sql_binds)[0] if include_sql else None
            stmts.append((st, literal))
        screens.append((c, ca, stmts))

    snaps = []
    if include_snapshots:
        snaps = store.snapshots(capture_id) if capture_id else store.snapshots()
        for s in snaps:
            from .web import masked
            s["rows"], idx, _ = masked(s["columns"], s["rows"], s["sources"], mask_mode)
            s["masked_cols"] = [s["columns"][i] for i in sorted(idx)]

    research_modules = []
    if include_research:
        by_module = {}
        for sec in sections:
            sec["research"] = knowledge.classify(sec["key"][1])
            mid = sec["research"].module.id if sec["research"] else None
            by_module.setdefault(mid, []).append(sec)
        research_modules = [(knowledge.MODULE_BY_ID[m.id], by_module[m.id]) for m in knowledge.MODULES if m.id in by_module]
        if None in by_module:
            research_modules.append((None, by_module[None]))

    cov = None if capture_id else compute_coverage(pa, catalog, annotations, store.list_screens(), captures_all,
                                                   project_relations())
    html = render_template(
        "report.html", title=title, created=datetime.now().strftime("%Y-%m-%d %H:%M"),
        screens=screens, stmt_count=len({st.sql_id for _, ca in selected for st in ca.statements}),
        sections=sections, relations=relations, er=er, col_usage=col_usage, cov=cov,
        annotations=annotations, snaps=snaps, mask_mode=mask_mode, include_sql=include_sql,
        include_profiles=include_profiles, show=show, include_research=include_research,
        research_modules=research_modules,
        mapping=mapping_rows(pa, annotations, include_unused_annotated=not capture_id) if not capture_id else
        [r for r in mapping_rows(pa, annotations, False) if r["col"] in col_usage],
        all_columns=all_columns, single=bool(capture_id))
    log("report", "%s (maske: %s)%s" % (title, mask_mode, " indirildi" if args.get("download") == "1" else ""))
    headers = {}
    if args.get("download") == "1":
        name = "siron_rapor_%s.html" % (("ekran_%d" % capture_id) if capture_id else "proje")
        headers["Content-Disposition"] = "attachment; filename=%s" % name
    return Response(html, mimetype="text/html; charset=utf-8", headers=headers)
