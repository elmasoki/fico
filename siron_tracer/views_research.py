"""Routes: the Siron AML research, tied to what the schema and the captures show."""
from __future__ import annotations

from datetime import datetime

from flask import abort, flash, redirect, render_template, request, url_for

from . import knowledge as kb
from .catalog import ann
from .mdrender import render as render_markdown
from .views import bp
from .web import ctx, get_catalog, known_schemas, log, project_analysis

DOC_META = "research_doc"
MAX_DOC_BYTES = 2 * 1024 * 1024


def research_document():
    """(markdown, info) - an uploaded version wins over the bundled one."""
    store = ctx()[2]
    text = store.get_meta(DOC_META)
    if text:
        return text, {"custom": True, "name": store.get_meta(DOC_META + "_name") or "araştırma.md",
                      "updated": store.get_meta(DOC_META + "_updated")}
    return kb.load_document(), {"custom": False, "name": "siron_aml_arastirma.md", "updated": None}


def classified_tables():
    """Every table the app knows (catalog + captures) with its research classification and evidence."""
    catalog = get_catalog()
    pa = project_analysis()
    annotations = ctx()[2].annotations()
    keys = set(catalog.tables if catalog else ()) | set(pa.tables)
    rows = []
    for key in keys:
        table = catalog.tables.get(key) if catalog else None
        entry = pa.tables.get(key) or {}
        rows.append({"key": key, "table": table, "cls": kb.classify(key[1]),
                     "screens": len(entry.get("screens", ())), "indirect": entry.get("indirect"),
                     "status": ann(annotations, key).get("status") or ""})
    rows.sort(key=lambda r: (-r["screens"], r["key"][1]))
    return rows


def module_stats(rows):
    stats = {m.id: {"module": m, "tables": 0, "seen": 0, "rows": 0, "decided": 0, "known_found": 0}
             for m in kb.MODULES}
    unclassified = []
    for r in rows:
        if not r["cls"]:
            unclassified.append(r)
            continue
        s = stats[r["cls"].module.id]
        s["tables"] += 1
        s["seen"] += 1 if r["screens"] else 0
        s["rows"] += (r["table"].num_rows or 0) if r["table"] else 0
        s["decided"] += 1 if r["status"] else 0
        s["known_found"] += 1 if r["cls"].known else 0
    for m in kb.MODULES:
        stats[m.id]["known_total"] = len([t for t in kb.KNOWN_TABLES if t.module == m.id])
    return stats, unclassified


def _names_in_schema(rows):
    found = {}
    for r in rows:
        found.setdefault(r["key"][1], r)
    return found


@bp.route("/research")
def research():
    rows = classified_tables()
    stats, unclassified = module_stats(rows)
    by_conf = {c: 0 for c in kb.CONFIDENCE_ORDER}
    for r in rows:
        if r["cls"]:
            by_conf[r["cls"].confidence] += 1
    _, info = research_document()
    return render_template("research.html", tab="overview", stats=stats, rows=rows, unclassified=unclassified,
                           by_conf=by_conf, findings=kb.KEY_FINDINGS, doc_info=info,
                           has_catalog=bool(get_catalog()), kb=kb)


@bp.route("/research/module/<module_id>")
def research_module(module_id):
    module = kb.MODULE_BY_ID.get(module_id)
    if module is None:
        abort(404)
    rows = [r for r in classified_tables() if r["cls"] and r["cls"].module.id == module_id]
    found = {r["key"][1] for r in rows}
    missing = [t for t in kb.KNOWN_TABLES if t.module == module_id and t.name not in found]
    families = [f for f in kb.FAMILIES if f.module == module_id]
    return render_template("research_module.html", tab="overview", module=module, rows=rows, missing=missing,
                           families=families, has_catalog=bool(get_catalog()), kb=kb)


@bp.route("/research/tables")
def research_tables():
    q = request.args.get("q", "").strip().upper()
    module = request.args.get("module", "")
    conf = request.args.get("conf", "")
    where = request.args.get("where", "")
    in_schema = _names_in_schema(classified_tables())
    items = []
    for t in kb.KNOWN_TABLES:
        if module and t.module != module:
            continue
        if conf and t.confidence != conf:
            continue
        if q and q not in t.name and q not in t.meaning.upper() and q not in t.expansion.upper():
            continue
        hit = in_schema.get(t.name)
        if where == "found" and not hit or where == "missing" and hit:
            continue
        items.append({"t": t, "hit": hit})
    return render_template("research_tables.html", tab="tables", items=items, q=q, module=module, conf=conf,
                           where=where, found=sum(1 for t in kb.KNOWN_TABLES if t.name in in_schema),
                           has_catalog=bool(get_catalog()), kb=kb)


@bp.route("/research/terms")
def research_terms():
    name = request.args.get("name", "").strip().upper()
    explained = kb.explain(name) if name else []
    cls = kb.classify(name) if name else None
    return render_template("research_terms.html", tab="terms", name=name, explained=explained, cls=cls, kb=kb)


@bp.route("/research/queries")
def research_queries():
    settings = ctx()[0]
    schema = (request.args.get("schema") or settings.current_schema).upper()
    groups = [(cat, [q for q in kb.QUERIES if q.category == cat]) for cat in kb.QUERY_CATEGORIES]
    return render_template("research_queries.html", tab="queries", groups=groups, schema=schema,
                           schemas=known_schemas(), kb=kb)


@bp.route("/research/document", methods=["GET", "POST"])
def research_doc():
    store = ctx()[2]
    if request.method == "POST":
        if request.form.get("action") == "reset":
            for k in (DOC_META, DOC_META + "_name", DOC_META + "_updated"):
                store.set_meta(k, "")
            log("research", "Araştırma belgesi uygulamadaki sürüme döndürüldü")
            flash("Uygulamayla gelen araştırma belgesine dönüldü.", "ok")
            return redirect(url_for(".research_doc"))
        upload = request.files.get("file")
        raw = upload.read(MAX_DOC_BYTES + 1) if upload else b""
        if not raw.strip():
            flash("Bir Markdown (.md) dosyası seçin.", "error")
        elif len(raw) > MAX_DOC_BYTES:
            flash("Dosya 2 MB'tan büyük olamaz.", "error")
        else:
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = None
                flash("Dosya UTF-8 metin olmalı.", "error")
            if text is not None:
                store.set_meta(DOC_META, text)
                store.set_meta(DOC_META + "_name", upload.filename or "araştırma.md")
                store.set_meta(DOC_META + "_updated", datetime.now().strftime("%Y-%m-%d %H:%M"))
                log("research", "Araştırma belgesi güncellendi: %s" % (upload.filename or ""))
                flash("Araştırma belgesi güncellendi.", "ok")
        return redirect(url_for(".research_doc"))
    text, info = research_document()
    body, toc = render_markdown(text)
    return render_template("research_doc.html", tab="document", body=body, toc=toc, info=info, kb=kb)
