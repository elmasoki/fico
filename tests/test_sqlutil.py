from siron_tracer.sqlutil import (Bind, build_slots, compute_sql_id, extract_tables,
                                  find_placeholders, format_audit_binds, is_select,
                                  literal_sql, parse_audit_binds, substitute_binds)


def test_sql_id_matches_oracle():
    # well-known value from V$SQL
    assert compute_sql_id("select * from dual") == "a5ks9fhw2v9s1"


def test_parse_audit_binds_basic():
    assert parse_audit_binds(" #1(4):1001 #2(5):AHMET #3(0):") == [
        Bind(1, "1001"), Bind(2, "AHMET"), Bind(3, None)]


def test_parse_audit_binds_value_with_spaces_and_hash():
    assert parse_audit_binds(" #1(9):a b #2(1)x #2(1):7") == [Bind(1, "a b #2(1)x"), Bind(2, "7")]


def test_parse_audit_binds_byte_length():
    # length given in bytes for multi-byte characters
    assert parse_audit_binds(" #1(6):ÇĞŞ #2(1):1") == [Bind(1, "ÇĞŞ"), Bind(2, "1")]


def test_parse_audit_binds_empty():
    assert parse_audit_binds(None) == [] and parse_audit_binds("") == []


def test_format_roundtrip():
    raw = format_audit_binds(["10", None, "x y"])
    assert parse_audit_binds(raw) == [Bind(1, "10"), Bind(2, None), Bind(3, "x y")]


def test_placeholders_skip_strings_comments_and_assignments():
    sql = ("select ':x', \"A:B\" from t /* :c */ where a = :1 and b = :B2 -- :d\n"
           " and c = ? and to_char(d, 'HH24:MI') = :name and e := 1")
    assert [p.text for p in find_placeholders(sql)] == [":1", ":B2", "?", ":name"]


def test_literal_by_position():
    sql = "select * from t where a = :1 and b = :2 and c = :3"
    literal, slots = literal_sql(sql, " #1(1):5 #2(3):O'K #3(0):")
    assert literal == "select * from t where a = '5' and b = 'O''K' and c = NULL"
    assert not any(s.missing for s in slots)


def test_literal_repeated_named_bind_matches_by_name():
    sql = "select * from t where a = :id or b = :id and c = :n"
    literal, slots = literal_sql(sql, " #1(2):42 #2(1):x")
    assert literal == "select * from t where a = '42' or b = '42' and c = 'x'"
    assert [s.label for s in slots] == [":ID", ":N"]


def test_missing_binds_are_left_in_place():
    literal, slots = literal_sql("select 1 from t where a = :1 and b = :2", " #1(1):1")
    assert literal == "select 1 from t where a = '1' and b = :2"
    assert slots[1].missing


def test_slot_kinds():
    sql = "select * from t where a = :1 and d = :2 and n = :3"
    ph = find_placeholders(sql)
    slots = build_slots(ph, parse_audit_binds(" #1(2):10 #2(10):2026-01-01 #3(1):x"))
    slots[0].kind = "number"
    slots[1].kind, slots[1].value = "raw", "DATE '2026-01-01'"
    slots[2].kind = "null"
    assert substitute_binds(sql, ph, slots) == \
        "select * from t where a = 10 and d = DATE '2026-01-01' and n = NULL"


def test_extract_tables_heuristic():
    sql = ("select a.x from siron.cust a, acc b join tx t on t.id = b.id "
           "left outer join \"Mixed\" m on 1=1 where exists (select 1 from alerts al) "
           "and extract(year from b.d) = 2026 and x in (select y from table(f(1)))")
    assert extract_tables(sql) == [("SIRON", "CUST"), (None, "ACC"), (None, "TX"),
                                   (None, "Mixed"), (None, "ALERTS")]


def test_extract_tables_dml():
    assert extract_tables("insert into t1 (a, b) values (:1, :2)") == [(None, "T1")]
    assert extract_tables("update t2 x set a = 1") == [(None, "T2")]
    assert extract_tables("delete from t3 where a = 1") == [(None, "T3")]
    assert extract_tables("merge into m1 d using s1 s on (d.id = s.id) "
                          "when matched then update set d.a = s.a") == [(None, "M1"), (None, "S1")]


def test_extract_tables_with_catalogue():
    known = {("SIRON", "CUST"), ("SIRON", "ACC"), ("SIRON", "PKG_RISK"), ("OTHER", "ACC")}
    sql = "select pkg_risk.score(c.id) from cust c, other.acc a where c.acc = a.id"
    assert extract_tables(sql, known, "SIRON") == [
        ("SIRON", "PKG_RISK"), ("SIRON", "CUST"), ("OTHER", "ACC")]


def test_is_select():
    assert is_select("  /* x */ select 1 from dual")
    assert is_select("with a as (select 1 from dual) select * from a")
    assert is_select("(select 1 from dual)")
    assert not is_select("delete from t")
    assert not is_select("-- select\nupdate t set a = 1")
