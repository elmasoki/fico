"""Column profiling: fill rate, distinct count, min/max, length and the most
frequent values - the facts a migration mapping discussion needs.

Statistics are computed in Oracle with one aggregate query per batch of
columns; large tables are profiled on a SAMPLE."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .catalog import Column
from .relations import qi, qualified

BATCH = 90          # columns per aggregate query (each uses up to 6 select items)
# large tables are profiled on a SAMPLE, so exact COUNT(DISTINCT) stays affordable
TOP_VALUES = 8      # most frequent values kept per low-cardinality column
TOP_MAX_DISTINCT = 200
TOP_MAX_COLUMNS = 60


def sample_clause(num_rows: Optional[int], sample_rows: int) -> Tuple[str, Optional[float]]:
    if not num_rows or num_rows <= sample_rows:
        return "", None
    pct = max(0.0001, min(99.0, 100.0 * sample_rows / num_rows))
    return " SAMPLE (%s)" % ("%.4f" % pct).rstrip("0").rstrip("."), pct


def aggregate_sql(key, columns: List[Column], sample: str) -> str:
    items = ["COUNT(*)"]
    for c in columns:
        col = qi(c.name)
        if c.family == "lob":
            items += ["SUM(CASE WHEN %s IS NULL THEN 0 ELSE 1 END)" % col, "NULL", "NULL", "NULL",
                      "AVG(DBMS_LOB.GETLENGTH(%s))" % col, "MAX(DBMS_LOB.GETLENGTH(%s))" % col]
        elif c.family in ("char", "number", "date"):
            length = "LENGTH(%s)" % (col if c.family == "char" else "TO_CHAR(%s)" % col)
            items += ["COUNT(%s)" % col, "COUNT(DISTINCT %s)" % col, "MIN(%s)" % col,
                      "MAX(%s)" % col, "AVG(%s)" % length, "MAX(%s)" % length]
        else:
            items += ["COUNT(%s)" % col, "NULL", "NULL", "NULL", "NULL", "NULL"]
    return "SELECT %s FROM %s%s" % (", ".join(items), qualified(key), sample)


def top_values_sql(key, column: Column, sample: str, limit: int = TOP_VALUES) -> str:
    col = qi(column.name)
    return ("SELECT %s, COUNT(*) FROM %s%s WHERE %s IS NOT NULL GROUP BY %s "
            "ORDER BY 2 DESC FETCH FIRST %d ROWS ONLY" % (col, qualified(key), sample, col, col, limit))


def parse_aggregate(columns: List[Column], row: tuple) -> Dict[str, dict]:
    total = int(row[0] or 0)
    out = {}
    for i, c in enumerate(columns):
        non_null, distinct, mn, mx, avg_len, max_len = row[1 + i * 6: 7 + i * 6]
        non_null = int(non_null or 0)
        out[c.name] = {
            "rows": total, "non_null": non_null, "nulls": total - non_null,
            "fill_pct": round(100.0 * non_null / total, 1) if total else None,
            "distinct": int(distinct) if distinct is not None else None,
            "min": None if mn is None else str(mn), "max": None if mx is None else str(mx),
            "avg_len": round(float(avg_len), 1) if avg_len is not None else None,
            "max_len": int(max_len) if max_len is not None else None,
            "top": [],
        }
    return out


def profile_table(run, key, table, sample_rows: int = 200000, columns: Optional[List[str]] = None,
                  progress=None) -> Dict[str, dict]:
    """Profile `table` (catalog Table). `run(sql)` executes a SELECT and returns (cols, rows, truncated)."""
    cols = [c for c in table.columns if not columns or c.name in columns]
    sample, pct = sample_clause(table.num_rows, sample_rows)
    result: Dict[str, dict] = {}
    batches = [cols[i:i + BATCH] for i in range(0, len(cols), BATCH)]
    for n, batch in enumerate(batches):
        _, rows, _ = run(aggregate_sql(key, batch, sample))
        result.update(parse_aggregate(batch, rows[0]))
        if progress:
            progress((n + 1) / (len(batches) + 1))
    candidates = [c for c in cols if c.family in ("char", "number", "date")
                  and result[c.name]["distinct"] is not None
                  and 0 < result[c.name]["distinct"] <= TOP_MAX_DISTINCT][:TOP_MAX_COLUMNS]
    for c in candidates:
        _, rows, _ = run(top_values_sql(key, c, sample))
        result[c.name]["top"] = [[None if v is None else str(v), int(n)] for v, n in rows]
    for data in result.values():
        data["sampled"] = pct is not None
        data["sample_pct"] = round(pct, 4) if pct else None
    return result


def quality_flags(p: dict, nullable: bool = True) -> List[str]:
    """Short warnings worth discussing during mapping."""
    flags = []
    if not p or not p.get("rows"):
        return flags
    if p["non_null"] == 0:
        flags.append("hep boş")
    elif p.get("fill_pct") is not None and p["fill_pct"] < 5:
        flags.append("neredeyse boş")
    if p.get("distinct") == 1 and p["non_null"]:
        flags.append("tek değer")
    if p.get("distinct") and p["non_null"] and p["distinct"] >= p["non_null"] * 0.98 and p["non_null"] > 50:
        flags.append("benzersiz")
    return flags
