"""Coverage: how far the discovery has come and what is still open.

* screens  - inventory items that have (or lack) a capture
* tables   - schema tables touched by any capture vs never seen
* columns  - used columns with / without a mapping decision
* relations - inferred relations verified with data or not
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .catalog import ann

SCREEN_STATUSES = {"todo": "Yapılacak", "captured": "Yakalandı", "mapped": "Eşlendi",
                   "done": "Tamamlandı", "skip": "Kapsam dışı"}


@dataclass
class Coverage:
    screens_total: int = 0
    screens_captured: int = 0
    screens_by_status: Dict[str, int] = field(default_factory=dict)
    modules: List[dict] = field(default_factory=list)
    tables_total: int = 0
    tables_touched: int = 0
    tables_indirect: int = 0
    tables_batch_only: List[tuple] = field(default_factory=list)
    tables_by_status: Dict[str, int] = field(default_factory=dict)
    untouched: List[dict] = field(default_factory=list)
    columns_used: int = 0
    columns_decided: int = 0
    columns_targeted: int = 0
    columns_by_status: Dict[str, int] = field(default_factory=dict)
    undecided_columns: List[tuple] = field(default_factory=list)
    relations_inferred: int = 0
    relations_verified: int = 0
    unverified: list = field(default_factory=list)

    @staticmethod
    def pct(part: int, whole: int) -> Optional[float]:
        return round(100.0 * part / whole, 1) if whole else None

    @property
    def screens_pct(self):
        return self.pct(self.screens_captured, self.screens_total - self.screens_by_status.get("skip", 0))

    @property
    def tables_pct(self):
        return self.pct(self.tables_touched, self.tables_total)

    @property
    def columns_pct(self):
        return self.pct(self.columns_decided, self.columns_used)

    @property
    def relations_pct(self):
        return self.pct(self.relations_verified, self.relations_inferred)

    @property
    def tables_decided(self) -> int:
        return sum(v for k, v in self.tables_by_status.items() if k)


def screen_status(screen: dict, captures: List[dict]) -> str:
    """Stored status wins unless it is still 'todo' and a capture exists."""
    status = screen.get("status") or "todo"
    if status == "todo" and any(c.get("screen_id") == screen["id"] and c["status"] == "done" for c in captures):
        return "captured"
    return status


def compute(pa, catalog, annotations: dict, screens: List[dict], captures: List[dict],
            relations: list) -> Coverage:
    cov = Coverage()
    # screens -----------------------------------------------------------------
    by_module: Dict[str, dict] = {}
    for s in screens:
        st = screen_status(s, captures)
        cov.screens_by_status[st] = cov.screens_by_status.get(st, 0) + 1
        m = by_module.setdefault(s.get("module") or "—", {"module": s.get("module") or "—", "total": 0, "captured": 0})
        m["total"] += 1
        if st in ("captured", "mapped", "done"):
            m["captured"] += 1
            cov.screens_captured += 1
    cov.screens_total = len(screens)
    cov.modules = sorted(by_module.values(), key=lambda m: m["module"])

    # tables ------------------------------------------------------------------
    schema_tables = {k: t for k, t in (catalog.tables.items() if catalog else []) if t.obj_type == "TABLE"}
    cov.tables_total = len(schema_tables)
    touched = set(pa.tables)
    cov.tables_touched = len([k for k in touched if k in schema_tables]) if schema_tables else len(touched)
    cov.tables_indirect = len([k for k, e in pa.tables.items() if e.get("indirect")])
    cov.tables_batch_only = sorted(k for k, e in pa.tables.items() if e.get("kinds") == {"batch"})
    for key in (schema_tables or touched):
        status = ann(annotations, key).get("status") or ""
        if key in touched or status:
            cov.tables_by_status[status] = cov.tables_by_status.get(status, 0) + 1
    for key, t in schema_tables.items():
        if key not in touched:
            cov.untouched.append({"key": key, "table": t, "ann": ann(annotations, key)})
    cov.untouched.sort(key=lambda r: (-(r["table"].num_rows or 0), r["key"][1]))

    # columns -----------------------------------------------------------------
    for col in pa.columns:
        cov.columns_used += 1
        a = ann(annotations, col[:2], col[2])
        table_status = ann(annotations, col[:2]).get("status")
        status = a.get("status") or ("ignore" if table_status == "ignore" else "")
        cov.columns_by_status[status] = cov.columns_by_status.get(status, 0) + 1
        if status:
            cov.columns_decided += 1
        else:
            cov.undecided_columns.append(col)
        if a.get("target"):
            cov.columns_targeted += 1

    # relations ---------------------------------------------------------------
    for r in relations:
        if "constraint" in r.sources:
            continue
        cov.relations_inferred += 1
        if r.check is not None:
            cov.relations_verified += 1
        else:
            cov.unverified.append(r)
    return cov
