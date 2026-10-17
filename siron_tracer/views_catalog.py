"""Routes: data dictionary, table detail, relations, ER diagram, query builder, search."""
from __future__ import annotations

from flask import Response, abort, flash, redirect, render_template, request, url_for

from .catalog import label
from .relations import (SOURCE_LABELS, build_select, find_join_tree, parse_relation_id, qualified,
                        relation_id, to_dot, to_mermaid)
from .views import _search_table, bp
from .web import (ann, capture_analysis, capture_or_404, ctx, er_view, get_catalog, parse_key,
                  project_analysis, relations_for, table_like)


def _key_from_url(owner: str, name: str):
    return (None if owner == "-" else owner, name)


# --------------------------------------------------------------------------- tables

@bp.route("/tables")
def tables():
    _, _, store = ctx()
    catalog = get_catalog()
    pa = project_analysis()
    show_all = request.args.get("all") == "1" and catalog
    q = request.args.get("q", "").strip().upper()
    status = request.args.get("status", "")
    annotations = store.annotations()
    keys = list(catalog.tables) if show_all else table_like(pa.tables)
    used_cols = {}
    for col in pa.columns:
        used_cols.setdefault(col[:2], set()).add(col[2])
    rels = relations_for(table_like(pa.tables), pa.insights, min_confidence=50) if pa.tables else []
    rel_count = {}
    for r in rels:
        for k in {r.child, r.parent}:
            rel_count[k] = rel_count.get(k, 0) + 1
    rows = []
    for key in keys:
        table = catalog.tables.get(key) if catalog else None
        a = ann(annotations, key)
        if q and q not in key[1] and not (table and table.comment and q in table.comment.upper()):
            continue
        if status and (a.get("status") or "") != (status if status != "none" else ""):
            continue
        entry = pa.tables.get(key, {"screens": [], "actions": set(), "type": None})
        rows.append({"key": key, "table": table, "screens": entry["screens"], "actions": entry["actions"],
                     "used": len(used_cols.get(key, ())), "total": len(table.columns) if table else None,
                     "ann": a, "relations": rel_count.get(key, 0)})
    if show_all:
        rows.sort(key=lambda r: (-len(r["screens"]), r["key"][1]))
    return render_template("tables.html", rows=rows, show_all=show_all, q=q, status=status,
                           has_catalog=bool(catalog), capture_count=len(pa.captures))


@bp.route("/table/<owner>/<name>", methods=["GET", "POST"])
def table(owner, name):
    settings, oracle, store = ctx()
    key = _key_from_url(owner, name)
    catalog = get_catalog()
    info = catalog.tables.get(key) if catalog else None
    form = request.form

    if request.method == "POST" and form.get("action") == "annotate":
        store.save_annotation(key[0], key[1], "", form.get("status"), form.get("note"), form.get("target"))
        for col in (info.columns if info else []):
            store.save_annotation(key[0], key[1], col.name, form.get("status_" + col.name),
                                  form.get("note_" + col.name), form.get("target_" + col.name))
        flash("Notlar kaydedildi.", "ok")
        return redirect(url_for(".table", owner=owner, name=name))

    pa = project_analysis()
    entry = pa.tables.get(key, {"screens": [], "actions": set()})
    col_usage = {col[2]: data for col, data in pa.columns.items() if col[:2] == key}
    statements = []
    for capture, ca in pa.captures:
        for st in ca.statements:
            if key in st.tables:
                statements.append((capture, st))
    others = set(catalog.tables) if catalog else set(pa.tables)
    relations = relations_for([key], pa.insights, other=others | set(pa.tables))

    sample = sample_error = None
    findings, find_errors = [], []
    needle = form.get("value", "").strip()
    mode = form.get("mode", "ci")
    if request.method == "POST" and form.get("action") == "sample":
        try:
            sample = oracle.run_select("SELECT * FROM %s WHERE ROWNUM <= 20" % qualified(key))
        except Exception as exc:
            sample_error = str(exc)
    if request.method == "POST" and form.get("action") == "find" and needle:
        findings, error, skipped = _search_table(key, needle, mode, include_big=True)
        if error or skipped:
            find_errors.append(error or skipped)

    pk = set(catalog.primary_key(key)) if catalog else set()
    uk = {c for ctype, cols in (catalog.keys_of(key) if catalog else []) if ctype == "U" for c in cols}
    fk = catalog.fk_columns(key) if catalog else set()
    return render_template("table.html", key=key, info=info, entry=entry, col_usage=col_usage,
                           statements=statements, relations=relations, annotations=store.annotations(),
                           pk=pk, uk=uk, fk=fk, sample=sample, sample_error=sample_error,
                           findings=findings, find_errors=find_errors, needle=needle, mode=mode,
                           url_owner=owner)


# --------------------------------------------------------------------------- relations

def _scope():
    """(title, table keys, insights, capture or None) from ?capture=<id>"""
    capture_id = request.args.get("capture", type=int)
    if capture_id:
        capture = capture_or_404(capture_id)
        ca = capture_analysis(capture)
        return capture["name"], table_like(ca.table_keys), ca.insights, capture
    pa = project_analysis()
    return "Tüm ekranlar", table_like(pa.tables), pa.insights, None


@bp.route("/relations")
def relations():
    title, keys, insights, capture = _scope()
    min_conf = request.args.get("min", 0, type=int)
    source = request.args.get("source", "")
    rels = relations_for(keys, insights, min_confidence=min_conf) if keys else []
    if source:
        rels = [r for r in rels if source in r.sources]
    return render_template("relations.html", title=title, rels=rels, capture=capture, min_conf=min_conf,
                           source=source, source_labels=SOURCE_LABELS, has_catalog=bool(get_catalog()),
                           table_count=len(keys))


@bp.post("/relations/check")
def relation_check():
    _, oracle, store = ctx()
    rid = request.form.get("rid", "")
    try:
        child, ccols, parent, pcols = parse_relation_id(rid)
        matched, total = oracle.check_relation(child, ccols, parent, pcols)
        store.save_relation_check(relation_id(child, ccols, parent, pcols), matched, total)
        pct = 100.0 * matched / total if total else 0
        flash("Veri kontrolü: %s → %d/%d farklı değer eşleşti (%%%.1f)." % (rid, matched, total, pct), "ok")
    except Exception as exc:
        flash("İlişki kontrol edilemedi: %s" % exc, "error")
    return redirect(request.referrer or url_for(".relations"))


@bp.post("/relations/check-all")
def relation_check_all():
    """Check every inferred / SQL relation of the current scope that has no result yet."""
    _, oracle, store = ctx()
    title, keys, insights, _ = _scope()
    done = failed = 0
    for r in relations_for(keys, insights):
        if "constraint" in r.sources or r.check is not None:
            continue
        try:
            matched, total = oracle.check_relation(r.child, r.child_cols, r.parent, r.parent_cols)
            store.save_relation_check(r.id, matched, total)
            done += 1
        except Exception:
            failed += 1
    flash("%d ilişki veriyle kontrol edildi%s." % (done, ", %d hata" % failed if failed else ""), "ok")
    return redirect(request.referrer or url_for(".relations"))


@bp.route("/er")
def er():
    title, keys, insights, capture = _scope()
    min_conf = request.args.get("min", 50, type=int)
    rels = relations_for(keys, insights, min_confidence=min_conf) if keys else []
    view = er_view(keys, rels)
    return render_template("er.html", title=title, view=view, capture=capture, min_conf=min_conf,
                           rel_count=len(rels))


@bp.route("/er.<fmt>")
def er_export(fmt):
    title, keys, insights, _ = _scope()
    rels = relations_for(keys, insights, min_confidence=request.args.get("min", 50, type=int))
    if fmt == "mmd":
        text, mime = to_mermaid(keys, rels, get_catalog()), "text/plain"
    elif fmt == "dot":
        text, mime = to_dot(keys, rels), "text/vnd.graphviz"
    else:
        abort(404)
    return Response(text, mimetype=mime + "; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=siron_er.%s" % fmt})


# --------------------------------------------------------------------------- builder

@bp.route("/builder", methods=["GET", "POST"])
def builder():
    catalog = get_catalog()
    pa = project_analysis()
    touched = table_like(pa.tables)
    form = request.form
    selected = [parse_key(t) for t in form.getlist("t")]
    selected += [parse_key(t) for t in form.get("extra", "").replace(",", "\n").splitlines() if t.strip()]
    if catalog:
        selected = [catalog.resolve(k[0], k[1], ctx()[0].current_schema) or k for k in selected]
    selected = list(dict.fromkeys(selected))
    root = parse_key(form["root"]) if form.get("root") else (selected[0] if selected else None)
    if root in selected:
        selected.remove(root)
    sql = None
    edges, unreachable = [], []
    if request.method == "POST" and root:
        scope = set(catalog.tables) if catalog else set(touched)
        rels = relations_for(scope | set(selected) | {root}, pa.insights,
                             min_confidence=form.get("min", 50, type=int))
        edges, unreachable = find_join_tree(rels, [root] + selected)
        columns = None
        if form.get("used_only"):
            columns = {}
            for col in pa.columns:
                columns.setdefault(col[:2], []).append(col[2])
            if catalog:
                order = {(c.owner, c.table, c.name): c.position for t in catalog.tables.values() for c in t.columns}
                for k in columns:
                    columns[k].sort(key=lambda c: order.get((k[0], k[1], c), 9999))
        sql = build_select(root, edges, columns, form.get("join", "LEFT JOIN"), unreachable)
    return render_template("builder.html", touched=touched, selected=selected, root=root, sql=sql,
                           edges=edges, unreachable=unreachable, form=form)


# --------------------------------------------------------------------------- search

@bp.route("/search")
def search():
    _, _, store = ctx()
    q = request.args.get("q", "").strip()
    results = {"captures": [], "tables": [], "columns": [], "statements": [], "notes": []}
    if q:
        up = q.upper()
        results["captures"] = [c for c in store.list_captures() if up in c["name"].upper()
                               or up in (c["notes"] or "").upper()]
        catalog = get_catalog()
        if catalog:
            for t in catalog.tables.values():
                if up in t.name or (t.comment and up in t.comment.upper()):
                    results["tables"].append(t)
                for c in t.columns:
                    if up in c.name or (c.comment and up in c.comment.upper()):
                        results["columns"].append(c)
            results["tables"] = results["tables"][:200]
            results["columns"] = results["columns"][:300]
        results["statements"] = store.search_sql(q)
        results["notes"] = [a for a in store.annotations().values()
                            if up in (a.get("note") or "").upper() or up in (a.get("target") or "").upper()]
    return render_template("search.html", q=q, results=results)
