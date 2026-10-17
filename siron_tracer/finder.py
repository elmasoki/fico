"""'Where does the value I see on the Siron screen live?'

Two strategies:
* scan the results of the statements captured for a screen (fast, precise:
  these are exactly the queries that filled the screen), and map the result
  column back to table.column through the select list
* search the columns of chosen tables directly (one scan per table)
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Iterable, List, Optional, Tuple

from .catalog import Column
from .relations import qi, qualified

MODES = {"exact": "Birebir", "ci": "Büyük/küçük harf duyarsız", "contains": "İçeriyor"}


def normalise(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def cell_matches(cell, needle: str, mode: str) -> bool:
    text = normalise(cell)
    if not text:
        return False
    if mode == "exact":
        if text == needle:
            return True
        number = as_number(needle)
        return number is not None and as_number(text) == number
    if mode == "ci":
        return text.casefold() == needle.casefold()
    return needle.casefold() in text.casefold()


def as_number(text: str) -> Optional[Decimal]:
    if not re.match(r"^-?\d+([.,]\d+)?$", text or ""):
        return None
    try:
        return Decimal(text.replace(",", "."))
    except InvalidOperation:
        return None


def scan_result(columns: List[str], rows: List[tuple], needle: str, mode: str):
    """[(column_index, first_matching_row_index, match_count)]"""
    hits = {}
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            if cell_matches(cell, needle, mode):
                if c not in hits:
                    hits[c] = [r, 0]
                hits[c][1] += 1
    return [(c, first, count) for c, (first, count) in sorted(hits.items())]


def searchable_columns(columns: Iterable[Column], needle: str, mode: str) -> List[Column]:
    numeric = as_number(needle) is not None
    out = []
    for c in columns:
        if c.family == "char":
            if c.length and mode == "exact" and len(needle) > c.length:
                continue
            out.append(c)
        elif c.family == "number" and numeric and mode != "contains":
            out.append(c)
    return out


def table_search_sql(key, columns: List[Column], needle: str, mode: str, max_rows: int = 50) -> Tuple[str, dict]:
    """One scan of a table that flags which columns hold the value."""
    conds = []
    binds = {"max_rows": max_rows}  # only placeholders present in the SQL may be bound
    number = as_number(needle)
    for c in columns:
        col = qi(c.name)
        if c.family == "number":
            binds["n"] = number
            conds.append("%s = :n" % col)
            continue
        binds["v"] = needle
        if mode == "exact":
            conds.append("%s = :v" % col)
        elif mode == "ci":
            conds.append("UPPER(%s) = UPPER(:v)" % col)
        else:
            conds.append("UPPER(%s) LIKE '%%' || UPPER(:v) || '%%'" % col)
    flags = ", ".join("CASE WHEN %s THEN 1 ELSE 0 END" % c for c in conds)
    sql = "SELECT %s FROM %s WHERE (%s) AND ROWNUM <= :max_rows" % (flags, qualified(key), " OR ".join(conds))
    return sql, binds


def sample_sql(key, column: Column, needle: str, mode: str, rows: int = 20) -> str:
    """Literal SQL to look at the matching rows (opened in the SQL page)."""
    col = qi(column.name)
    lit = "'%s'" % needle.replace("'", "''")
    if column.family == "number":
        cond = "%s = %s" % (col, as_number(needle))
    elif mode == "exact":
        cond = "%s = %s" % (col, lit)
    elif mode == "ci":
        cond = "UPPER(%s) = UPPER(%s)" % (col, lit)
    else:
        cond = "UPPER(%s) LIKE '%%' || UPPER(%s) || '%%'" % (col, lit)
    return "SELECT *\n  FROM %s\n WHERE %s\n   AND ROWNUM <= %d" % (qualified(key), cond, rows)


# masking lives in privacy.py; kept importable from here for older callers
from .privacy import mask_rows, mask_value  # noqa: E402,F401
