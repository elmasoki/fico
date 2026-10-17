"""Helpers shared by the Flask views."""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from flask import abort, current_app

from .analysis import CaptureAnalysis, ProjectAnalysis, analyse, analyse_project
from .catalog import label
from .layout import layout
from .relations import Relation, build_relations
from .sqlutil import build_slots, find_placeholders, parse_audit_binds, substitute_binds

STATUSES = {"migrate": "Taşınacak", "review": "İncelenecek", "ignore": "Gereksiz"}


def ann(annotations: dict, key, column: str = "") -> dict:
    return annotations.get((key[0] or "", key[1], column), {})


def parse_key(text: str):
    text = text.strip().upper()
    if "." in text:
        owner, name = text.split(".", 1)
        return (owner, name)
    return (None, text)


def table_like(keys: Iterable) -> List:
    """Drop packages, sequences etc.; keep tables, views and unknown objects."""
    catalog = get_catalog()
    if not catalog:
        return list(keys)
    return [k for k in keys if k in catalog.tables or k not in catalog.objects]


def ctx():
    ext = current_app.extensions["siron"]
    return ext["settings"], ext["oracle"], ext["store"]


def get_catalog():
    cat = ctx()[2].catalog()
    return cat if cat else None


def capture_or_404(capture_id: int):
    capture = ctx()[2].get_capture(capture_id)
    if capture is None:
        abort(404)
    return capture


def capture_analysis(capture, exclude_noise: bool = True) -> CaptureAnalysis:
    settings, _, store = ctx()
    noise = store.noise_sql_ids() if exclude_noise and not capture["is_noise"] else None
    return analyse(store.records(capture["id"]), get_catalog(), settings.current_schema, noise)


def project_analysis() -> ProjectAnalysis:
    settings, _, store = ctx()
    return analyse_project(store.list_captures(), store.records, get_catalog(),
                           settings.current_schema, store.noise_sql_ids())


def relations_for(keys: Iterable, insights=(), other: Optional[Iterable] = None,
                  infer: bool = True, min_confidence: int = 0) -> List[Relation]:
    store = ctx()[2]
    return build_relations(get_catalog(), set(keys), set(other) if other is not None else None,
                           insights, store.relation_checks(), infer, min_confidence)


def literal_for(sql_text: str, raw_binds: Optional[str]):
    placeholders = find_placeholders(sql_text)
    slots = build_slots(placeholders, parse_audit_binds(raw_binds))
    return substitute_binds(sql_text, placeholders, slots), slots


# --------------------------------------------------------------------------- ER view

def _clip(cx, cy, w, h, tx, ty):
    """Point where the line from a box centre towards (tx, ty) leaves the box."""
    dx, dy = tx - cx, ty - cy
    if dx == 0 and dy == 0:
        return cx, cy
    sx = (w / 2) / abs(dx) if dx else float("inf")
    sy = (h / 2) / abs(dy) if dy else float("inf")
    s = min(sx, sy)
    return round(cx + dx * s, 1), round(cy + dy * s, 1)


def er_view(keys: Iterable, relations: List[Relation], focus: Iterable = ()) -> Dict:
    """Nodes/edges with coordinates for the SVG ER diagram."""
    from flask import url_for
    catalog = get_catalog()
    annotations = ctx()[2].annotations()
    focus = set(focus)
    keys = list(dict.fromkeys(list(keys) + [k for r in relations for k in (r.child, r.parent)]))
    sizes = {}
    for k in keys:
        name = k[1]
        sizes[k] = (max(110, 7.4 * len(name) + 26), 42)
    pos, width, height = layout([(k, w, h) for k, (w, h) in sizes.items()],
                                [(r.child, r.parent) for r in relations])
    nodes = []
    for k in keys:
        x, y = pos[k]
        w, h = sizes[k]
        table = catalog.tables.get(k) if catalog else None
        sub = []
        if table is not None:
            sub.append(table.obj_type.lower() if table.obj_type != "TABLE" else "")
            if table.num_rows is not None:
                sub.append("%s satır" % format(table.num_rows, ",").replace(",", "."))
        a = ann(annotations, k)
        nodes.append({
            "id": label(k), "label": k[1], "owner": k[0], "x": x, "y": y, "w": w, "h": h,
            "sub": " · ".join(s for s in sub if s), "status": a.get("status") or "",
            "focus": k in focus, "known": table is not None,
            "url": url_for("siron.table", owner=k[0] or "-", name=k[1]),
            "title": (table.comment if table is not None and table.comment else label(k)),
        })
    by_id = {n["id"]: n for n in nodes}
    edges = []
    for r in relations:
        a, b = by_id[label(r.child)], by_id[label(r.parent)]
        acx, acy, bcx, bcy = a["x"] + a["w"] / 2, a["y"] + a["h"] / 2, b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
        x1, y1 = _clip(acx, acy, a["w"], a["h"], bcx, bcy)
        x2, y2 = _clip(bcx, bcy, b["w"], b["h"], acx, acy)
        edges.append({
            "a": a["id"], "b": b["id"], "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "cls": r.main_source, "directed": r.directed, "self": r.child == r.parent,
            "verified": r.ratio is not None and r.ratio >= 0.95,
            "title": "%s\n%s · güven %d" % (r.text, ", ".join(r.sources), r.confidence),
        })
    return {"nodes": nodes, "edges": edges, "width": width, "height": height}
