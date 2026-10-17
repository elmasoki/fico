"""Capture timeline: audit records in time order, split into user "steps".

A Siron screen action (open, search, click a tab) fires a burst of SQL; a pause
separates it from the next one. Splitting the records wherever the gap between
two statements exceeds a threshold lines each burst up with one user action.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .sqlutil import parse_audit_binds
from .store import parse_ts


@dataclass
class Item:
    record_id: int
    ts: str
    offset: float                 # seconds since the first record
    sql_id: str
    action: Optional[str]
    sql_text: str
    binds: List[Optional[str]]
    tables: List[Tuple[Optional[str], str]]
    noise: bool = False
    repeat: int = 1               # consecutive executions of the same SQL folded into this item


@dataclass
class Step:
    index: int
    start: float
    end: float
    gap_before: Optional[float]
    items: List[Item] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def sql_count(self) -> int:
        return sum(i.repeat for i in self.items)

    @property
    def tables(self) -> List[Tuple[Optional[str], str]]:
        seen: Dict[Tuple, None] = {}
        for i in self.items:
            if not i.noise:
                for t in i.tables:
                    seen.setdefault(t, None)
        return list(seen)


def _ts(value: str) -> datetime:
    try:
        return parse_ts(value)
    except ValueError:
        return datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S")


def build_steps(records: Iterable[dict], tables_by_sql: Dict[str, list], gap: float = 2.0,
                noise_ids: Optional[Set[str]] = None, hide_noise: bool = False) -> List[Step]:
    noise_ids = noise_ids or set()
    rows = sorted((r for r in records if r.get("sql_id") and r.get("ts")), key=lambda r: (r["ts"], r["id"]))
    steps: List[Step] = []
    first = prev = None
    for r in rows:
        noise = r["sql_id"] in noise_ids
        if noise and hide_noise:
            continue
        t = _ts(r["ts"])
        first = first or t
        offset = (t - first).total_seconds()
        since = None if prev is None else (t - prev).total_seconds()
        prev = t
        if not steps or (since is not None and since > gap):
            steps.append(Step(len(steps) + 1, offset, offset, since))
        step = steps[-1]
        step.end = offset
        last = step.items[-1] if step.items else None
        binds = [b.value for b in parse_audit_binds(r.get("sql_binds"))]
        if last and last.sql_id == r["sql_id"] and last.binds == binds:
            last.repeat += 1
            continue
        step.items.append(Item(r["id"], r["ts"], offset, r["sql_id"], r.get("action"), r.get("sql_text") or "",
                               binds, tables_by_sql.get(r["sql_id"], []), noise))
    return steps
