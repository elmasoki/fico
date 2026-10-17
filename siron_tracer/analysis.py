"""Turns raw audit records into executions, statements (per SQL_ID), table and
column usage - per capture (screen) and for the whole project."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

from .sqlinsight import ColumnKey, SqlInsight, analyse_sql

ObjectKey = Tuple[Optional[str], str]

# Audit rows that never carry user SQL worth analysing
_IGNORED_ACTIONS = {"LOGON", "LOGOFF", "LOGOFF BY CLEANUP", "SET ROLE", "COMMIT", "ROLLBACK"}

_INSIGHTS: Dict[tuple, SqlInsight] = {}


def insight_for(sql_id: str, sql_text: str, catalog=None, default_owner=None) -> SqlInsight:
    key = (sql_id, catalog.version if catalog else "", default_owner)
    hit = _INSIGHTS.get(key)
    if hit is None:
        if len(_INSIGHTS) > 20000:
            _INSIGHTS.clear()
        hit = _INSIGHTS[key] = analyse_sql(sql_text, catalog, default_owner)
    return hit


@dataclass
class Execution:
    record_id: int
    ts: str
    sql_id: str
    sql_text: str
    sql_binds: Optional[str]
    action: Optional[str]
    session_id: Optional[str]
    return_code: Optional[str]
    audit_objects: List[ObjectKey] = field(default_factory=list)


@dataclass
class Statement:
    sql_id: str
    sql_text: str
    action: Optional[str]
    executions: List[Execution] = field(default_factory=list)
    insight: SqlInsight = field(default_factory=SqlInsight)
    tables: List[ObjectKey] = field(default_factory=list)

    @property
    def exec_count(self) -> int:
        return len(self.executions)

    @property
    def first_ts(self) -> str:
        return self.executions[0].ts

    @property
    def bind_sets(self) -> List[Execution]:
        """One execution per distinct bind value set."""
        seen, out = set(), []
        for e in self.executions:
            if e.sql_binds not in seen:
                seen.add(e.sql_binds)
                out.append(e)
        return out

    @property
    def failed(self) -> int:
        return sum(1 for e in self.executions if e.return_code not in (None, "0"))

    @property
    def is_select(self) -> bool:
        return (self.action or "").upper() == "SELECT" or \
            self.sql_text.lstrip().upper().startswith(("SELECT", "WITH"))


@dataclass
class TableUsage:
    owner: Optional[str]
    name: str
    obj_type: Optional[str]
    statements: List[Statement] = field(default_factory=list)
    actions: Set[str] = field(default_factory=set)
    columns: Set[str] = field(default_factory=set)

    @property
    def key(self) -> ObjectKey:
        return (self.owner, self.name)

    @property
    def label(self) -> str:
        return "%s.%s" % (self.owner, self.name) if self.owner else self.name

    @property
    def exec_count(self) -> int:
        return sum(s.exec_count for s in self.statements)


@dataclass
class ColumnUsage:
    kinds: Set[str] = field(default_factory=set)
    sql_ids: Set[str] = field(default_factory=set)


@dataclass
class CaptureAnalysis:
    statements: List[Statement]
    tables: List[TableUsage]
    columns: Dict[ColumnKey, ColumnUsage]

    @property
    def insights(self) -> List[Tuple[str, SqlInsight]]:
        return [(s.sql_id, s.insight) for s in self.statements]

    @property
    def table_keys(self) -> List[ObjectKey]:
        return [t.key for t in self.tables]

    def statement(self, sql_id: str) -> Optional[Statement]:
        return next((s for s in self.statements if s.sql_id == sql_id), None)


def group_executions(records: Iterable[dict]) -> List[Execution]:
    """Collapse the per-object audit rows of one statement execution."""
    executions: "OrderedDict[tuple, Execution]" = OrderedDict()
    for r in records:
        if not r.get("sql_text") or (r.get("action") or "").upper() in _IGNORED_ACTIONS:
            continue
        if r.get("statement_id") and r.get("session_id"):
            key = (r["session_id"], r["statement_id"], r["sql_id"], r.get("sql_binds"))
        else:
            key = ("rec", r["id"])
        ex = executions.get(key)
        if ex is None:
            ex = executions[key] = Execution(
                record_id=r["id"], ts=r["ts"], sql_id=r["sql_id"], sql_text=r["sql_text"],
                sql_binds=r.get("sql_binds"), action=r.get("action"),
                session_id=r.get("session_id"), return_code=r.get("return_code"))
        if r.get("obj_name"):
            obj = ((r.get("obj_schema") or None), r["obj_name"])
            if obj not in ex.audit_objects:
                ex.audit_objects.append(obj)
    return list(executions.values())


def analyse(records: List[dict], catalog=None, default_owner: Optional[str] = None,
            exclude_sql_ids: Optional[Set[str]] = None) -> CaptureAnalysis:
    objects = catalog.objects if catalog else {}
    statements: "OrderedDict[str, Statement]" = OrderedDict()
    for ex in group_executions(records):
        if exclude_sql_ids and ex.sql_id in exclude_sql_ids:
            continue
        st = statements.get(ex.sql_id)
        if st is None:
            insight = insight_for(ex.sql_id, ex.sql_text, catalog, default_owner)
            st = statements[ex.sql_id] = Statement(ex.sql_id, ex.sql_text, ex.action, insight=insight,
                                                   tables=list(insight.objects))
        st.executions.append(ex)
        for obj in ex.audit_objects:
            if obj not in st.tables and not any(t[1] == obj[1] and obj[0] in (None, t[0]) for t in st.tables):
                st.tables.append(obj)

    usage: Dict[ObjectKey, TableUsage] = {}
    columns: Dict[ColumnKey, ColumnUsage] = {}
    for st in statements.values():
        for key in st.tables:
            u = usage.get(key)
            if u is None:
                u = usage[key] = TableUsage(key[0], key[1], objects.get(key))
            u.statements.append(st)
            if st.action:
                u.actions.add(st.action)
        for col, kinds in st.insight.columns.items():
            cu = columns.setdefault(col, ColumnUsage())
            cu.kinds |= kinds
            cu.sql_ids.add(st.sql_id)
            if col[:2] in usage:
                usage[col[:2]].columns.add(col[2])
    tables = sorted(usage.values(), key=lambda u: (-len(u.statements), u.label))
    return CaptureAnalysis(list(statements.values()), tables, columns)


# --------------------------------------------------------------------------- project

@dataclass
class ProjectAnalysis:
    captures: List[Tuple[dict, CaptureAnalysis]]
    tables: Dict[ObjectKey, dict]     # key -> {"type", "screens": [(capture, TableUsage)], "actions"}
    columns: Dict[ColumnKey, dict]    # key -> {"kinds", "screens": {capture_id: capture}}

    @property
    def insights(self):
        seen, out = set(), []
        for _, ca in self.captures:
            for sql_id, ins in ca.insights:
                if sql_id not in seen:
                    seen.add(sql_id)
                    out.append((sql_id, ins))
        return out

    @property
    def table_keys(self) -> List[ObjectKey]:
        return list(self.tables)


def analyse_project(captures: Iterable[dict], load_records: Callable[[int], List[dict]], catalog=None,
                    default_owner=None, noise: Optional[Set[str]] = None) -> ProjectAnalysis:
    result = ProjectAnalysis([], {}, {})
    for c in captures:
        if c["status"] != "done" or c["is_noise"]:
            continue
        ca = analyse(load_records(c["id"]), catalog, default_owner, noise)
        result.captures.append((c, ca))
        for t in ca.tables:
            entry = result.tables.setdefault(t.key, {"type": t.obj_type, "screens": [], "actions": set()})
            entry["screens"].append((c, t))
            entry["actions"] |= t.actions
        for col, cu in ca.columns.items():
            entry = result.columns.setdefault(col, {"kinds": set(), "screens": {}})
            entry["kinds"] |= cu.kinds
            entry["screens"][c["id"]] = c
    result.tables = dict(sorted(result.tables.items(),
                                key=lambda kv: (-len(kv[1]["screens"]), kv[0][1])))
    return result
