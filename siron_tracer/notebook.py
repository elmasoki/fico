"""Query notebook: hand-written migration queries checked against what Siron shows.

A verification case is a set of bind values plus expectations written as plain
lines, taken from the Siron screen for that record:

    satır = 3                  row count (also >=, <=, !=, >, <)
    FULL_NAME = AHMET YILMAZ   some row has this value
    IBAN ~ TR00                some row contains this (case-insensitive)
    RISK_CLASS != H            no row has this value
    IBAN dolu                  some row has a value (``boş`` for none)
    tüm STATUS = OPEN          every row (prefix ``tüm`` / ``all``)

Values compare as numbers when both sides are numbers, dates by prefix
(``2026-09-01`` matches ``2026-09-01 00:00:00``), text exactly after trimming.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Sequence, Tuple

ROW_WORDS = {"SATIR", "SATİR", "SATIR_SAYISI", "ROWS", "ROW", "COUNT", "ADET"}
_LINE = re.compile(r"^(?P<all>(tüm|tum|all|her)\s+)?(?P<col>[^\s=!<>~]+)\s*(?P<op>>=|<=|!=|=|>|<|~|\bdolu\b|\bboş\b|\bbos\b)\s*(?P<val>.*)$",
                   re.I)


@dataclass
class Expectation:
    line: str
    column: str
    op: str
    value: str
    every: bool = False

    @property
    def is_rows(self) -> bool:
        return self.column.upper().replace("I", "I") in ROW_WORDS or self.column.lower() in ("satır", "satir")


@dataclass
class CheckResult:
    line: str
    ok: bool
    detail: str


@dataclass
class CaseResult:
    status: str                         # pass / fail / error
    checks: List[CheckResult] = field(default_factory=list)
    rows: int = 0
    error: Optional[str] = None
    columns: List[str] = field(default_factory=list)
    sample: List[list] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"status": self.status, "rows": self.rows, "error": self.error, "columns": self.columns,
                "sample": self.sample, "checks": [c.__dict__ for c in self.checks]}


def parse_binds(text: str) -> Dict[str, str]:
    """'musteri_no = 104233' lines (':' prefix optional) -> {'MUSTERI_NO': '104233'}."""
    out = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        out[name.strip().lstrip(":").upper()] = value.strip()
    return out


def parse_expectations(text: str) -> Tuple[List[Expectation], List[str]]:
    """(expectations, lines that could not be read)."""
    out, bad = [], []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE.match(line)
        if not m:
            bad.append(line)
            continue
        op = m.group("op").lower().replace("bos", "boş")
        out.append(Expectation(line, m.group("col").strip().upper(), op, m.group("val").strip(), bool(m.group("all"))))
    return out, bad


def _num(v) -> Optional[Decimal]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float, Decimal)):
        return Decimal(str(v))
    try:
        return Decimal(str(v).strip().replace(",", ".")) if re.fullmatch(r"\s*-?\d+([.,]\d+)?\s*", str(v)) else None
    except InvalidOperation:
        return None


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    return str(v).strip()


def values_equal(cell, expected: str) -> bool:
    if cell is None:
        return expected.upper() in ("", "NULL")
    a, b = _num(cell), _num(expected)
    if a is not None and b is not None:
        return a == b
    text = _text(cell)
    if isinstance(cell, (date, datetime)) or re.match(r"\d{4}-\d{2}-\d{2}", text):
        return text.startswith(expected) if expected else not text
    return text == expected


def _compare_count(n: int, op: str, value: str) -> bool:
    try:
        target = int(value.rstrip("+").strip())
    except ValueError:
        return False
    if value.strip().endswith("+"):          # "10000+" from a capped count means "at least"
        return n >= target
    return {"=": n == target, "!=": n != target, ">=": n >= target, "<=": n <= target,
            ">": n > target, "<": n < target}.get(op, False)


def _cell_ok(cell, op: str, value: str) -> bool:
    if op == "=":
        return values_equal(cell, value)
    if op == "!=":
        return not values_equal(cell, value)
    if op == "~":
        return value.upper() in _text(cell).upper()
    if op == "dolu":
        return _text(cell) != ""
    if op == "boş":
        return _text(cell) == ""
    a, b = _num(cell), _num(value)
    if a is None or b is None:
        a, b = _text(cell), value
    return {">=": a >= b, "<=": a <= b, ">": a > b, "<": a < b}.get(op, False)


def evaluate(columns: Sequence[str], rows: Sequence[Sequence], expectations: List[Expectation]) -> List[CheckResult]:
    index = {c.upper(): i for i, c in enumerate(columns)}
    out = []
    for e in expectations:
        if e.is_rows:
            ok = _compare_count(len(rows), e.op if e.op in ("=", "!=", ">=", "<=", ">", "<") else "=", e.value)
            out.append(CheckResult(e.line, ok, "%d satır döndü" % len(rows)))
            continue
        if e.column not in index:
            out.append(CheckResult(e.line, False, "sonuçta %s kolonu yok" % e.column))
            continue
        cells = [r[index[e.column]] for r in rows]
        if e.op == "!=" and not e.every:
            bad = [c for c in cells if values_equal(c, e.value)]
            out.append(CheckResult(e.line, not bad, "hiçbir satırda yok" if not bad else "%d satırda var" % len(bad)))
            continue
        matches = [c for c in cells if _cell_ok(c, e.op, e.value)]
        if e.every:
            ok = bool(cells) and len(matches) == len(cells)
            detail = "%d / %d satır uyuyor" % (len(matches), len(cells))
        else:
            ok = bool(matches)
            seen = ", ".join(sorted({_text(c) or "∅" for c in cells})[:5])
            detail = "bulundu" if ok else ("sonuçtaki değerler: %s" % seen if cells else "sonuç boş")
        out.append(CheckResult(e.line, ok, detail))
    return out


def run_case(run, sql: str, binds_text: str, expect_text: str, placeholders: Sequence[str]) -> CaseResult:
    """`run(sql, binds)` -> (columns, rows). Only binds used by the SQL are passed (DPY-4008)."""
    given = parse_binds(binds_text)
    wanted = [p.upper() for p in placeholders]
    missing = [p for p in wanted if p not in given]
    if missing:
        return CaseResult("error", error="Bind değeri eksik: %s" % ", ".join(":" + m for m in missing))
    expectations, bad = parse_expectations(expect_text)
    if bad:
        return CaseResult("error", error="Okunamayan beklenti satırı: %s" % "; ".join(bad))
    if not expectations:
        return CaseResult("error", error="Beklenti yok: en az bir satır yazın (ör. satır = 1).")
    try:
        columns, rows = run(sql, {p: given[p] for p in dict.fromkeys(wanted)})
    except Exception as exc:
        return CaseResult("error", error=str(exc)[:500])
    checks = evaluate(columns, rows, expectations)
    status = "pass" if all(c.ok for c in checks) else "fail"
    return CaseResult(status, checks, len(rows), columns=list(columns),
                      sample=[[_text(v) for v in r] for r in rows[:20]])


def expectations_from_row(columns: Sequence[str], rows: Sequence[Sequence], max_columns: int = 12) -> str:
    """Suggested expectation lines from a reference result (e.g. the screen's own SQL)."""
    lines = ["satır = %d" % len(rows)]
    if rows:
        for c, v in list(zip(columns, rows[0]))[:max_columns]:
            if v is None or c.upper() in ("RN", "ROWNUM"):
                continue
            text = _text(v)
            if len(text) <= 80:
                lines.append("%s = %s" % (c.upper(), text))
    return "\n".join(lines)


def diff_html(old: str, new: str) -> List[Tuple[str, str]]:
    """[(kind, line)] with kind in ' ', '+', '-' for a simple side-by-side-free diff view."""
    out = []
    for line in difflib.ndiff((old or "").splitlines(), (new or "").splitlines()):
        if line.startswith("? "):
            continue
        out.append((line[0], line[2:]))
    return out
