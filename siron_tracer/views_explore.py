"""Routes that help map a screen to its SQL: capture timeline, capture comparison,
linking several SQLs to an inventory screen at once."""
from __future__ import annotations

from flask import flash, redirect, render_template, request, url_for

from .timeline import build_steps
from .views import bp
from .web import capture_analysis, capture_or_404, ctx


@bp.route("/captures/<int:capture_id>/timeline")
def capture_timeline(capture_id):
    _, _, store = ctx()
    capture = capture_or_404(capture_id)
    ca = capture_analysis(capture, exclude_noise=False)
    gap = max(0.2, min(request.args.get("gap", 2.0, type=float), 120.0))
    hide_noise = request.args.get("noise", "1") == "1" and not capture["is_noise"]
    noise_ids = store.noise_sql_ids() if not capture["is_noise"] else set()
    steps = build_steps(store.records(capture_id), {st.sql_id: st.tables for st in ca.statements}, gap,
                        noise_ids, hide_noise)
    return render_template("capture_timeline.html", capture=capture, ca=ca, steps=steps, gap=gap,
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
