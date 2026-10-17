import re
from datetime import datetime, timedelta

import pytest

from siron_tracer import create_app
from siron_tracer.config import Settings
from siron_tracer.sqlutil import compute_sql_id
from siron_tracer.store import Store

T0 = datetime(2026, 10, 17, 9, 0, 0)

Q1 = "SELECT c.name, a.iban FROM customer c JOIN account a ON a.cust_id = c.id WHERE c.id = :1"
Q2 = "SELECT * FROM alert WHERE status = :B1 AND cust_no = :B2"
NOISE = "SELECT 1 FROM DUAL"


def rec(i, sql, binds=None, obj=None, action="SELECT", stmt=None):
    return {"ts": (T0 + timedelta(seconds=i)).strftime("%Y-%m-%d %H:%M:%S.%f"),
            "db_user": "SIRON", "os_user": "app", "host": "APPSRV", "program": "JDBC",
            "session_id": "77", "entry_id": str(i), "statement_id": str(stmt or i),
            "action": action, "obj_schema": "SIRON" if obj else None, "obj_name": obj,
            "sql_text": sql, "sql_binds": binds, "return_code": "0", "client_id": None,
            "sql_id": compute_sql_id(sql) if sql else None}


CATALOG = {
    "objects": [("SIRON", "CUSTOMER", "TABLE"), ("SIRON", "ACCOUNT", "TABLE"), ("SIRON", "ALERT", "TABLE"),
                ("SIRON", "PKG_RISK", "PACKAGE")],
    "tables": [("SIRON", "CUSTOMER", "TABLE", 1000, "2026-10-01 10:00", "Müşteri ana tablosu"),
               ("SIRON", "ACCOUNT", "TABLE", 5000, None, None),
               ("SIRON", "ALERT", "TABLE", 300, None, "AML alarmları")],
    "columns": [("SIRON", "CUSTOMER", "ID", 1, "NUMBER", 22, 10, 0, "N", None),
                ("SIRON", "CUSTOMER", "CUST_NO", 2, "VARCHAR2", 20, None, None, "N", "Müşteri no"),
                ("SIRON", "CUSTOMER", "NAME", 3, "VARCHAR2", 200, None, None, "Y", None),
                ("SIRON", "ACCOUNT", "ID", 1, "NUMBER", 22, None, None, "N", None),
                ("SIRON", "ACCOUNT", "CUST_ID", 2, "NUMBER", 22, None, None, "N", None),
                ("SIRON", "ACCOUNT", "IBAN", 3, "VARCHAR2", 34, None, None, "Y", None),
                ("SIRON", "ALERT", "ALERT_ID", 1, "NUMBER", 22, None, None, "N", None),
                ("SIRON", "ALERT", "CUST_NO", 2, "VARCHAR2", 20, None, None, "Y", None),
                ("SIRON", "ALERT", "STATUS", 3, "VARCHAR2", 10, None, None, "Y", None)],
    "constraints": [("SIRON", "CUSTOMER_PK", "P", "CUSTOMER", None, None),
                    ("SIRON", "CUSTOMER_UK", "U", "CUSTOMER", None, None),
                    ("SIRON", "ACCOUNT_PK", "P", "ACCOUNT", None, None),
                    ("SIRON", "ALERT_PK", "P", "ALERT", None, None)],
    "cons_columns": [("SIRON", "CUSTOMER_PK", "ID", 1), ("SIRON", "CUSTOMER_UK", "CUST_NO", 1),
                     ("SIRON", "ACCOUNT_PK", "ID", 1), ("SIRON", "ALERT_PK", "ALERT_ID", 1)],
    "dependencies": [("SIRON", "PKG_RISK", "PACKAGE BODY", "SIRON", "ALERT", "TABLE")],
}


class FakeOracle:
    def __init__(self):
        self.clock = T0
        self.records = []
        self.ran = []
        self.result = (["NAME", "IBAN"], [("Ali Veli", "TR01")], False)

    def now(self):
        self.clock += timedelta(minutes=1)
        return self.clock, self.clock + timedelta(hours=3)

    def local_to_utc(self, local):
        return local - timedelta(hours=3)

    def fetch_records(self, f, flush=False, source=None):
        self.last_filter = f
        return list(self.records)

    def load_catalog(self, schemas):
        return CATALOG

    def run_select(self, sql, max_rows=None, binds=None, timeout_sec=None, schema=None):
        self.ran.append((sql, binds))
        self.last_schema = schema
        for name in binds or {}:  # python-oracledb rejects binds that are not in the SQL (DPY-4008)
            assert re.search(r":%s\b" % name, sql), "bind :%s not in SQL" % name
        if binds and "CASE WHEN" in sql:  # table value search: one flag column per searched column
            n = sql.count("CASE WHEN")
            flags = [1 if "CUST_NO" in part else 0 for part in sql.split("CASE WHEN")[1:]]
            return ["F%d" % i for i in range(n)], [tuple(flags)], False
        return self.result

    def stream_select(self, sql, max_rows, batch=2000, schema=None):
        self.ran.append((sql, None))
        yield ["NAME", "IBAN"]
        yield [("Ali Veli", "TR01"), ("Ayşe", "TR02")]

    def check_relation(self, child, ccols, parent, pcols, sample=5000):
        return 98, 100

    def cursor_info(self, sql_id):
        return ["INST_ID"], [(1,)], []

    def profile(self, key, table, sample_rows=200000, columns=None, progress=None):
        if progress:
            progress(0.5)
        return {c.name: {"rows": 100, "non_null": 90, "nulls": 10, "fill_pct": 90.0, "distinct": 3,
                         "min": "A", "max": "Z", "avg_len": 5, "max_len": 9, "top": [["Ali Veli", 40], ["X", 30]],
                         "sampled": False, "sample_pct": None} for c in table.columns}

    def diagnostics(self, users=None, schemas=None):
        return [("Bağlantı", True, "Oracle 19c")]


@pytest.fixture
def env():
    settings = Settings(oracle_dsn="x", oracle_user="u", siron_db_user="SIRON",
                        siron_schemas=["SIRON"], secret_key="t")
    oracle = FakeOracle()
    app = create_app(settings, oracle=oracle, store=Store(":memory:"), sync_jobs=True)
    app.config["TESTING"] = True
    return app.test_client(), oracle, app.extensions["siron"]["store"]


def capture(client, store, oracle, name, records):
    oracle.records = records
    client.post("/captures", data={"name": name})
    cid = store.list_captures()[0]["id"]
    client.post("/captures/%d/stop" % cid)
    return cid


def test_capture_flow(env):
    client, oracle, store = env
    assert client.get("/").status_code == 200
    client.post("/captures", data={"name": "Müşteri detay"})
    cid = store.list_captures()[0]["id"]
    assert "Kayıt sürüyor" in client.get("/captures/%d" % cid).get_data(as_text=True)

    oracle.records = [
        rec(1, Q1, " #1(3):123", obj="CUSTOMER", stmt=1),
        rec(2, Q1, " #1(3):123", obj="ACCOUNT", stmt=1),   # same execution, 2nd object
        rec(3, Q1, " #1(3):456", obj="CUSTOMER", stmt=3),
        rec(4, Q2, " #1(4):OPEN #2(5):AHMET", obj="ALERT"),
        rec(5, None, None, action="LOGON"),
    ]
    client.post("/captures/%d/stop" % cid)
    c = store.get_capture(cid)
    assert c["status"] == "done" and c["record_count"] == 5

    html = client.get("/captures/%d" % cid).get_data(as_text=True)
    for word in ("SIRON.CUSTOMER", "SIRON.ACCOUNT", "SIRON.ALERT", compute_sql_id(Q1)):
        assert word in html

    sid = compute_sql_id(Q1)
    html = client.get("/captures/%d/sql/%s" % (cid, sid)).get_data(as_text=True)
    assert "c.id = &#39;123&#39;" in html

    r = client.post("/captures/%d/sql/%s" % (cid, sid),
                    data={"do": "run", "value_0": "999", "kind_0": "number",
                          "sql_override": "x", "literal_orig": "x"})
    assert r.status_code == 200
    assert oracle.ran[-1][0].endswith("c.id = 999")
    assert "TR01" in r.get_data(as_text=True)

    client.post("/captures/%d/sql/%s" % (cid, sid),
                data={"do": "run", "sql_override": "select 2 from dual", "literal_orig": "x"})
    assert oracle.ran[-1][0] == "select 2 from dual"

    assert client.get("/captures/%d/sql/%s?cursor=1" % (cid, sid)).status_code == 200
    csv_text = client.get("/captures/%d/statements.csv" % cid).get_data(as_text=True)
    assert sid in csv_text and "'456'" not in csv_text and "'123'" in csv_text


def test_noise_capture_hides_sql(env):
    client, oracle, store = env
    noise_id = capture(client, store, oracle, "boşta", [rec(1, NOISE)])
    client.post("/captures/%d/update" % noise_id, data={"toggle_noise": "1"})
    assert store.get_capture(noise_id)["is_noise"] == 1
    cid = capture(client, store, oracle, "uyarılar", [rec(1, NOISE), rec(2, Q2, " #1(1):A #2(1):B")])
    html = client.get("/captures/%d" % cid).get_data(as_text=True)
    assert compute_sql_id(Q2) in html and compute_sql_id(NOISE) not in html
    assert compute_sql_id(NOISE) in client.get("/captures/%d?noise=0" % cid).get_data(as_text=True)


def test_catalog_columns_relations_and_er(env):
    client, oracle, store = env
    client.post("/catalog/refresh")
    assert len(store.catalog().tables) == 3
    cid = capture(client, store, oracle, "Müşteri", [rec(1, Q1, " #1(1):1"), rec(2, Q2, " #1(1):A #2(1):B")])

    html = client.get("/captures/%d/columns" % cid).get_data(as_text=True)
    assert "IBAN" in html and "gösterim" in html and "CUST_ID" in html and "SELECT *" in html

    html = client.get("/relations?capture=%d" % cid).get_data(as_text=True)
    assert "ACCOUNT" in html and "(CUST_ID)" in html          # from the SQL join
    assert "(CUST_NO)" in html                                   # name inference ALERT -> CUSTOMER

    r = client.post("/relations/check", data={"rid": "SIRON.ALERT(CUST_NO)>SIRON.CUSTOMER(CUST_NO)"})
    assert r.status_code == 302
    assert store.relation_checks()["SIRON.ALERT(CUST_NO)>SIRON.CUSTOMER(CUST_NO)"] == (98, 100)
    client.post("/relations/check-all?capture=%d" % cid)
    assert len(store.relation_checks()) >= 2

    html = client.get("/er?capture=%d&min=0" % cid).get_data(as_text=True)
    assert "<svg" in html and 'data-id="SIRON.ACCOUNT"' in html
    mmd = client.get("/er.mmd?capture=%d&min=0" % cid).get_data(as_text=True)
    assert mmd.startswith("erDiagram") and "CUSTOMER ||--o{ ACCOUNT" in mmd
    assert "digraph" in client.get("/er.dot").get_data(as_text=True)
    assert client.get("/relations").status_code == 200
    assert client.get("/er").status_code == 200


def test_tables_annotations_mapping(env):
    client, oracle, store = env
    client.post("/catalog/refresh")
    capture(client, store, oracle, "Müşteri", [rec(1, Q1, " #1(1):1")])
    html = client.get("/tables").get_data(as_text=True)
    assert "Müşteri ana tablosu" in html and "SIRON.CUSTOMER" in html
    assert "AML alarmları" in client.get("/tables?all=1").get_data(as_text=True)

    client.post("/table/SIRON/CUSTOMER", data={"action": "annotate", "status": "migrate", "note": "ana veri",
                                               "target": "PARTY", "status_NAME": "migrate",
                                               "target_NAME": "PARTY.FULL_NAME", "note_NAME": "ad soyad"})
    anns = store.annotations()
    assert anns[("SIRON", "CUSTOMER", "")]["target"] == "PARTY"
    assert anns[("SIRON", "CUSTOMER", "NAME")]["target"] == "PARTY.FULL_NAME"
    assert ("SIRON", "CUSTOMER", "ID") not in anns   # empty rows are not stored

    html = client.get("/table/SIRON/CUSTOMER").get_data(as_text=True)
    assert "PARTY.FULL_NAME" in html and "Müşteri no" in html and "ACCOUNT" in html
    html = client.post("/table/SIRON/CUSTOMER", data={"action": "sample"}).get_data(as_text=True)
    assert "TR01" in html
    html = client.post("/table/SIRON/CUSTOMER", data={"action": "find", "value": "C-1", "mode": "exact"}).get_data(as_text=True)
    assert "CUST_NO" in html

    html = client.get("/mapping").get_data(as_text=True)
    assert "PARTY.FULL_NAME" in html and "IBAN" in html
    csv_text = client.get("/mapping.csv").get_data(as_text=True)
    assert "PARTY.FULL_NAME" in csv_text and "Taşınacak" in csv_text
    assert "Taşınacak" in client.get("/tables?status=migrate").get_data(as_text=True)


def test_value_finder(env):
    client, oracle, store = env
    client.post("/catalog/refresh")
    cid = capture(client, store, oracle, "Müşteri", [rec(1, Q1, " #1(1):1"), rec(2, Q2, " #1(1):A #2(1):B")])
    html = client.post("/captures/%d/find" % cid, data={"value": "ali veli", "mode": "ci",
                                                         "strategy": "results"}).get_data(as_text=True)
    assert "SIRON.CUSTOMER.NAME" in html
    html = client.post("/captures/%d/find" % cid, data={"value": "C-1", "mode": "exact", "strategy": "tables"},
                       follow_redirects=True).get_data(as_text=True)
    assert "SIRON.CUSTOMER.<b>CUST_NO</b>" in html and "SIRON.ALERT.<b>CUST_NO</b>" in html
    assert store.list_jobs(1)[0]["status"] == "done"


def test_builder_sql_exports_snapshots_reports(env):
    client, oracle, store = env
    client.post("/catalog/refresh")
    cid = capture(client, store, oracle, "Müşteri", [rec(1, Q1, " #1(1):1"), rec(2, Q2, " #1(1):A #2(1):B")])

    html = client.post("/builder", data={"t": ["SIRON.ACCOUNT", "SIRON.ALERT"], "root": "SIRON.CUSTOMER",
                                         "used_only": "1"}).get_data(as_text=True)
    assert "LEFT JOIN SIRON.ACCOUNT t2 ON t2.CUST_ID = t1.ID" in html
    assert "LEFT JOIN SIRON.ALERT t3 ON t3.CUST_NO = t1.CUST_NO" in html
    assert "t1.NAME" in html

    r = client.post("/sql", data={"sql": "select * from customer", "do": "csv"})
    assert "Ayşe" in r.get_data(as_text=True) and r.headers["Content-Disposition"].startswith("attachment")
    r = client.post("/sql", data={"sql": "select name, iban from customer", "do": "html", "mask": "all"})
    body = r.get_data(as_text=True)
    assert "<table>" in body and "Ali Veli" not in body and "Al****li" in body
    body = client.post("/sql", data={"sql": "select name, iban from customer", "do": "html",
                                     "mask": "sensitive"}).get_data(as_text=True)
    assert "Ali Veli" in body and "TR01" not in body          # IBAN is detected as sensitive
    body = client.post("/sql", data={"sql": "select name, iban from customer", "do": "html",
                                     "mask": "none"}).get_data(as_text=True)
    assert "TR01" in body

    sid = compute_sql_id(Q1)
    client.post("/captures/%d/sql/%s" % (cid, sid), data={"do": "snapshot", "title": "Hesaplar"})
    client.post("/sql", data={"sql": "select name from customer", "do": "snapshot", "title": "Serbest"})
    snaps = store.snapshots()
    assert [s["title"] for s in snaps] == ["Hesaplar", "Serbest"]
    assert snaps[0]["sources"] == ["SIRON.CUSTOMER.NAME", "SIRON.ACCOUNT.IBAN"]
    assert "Hesaplar" in client.get("/snapshots").get_data(as_text=True)

    html = client.get("/report.html").get_data(as_text=True)
    for word in ("Siron AML veri eşleme raporu", "SIRON.CUSTOMER", "Kolon eşleme matrisi", "<svg", "Hesaplar", "Ali Veli"):
        assert word in html
    html = client.get("/report.html?mask=all&capture=%d" % cid).get_data(as_text=True)
    assert "Ekran raporu" in html and "Ali Veli" not in html
    r = client.get("/report.html?download=1")
    assert "attachment" in r.headers["Content-Disposition"]
    assert client.get("/report").status_code == 200

    client.post("/snapshots/%d/delete" % snaps[0]["id"])
    assert len(store.snapshots()) == 1


def test_search_range_check(env):
    client, oracle, store = env
    client.post("/catalog/refresh")
    r = client.post("/captures/range", data={"name": "geçmiş", "start": "2026-10-17T12:00",
                                             "end": "2026-10-17T12:05:30"})
    assert r.status_code == 302
    c = store.list_captures()[0]
    assert c["start_utc"].startswith("2026-10-17 09:00:00")
    oracle.records = [rec(1, Q1, " #1(1):1")]
    client.post("/captures/%d/refetch" % c["id"])
    html = client.get("/search?q=iban").get_data(as_text=True)
    assert "IBAN" in html and compute_sql_id(Q1) in html
    assert "Müşteri ana tablosu" in client.get("/search?q=müşteri").get_data(as_text=True)
    assert "Oracle 19c" in client.get("/check").get_data(as_text=True)
    client.post("/captures/%d/delete" % c["id"])
    assert store.get_capture(c["id"]) is None


def test_pages_work_without_catalog(env):
    client, oracle, store = env
    cid = capture(client, store, oracle, "katalogsuz", [rec(1, Q1, " #1(1):1"), rec(2, Q2, " #1(1):A #2(1):B")])
    for url in ("/", "/captures/%d" % cid, "/captures/%d/columns" % cid, "/captures/%d/find" % cid,
                "/tables", "/relations", "/er", "/mapping", "/builder", "/report", "/report.html",
                "/table/SIRON/CUSTOMER", "/search?q=x", "/snapshots", "/sql"):
        assert client.get(url).status_code == 200, url
    html = client.get("/relations").get_data(as_text=True)
    assert "CUST_ID" in html  # SQL joins work without the data dictionary
