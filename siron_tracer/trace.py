"""Record trace: every table that holds data about one known record.

Start from a value you know (a customer number from a Siron screen), find the
key-like columns that contain it, then follow relations outwards: the matched
rows' key values (customer id, account numbers ...) are looked up in related
tables, hop by hop. The result answers "where else does this customer's data
live?" - including tables no screen capture ever touched.

Only key-like columns are searched (primary/unique/foreign keys, leading index
columns, names that look like identifiers), so lookups stay on indexes; big
tables without an index on the column are skipped unless asked for.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from .catalog import label
from .relations import Relation, qi, qualified

ObjectKey = Tuple[Optional[str], str]
Run = Callable[[str, dict, int], Tuple[List[str], List[tuple]]]

KEY_NAME = re.compile(r"(^ID$|_ID$|[A-Z]ID$|NR$|_NO$|NO$|NUM$|NUMBER$|_KEY$|KEY$|KUERZEL$|^IBAN$|^TCKN$|^VKN$|^CIF|"
                      r"^KUND|^CUST|^KONTO|^ACC)")
COUNT_CAP = 10000
SAMPLE_ROWS = 10
VALUES_PER_HOP = 200
TEXT = {"char"}


@dataclass
class Hop:
    from_table: ObjectKey
    from_col: str
    to_table: ObjectKey
    to_col: str
    how: str                       # FK / SQL / Tahmin

    def text(self) -> str:
        return "%s.%s → %s.%s" % (self.from_table[1], self.from_col, self.to_table[1], self.to_col)


@dataclass
class Hit:
    key: ObjectKey
    column: str                    # column matched in this table
    depth: int
    where: str                     # SQL condition on this table
    binds: Dict[str, str]
    count: int
    capped: bool
    path: List[Hop] = field(default_factory=list)
    columns: List[str] = field(default_factory=list)
    rows: List[list] = field(default_factory=list)
    seed_column: str = ""          # column of the start table that held the traced value

    def as_dict(self) -> dict:
        return {"table": label(self.key), "owner": self.key[0], "name": self.key[1], "column": self.column,
                "depth": self.depth, "count": self.count, "capped": self.capped,
                "path": [{"from": label(h.from_table), "from_col": h.from_col, "to": label(h.to_table),
                          "to_col": h.to_col, "how": h.how, "text": h.text()} for h in self.path],
                "columns": self.columns, "rows": self.rows, "seed_column": self.seed_column,
                "seed_table": label(self.path[0].from_table) if self.path else label(self.key)}


def _compatible(col, value: str) -> bool:
    if col.family == "number":
        return bool(re.fullmatch(r"-?\d+(\.\d+)?", value))
    if col.family in TEXT:
        return col.length is None or len(value) <= col.length
    return False


def candidate_columns(catalog, value: str, big_rows: int, include_big: bool = False,
                      only: Optional[Sequence[Tuple[ObjectKey, str]]] = None):
    """([(table key, column)], [skipped (label, reason)]) - the columns worth an indexed lookup."""
    out, skipped = [], []
    for key, table in sorted(catalog.tables.items(), key=lambda kv: (kv[0][0] or "", kv[0][1])):
        if table.obj_type != "TABLE":
            continue
        keyish = set(catalog.fk_columns(key)) | {c for _, cols in catalog.keys_of(key) for c in cols}
        indexed = catalog.indexed.get(key, set())
        for col in table.columns:
            if only is not None and (key, col.name) not in only:
                continue
            if not _compatible(col, value):
                continue
            if only is None and not (col.name in keyish or col.name in indexed or KEY_NAME.search(col.name)):
                continue
            if col.name not in indexed and not include_big and (table.num_rows or 0) > big_rows:
                skipped.append((label(key) + "." + col.name, "büyük tablo, kolon indeksli değil"))
                continue
            out.append((key, col.name))
    return out, skipped


def _count(run: Run, key: ObjectKey, where: str, binds: dict) -> Tuple[int, bool]:
    sql = "SELECT COUNT(*) FROM (SELECT 1 FROM %s WHERE %s AND ROWNUM <= %d)" % (qualified(key), where, COUNT_CAP + 1)
    n = run(sql, binds, 1)[1][0][0]
    return min(n, COUNT_CAP), n > COUNT_CAP


def _sample(run: Run, key: ObjectKey, where: str, binds: dict):
    cols, rows = run("SELECT * FROM %s WHERE %s AND ROWNUM <= %d" % (qualified(key), where, SAMPLE_ROWS),
                     binds, SAMPLE_ROWS)
    return list(cols), [[None if v is None else str(v)[:200] for v in r] for r in rows]


def _values(run: Run, key: ObjectKey, col: str, where: str, binds: dict) -> List[str]:
    sql = "SELECT DISTINCT %s FROM %s WHERE %s AND %s IS NOT NULL AND ROWNUM <= %d" % (
        qi(col), qualified(key), where, qi(col), VALUES_PER_HOP)
    return [str(r[0]) for r in run(sql, binds, VALUES_PER_HOP)[1]]


def _in(col: str, values: List[str]) -> Tuple[str, dict]:
    binds = {"v%d" % i: v for i, v in enumerate(values)}
    return "%s IN (%s)" % (qi(col), ", ".join(":" + k for k in binds)), binds


def _neighbours(relations: List[Relation], key: ObjectKey):
    """(own column, other table, other column, how) for single-column relations touching `key`."""
    how = {"constraint": "FK", "sql": "SQL", "name": "Tahmin"}
    for r in relations:
        if len(r.child_cols) != 1 or r.child == r.parent:
            continue
        src = next((how[s] for s in ("constraint", "sql", "name") if s in r.sources), "Tahmin")
        if r.child == key:
            yield r.child_cols[0], r.parent, r.parent_cols[0], src
        if r.parent == key:
            yield r.parent_cols[0], r.child, r.child_cols[0], src


def trace(run: Run, catalog, relations: List[Relation], value: str, *, depth: int = 2, big_rows: int = 2000000,
          include_big: bool = False, only: Optional[Sequence[Tuple[ObjectKey, str]]] = None,
          progress: Callable[[float, str], None] = lambda p, m: None) -> dict:
    value = (value or "").strip()
    errors: List[Tuple[str, str]] = []
    cands, skipped = candidate_columns(catalog, value, big_rows, include_big, only)
    hits: Dict[ObjectKey, Hit] = {}
    # depth 0: where does the value itself appear?
    for n, (key, col) in enumerate(cands):
        progress(60.0 * n / max(len(cands), 1), "%s.%s aranıyor" % (key[1], col))
        where, binds = "%s = :v" % qi(col), {"v": value}
        try:
            count, capped = _count(run, key, where, binds)
        except Exception as exc:
            errors.append((label(key) + "." + col, str(exc)[:200]))
            continue
        if count and (key not in hits or hits[key].count < count):
            hits[key] = Hit(key, col, 0, where, binds, count, capped, seed_column=col)
    # following hops: carry the matched rows' key values along relations
    frontier = list(hits.values())
    for level in range(1, depth + 1):
        nxt: List[Hit] = []
        for n, hit in enumerate(frontier):
            progress(60 + 35.0 * (level - 1 + n / max(len(frontier), 1)) / depth, "%s ilişkileri izleniyor" % hit.key[1])
            for own, other, other_col, how in _neighbours(relations, hit.key):
                if other in hits or other not in catalog.tables:
                    continue
                try:
                    values = _values(run, hit.key, own, hit.where, hit.binds)
                    if not values:
                        continue
                    where, binds = _in(other_col, values)
                    count, capped = _count(run, other, where, binds)
                except Exception as exc:
                    errors.append((label(other) + "." + other_col, str(exc)[:200]))
                    continue
                if count:
                    hits[other] = Hit(other, other_col, level, where, binds, count, capped,
                                      hit.path + [Hop(hit.key, own, other, other_col, how)], seed_column=hit.seed_column)
                    nxt.append(hits[other])
        frontier = nxt
        if not frontier:
            break
    for hit in hits.values():
        try:
            hit.columns, hit.rows = _sample(run, hit.key, hit.where, hit.binds)
        except Exception as exc:
            errors.append((label(hit.key), str(exc)[:200]))
    progress(100, "tamamlandı")
    ordered = sorted(hits.values(), key=lambda h: (h.depth, -h.count, h.key[1]))
    return {"value": value, "depth": depth, "searched": len(cands), "hits": [h.as_dict() for h in ordered],
            "skipped": skipped[:200], "skipped_count": len(skipped), "errors": errors[:100]}


def path_sql(hit: dict, seed_column: Optional[str] = None, bind: str = "deger") -> str:
    """SELECT that walks the hit's path from the seed table, filtered by the traced value."""
    path = hit.get("path") or []
    if not path:
        return "SELECT t0.*\n  FROM %s t0\n WHERE t0.%s = :%s" % (_q(hit["owner"], hit["name"]), qi(hit["column"]), bind)
    first = path[0]
    owner, name = _split(first["from"])
    seed_col = seed_column or hit.get("seed_column")
    lines = ["SELECT t%d.*" % len(path), "  FROM %s t0" % _q(owner, name)]
    for i, hop in enumerate(path, start=1):
        o, nme = _split(hop["to"])
        lines.append("  JOIN %s t%d ON t%d.%s = t%d.%s" % (_q(o, nme), i, i, qi(hop["to_col"]), i - 1, qi(hop["from_col"])))
    if seed_col:
        lines.append(" WHERE t0.%s = :%s" % (qi(seed_col), bind))
    return "\n".join(lines)


def _split(text: str) -> Tuple[Optional[str], str]:
    owner, _, name = text.rpartition(".")
    return owner or None, name


def _q(owner, name) -> str:
    return qualified((owner or None, name))
