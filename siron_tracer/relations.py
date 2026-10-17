"""Relationship discovery between tables.

Three kinds of evidence are combined into one list of relations:

* constraint - declared foreign keys (DBA_CONSTRAINTS)                  -> 100
* sql        - equality joins Siron itself executes (captured SQL)      ->  90
* name       - column name / type matches another table's key column  -> 50-70

A relation can be checked against the data (how many distinct child values
exist in the parent); the result raises or lowers its confidence.

The module also finds join paths between chosen tables and turns them into a
SELECT, and exports relations as Mermaid / Graphviz text.
"""
from __future__ import annotations

import heapq
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .catalog import Catalog, ObjectKey, label

SOURCE_LABELS = {"constraint": "Constraint (FK)", "sql": "Siron SQL join", "name": "Ad/tip tahmini"}
GENERIC_COLUMNS = {"ID", "NO", "CODE", "CD", "KEY", "NAME", "TYPE", "STATUS", "VALUE",
                   "DESCRIPTION", "DESC", "VERSION", "SEQ", "FLAG"}


@dataclass
class Relation:
    child: ObjectKey
    child_cols: Tuple[str, ...]
    parent: ObjectKey
    parent_cols: Tuple[str, ...]
    directed: bool = True
    sources: Dict[str, str] = field(default_factory=dict)
    sql_ids: Set[str] = field(default_factory=set)
    base_confidence: int = 0
    check: Optional[Tuple[int, int]] = None  # (matched, total) from a data check

    @property
    def key(self):
        return (self.child, self.child_cols, self.parent, self.parent_cols)

    @property
    def id(self) -> str:
        return relation_id(self.child, self.child_cols, self.parent, self.parent_cols)

    @property
    def ratio(self) -> Optional[float]:
        if self.check and self.check[1]:
            return self.check[0] / self.check[1]
        return None

    @property
    def confidence(self) -> int:
        conf = self.base_confidence
        if "constraint" in self.sources:
            conf = 100
        elif "sql" in self.sources:
            conf = max(conf, 90)
        ratio = self.ratio
        if ratio is not None and "constraint" not in self.sources:
            if ratio >= 0.95:
                conf = max(conf, 85)
            elif ratio < 0.5:
                conf = min(conf, 25)
        return conf

    @property
    def main_source(self) -> str:
        for s in ("constraint", "sql", "name"):
            if s in self.sources:
                return s
        return "name"

    def condition(self, child_alias: str, parent_alias: str) -> str:
        return " AND ".join("%s.%s = %s.%s" % (child_alias, qi(c), parent_alias, qi(p))
                            for c, p in zip(self.child_cols, self.parent_cols))

    def other(self, key: ObjectKey) -> ObjectKey:
        return self.parent if key == self.child else self.child

    @property
    def text(self) -> str:
        arrow = "→" if self.directed else "↔"
        return "%s(%s) %s %s(%s)" % (label(self.child), ", ".join(self.child_cols), arrow,
                                     label(self.parent), ", ".join(self.parent_cols))


def relation_id(child, child_cols, parent, parent_cols) -> str:
    return "%s(%s)>%s(%s)" % (label(child), ",".join(child_cols), label(parent), ",".join(parent_cols))


def parse_relation_id(rid: str):
    m = re.match(r"^(.+?)\((.*?)\)>(.+?)\((.*?)\)$", rid)
    if not m:
        raise ValueError(rid)

    def key(text):
        parts = text.split(".")
        return (parts[0], parts[1]) if len(parts) == 2 else (None, parts[0])

    return key(m.group(1)), tuple(m.group(2).split(",")), key(m.group(3)), tuple(m.group(4).split(","))


def qi(name: Optional[str]) -> str:
    """Quote an Oracle identifier only when it needs quoting."""
    if name is None:
        return ""
    return name if re.match(r"^[A-Z][A-Z0-9_$#]*$", name) else '"%s"' % name.replace('"', '')


def qualified(key: ObjectKey) -> str:
    return "%s.%s" % (qi(key[0]), qi(key[1])) if key[0] else qi(key[1])


# --------------------------------------------------------------------------- naming

def _stems(table_name: str) -> Set[str]:
    stems = {table_name}
    for suffix in ("_TBL", "_TAB", "_T"):
        if table_name.endswith(suffix) and len(table_name) > len(suffix) + 2:
            stems.add(table_name[: -len(suffix)])
    for s in list(stems):
        if "_" in s and len(s.split("_", 1)[1]) >= 3:
            stems.add(s.split("_", 1)[1])  # prefix such as TB_, SIR_
    for s in list(stems):
        if s.endswith("IES") and len(s) > 4:
            stems.add(s[:-3] + "Y")
        elif s.endswith("ES") and len(s) > 4:
            stems.add(s[:-2])
        if s.endswith("S") and len(s) > 3:
            stems.add(s[:-1])
    return stems


def _key_suffixes(key_col: str) -> Set[str]:
    out = {"_" + key_col}
    if key_col == "ID" or key_col.endswith("ID"):
        out |= {"_ID", "ID"}
    if key_col.endswith("NO"):
        out |= {"_NO"}
    if key_col.endswith("CODE") or key_col.endswith("CD"):
        out |= {"_CODE", "_CD"}
    if key_col.endswith("KEY"):
        out |= {"_KEY"}
    return out


def _refers_to(cols: Tuple[str, ...], table: ObjectKey) -> bool:
    stems = _stems(table[1])
    return any(c.startswith(s + "_") or c == s + "ID" for c in cols for s in stems)


# --------------------------------------------------------------------------- build

class _Builder:
    def __init__(self, catalog: Optional[Catalog], focus: Set[ObjectKey], other: Optional[Set[ObjectKey]]):
        self.catalog = catalog
        self.focus = set(focus)
        self.other = set(other) if other is not None else self.focus
        self.rels: Dict[tuple, Relation] = {}

    def in_scope(self, a: ObjectKey, b: ObjectKey) -> bool:
        return (a in self.focus and b in self.other) or (b in self.focus and a in self.other)

    def add(self, child, ccols, parent, pcols, source, evidence, confidence, directed=True, sql_id=None):
        ccols, pcols = tuple(ccols), tuple(pcols)
        key = (child, ccols, parent, pcols)
        rkey = (parent, pcols, child, ccols)
        rel = self.rels.get(key)
        if rel is None and rkey in self.rels:
            rel = self.rels[rkey]
            if directed and not rel.directed:  # adopt the better known direction
                del self.rels[rkey]
                rel.child, rel.child_cols, rel.parent, rel.parent_cols = child, ccols, parent, pcols
                rel.directed = True
                self.rels[key] = rel
        if rel is None:
            rel = self.rels[key] = Relation(child, ccols, parent, pcols, directed)
        if source not in rel.sources:
            rel.sources[source] = evidence
        elif source == "sql" and evidence not in rel.sources[source]:
            rel.sources[source] += ", " + evidence
        rel.base_confidence = max(rel.base_confidence, confidence)
        if sql_id:
            rel.sql_ids.add(sql_id)

    def from_constraints(self):
        if not self.catalog:
            return
        for child, ccols, parent, pcols, name in self.catalog.foreign_keys():
            if self.in_scope(child, parent):
                self.add(child, ccols, parent, pcols, "constraint", name, 100)

    def from_sql(self, insights):
        cat = self.catalog
        for sql_id, insight in insights:
            groups: Dict[tuple, List[Tuple[str, str]]] = {}
            for j in insight.joins:
                lt, rt = j.left[:2], j.right[:2]
                groups.setdefault((lt, j.left_alias, rt, j.right_alias), []).append((j.left[2], j.right[2]))
            for (lt, _, rt, _), pairs in groups.items():
                if not self.in_scope(lt, rt):
                    continue
                pairs = sorted(set(pairs))
                lcols = tuple(p[0] for p in pairs)
                rcols = tuple(p[1] for p in pairs)
                l_key = bool(cat) and cat.is_key(lt, lcols)
                r_key = bool(cat) and cat.is_key(rt, rcols)
                if r_key and not l_key:
                    args = (lt, lcols, rt, rcols, True)
                elif l_key and not r_key:
                    args = (rt, rcols, lt, lcols, True)
                elif not l_key and not r_key and _refers_to(lcols, rt) and not _refers_to(rcols, lt):
                    args = (lt, lcols, rt, rcols, True)
                elif not l_key and not r_key and _refers_to(rcols, lt) and not _refers_to(lcols, rt):
                    args = (rt, rcols, lt, lcols, True)
                else:
                    args = (lt, lcols, rt, rcols, False)
                c, cc, p, pc, directed = args
                self.add(c, cc, p, pc, "sql", sql_id, 90, directed=directed, sql_id=sql_id)

    def from_names(self):
        cat = self.catalog
        if not cat:
            return
        candidates = [k for k in (self.focus | self.other) if cat.has_columns(k)]
        index: Dict[str, List[Tuple[ObjectKey, str, int]]] = {}
        for p in candidates:
            for _, cols in cat.keys_of(p):
                if len(cols) != 1:
                    continue
                k = cols[0]
                if k not in GENERIC_COLUMNS:
                    index.setdefault(k, []).append((p, k, 70))
                for stem in _stems(p[1]):
                    for suffix in _key_suffixes(k):
                        if stem + suffix != k:
                            index.setdefault(stem + suffix, []).append((p, k, 65))
        existing = {(r.child, r.child_cols) for r in self.rels.values()} | \
                   {(r.parent, r.parent_cols) for r in self.rels.values() if not r.directed}
        for c in candidates:
            own_pk = cat.primary_key(c)
            for col in cat.columns(c):
                for p, k, score in index.get(col.name, ()):
                    if p == c or not self.in_scope(c, p) or (c, (col.name,)) in existing:
                        continue
                    parent_col = cat.column(p, k)
                    if parent_col is None or parent_col.family != col.family or col.family in ("lob", "date"):
                        continue
                    if own_pk == (col.name,):
                        if col.name != k:
                            continue
                        score = 55  # shared primary key: 1-1 extension table
                    self.add(c, (col.name,), p, (k,), "name",
                             "%s.%s ~ %s.%s" % (c[1], col.name, p[1], k), score)


def build_relations(catalog: Optional[Catalog], focus: Iterable[ObjectKey],
                    other: Optional[Iterable[ObjectKey]] = None, insights=(),
                    checks: Optional[Dict[str, Tuple[int, int]]] = None,
                    infer: bool = True, min_confidence: int = 0) -> List[Relation]:
    """Relations with one end in `focus` and the other in `other` (default: focus)."""
    b = _Builder(catalog, set(focus), set(other) if other is not None else None)
    b.from_constraints()
    b.from_sql(insights)
    if infer:
        b.from_names()
    checks = checks or {}
    rels = list(b.rels.values())
    for r in rels:
        r.check = checks.get(r.id)
        if r.check is None and not r.directed:
            r.check = checks.get(relation_id(r.parent, r.parent_cols, r.child, r.child_cols))
    rels = [r for r in rels if r.confidence >= min_confidence]
    return sorted(rels, key=lambda r: (-r.confidence, r.text))


# --------------------------------------------------------------------------- join paths

def find_join_tree(relations: List[Relation], tables: List[ObjectKey]):
    """Connect `tables` (first one is the root) with the most trusted relations.

    Returns (edges, unreachable). A greedy Steiner tree: every next table is
    attached to the current tree by its cheapest path (cost = 101 - confidence).
    """
    graph: Dict[ObjectKey, List[Tuple[ObjectKey, Relation]]] = {}
    for r in relations:
        if r.child == r.parent:
            continue
        graph.setdefault(r.child, []).append((r.parent, r))
        graph.setdefault(r.parent, []).append((r.child, r))
    if not tables:
        return [], []
    tree = {tables[0]}
    edges: List[Relation] = []
    unreachable: List[ObjectKey] = []
    for target in tables[1:]:
        if target in tree:
            continue
        dist = {target: 0}
        back: Dict[ObjectKey, Tuple[ObjectKey, Relation]] = {}
        heap = [(0, 0, target)]
        found = None
        counter = 0
        while heap:
            d, _, node = heapq.heappop(heap)
            if node in tree:
                found = node
                break
            if d > dist.get(node, 1e18):
                continue
            for nxt, rel in graph.get(node, ()):
                nd = d + (101 - rel.confidence)
                if nd < dist.get(nxt, 1e18):
                    dist[nxt] = nd
                    back[nxt] = (node, rel)
                    counter += 1
                    heapq.heappush(heap, (nd, counter, nxt))
        if found is None:
            unreachable.append(target)
            continue
        node = found
        while node != target:
            prev, rel = back[node]
            if rel not in edges:
                edges.append(rel)
            tree.add(node)
            node = prev
        tree.add(target)
    return edges, unreachable


def build_select(root: ObjectKey, edges: List[Relation], columns: Optional[Dict[ObjectKey, List[str]]] = None,
                 join: str = "LEFT JOIN", extra_tables: Iterable[ObjectKey] = ()) -> str:
    """SELECT joining `root` to the tables of `edges`."""
    alias = {root: "t1"}
    order = [root]
    joins = []
    pending = list(edges)
    while pending:
        progressed = False
        for rel in list(pending):
            known = [k for k in (rel.child, rel.parent) if k in alias]
            if not known:
                continue
            pending.remove(rel)
            progressed = True
            new = rel.other(known[0])
            if new in alias:
                continue
            alias[new] = "t%d" % (len(alias) + 1)
            order.append(new)
            joins.append("  %s %s %s ON %s" % (join, qualified(new), alias[new],
                                               rel.condition(alias[rel.child], alias[rel.parent])))
        if not progressed:
            break
    for key in extra_tables:
        if key not in alias:
            alias[key] = "t%d" % (len(alias) + 1)
            order.append(key)
            joins.append("  CROSS JOIN %s %s  -- ilişki bulunamadı" % (qualified(key), alias[key]))
    select = []
    for key in order:
        cols = (columns or {}).get(key)
        if cols:
            select.extend("%s.%s" % (alias[key], qi(c)) for c in cols)
        else:
            select.append("%s.*" % alias[key])
    return "SELECT %s\n  FROM %s t1\n%s" % (",\n       ".join(select), qualified(root), "\n".join(joins))


# --------------------------------------------------------------------------- export

def _entity(key: ObjectKey, multi_owner: bool) -> str:
    name = "%s_%s" % (key[0], key[1]) if multi_owner and key[0] else key[1]
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


def to_mermaid(tables: Iterable[ObjectKey], relations: List[Relation], catalog: Optional[Catalog] = None) -> str:
    tables = list(tables)
    multi = len({t[0] for t in tables}) > 1
    lines = ["erDiagram"]
    rel_cols: Dict[ObjectKey, Set[str]] = {}
    for r in relations:
        rel_cols.setdefault(r.child, set()).update(r.child_cols)
        rel_cols.setdefault(r.parent, set()).update(r.parent_cols)
    for t in tables:
        attrs = []
        if catalog:
            pk = set(catalog.primary_key(t))
            fk = catalog.fk_columns(t)
            for c in catalog.columns(t):
                if c.name in pk or c.name in rel_cols.get(t, ()):
                    marks = ",".join(m for m, on in (("PK", c.name in pk), ("FK", c.name in fk)) if on)
                    attrs.append("        %s %s%s" % (re.sub(r"\W", "_", c.data_type or "X"), c.name,
                                                       " " + marks if marks else ""))
        lines.append("    %s {" % _entity(t, multi) if attrs else "    %s" % _entity(t, multi))
        if attrs:
            lines.extend(attrs)
            lines.append("    }")
    for r in relations:
        line = "--" if r.main_source != "name" else ".."
        card = "||%so{" % line if r.directed else "}o%so{" % line
        text = ", ".join("%s=%s" % (c, p) for c, p in zip(r.child_cols, r.parent_cols))
        lines.append('    %s %s %s : "%s"' % (_entity(r.parent, multi), card, _entity(r.child, multi), text))
    return "\n".join(lines)


def to_dot(tables: Iterable[ObjectKey], relations: List[Relation]) -> str:
    lines = ["digraph siron {", "  rankdir=LR;", '  node [shape=box, style="rounded", fontname="Helvetica"];']
    for t in tables:
        lines.append('  "%s";' % label(t))
    styles = {"constraint": "solid", "sql": "bold", "name": "dashed"}
    for r in relations:
        text = ", ".join("%s=%s" % (c, p) for c, p in zip(r.child_cols, r.parent_cols))
        lines.append('  "%s" -> "%s" [label="%s", style=%s%s];' % (
            label(r.child), label(r.parent), text, styles[r.main_source], "" if r.directed else ", dir=none"))
    lines.append("}")
    return "\n".join(lines)
