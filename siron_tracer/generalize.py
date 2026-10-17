"""Turn a captured screen query into an extraction query for all records.

The SQL Siron ran for one customer (``WHERE k.kundnr = :1``) carries exactly the
joins, columns and constant filters the screen needs. Dropping the parts that
depend on bind values - and the paging the application adds - leaves a query
that returns the same kind of data for every record:

* WHERE / HAVING / ON / START WITH conditions are split into AND-ed parts; a part
  that uses a bind value or ROWNUM is removed (an emptied ON becomes ``1 = 1``)
* sub-queries are processed first, so paging wrappers and ``IN (SELECT ...)``
  filters are cleaned too
* FETCH FIRST / OFFSET paging is removed; any other bind becomes NULL

Removing a condition can only widen the result, never narrow it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Union

from .sqlutil import _PLACEHOLDER_RE, _scan

_TOKEN = re.compile(r"\s+|(?<![:\w$#]):(?:[A-Za-z_][\w$#]*|\d+)|\?|[A-Za-z_][\w$#]*|\d+(?:\.\d+)?|[(),;]|.", re.S)
_WORD = re.compile(r"[A-Za-z_][\w$#]*\Z")
_JOIN_WORDS = {"JOIN", "INNER", "LEFT", "RIGHT", "FULL", "CROSS", "NATURAL", "OUTER", "WHERE"}


@dataclass
class Tok:
    kind: str     # ws, word, ph, lp, rp, comma, semi, lit, other
    text: str

    @property
    def up(self) -> str:
        return self.text.upper() if self.kind == "word" else ""


@dataclass
class Group:
    items: List["Item"]
    removed: List[str] = field(default_factory=list)
    kept: List[str] = field(default_factory=list)


Item = Union[Tok, Group]


@dataclass
class Generalized:
    sql: str
    removed: List[str]          # conditions dropped because they depend on bind values / paging
    kept: List[str]             # constant conditions that stay (e.g. HISTBIS = '9999')
    nulled: List[str]           # binds outside conditions replaced with NULL
    error: Optional[str] = None

    @property
    def changed(self) -> bool:
        return bool(self.removed or self.nulled)


# --------------------------------------------------------------------------- tokens

def _tokens(sql: str) -> List[Tok]:
    out: List[Tok] = []
    for kind, s, e in _scan(sql):
        chunk = sql[s:e]
        if kind != "code":
            out.append(Tok("lit" if kind in ("string", "qident") else "ws", chunk if kind != "comment" else " "))
            continue
        for m in _TOKEN.finditer(chunk):
            t = m.group(0)
            if t.isspace():
                out.append(Tok("ws", t))
            elif _PLACEHOLDER_RE.fullmatch(t):
                out.append(Tok("ph", t))
            elif t == "(":
                out.append(Tok("lp", t))
            elif t == ")":
                out.append(Tok("rp", t))
            elif t == ",":
                out.append(Tok("comma", t))
            elif t == ";":
                out.append(Tok("semi", t))
            elif _WORD.match(t):
                out.append(Tok("word", t))
            else:
                out.append(Tok("other", t))
    return out


def _tree(tokens: List[Tok]) -> List[Item]:
    stack: List[List[Item]] = [[]]
    for t in tokens:
        if t.kind == "lp":
            stack[-1].append(t)
            stack.append([])
        elif t.kind == "rp" and len(stack) > 1:
            inner = stack.pop()
            stack[-1].append(Group(inner))
            stack[-1].append(t)
        else:
            stack[-1].append(t)
    while len(stack) > 1:                     # unbalanced: close what is open
        inner = stack.pop()
        stack[-1].append(Group(inner))
    return stack[0]


def _text(items: List[Item]) -> str:
    return "".join(_text(i.items) if isinstance(i, Group) else i.text for i in items)


def _compact(items: List[Item]) -> str:
    text = re.sub(r"\s+", " ", _text(items)).strip()
    return re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", text))


def _has(items: List[Item], pred) -> bool:
    for i in items:
        if isinstance(i, Group):
            if _has(i.items, pred):
                return True
        elif pred(i):
            return True
    return False


def _next_word(items: List[Item], i: int) -> str:
    for j in range(i + 1, len(items)):
        it = items[j]
        if isinstance(it, Tok) and it.kind == "ws":
            continue
        return it.up if isinstance(it, Tok) else ""
    return ""


# --------------------------------------------------------------------------- clauses

def _clause_start(items: List[Item], i: int) -> Optional[str]:
    it = items[i]
    if not isinstance(it, Tok) or it.kind != "word":
        return None
    if it.up in ("WHERE", "HAVING", "ON"):
        return it.up
    if it.up == "START" and _next_word(items, i) == "WITH":
        return "START WITH"
    return None


def _clause_end(items: List[Item], i: int, kind: str) -> bool:
    it = items[i]
    if isinstance(it, Group):
        return False
    if it.kind in ("semi",):
        return True
    if kind == "ON" and it.kind == "comma":
        return True
    up = it.up
    if not up:
        return False
    nxt = _next_word(items, i)
    if up in ("GROUP", "ORDER", "CONNECT") and nxt == "BY":
        return True
    if up == "START" and nxt == "WITH":
        return True
    if up == "FOR" and nxt == "UPDATE":
        return True
    if up == "FETCH" and nxt in ("FIRST", "NEXT"):
        return True
    if up in ("HAVING", "UNION", "MINUS", "INTERSECT", "EXCEPT", "OFFSET", "MODEL", "WINDOW", "RETURNING"):
        return True
    if up == "WHERE" and kind != "WHERE":
        return True
    if kind == "ON" and up in _JOIN_WORDS:
        return True
    return False


def _split_and(body: List[Item]) -> List[List[Item]]:
    parts: List[List[Item]] = [[]]
    between = case = 0
    for it in body:
        if isinstance(it, Tok) and it.kind == "word":
            up = it.up
            if up == "CASE":
                case += 1
            elif up == "END" and case:
                case -= 1
            elif up == "BETWEEN":
                between += 1
            elif up == "AND":
                if between:
                    between -= 1
                elif not case:
                    parts.append([])
                    continue
        parts[-1].append(it)
    return parts


def _bound(part: List[Item]) -> bool:
    return _has(part, lambda t: t.kind == "ph" or t.up == "ROWNUM")


def _process(items: List[Item]) -> Tuple[List[Item], List[str], List[str], List[str]]:
    # inner levels first (sub-queries, IN lists, paging wrappers)
    for it in items:
        if isinstance(it, Group):
            it.items, it.removed, it.kept, _ = _process(it.items)
    out: List[Item] = []
    removed: List[str] = []
    kept: List[str] = []
    i = 0
    while i < len(items):
        kind = _clause_start(items, i)
        if not kind:
            out.append(items[i])
            i += 1
            continue
        head = [items[i]]
        j = i + 1
        if kind == "START WITH":                       # keep both words in the head
            while j < len(items) and not (isinstance(items[j], Tok) and items[j].up == "WITH"):
                head.append(items[j])
                j += 1
            head.append(items[j])
            j += 1
        start = j
        while j < len(items) and not _clause_end(items, j, kind):
            j += 1
        body = items[start:j]
        parts = _split_and(body)
        keep_parts, drop_parts = [], []
        for p in parts:
            (drop_parts if _bound(p) else keep_parts).append(p)
        removed += [_compact(p) for p in drop_parts if _compact(p)]
        kept += [_compact(p) for p in keep_parts if _compact(p)]
        trailing_ws = Tok("ws", " ")
        if keep_parts:
            out += head + [Tok("ws", " ")]
            for n, p in enumerate(keep_parts):
                if n:
                    out += [Tok("ws", " "), Tok("word", "AND"), Tok("ws", " ")]
                out += _strip(p)
            out.append(trailing_ws)
        elif kind == "ON":
            out += head + [Tok("ws", " "), Tok("other", "1 = 1"), trailing_ws]
        else:
            out.append(trailing_ws)                     # the whole WHERE / HAVING / START WITH goes
        i = j
    out = _drop_paging(out, removed)
    # collect what surviving sub-groups reported
    for it in out:
        if isinstance(it, Group):
            removed += it.removed
            kept += it.kept
    return out, removed, kept, []


def _null_binds(items: List[Item], nulled: List[str]):
    """Binds left outside conditions (select list, ORDER BY ...) become NULL - only after every
    condition was judged, so a bound condition is never kept as ``x = NULL``."""
    for n, it in enumerate(items):
        if isinstance(it, Group):
            _null_binds(it.items, nulled)
        elif it.kind == "ph":
            nulled.append(it.text)
            items[n] = Tok("word", "NULL")


def _strip(part: List[Item]) -> List[Item]:
    s, e = 0, len(part)
    while s < e and isinstance(part[s], Tok) and part[s].kind == "ws":
        s += 1
    while e > s and isinstance(part[e - 1], Tok) and part[e - 1].kind == "ws":
        e -= 1
    return part[s:e]


def _drop_paging(items: List[Item], removed: List[str]) -> List[Item]:
    """Remove FETCH FIRST|NEXT ... ONLY|WITH TIES and OFFSET ... ROW(S) at this level."""
    out: List[Item] = []
    i = 0
    while i < len(items):
        it = items[i]
        if isinstance(it, Tok) and (it.up == "FETCH" and _next_word(items, i) in ("FIRST", "NEXT") or it.up == "OFFSET"):
            stop = ("ONLY", "TIES") if it.up == "FETCH" else ("ROW", "ROWS")
            j = i + 1
            while j < len(items) and not (isinstance(items[j], Tok) and items[j].up in stop):
                j += 1
            removed.append(_compact(items[i:j + 1]))
            out.append(Tok("ws", " "))
            i = j + 1
            continue
        out.append(it)
        i += 1
    return out


def _tidy(sql: str) -> str:
    sql = re.sub(r"[ \t]+\n", "\n", sql)
    sql = re.sub(r"[ \t]{2,}", " ", sql)
    sql = re.sub(r"\(\s+\)", "()", sql)
    sql = re.sub(r"\s+\)", ")", sql)
    return sql.strip().rstrip(";").strip()


def generalize(sql: str) -> Generalized:
    text = (sql or "").strip()
    head = re.sub(r"^(\s|--[^\n]*\n|/\*.*?\*/)*", "", text, flags=re.S)[:10].upper()
    if not (head.startswith("SELECT") or head.startswith("WITH") or head.startswith("(")):
        return Generalized(text, [], [], [], "Yalnız SELECT / WITH sorguları taşıma sorgusuna çevrilebilir.")
    items, removed, kept, _ = _process(_tree(_tokens(text)))
    nulled: List[str] = []
    _null_binds(items, nulled)
    dedup = lambda xs: list(dict.fromkeys(x for x in xs if x))  # noqa: E731
    return Generalized(_tidy(_text(items)), dedup(removed), dedup(kept), dedup(nulled))
