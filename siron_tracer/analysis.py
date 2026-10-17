"""Turns raw audit records into executions, statements (per SQL_ID) and a
table summary."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .sqlutil import ObjectKey, extract_tables

# Audit rows that never carry user SQL worth analysing
_IGNORED_ACTIONS = {"LOGON", "LOGOFF", "LOGOFF BY CLEANUP", "SET ROLE", "COMMIT", "ROLLBACK"}


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


def group_executions(records: Iterable[dict]) -> List[Execution]:
    """Collapse the per-object audit rows of one statement execution.

    Traditional auditing (and unified object auditing) writes one row per
    object accessed; those share session id + statement id.
    """
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


def group_statements(executions: Iterable[Execution], objects: Optional[Dict[ObjectKey, str]] = None,
                     default_owner: Optional[str] = None,
                     exclude_sql_ids: Optional[Set[str]] = None) -> List[Statement]:
    known = set(objects) if objects else None
    statements: "OrderedDict[str, Statement]" = OrderedDict()
    for ex in executions:
        if exclude_sql_ids and ex.sql_id in exclude_sql_ids:
            continue
        st = statements.get(ex.sql_id)
        if st is None:
            st = statements[ex.sql_id] = Statement(ex.sql_id, ex.sql_text, ex.action)
            st.tables = extract_tables(ex.sql_text, known, default_owner)
        st.executions.append(ex)
        for obj in ex.audit_objects:
            if obj not in st.tables and not (obj[0] is None and any(t[1] == obj[1] for t in st.tables)):
                st.tables.append(obj)
    return list(statements.values())


@dataclass
class TableUsage:
    owner: Optional[str]
    name: str
    obj_type: Optional[str]
    statements: List[Statement] = field(default_factory=list)
    actions: Set[str] = field(default_factory=set)

    @property
    def label(self) -> str:
        return "%s.%s" % (self.owner, self.name) if self.owner else self.name

    @property
    def exec_count(self) -> int:
        return sum(s.exec_count for s in self.statements)


def table_summary(statements: Iterable[Statement],
                  objects: Optional[Dict[ObjectKey, str]] = None) -> List[TableUsage]:
    objects = objects or {}
    usage: Dict[ObjectKey, TableUsage] = {}
    for st in statements:
        for owner, name in st.tables:
            u = usage.get((owner, name))
            if u is None:
                u = usage[(owner, name)] = TableUsage(owner, name, objects.get((owner, name)))
            u.statements.append(st)
            if st.action:
                u.actions.add(st.action)
    return sorted(usage.values(), key=lambda u: (-len(u.statements), u.label))


def analyse(records: List[dict], objects=None, default_owner=None, exclude_sql_ids=None):
    executions = group_executions(records)
    statements = group_statements(executions, objects, default_owner, exclude_sql_ids)
    return statements, table_summary(statements, objects)
