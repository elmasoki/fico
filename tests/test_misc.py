from catalog_fixture import make

from siron_tracer.finder import (cell_matches, mask_value, sample_sql, scan_result, searchable_columns,
                                 table_search_sql)
from siron_tracer.layout import layout
from siron_tracer.sqlutil import format_sql

CAT = make()


def test_cell_matching():
    assert cell_matches("Ali Veli", "ali veli", "ci") and not cell_matches("Ali Veli", "ali veli", "exact")
    assert cell_matches(125.0, "125", "exact") and cell_matches("00125", "125", "exact")
    assert cell_matches("TR12 3456", "3456", "contains") and not cell_matches(None, "x", "contains")
    assert scan_result(["A", "B"], [("x", "y"), ("y", "y")], "y", "exact") == [(0, 1, 1), (1, 0, 2)]


def test_table_search_sql():
    cols = searchable_columns(CAT.columns(("SIRON", "ACCOUNT")), "1001", "exact")
    assert [c.name for c in cols] == ["ID", "CUST_ID", "ACC_NO", "IBAN", "BALANCE"]
    assert [c.name for c in searchable_columns(CAT.columns(("SIRON", "ACCOUNT")), "abc", "ci")] == ["ACC_NO", "IBAN"]
    sql, binds = table_search_sql(("SIRON", "ACCOUNT"), cols, "1001", "exact")
    assert sql.startswith("SELECT CASE WHEN ID = :n") and "FROM SIRON.ACCOUNT WHERE (" in sql
    assert binds["v"] == "1001" and str(binds["n"]) == "1001"
    only_numbers = [c for c in cols if c.family == "number"]
    sql, binds = table_search_sql(("SIRON", "ACCOUNT"), only_numbers, "1001", "exact")
    assert ":v" not in sql and set(binds) == {"n", "max_rows"}
    assert "UPPER(IBAN) LIKE" in sample_sql(("SIRON", "ACCOUNT"), cols[3], "o'k", "contains")
    assert "'o''k'" in sample_sql(("SIRON", "ACCOUNT"), cols[3], "o'k", "contains")


def test_masking():
    assert mask_value("TR120006400000112345678901") == "TR**********************01"
    assert mask_value("Ali") == "A*i" and mask_value(None) is None and mask_value(7) == "*"


def test_layout_bounds():
    pos, w, h = layout([(i, 120, 40) for i in range(12)], [(0, 1), (1, 2), (3, 4)])
    assert len(pos) == 12 and all(0 <= x <= w - 120 and 0 <= y <= h - 40 for x, y in pos.values())
    boxes = list(pos.values())
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            (x1, y1), (x2, y2) = boxes[i], boxes[j]
            assert abs(x1 - x2) >= 120 or abs(y1 - y2) >= 40, "boxes overlap"
    assert layout([], []) == ({}, 400, 200)


def test_format_sql():
    out = format_sql("select a, b from t where x = 'from y' and z between 1 and 2 order by a")
    assert out.splitlines() == ["SELECT a, b", "FROM t", "WHERE x = 'from y'", "  AND z between 1 and 2", "ORDER BY a"]
