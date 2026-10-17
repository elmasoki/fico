import time
from datetime import timedelta

import pytest

from conftest import oracledb, wait_for
from siron_tracer.catalog import Catalog
from siron_tracer.finder import searchable_columns, table_search_sql
from siron_tracer.oracle import OracleError
from siron_tracer.sources import AuditFilter, fetch_cursor_cache, fetch_unified
from siron_tracer.sqlutil import compute_sql_id
from siron_tracer.store import Store

C, A, AL = ("SIRON", "CUSTOMER"), ("SIRON", "ACCOUNT"), ("SIRON", "ALERT")


@pytest.fixture(scope="module")
def catalog(oracle, settings):
    store = Store(":memory:")
    store.replace_catalog(oracle.load_catalog(["SIRON"]))
    return store.catalog()


def test_clock(oracle):
    utc, local = oracle.now()
    assert abs((oracle.local_to_utc(local.replace(microsecond=0)) - utc).total_seconds()) < 5


def test_catalog_load(catalog):
    assert {C, A, AL, ("SIRON", "COUNTRY"), ("SIRON", "V_CUSTOMER_ACCOUNTS")} <= set(catalog.tables)
    assert catalog.tables[C].comment == "Müşteri ana kaydı"
    assert catalog.column(C, "CUST_NO").comment == "Müşteri numarası"
    assert catalog.tables[C].num_rows == 200
    assert catalog.primary_key(A) == ("ID",)
    assert catalog.is_key(C, ("CUST_NO",))
    assert (A, ("CUST_ID",), C, ("ID",)) in [fk[:4] for fk in catalog.foreign_keys()]
    assert catalog.objects[("SIRON", "PKG_RISK")] == "PACKAGE"


def test_dependencies(catalog):
    assert AL in catalog.underlying_tables(("SIRON", "PKG_RISK"))
    assert set(catalog.underlying_tables(("SIRON", "V_CUSTOMER_ACCOUNTS"))) >= {C, A}
    assert ("SIRON", "PKG_RISK") in [k for k, _ in catalog.used_by(AL)]


def test_run_select_is_read_only(oracle):
    cols, rows, truncated = oracle.run_select("select cust_no, full_name from customer order by id", max_rows=5)
    assert cols == ["CUST_NO", "FULL_NAME"] and len(rows) == 5 and truncated
    with pytest.raises(OracleError):
        oracle.run_select("delete from customer")
    with pytest.raises(oracledb.DatabaseError):  # read-only transaction blocks locking
        oracle.run_select("select * from customer for update")
    cols, rows, _ = oracle.run_select("select count(*) from customer where id = :n", binds={"n": 7})
    assert rows == [(1,)]


def test_stream_select(oracle):
    gen = oracle.stream_select("select id from account order by id", max_rows=1000, batch=150)
    assert next(gen) == ["ID"]
    batches = list(gen)
    assert [len(b) for b in batches] == [150, 150, 100]


def test_check_relation(oracle):
    assert oracle.check_relation(A, ("CUST_ID",), C, ("ID",)) == (200, 200)
    matched, total = oracle.check_relation(AL, ("CUST_NO",), C, ("CUST_NO",))
    assert (matched, total) == (47, 50)


def test_table_value_search(oracle, catalog):
    cols = searchable_columns(catalog.columns(C), "C0042", "exact")
    sql, binds = table_search_sql(C, cols, "C0042", "exact")
    _, rows, _ = oracle.run_select(sql, binds=binds, max_rows=50)
    flags = dict(zip([c.name for c in cols], rows[0]))
    assert flags["CUST_NO"] == 1 and flags["FULL_NAME"] == 0
    cols = searchable_columns(catalog.columns(A), "21", "exact")
    sql, binds = table_search_sql(A, cols, "21", "exact")
    _, rows, _ = oracle.run_select(sql, binds=binds, max_rows=50)
    assert rows  # numeric search (ID / CUST_ID = 21)


def test_profile(oracle, catalog):
    stats = oracle.profile(C, catalog.tables[C])
    assert stats["ID"]["rows"] == 200 and stats["ID"]["distinct"] == 200
    assert stats["RISK_CLASS"]["distinct"] == 3
    assert sorted(v for v, _ in stats["RISK_CLASS"]["top"]) == ["H", "L", "M"]
    assert stats["COUNTRY_CODE"]["top"][0] == ["TR", 150]
    assert stats["BIRTH_DATE"]["non_null"] == 200 and stats["BIRTH_DATE"]["min"]
    sampled = oracle.profile(A, catalog.tables[A], sample_rows=100)  # forces SAMPLE (...)
    assert sampled["ID"]["sampled"] is True


def test_diagnostics(oracle):
    checks = dict((t, ok) for t, ok, _ in oracle.diagnostics(["SIRON"], ["SIRON"]))
    assert checks["Bağlantı / sürüm"]


def test_unified_audit_and_cursor_cache(oracle, audit_policy, siron_conn):
    start_utc, start_local = oracle.now()
    time.sleep(1)
    cur = siron_conn.cursor()
    sql = "SELECT c.full_name, a.iban FROM customer c JOIN account a ON a.cust_id = c.id WHERE c.cust_no = :1"
    cur.execute(sql, ["C0005"])
    cur.fetchall()
    cur.execute("SELECT pkg_risk.score(:p) FROM dual", p="C0003")
    cur.fetchall()
    time.sleep(1)

    def fetch():
        end_utc, end_local = oracle.now()
        f = AuditFilter(["SIRON"], start_utc, end_utc + timedelta(seconds=1), start_local,
                        end_local + timedelta(seconds=1))
        with oracle.connect() as conn:
            oracle.flush_unified(conn)
            return [r for r in fetch_unified(conn, f) if r["sql_text"]]

    rows = wait_for(fetch)
    texts = {r["sql_text"]: r for r in rows}
    assert sql in texts, list(texts)
    rec = texts[sql]
    assert "C0005" in (rec["sql_binds"] or "")
    assert rec["sql_id"] == compute_sql_id(sql)
    with oracle.connect() as conn, conn.cursor() as c2:  # computed SQL_ID matches V$SQL
        c2.execute("SELECT COUNT(*) FROM v$sql WHERE sql_id = :1", [rec["sql_id"]])
        assert c2.fetchone()[0] >= 1

    end_utc, end_local = oracle.now()
    f = AuditFilter(["SIRON"], start_utc, end_utc, start_local - timedelta(minutes=1), end_local + timedelta(minutes=1))
    with oracle.connect() as conn:
        cached = fetch_cursor_cache(conn, f)
    assert any(r["sql_id"] == compute_sql_id(sql) for r in cached)
