from catalog_fixture import make
from test_features import env  # noqa: F401  (pytest fixture)

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


def test_sensitive_detection():
    from siron_tracer.privacy import Privacy
    p = Privacy()
    for name in ("TCKN", "TC_KIMLIK_NO", "IBAN", "ACC_NO", "PHONE_NUMBER", "EMAIL", "FULL_NAME", "BIRTH_DATE", "ADRES"):
        assert p.guess(name), name
    for name in ("STATUS", "AMOUNT", "SCENARIO_ID", "NAME", "CURRENCY"):
        assert not p.guess(name), name
    assert p.is_sensitive("STATUS", {"sensitive": 1}) and not p.is_sensitive("IBAN", {"sensitive": 0})
    idx = p.mask_indexes(["A", "B", "PHONE"], ["S.T.IBAN", "S.T.STATUS", None], "sensitive")
    assert idx == {0, 2}


def test_signature_groups_literals():
    from siron_tracer.sqlutil import sql_signature
    a = sql_signature("select * from t where a = 'x' and b = 12 and c in (1,2,3) and d = :1")
    b = sql_signature("SELECT *  FROM t WHERE a='yy' AND b=7 AND c IN (4, 5) AND d = :1")
    assert a == b and ":1" in a
    assert sql_signature("select a from t where x = 1") != sql_signature("select b from t where x = 1")


def test_load_order_and_cycles():
    from siron_tracer.migration import load_order
    from siron_tracer.relations import build_relations
    rels = build_relations(CAT, set(CAT.tables))
    order, parents = load_order(list(CAT.tables), rels)
    names = [k[1] for k, _ in order]
    assert names.index("CUSTOMER") < names.index("ACCOUNT") < names.index("TRANSACTION")


def test_excel_parsing_rules():
    from siron_tracer.excel import parse_flag, parse_status
    assert parse_status("Taşınacak") == "migrate" and parse_status("gereksiz") == "ignore" and parse_status("") is None
    assert parse_flag("Evet") == 1 and parse_flag("hayır") == 0 and parse_flag("Evet (tahmin)") is None
    import pytest
    with pytest.raises(ValueError):
        parse_status("Belki")


def test_dependency_resolution():
    from siron_tracer.catalog import Catalog, Dependency
    deps = [Dependency("S", "PKG", "PACKAGE BODY", "S", "V1", "VIEW"),
            Dependency("S", "V1", "VIEW", "S", "T1", "TABLE"),
            Dependency("S", "PKG", "PACKAGE BODY", "S", "T2", "TABLE")]
    cat = Catalog(list(CAT.tables.values()), {}, [], "v", deps)
    assert set(cat.underlying_tables(("S", "PKG"))) == {("S", "V1"), ("S", "T1"), ("S", "T2")}
    assert ("S", "PKG") in [k for k, _ in cat.used_by(("S", "T2"))]


def test_colour_theme(env, tmp_path):
    from siron_tracer.config import load_settings
    client = env[0]
    html = client.get("/").get_data(as_text=True)
    assert 'data-brand="siron"' in html and 'data-brand="odea"' in html and "Odeabank" in html   # default + menu
    assert "Varsayılan renk teması" in client.get("/settings").get_data(as_text=True)
    ini = tmp_path / "c.ini"
    ini.write_text("[oracle]\ndsn = x\n[siron]\ndb_user = SIRON\n[app]\nui_theme = Odea\n", encoding="utf-8")
    assert load_settings(str(ini)).ui_theme == "odea"
    ini.write_text("[oracle]\ndsn = x\n[siron]\ndb_user = SIRON\n[app]\nui_theme = mor\n", encoding="utf-8")
    try:
        load_settings(str(ini))
        assert False, "unknown theme accepted"
    except ValueError as exc:
        assert "ui_theme" in str(exc)
