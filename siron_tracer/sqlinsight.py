"""Statement-level analysis used for column lineage and relationship discovery.

For one SQL text it finds:
* table references and their aliases
* every column reference, resolved to (owner, table, column), with the clause it
  appears in (select / filter / order / group / set)
* equality join predicates between columns of two tables (a.x = b.y, also (+))
* the top-level select list and the source column of each item

It is a tolerant, token based analyser rather than a full SQL parser: it is
meant for the SQL an application like Siron generates (ORM style aliases,
ANSI and old-style joins, subqueries), and it never fails - unknown syntax
simply yields fewer findings.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .sqlutil import _split_ident, _tokens, extract_tables, table_refs

ObjectKey = Tuple[Optional[str], str]
ColumnKey = Tuple[Optional[str], str, str]

_CLAUSES = {
    "SELECT": "select", "FROM": "from", "JOIN": "from", "WHERE": "filter", "ON": "filter",
    "HAVING": "filter", "GROUP": "group", "ORDER": "order", "SET": "set", "INTO": "set",
    "VALUES": "values", "USING": "from", "CONNECT": "filter", "START": "filter",
    "UPDATE": "from", "MERGE": "from", "DELETE": "from", "RETURNING": "other",
}
_NEEDS_NEXT = {"GROUP": "BY", "ORDER": "BY", "CONNECT": "BY", "START": "WITH"}
_NOT_COLUMN = {
    "SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "NULL", "IS", "IN", "AS", "ON", "JOIN",
    "BY", "ROWNUM", "ROWID", "SYSDATE", "SYSTIMESTAMP", "LEVEL", "CASE", "WHEN", "THEN",
    "ELSE", "END", "DISTINCT", "UNIQUE", "EXISTS", "LIKE", "BETWEEN", "ASC", "DESC", "UNION",
    "ALL", "ANY", "SOME", "PRIOR", "TRUE", "FALSE", "NULLS", "FIRST", "LAST", "USER",
}

USAGE_LABELS = {
    "select": "gösterim", "filter": "filtre/join", "order": "sıralama", "group": "gruplama",
    "set": "yazma", "values": "yazma", "other": "diğer", "from": "diğer",
}


@dataclass
class JoinPredicate:
    left: ColumnKey
    right: ColumnKey
    left_alias: str
    right_alias: str


@dataclass
class SelectItem:
    name: str
    expression: str
    source: Optional[ColumnKey] = None
    star: Optional[ObjectKey] = None  # a.* -> table key
    star_all: bool = False            # bare *


@dataclass
class SqlInsight:
    tables: List[ObjectKey] = field(default_factory=list)    # tables/views referenced in FROM etc.
    objects: List[ObjectKey] = field(default_factory=list)   # every catalogue object (incl. packages)
    aliases: Dict[str, ObjectKey] = field(default_factory=dict)
    columns: Dict[ColumnKey, Set[str]] = field(default_factory=dict)
    star_tables: Set[ObjectKey] = field(default_factory=set)
    joins: List[JoinPredicate] = field(default_factory=list)
    select_items: List[SelectItem] = field(default_factory=list)


def _sort_key(col: ColumnKey, alias: str):
    return tuple(x or "" for x in col) + (alias or "",)


def _cte_names(toks) -> Set[str]:
    names = set()
    for i in range(1, len(toks) - 2):
        kind, text = toks[i]
        if (kind == "ident" and "." not in text and toks[i + 1][0] == "ident"
                and toks[i + 1][1].upper() == "AS" and toks[i + 2] == ("punct", "(")
                and (toks[i - 1] == ("punct", ",") or toks[i - 1][1].upper() == "WITH")):
            names.add(_split_ident(text)[0])
    return names


class _Analyser:
    def __init__(self, sql: str, catalog=None, default_owner: Optional[str] = None):
        self.sql = sql
        self.catalog = catalog if catalog else None
        self.default_owner = default_owner
        self.toks = list(_tokens(sql))
        self.insight = SqlInsight()

    # ------------------------------------------------------------------ tables
    def _tables(self):
        ins, cat = self.insight, self.catalog
        ctes = _cte_names(self.toks)
        ambiguous: Set[str] = set()

        def bind(qualifier: str, key: ObjectKey):
            if qualifier in ins.aliases and ins.aliases[qualifier] != key:
                ambiguous.add(qualifier)
            else:
                ins.aliases[qualifier] = key

        for owner, name, alias in table_refs(self.toks):
            if not owner and name in ctes:
                continue
            key = cat.resolve(owner, name, self.default_owner) if cat else None
            key = key or (owner or (None if cat else self.default_owner), name)
            if key not in ins.tables:
                ins.tables.append(key)
            if alias:
                bind(alias, key)
            bind(name, key)
            if owner:
                bind("%s.%s" % (owner, name), key)
        for q in ambiguous:
            ins.aliases.pop(q, None)

        ins.objects = list(ins.tables)
        if cat:
            for key in extract_tables(self.sql, cat.object_keys(), self.default_owner):
                if key not in ins.objects:
                    ins.objects.append(key)

    # ------------------------------------------------------------------ columns
    def resolve(self, text: str) -> Optional[Tuple[ColumnKey, str]]:
        ins, cat = self.insight, self.catalog
        parts = _split_ident(text)
        if len(parts) >= 2:
            qualifier, col = ".".join(parts[:-1]), parts[-1]
            key = ins.aliases.get(qualifier)
            if key is None and len(parts) == 3:
                key = ins.aliases.get(parts[1])
            if key is None:
                return None
            if cat and cat.has_columns(key) and not cat.column(key, col):
                return None
            return (key[0], key[1], col), qualifier
        col = parts[0]
        if not cat or col in _NOT_COLUMN or col in ins.aliases:
            return None
        candidates = [k for k in ins.tables if cat.column(k, col)]
        if len(candidates) == 1:
            key = candidates[0]
            return (key[0], key[1], col), key[1]
        return None

    def _columns(self):
        ins, toks = self.insight, self.toks
        clause = "other"
        for i, (kind, text) in enumerate(toks):
            nxt = toks[i + 1] if i + 1 < len(toks) else ("", "")
            prev = toks[i - 1] if i else ("", "")
            if kind == "ident":
                word = text.upper()
                if word in _CLAUSES and "." not in word:
                    need = _NEEDS_NEXT.get(word)
                    if need is None or nxt[1].upper() == need:
                        clause = _CLAUSES[word]
                        continue
                if prev == ("other", ":") or prev[1].upper() == "AS":
                    continue  # bind variable or select alias
                if nxt == ("punct", "(") and not (i + 2 < len(toks) and toks[i + 2] == ("other", "+")):
                    continue  # function call
                if clause == "from" and "." not in text:
                    continue  # table name or alias
                if nxt == ("punct", ".") and i + 2 < len(toks) and toks[i + 2] == ("other", "*"):
                    key = ins.aliases.get(".".join(_split_ident(text)))
                    if key:
                        ins.star_tables.add(key)
                    continue
                resolved = self.resolve(text)
                if resolved:
                    ins.columns.setdefault(resolved[0], set()).add(clause)
            elif (kind, text) == ("other", "*") and clause == "select" and (
                    prev == ("punct", ",") or prev[1].upper() in ("SELECT", "DISTINCT", "UNIQUE", "ALL")):
                ins.star_tables.update(k for k in ins.tables)

    # ------------------------------------------------------------------ joins
    def _operand(self, idx: int, left: bool) -> Optional[Tuple[ColumnKey, str]]:
        toks = self.toks
        if left:
            if idx >= 2 and toks[idx] == ("punct", ")") and toks[idx - 1] == ("other", "+"):
                idx -= 3
            if idx < 0 or toks[idx][0] != "ident" or (idx and toks[idx - 1] == ("other", ":")):
                return None
        else:
            if idx >= len(toks) or toks[idx][0] != "ident":
                return None
            if idx + 1 < len(toks) and toks[idx + 1] == ("punct", "(") and not (
                    idx + 2 < len(toks) and toks[idx + 2] == ("other", "+")):
                return None
        return self.resolve(toks[idx][1])

    def _joins(self):
        ins, toks = self.insight, self.toks
        seen = set()
        clause = "other"
        for i, (kind, text) in enumerate(toks):
            if kind == "ident" and text.upper() in _CLAUSES:
                clause = _CLAUSES[text.upper()]
            if (kind, text) != ("other", "=") or clause == "set" or i == 0:
                continue
            if toks[i - 1] in (("other", "<"), ("other", ">"), ("other", "!"), ("other", ":")):
                continue
            left, right = self._operand(i - 1, True), self._operand(i + 1, False)
            if not left or not right:
                continue
            (lc, la), (rc, ra) = left, right
            if lc[:2] == rc[:2] and la == ra:
                continue
            if _sort_key(rc, ra) < _sort_key(lc, la):
                lc, la, rc, ra = rc, ra, lc, la
            if (lc, la, rc, ra) not in seen:
                seen.add((lc, la, rc, ra))
                ins.joins.append(JoinPredicate(lc, rc, la, ra))

    # ------------------------------------------------------------------ select list
    def _select_list(self):
        toks, ins = self.toks, self.insight
        depth, start = 0, None
        for i, (kind, text) in enumerate(toks):
            if (kind, text) == ("punct", "("):
                depth += 1
            elif (kind, text) == ("punct", ")"):
                depth -= 1
            elif depth == 0 and kind == "ident" and text.upper() == "SELECT":
                start = i + 1
                break
        if start is None:
            return
        items, current, depth = [], [], 0
        for kind, text in toks[start:]:
            if (kind, text) == ("punct", "("):
                depth += 1
            elif (kind, text) == ("punct", ")"):
                depth -= 1
            if depth == 0 and kind == "ident" and text.upper() in ("FROM", "INTO"):
                break
            if depth == 0 and (kind, text) == ("punct", ","):
                items.append(current)
                current = []
                continue
            current.append((kind, text))
        if current:
            items.append(current)
        if items and items[0] and items[0][0][1].upper() in ("DISTINCT", "UNIQUE", "ALL"):
            items[0] = items[0][1:]

        for item in items:
            if not item:
                continue
            alias = None
            if len(item) >= 2 and item[-1][0] == "ident" and "." not in item[-1][1]:
                before = item[-2]
                if before[0] == "ident" or before == ("punct", ")"):
                    alias = _split_ident(item[-1][1])[0]
                    item = item[:-2] if before[1].upper() == "AS" else item[:-1]
            expression = " ".join(t for _, t in item).replace(" . ", ".").replace("( ", "(").replace(" )", ")")
            si = SelectItem(name=alias or "", expression=expression)
            if [t for _, t in item] == ["*"]:
                si.star_all = True
            elif len(item) == 3 and item[1] == ("punct", ".") and item[2] == ("other", "*"):
                si.star = ins.aliases.get(".".join(_split_ident(item[0][1])))
            elif len(item) == 1 and item[0][0] == "ident":
                resolved = self.resolve(item[0][1])
                if resolved:
                    si.source = resolved[0]
                si.name = si.name or _split_ident(item[0][1])[-1]
            si.name = si.name or expression.upper()
            ins.select_items.append(si)

    def run(self) -> SqlInsight:
        self._tables()
        self._columns()
        self._joins()
        self._select_list()
        return self.insight


def analyse_sql(sql: str, catalog=None, default_owner: Optional[str] = None) -> SqlInsight:
    try:
        return _Analyser(sql, catalog, default_owner).run()
    except Exception:  # never let an odd statement break a page
        return SqlInsight()


def map_result_columns(insight: SqlInsight, result_columns: List[str], catalog=None) -> List[Optional[ColumnKey]]:
    """Source column for each column of a query result (None when it is an expression)."""
    expanded: List[Optional[ColumnKey]] = []
    exact = True
    for item in insight.select_items:
        if item.star_all or item.star:
            keys = insight.tables if item.star_all else [item.star]
            for key in keys:
                cols = catalog.columns(key) if catalog and key else []
                if not cols:
                    exact = False
                expanded.extend((key[0], key[1], c.name) for c in cols)
        else:
            expanded.append(item.source)
    if exact and len(expanded) == len(result_columns):
        return expanded
    # fall back to matching by name
    out: List[Optional[ColumnKey]] = []
    for name in result_columns:
        hits = {c for c in expanded if c and c[2] == name.upper()}
        if not hits and catalog:
            hits = {(k[0], k[1], name.upper()) for k in insight.tables if catalog.column(k, name.upper())}
        out.append(hits.pop() if len(hits) == 1 else None)
    return out
