"""Pure-Python SQL helpers (no database access).

* compute_sql_id      - Oracle SQL_ID of a statement text (MD5 based, same as V$SQL.SQL_ID)
* parse_audit_binds   - parse the "#1(3):abc #2(1):5" format of SQL_BINDS / SQL_BIND columns
* find_placeholders   - locate :1, :B1, :name and ? placeholders outside strings/comments
* build_slots         - match audit bind values to placeholders
* substitute_binds    - produce a literal SQL with bind values put in place
* extract_tables      - find table/view names referenced by a statement
* is_select           - True for SELECT / WITH statements
"""
from __future__ import annotations

import hashlib
import re
import struct
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Set, Tuple

# --------------------------------------------------------------------------- SQL_ID

_SQLID_ALPHABET = "0123456789abcdfghjkmnpqrstuvwxyz"


def compute_sql_id(sql_text: str, encoding: str = "utf-8") -> str:
    """Return the Oracle SQL_ID for a statement text.

    Oracle hashes the exact statement text followed by a NUL byte with MD5 and
    encodes the last 8 bytes of the digest in base32.
    """
    digest = hashlib.md5(sql_text.encode(encoding) + b"\x00").digest()
    _, _, msb, lsb = struct.unpack("<IIII", digest)
    value = (msb << 32) | lsb
    chars = []
    for _ in range(13):
        chars.append(_SQLID_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(chars))


# --------------------------------------------------------------------------- audit binds

@dataclass
class Bind:
    position: int
    value: Optional[str]  # None means NULL / empty


_BIND_HDR = re.compile(r"#(\d+)\((\d+)\):")


def _is_boundary(raw: str, idx: int) -> bool:
    rest = raw[idx:]
    if not rest.strip():
        return True
    return rest[:1].isspace() and _BIND_HDR.match(rest.lstrip()) is not None


def _value_end(raw: str, start: int, length: int) -> int:
    end = start + length
    if _is_boundary(raw, end):
        return end
    # The length may be expressed in bytes when the value has multi-byte characters.
    nbytes, i = 0, start
    while i < len(raw) and nbytes < length:
        nbytes += len(raw[i].encode("utf-8"))
        i += 1
    if _is_boundary(raw, i):
        return i
    nxt = re.compile(r"\s#\d+\(\d+\):").search(raw, start)
    return nxt.start() if nxt else len(raw)


def parse_audit_binds(raw: Optional[str]) -> List[Bind]:
    """Parse the bind list written by Oracle auditing.

    Example: ' #1(4):1001 #2(5):AHMET #3(0):'
    """
    if not raw:
        return []
    binds: List[Bind] = []
    pos = 0
    while True:
        m = _BIND_HDR.search(raw, pos)
        if not m:
            break
        length = int(m.group(2))
        start = m.end()
        end = _value_end(raw, start, length)
        value = raw[start:end]
        binds.append(Bind(int(m.group(1)), value if value != "" else None))
        pos = end
    return binds


def format_audit_binds(values: Iterable[Optional[str]]) -> str:
    """Inverse of parse_audit_binds (used to normalise V$SQL_BIND_CAPTURE values)."""
    parts = []
    for i, v in enumerate(values, start=1):
        v = "" if v is None else v
        parts.append("#%d(%d):%s" % (i, len(v), v))
    return " " + " ".join(parts) if parts else ""


# --------------------------------------------------------------------------- lexical scan

def _scan(sql: str) -> List[Tuple[str, int, int]]:
    """Split SQL into spans of kind code / string / qident / comment."""
    spans: List[Tuple[str, int, int]] = []
    i, n, code_start = 0, len(sql), 0
    while i < n:
        c = sql[i]
        if c == "-" and sql.startswith("--", i):
            j = sql.find("\n", i)
            j, kind = (n if j < 0 else j + 1), "comment"
        elif c == "/" and sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            j, kind = (n if j < 0 else j + 2), "comment"
        elif (c in "qQ" and i + 2 < n and sql[i + 1] == "'"
              and (i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] in "_$#"))):
            opener = sql[i + 2]
            closer = {"[": "]", "{": "}", "(": ")", "<": ">"}.get(opener, opener)
            j = sql.find(closer + "'", i + 3)
            j, kind = (n if j < 0 else j + 2), "string"
        elif c == "'":
            j = i + 1
            while True:
                k = sql.find("'", j)
                if k < 0:
                    j = n
                    break
                if k + 1 < n and sql[k + 1] == "'":
                    j = k + 2
                    continue
                j = k + 1
                break
            kind = "string"
        elif c == '"':
            k = sql.find('"', i + 1)
            j, kind = (n if k < 0 else k + 1), "qident"
        else:
            i += 1
            continue
        if code_start < i:
            spans.append(("code", code_start, i))
        spans.append((kind, i, j))
        i = code_start = j
    if code_start < n:
        spans.append(("code", code_start, n))
    return spans


def strip_comments(sql: str) -> str:
    return "".join(sql[s:e] for kind, s, e in _scan(sql) if kind != "comment")


def is_select(sql: str) -> bool:
    body = strip_comments(sql).strip().lstrip("(").lstrip()
    head = body[:6].upper()
    return head.startswith("SELECT") or head.startswith("WITH")


# --------------------------------------------------------------------------- placeholders

@dataclass
class Placeholder:
    text: str   # as written in the SQL, e.g. ":B1", ":1", "?"
    name: str   # normalised name used for matching, e.g. "B1"
    start: int
    end: int


_PLACEHOLDER_RE = re.compile(r"(?<![:\w$#]):([A-Za-z_][\w$#]*|\d+)|\?")


def find_placeholders(sql: str) -> List[Placeholder]:
    out: List[Placeholder] = []
    for kind, s, e in _scan(sql):
        if kind != "code":
            continue
        for m in _PLACEHOLDER_RE.finditer(sql, s, e):
            if m.group(0) == "?":
                name = str(sum(1 for p in out if p.text == "?") + 1)
            else:
                name = m.group(1).upper()
            out.append(Placeholder(m.group(0), name, m.start(), m.end()))
    return out


@dataclass
class BindSlot:
    """One editable bind value; may cover several occurrences of the same name."""
    label: str
    occurrences: List[int]
    value: Optional[str]
    missing: bool = False
    kind: str = "text"  # text | number | raw | null


def build_slots(placeholders: List[Placeholder], binds: List[Bind]) -> List[BindSlot]:
    """Match audit bind values to placeholders.

    Audit records list one value per bind position. When a named bind is used
    more than once and the number of values equals the number of distinct
    names, values are matched by name; otherwise by occurrence order.
    """
    ordered = [b.value for b in sorted(binds, key=lambda b: b.position)]
    names = [p.name for p in placeholders]
    distinct = list(dict.fromkeys(names))
    if len(distinct) < len(names) and len(ordered) == len(distinct):
        return [
            BindSlot(":" + name, [i for i, n in enumerate(names) if n == name], ordered[idx])
            for idx, name in enumerate(distinct)
        ]
    slots = []
    for i, p in enumerate(placeholders):
        if i < len(ordered):
            slots.append(BindSlot(p.text, [i], ordered[i]))
        else:
            slots.append(BindSlot(p.text, [i], None, missing=True))
    return slots


def to_literal(value: Optional[str], kind: str = "text") -> str:
    if kind == "null" or value is None or (value == "" and kind != "raw"):
        return "NULL"
    if kind in ("number", "raw"):
        return value
    return "'" + value.replace("'", "''") + "'"


def substitute_binds(sql: str, placeholders: List[Placeholder], slots: List[BindSlot]) -> str:
    replacement = {}
    for slot in slots:
        if slot.missing:
            continue
        for idx in slot.occurrences:
            replacement[idx] = to_literal(slot.value, slot.kind)
    out, last = [], 0
    for idx, p in enumerate(placeholders):
        out.append(sql[last:p.start])
        out.append(replacement.get(idx, sql[p.start:p.end]))
        last = p.end
    out.append(sql[last:])
    return "".join(out)


def literal_sql(sql: str, raw_binds: Optional[str]) -> Tuple[str, List[BindSlot]]:
    """Convenience: audit SQL text + raw audit binds -> (literal SQL, slots)."""
    placeholders = find_placeholders(sql)
    slots = build_slots(placeholders, parse_audit_binds(raw_binds))
    return substitute_binds(sql, placeholders, slots), slots


# --------------------------------------------------------------------------- tables

ObjectKey = Tuple[Optional[str], str]  # (owner or None, name)

_TOKEN_RE = re.compile(
    r'(?P<ident>(?:"[^"]+"|[A-Za-z_][\w$#]*)(?:\s*\.\s*(?:"[^"]+"|[A-Za-z_][\w$#]*))*)'
    r"|(?P<punct>[(),.;])"
    r"|(?P<other>\S)"
)

_TABLE_KW = {"FROM", "JOIN", "INTO", "UPDATE", "USING"}
_NOT_ALIAS = {
    "WHERE", "GROUP", "ORDER", "JOIN", "INNER", "LEFT", "RIGHT", "FULL", "OUTER",
    "CROSS", "NATURAL", "ON", "UNION", "MINUS", "INTERSECT", "EXCEPT", "CONNECT",
    "START", "HAVING", "FETCH", "FOR", "PIVOT", "UNPIVOT", "PARTITION", "SAMPLE",
    "SET", "VALUES", "SELECT", "WITH", "USING", "WHEN", "THEN", "RETURNING",
    "RETURN", "LOG", "MODEL", "OFFSET", "LIMIT", "WINDOW", "AS", "SUBPARTITION",
}
_SKIP_NAMES = {"DUAL", "TABLE", "LATERAL", "THE", "ONLY", "XMLTABLE", "JSON_TABLE"}
# functions whose arguments use the FROM keyword, e.g. EXTRACT(YEAR FROM d)
_FROM_FUNCS = {"EXTRACT", "TRIM", "SUBSTRING", "OVERLAY", "POSITION", "LISTAGG"}


def _code_only(sql: str) -> str:
    parts = []
    for kind, s, e in _scan(sql):
        parts.append(sql[s:e] if kind in ("code", "qident") else " " * (e - s))
    return "".join(parts)


def _split_ident(token: str) -> List[str]:
    parts = [p.strip() for p in re.findall(r'"[^"]+"|[^.\s]+', token)]
    return [p[1:-1] if p.startswith('"') else p.upper() for p in parts]


def _tokens(sql: str):
    for m in _TOKEN_RE.finditer(_code_only(sql)):
        if m.group("ident"):
            yield "ident", m.group("ident")
        elif m.group("punct"):
            yield "punct", m.group("punct")
        else:
            yield "other", m.group("other")


def _heuristic_tables(sql: str) -> List[ObjectKey]:
    toks = list(_tokens(sql))
    found: List[ObjectKey] = []
    parens: List[str] = []  # identifier before each open parenthesis
    i = 0
    while i < len(toks):
        kind, text = toks[i]
        word = text.upper() if kind == "ident" else ""
        if (kind, text) == ("punct", "("):
            prev = toks[i - 1] if i else ("", "")
            parens.append(prev[1].upper() if prev[0] == "ident" else "")
        elif (kind, text) == ("punct", ")") and parens:
            parens.pop()
        elif word == "FROM" and parens and parens[-1] in _FROM_FUNCS:
            pass
        elif word in _TABLE_KW:
            multi = word == "FROM"
            j = i + 1
            while j < len(toks):
                k, t = toks[j]
                if k != "ident" or t.upper() in _NOT_ALIAS:
                    break
                parts = _split_ident(t)
                if parts[-1] not in _SKIP_NAMES and t.upper() not in _TABLE_KW:
                    if word != "INTO" and j + 1 < len(toks) and toks[j + 1] == ("punct", "("):
                        break  # table function such as TABLE(...)
                    found.append((parts[-2] if len(parts) > 1 else None, parts[-1]))
                j += 1
                # optional alias, with or without AS
                if j < len(toks) and toks[j][0] == "ident" and toks[j][1].upper() == "AS":
                    j += 1
                if (j < len(toks) and toks[j][0] == "ident"
                        and toks[j][1].upper() not in _NOT_ALIAS):
                    j += 1
                if multi and j < len(toks) and toks[j] == ("punct", ","):
                    j += 1
                    continue
                break
            i = max(j, i + 1)
            continue
        i += 1
    return found


def extract_tables(sql: str, known_objects: Optional[Set[ObjectKey]] = None,
                   default_owner: Optional[str] = None) -> List[ObjectKey]:
    """Return referenced objects as (owner, name) pairs, in first-seen order.

    With a known object catalogue (owner, name) every identifier that matches a
    catalogue entry is reported, which also catches packages/functions and
    objects referenced in unusual syntax. Without it a FROM/JOIN/INTO/UPDATE
    heuristic is used.
    """
    result: List[ObjectKey] = []

    def add(key: ObjectKey):
        if key not in result:
            result.append(key)

    if not known_objects:
        for owner, name in _heuristic_tables(sql):
            add((owner or default_owner, name))
        return result

    names_by_owner = {}
    for owner, name in known_objects:
        names_by_owner.setdefault(name, set()).add(owner)

    prev = None
    for kind, text in _tokens(sql):
        if kind == "ident" and prev != ("punct", "."):
            parts = _split_ident(text)
            # schema.object[.member] or object[.member]
            if len(parts) >= 2 and (parts[0], parts[1]) in known_objects:
                add((parts[0], parts[1]))
            elif parts[0] in names_by_owner:
                owners = names_by_owner[parts[0]]
                owner = default_owner if default_owner in owners else sorted(owners)[0]
                add((owner, parts[0]))
        prev = (kind, text)
    return result
