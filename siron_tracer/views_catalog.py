"""Routes: tables, table detail (mapping, profile, dependencies), relations,
ER diagram, query builder, search."""
from __future__ import annotations

from flask import Response, abort, flash, redirect, render_template, request, url_for

from . import knowledge
from .catalog import label
from .profiling import quality_flags
from .relations import (SOURCE_LABELS, build_select, find_join_tree, parse_relation_id, qualified,
                        relation_id, to_dot, to_mermaid)
from .views import bp, search_table
from .web import (ann, capture_analysis, capture_or_404, ctx, er_view, ext, get_catalog, is_sensitive,
                  known_schemas, log, parse_key, project_analysis, project_relations, relations_for, table_like)


def _key_from_url(owner: str, name: str):
    return (None if owner == "-" else owner, name)


def profile_job(keys, title):
    """Background job profiling the given tables."""
    settings, oracle, store = ctx()
    catalog = get_catalog()
    keys = [k for k in keys if catalog and k in catalog.tables]

    def work(job):
        done = []
        for n, key in enumerate(keys):
            base = 100.0 * n / max(len(keys), 1)
            job.progress(base, "%s profilleniyor" % label(key))
            stats = oracle.profile(key, catalog.tables[key], settings.profile_sample_rows,
                                   progress=lambda f: job.progress(base + f * 100.0 / max(len(keys), 1)))
            for col, data in stats.items():
                store.save_profile(key[0], key[1], col, data)
            done.append(label(key))
        store.log("profile", "Veri profili: %s" % ", ".join(done))
        job.message = "%d tablo profillendi" % len(done)
        return {"tables": done}

    if not keys:
        flash("Profillenecek tablo yok (veri sözlüğü yüklü mü?).", "error")
        return None
    return ext()["jobs"].submit("profile", title, work, {"tables": [label(k) for k in keys]})


# --------------------------------------------------------------------------- tables

@bp.route("/tables")
def tables():
    _, _, store = ctx()
    catalog = get_catalog()
    pa = project_analysis()
    show_all = request.args.get("all") == "1" and catalog
    q = request.args.get("q", "").strip().upper()
    status = request.args.get("status", "")
    module = request.args.get("module", "")
    annotations = store.annotations()
    profiled = {(k[0], k[1]) for k in store.profiles()}
    keys = list(catalog.tables) if show_all else table_like(pa.tables)
    used_cols = {}
    for col in pa.columns:
        used_cols.setdefault(col[:2], set()).add(col[2])
    rel_count = {}
    for r in project_relations(50):
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
        cls = knowledge.classify(key[1])
        if module and (cls.module.id if cls else "none") != module:
            continue
        entry = pa.tables.get(key, {"screens": [], "actions": set(), "type": None, "indirect": False, "kinds": set()})
        rows.append({"key": key, "table": table, "cls": cls, "screens": entry["screens"], "actions": entry["actions"],
                     "indirect": entry.get("indirect"), "kinds": entry.get("kinds", set()),
                     "used": len(used_cols.get(key, ())), "total": len(table.columns) if table else None,
                     "ann": a, "relations": rel_count.get(key, 0), "profiled": (key[0] or None, key[1]) in profiled})
    rows.sort(key=lambda r: (-len(r["screens"]), r["key"][1]))
    return render_template("tables.html", rows=rows, show_all=show_all, q=q, status=status, module=module,
                           modules=knowledge.MODULES,
                           has_catalog=bool(catalog), capture_count=len(pa.captures))


@bp.post("/tables/bulk")
def tables_bulk():
    _, _, store = ctx()
    keys = [parse_key(k) for k in request.form.getlist("k")]
    action = request.form.get("action")
    if not keys:
        flash("Önce tablo seçin.", "error")
        return redirect(request.referrer or url_for(".tables"))
    if action == "profile":
        job_id = profile_job(keys, "Veri profili: %d tablo" % len(keys))
        return redirect(url_for(".job", job_id=job_id) if job_id else request.referrer or url_for(".tables"))
    if action in ("migrate", "review", "ignore", "clear"):
        for key in keys:
            store.save_annotation(key[0], key[1], "", status=None if action == "clear" else action)
        flash("%d tablonun durumu güncellendi." % len(keys), "ok")
    return redirect(request.referrer or url_for(".tables"))


@bp.route("/table/<owner>/<name>", methods=["GET", "POST"])
def table(owner, name):
    settings, oracle, store = ctx()
    key = _key_from_url(owner, name)
    catalog = get_catalog()
    info = catalog.tables.get(key) if catalog else None
    form = request.form

    if request.method == "POST" and form.get("action") == "annotate":
        store.save_annotation(key[0], key[1], "", status=form.get("status"), note=form.get("note"),
                              target=form.get("target"), extract_filter=form.get("extract_filter"))
        for col in (info.columns if info else []):
            store.save_annotation(key[0], key[1], col.name, status=form.get("status_" + col.name),
                                  note=form.get("note_" + col.name), target=form.get("target_" + col.name),
                                  sensitive=form.get("sens_" + col.name))
        flash("Eşleme notları kaydedildi.", "ok")
        return redirect(url_for(".table", owner=owner, name=name))
    if request.method == "POST" and form.get("action") == "profile":
        job_id = profile_job([key], "Veri profili: %s" % label(key))
        return redirect(url_for(".job", job_id=job_id) if job_id else url_for(".table", owner=owner, name=name))

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
    annotations = store.annotations()
    profiles = {k[2]: v for k, v in store.profiles(key).items()}

    sample = sample_error = None
    findings, find_errors = [], []
    needle = form.get("value", "").strip()
    mode = form.get("mode", "ci")
    if request.method == "POST" and form.get("action") == "sample":
        try:
            sample = oracle.run_select("SELECT * FROM %s WHERE ROWNUM <= 20" % qualified(key))
            log("query", "Örnek satırlar: %s" % label(key), rows=len(sample[1]))
        except Exception as exc:
            sample_error = str(exc)
    if request.method == "POST" and form.get("action") == "find" and needle:
        findings, error, skipped = search_table(oracle, settings, catalog, key, needle, mode, include_big=True)
        if error or skipped:
            find_errors.append(error or skipped)

    pk = set(catalog.primary_key(key)) if catalog else set()
    uk = {c for ctype, cols in (catalog.keys_of(key) if catalog else []) if ctype == "U" for c in cols}
    fk = catalog.fk_columns(key) if catalog else set()
    sensitive = {c.name: is_sensitive(key, c.name, annotations) for c in (info.columns if info else [])}
    flags = {c.name: quality_flags(profiles.get(c.name), c.nullable) for c in (info.columns if info else [])}
    deps = catalog.depends_on(key) if catalog else []
    used_by = catalog.used_by(key) if catalog else []
    base_tables = catalog.underlying_tables(key) if catalog and info and info.obj_type != "TABLE" else []
    return render_template("table.html", key=key, info=info, entry=entry, col_usage=col_usage,
                           statements=statements, relations=relations, annotations=annotations,
                           pk=pk, uk=uk, fk=fk, sample=sample, sample_error=sample_error, profiles=profiles,
                           findings=findings, find_errors=find_errors, needle=needle, mode=mode,
                           sensitive=sensitive, flags=flags, deps=deps, used_by=used_by, base_tables=base_tables,
                           url_owner=owner, obj_type=catalog.objects.get(key) if catalog else None)


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
    state = request.args.get("state", "")
    rels = (relations_for(keys, insights, min_confidence=min_conf) if capture else project_relations(min_conf)) \
        if keys else []
    if source:
        rels = [r for r in rels if source in r.sources]
    if state == "unverified":
        rels = [r for r in rels if "constraint" not in r.sources and r.check is None]
    elif state == "verified":
        rels = [r for r in rels if r.check is not None]
    return render_template("relations.html", title=title, rels=rels, capture=capture, min_conf=min_conf,
                           source=source, state=state, source_labels=SOURCE_LABELS,
                           has_catalog=bool(get_catalog()), table_count=len(keys))


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
        log("relcheck", "%s: %d/%d" % (rid, matched, total))
    except Exception as exc:
        flash("İlişki kontrol edilemedi: %s" % exc, "error")
    return redirect(request.referrer or url_for(".relations"))


@bp.post("/relations/check-all")
def relation_check_all():
    """Background job: check every inferred / SQL relation of the scope that has no result yet."""
    _, oracle, store = ctx()
    title, keys, insights, _ = _scope()
    todo = [r for r in relations_for(keys, insights) if "constraint" not in r.sources and r.check is None]

    def work(job):
        done = failed = 0
        for n, r in enumerate(todo):
            job.progress(100.0 * n / max(len(todo), 1), r.text)
            try:
                matched, total = oracle.check_relation(r.child, r.child_cols, r.parent, r.parent_cols)
                store.save_relation_check(r.id, matched, total)
                done += 1
            except Exception:
                failed += 1
        store.log("relcheck", "%d ilişki doğrulandı, %d hata (%s)" % (done, failed, title))
        job.message = "%d ilişki doğrulandı%s" % (done, ", %d hata" % failed if failed else "")
        return {"checked": done, "failed": failed}

    job_id = ext()["jobs"].submit("relcheck", "İlişki doğrulama: %s (%d)" % (title, len(todo)), work)
    return redirect(url_for(".job", job_id=job_id))


@bp.route("/er")
def er():
    title, keys, insights, capture = _scope()
    min_conf = request.args.get("min", 50, type=int)
    rels = (relations_for(keys, insights, min_confidence=min_conf) if capture else project_relations(min_conf)) \
        if keys else []
    view = er_view(keys, rels)
    return render_template("er.html", title=title, view=view, capture=capture, min_conf=min_conf,
                           rel_count=len(rels))


@bp.route("/er.<fmt>")
def er_export(fmt):
    title, keys, insights, capture = _scope()
    min_conf = request.args.get("min", 50, type=int)
    rels = relations_for(keys, insights, min_confidence=min_conf) if capture else project_relations(min_conf)
    if fmt == "mmd":
        text, mime = to_mermaid(keys, rels, get_catalog()), "text/plain"
    elif fmt == "dot":
        text, mime = to_dot(keys, rels), "text/vnd.graphviz"
    else:
        abort(404)
    log("export_er", "ER %s (%s)" % (fmt, title))
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
    results = {"captures": [], "tables": [], "columns": [], "statements": [], "notes": [], "screens": [], "research": []}
    if q:
        up = q.upper()
        results["captures"] = [c for c in store.list_captures() if up in c["name"].upper()
                               or up in (c["notes"] or "").upper()]
        results["screens"] = [s for s in store.list_screens() if up in s["name"].upper()
                              or up in (s["module"] or "").upper()]
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
        results["research"] = [t for t in knowledge.KNOWN_TABLES
                               if up in t.name or up in t.meaning.upper() or up in t.expansion.upper()][:30]
        results["statements"] = store.search_sql(q)
        results["notes"] = [a for a in store.annotations().values()
                            if up in (a.get("note") or "").upper() or up in (a.get("target") or "").upper()]
    return render_template("search.html", q=q, results=results,
                           total=sum(len(v) for v in results.values()))
