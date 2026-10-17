"""Capture timeline: audit records in time order, split into user "steps".

A Siron screen action (open, search, click a tab) fires a burst of SQL; a pause
separates it from the next one. Splitting the records wherever the gap between
two statements exceeds a threshold lines each burst up with one user action.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .sessions import source_key
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
    source: str = ""              # sessions.source_key of the record (who ran it)


@dataclass
class Marker:
    id: int
    ts: str
    label: str
    offset: float = 0.0


@dataclass
class Step:
    index: int
    start: float
    end: float
    gap_before: Optional[float]
    items: List[Item] = field(default_factory=list)
    markers: List[Marker] = field(default_factory=list)

    @property
    def label(self) -> str:
        return " · ".join(m.label for m in self.markers)

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
                noise_ids: Optional[Set[str]] = None, hide_noise: bool = False,
                markers: Iterable[dict] = ()) -> List[Step]:
    """Split records into steps at pauses longer than `gap` seconds and at user markers.

    A marker (a note the user dropped while recording) always opens a new step and names it;
    markers after the last record end up in a final step without SQL.
    """
    noise_ids = noise_ids or set()
    rows = [r for r in records if r.get("sql_id") and r.get("ts") and not (hide_noise and r["sql_id"] in noise_ids)]
    rows.sort(key=lambda r: (r["ts"], r["id"]))
    pending = sorted((Marker(m["id"], m["ts"], m["label"]) for m in markers), key=lambda m: (m.ts, m.id))
    steps: List[Step] = []
    first = _ts(rows[0]["ts"]) if rows else None
    prev = None
    for r in rows:
        noise = r["sql_id"] in noise_ids
        t = _ts(r["ts"])
        offset = (t - first).total_seconds()
        since = None if prev is None else (t - prev).total_seconds()
        prev = t
        due = []
        while pending and _ts(pending[0].ts) <= t:
            m = pending.pop(0)
            m.offset = (_ts(m.ts) - first).total_seconds()
            due.append(m)
        if not steps or due or (since is not None and since > gap):
            steps.append(Step(len(steps) + 1, offset, offset, since, markers=due))
        step = steps[-1]
        step.end = offset
        last = step.items[-1] if step.items else None
        binds = [b.value for b in parse_audit_binds(r.get("sql_binds"))]
        source = source_key(r)
        if last and last.sql_id == r["sql_id"] and last.binds == binds and last.source == source:
            last.repeat += 1
            continue
        step.items.append(Item(r["id"], r["ts"], offset, r["sql_id"], r.get("action"), r.get("sql_text") or "",
                               binds, tables_by_sql.get(r["sql_id"], []), noise, source=source))
    if pending:
        for m in pending:
            m.offset = (_ts(m.ts) - first).total_seconds() if first else 0.0
        end = steps[-1].end if steps else 0.0
        steps.append(Step(len(steps) + 1, max(end, pending[0].offset), max(end, pending[0].offset), None,
                          markers=pending))
    return steps
