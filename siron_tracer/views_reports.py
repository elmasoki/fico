"""Routes: saved result snapshots, the mapping matrix and the HTML reports."""
from __future__ import annotations

from datetime import datetime

from flask import Response, flash, redirect, render_template, request, url_for

from .catalog import label
from .finder import mask_rows
from .views import _csv, bp
from .web import (ann, capture_or_404, ctx, er_view, get_catalog, literal_for, project_analysis,
                  relations_for, table_like)


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

def _mapping_rows(pa, annotations, include_unused_annotated=True):
    """One row per used (or annotated) column: the migration mapping matrix."""
    catalog = get_catalog()
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
                     "table_ann": ann(annotations, col[:2])})
    return rows


@bp.route("/mapping")
def mapping():
    _, _, store = ctx()
    pa = project_analysis()
    rows = _mapping_rows(pa, store.annotations())
    status = request.args.get("status", "")
    if status:
        rows = [r for r in rows if (r["ann"].get("status") or r["table_ann"].get("status") or "") == status]
    return render_template("mapping.html", rows=rows, status=status)


@bp.route("/mapping.csv")
def mapping_csv():
    from .web import STATUSES
    from .sqlinsight import USAGE_LABELS
    _, _, store = ctx()
    pa = project_analysis()
    out = []
    for r in _mapping_rows(pa, store.annotations()):
        info, a = r["info"], r["ann"]
        out.append([r["col"][0] or "", r["col"][1], r["col"][2], info.type_label if info else "",
                    (info.comment or "") if info else "",
                    ", ".join(sorted({USAGE_LABELS.get(k, k) for k in r["kinds"]})),
                    ", ".join(c["name"] for c in r["screens"]),
                    STATUSES.get(a.get("status") or r["table_ann"].get("status") or "", ""),
                    a.get("target") or "", a.get("note") or ""])
    return _csv(out, ["sema", "tablo", "kolon", "tip", "aciklama", "kullanim", "ekranlar", "durum",
                      "hedef_alan", "not"], "siron_kolon_esleme.csv")


# --------------------------------------------------------------------------- reports

@bp.route("/report")
def report_options():
    _, _, store = ctx()
    return render_template("report_options.html", captures=[c for c in store.list_captures()
                                                            if c["status"] == "done" and not c["is_noise"]])


@bp.route("/report.html")
def report():
    settings, _, store = ctx()
    args = request.args
    capture_id = args.get("capture", type=int)
    masked = args.get("mask") == "1"
    include_sql = args.get("sql", "1") == "1"
    include_snapshots = args.get("snapshots", "1") == "1"
    all_columns = args.get("cols") == "all"
    catalog = get_catalog()
    annotations = store.annotations()

    pa = project_analysis()
    if capture_id:
        capture = capture_or_404(capture_id)
        pa.captures = [(c, ca) for c, ca in pa.captures if c["id"] == capture_id]
        if not pa.captures:  # noise capture or still recording: analyse it anyway
            from .web import capture_analysis
            pa.captures = [(capture, capture_analysis(capture, exclude_noise=False))]
        title = "Ekran raporu: %s" % capture["name"]
    else:
        title = "Siron AML veri eşleme raporu"

    keys = []
    insights = []
    for _, ca in pa.captures:
        keys.extend(k for k in table_like(ca.table_keys) if k not in keys)
        insights.extend(ca.insights)
    relations = relations_for(keys, insights, min_confidence=50) if keys else []
    er = er_view(keys, relations) if keys else None

    col_usage = {}
    for c, ca in pa.captures:
        for col, cu in ca.columns.items():
            entry = col_usage.setdefault(col, {"kinds": set(), "screens": []})
            entry["kinds"] |= cu.kinds
            if c not in entry["screens"]:
                entry["screens"].append(c)

    sections = []
    for key in keys:
        info = catalog.tables.get(key) if catalog else None
        if info:
            cols = [c for c in info.columns if all_columns or (key[0], key[1], c.name) in col_usage
                    or ann(annotations, key, c.name)]
        else:
            cols = []
        used_unknown = [col for col in col_usage if col[:2] == key and not (info and catalog.column(key, col[2]))]
        screens = [c for c, ca in pa.captures if key in ca.table_keys]
        sections.append({"key": key, "info": info, "cols": cols, "used_unknown": used_unknown,
                         "screens": screens,
                         "relations": [r for r in relations if key in (r.child, r.parent)],
                         "pk": set(catalog.primary_key(key)) if catalog else set(),
                         "fk": catalog.fk_columns(key) if catalog else set()})

    screens = []
    for c, ca in pa.captures:
        stmts = []
        for st in ca.statements:
            literal = literal_for(st.sql_text, st.executions[0].sql_binds)[0] if include_sql else None
            stmts.append((st, literal))
        screens.append((c, ca, stmts))

    snaps = []
    if include_snapshots:
        snaps = store.snapshots(capture_id) if capture_id else store.snapshots()
        if masked:
            for s in snaps:
                s["rows"] = mask_rows(s["rows"])

    html = render_template(
        "report.html", title=title, created=datetime.now().strftime("%Y-%m-%d %H:%M"),
        screens=screens, stmt_count=len({st.sql_id for _, ca in pa.captures for st in ca.statements}),
        sections=sections, relations=relations, er=er, col_usage=col_usage,
        annotations=annotations, snaps=snaps, masked=masked, include_sql=include_sql,
        mapping=_mapping_rows(pa, annotations, include_unused_annotated=not capture_id),
        all_columns=all_columns, single=bool(capture_id))
    headers = {}
    if args.get("download") == "1":
        name = "siron_rapor_%s.html" % (("ekran_%d" % capture_id) if capture_id else "proje")
        headers["Content-Disposition"] = "attachment; filename=%s" % name
    return Response(html, mimetype="text/html; charset=utf-8", headers=headers)
